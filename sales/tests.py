from django.urls import reverse
from rest_framework.test import APITestCase

from accounting.models import Bank
from catalog.models import Product
from inventory.models import Load
from parties.models import Party
from sales.models import Sale, get_porterage_settings


class SalesSmokeTests(APITestCase):
    def setUp(self):
        settings_row = get_porterage_settings()
        settings_row.rate_per_kg = 15000
        settings_row.round_enabled = True
        settings_row.save()

        self.product = Product.objects.create(
            name='سیب', tare_weight='1.000', sticker='apple', background='#2E7D32'
        )
        self.other = Product.objects.create(name='خیار', tare_weight='0.500')
        self.load = Load.objects.create(
            product=self.product, label='درجه یک', tare_weight='1.000'
        )
        self.other_load = Load.objects.create(
            product=self.other, label='الف', tare_weight='0.500'
        )
        self.party = Party.objects.create(name='رضایی', label='همسایه')
        self.bank = Bank.objects.create(name='بانک ملت')
        self.sale_id = self.client.post(
            reverse('sale-list-create'), {}, format='json'
        ).data['id']

    def add_line(self, **payload):
        return self.client.post(
            reverse('sale-line-create', args=[self.sale_id]), payload, format='json'
        )

    def test_full_flow(self):
        created = self.client.get(reverse('sale-detail', args=[self.sale_id]))
        self.assertEqual(created.status_code, 200)
        self.assertEqual(
            sorted(created.data.keys()),
            [
                'account',
                'created_at',
                'finalized_at',
                'id',
                'lines',
                'payments',
                'porterage',
                'status',
                'summary',
                'total_amount',
            ],
        )
        self.assertIsNone(created.data['account'])

        response = self.add_line(
            load=self.load.id, gross_weight='103.500', quantity=5, rate=450000
        )
        self.assertEqual(response.status_code, 201)
        line = response.data['lines'][0]
        self.assertEqual(line['net_weight'], '98.500')
        self.assertEqual(line['line_total'], 44325000)
        self.assertEqual(line['product_name'], 'سیب')
        self.assertEqual(line['label'], 'درجه یک')
        # 103.500 * 15000 = 1552500 -> rounded to 1550000
        self.assertEqual(response.data['porterage'], {'amount': 1550000})
        self.assertEqual(response.data['total_amount'], 44325000 + 1550000)

        # Same load twice is allowed.
        again = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=100
        )
        self.assertEqual(again.status_code, 201)
        self.assertEqual(len(again.data['lines']), 2)
        self.assertEqual(again.data['porterage'], {'amount': 1700000})

        # Payment bank rules.
        url = reverse('sale-payment-create', args=[self.sale_id])
        self.assertEqual(
            self.client.post(
                url,
                {'method': 'pos', 'bank': self.bank.id, 'amount': 1000},
                format='json',
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.post(
                url, {'method': 'cash', 'amount': 5}, format='json'
            ).status_code,
            201,
        )
        bad = self.client.post(
            url, {'method': 'cash', 'bank': self.bank.id, 'amount': 5}, format='json'
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn('bank', bad.data)
        bad = self.client.post(
            url, {'method': 'pos', 'amount': 5}, format='json'
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn('bank', bad.data)

        # Account.
        account = self.client.put(
            reverse('sale-account', args=[self.sale_id]),
            {'party': self.party.id, 'amount': -500},
            format='json',
        )
        self.assertEqual(account.status_code, 200)
        self.assertEqual(
            account.data['account'],
            {
                'party': {'id': self.party.id, 'name': 'رضایی', 'label': 'همسایه'},
                'amount': -500,
            },
        )

        # Cannot finalize while remaining != 0.
        finalize = reverse('sale-finalize', args=[self.sale_id])
        unsettled = self.client.post(finalize)
        self.assertEqual(unsettled.status_code, 409)
        self.assertEqual(unsettled.json()['code'], 'not_settled')
        self.assertNotEqual(unsettled.json()['remaining'], 0)

        # Settle it exactly: drop the account, drop the porterage, and pay the
        # whole total with the single remaining payment.
        self.client.delete(reverse('sale-account', args=[self.sale_id]))
        self.client.delete(reverse('sale-payment-detail', args=[self.sale_id, 2]))
        self.client.put(
            reverse('sale-porterage', args=[self.sale_id]),
            {'amount': 0},
            format='json',
        )
        total = self.client.get(
            reverse('sale-detail', args=[self.sale_id])
        ).data['total_amount']
        self.client.patch(
            reverse('sale-payment-detail', args=[self.sale_id, 1]),
            {'amount': total},
            format='json',
        )
        settled = self.client.post(finalize)
        self.assertEqual(settled.status_code, 200)
        # No money owed by a buyer, so this is a plain final sale.
        self.assertEqual(settled.data['status'], 'final')
        self.assertEqual(settled.data['summary']['remaining'], 0)
        finalized_at = Sale.objects.get(pk=self.sale_id).finalized_at
        self.assertIsNotNone(finalized_at)

        # Idempotent.
        again = self.client.post(finalize)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(Sale.objects.get(pk=self.sale_id).finalized_at, finalized_at)

        # Editing reopens the sale.
        reopened = self.add_line(
            load=self.other_load.id, gross_weight='10.000', quantity=1, rate=100
        )
        self.assertEqual(reopened.status_code, 201)
        self.assertEqual(reopened.data['status'], 'draft')
        self.assertIsNone(Sale.objects.get(pk=self.sale_id).finalized_at)

        # Undo that edit so the sale is settled again, then finalize.
        added = reopened.data['lines'][-1]['id']
        undone = self.client.delete(
            reverse('sale-line-detail', args=[self.sale_id, added])
        )
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(undone.data['status'], 'draft')
        self.assertEqual(self.client.post(finalize).status_code, 200)

        # Deleting is refused once it is not a draft.
        blocked = self.client.delete(reverse('sale-detail', args=[self.sale_id]))
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()['code'], 'not_deletable')

        # A load used by a line cannot be deleted.
        used = self.client.delete(reverse('load-detail', args=[self.load.id]))
        self.assertEqual(used.status_code, 409)
        self.assertEqual(used.json()['code'], 'in_use')

    def test_fresh_sale_has_no_lines_and_cannot_finalize(self):
        empty_id = self.client.post(
            reverse('sale-list-create'), {}, format='json'
        ).data['id']
        response = self.client.post(reverse('sale-finalize', args=[empty_id]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'no_lines')

    def test_draft_can_be_deleted_with_its_children(self):
        self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=100
        )
        response = self.client.delete(reverse('sale-detail', args=[self.sale_id]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Sale.objects.filter(pk=self.sale_id).exists())
        from sales.models import Invoice, InvoiceLine, Payment, Porterage

        self.assertFalse(Invoice.objects.filter(sale_id=self.sale_id).exists())
        self.assertFalse(Porterage.objects.filter(sale_id=self.sale_id).exists())
        self.assertFalse(Payment.objects.filter(sale_id=self.sale_id).exists())
        self.assertFalse(InvoiceLine.objects.filter(invoice__sale_id=self.sale_id).exists())

    def test_list_shape_and_filters(self):
        listing = self.client.get(reverse('sale-list-create'))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            sorted(listing.data.keys()), ['next', 'previous', 'results']
        )
        item = listing.data['results'][0]
        self.assertEqual(
            sorted(item.keys()),
            ['created_at', 'id', 'party', 'products', 'status', 'total_amount'],
        )
        self.assertIsNone(item['party'])
        self.assertEqual(item['products'], [])

        self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=100
        )
        item = self.client.get(reverse('sale-list-create')).data['results'][0]
        self.assertEqual(
            item['products'], [{'id': self.product.id, 'sticker': 'apple', 'background': '#2E7D32'}]
        )

        self.assertEqual(
            self.client.get(reverse('sale-list-create'), {'status': 'draft'}).data[
                'results'
            ][0]['id'],
            self.sale_id,
        )
        self.assertEqual(
            self.client.get(
                reverse('sale-list-create'), {'status': 'final'}
            ).data['results'],
            [],
        )
        bad = self.client.get(reverse('sale-list-create'), {'status': 'bogus'})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('status', bad.data)

    def test_porterage_settings_endpoint(self):
        url = reverse('porterage-settings')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data.keys()),
            ['rate_per_kg', 'round_enabled', 'works_with_porters'],
        )
        patched = self.client.patch(url, {'rate_per_kg': 2500}, format='json')
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data['rate_per_kg'], 2500)
        self.assertEqual(
            self.client.patch(url, {'rate_per_kg': -1}, format='json').status_code, 400
        )