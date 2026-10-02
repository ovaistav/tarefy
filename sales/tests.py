from decimal import Decimal

from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from rest_framework.test import APITestCase

from accounting.models import Bank
from catalog.models import Product
from inventory.models import Load
from parties.models import Party
from sales.models import (
    Invoice,
    InvoiceLine,
    Payment,
    Porterage,
    PorterageSettings,
    Sale,
    get_porterage_settings,
)
from sales.services import round_porterage


class SalesTestCase(APITestCase):
    """Shared fixtures: one product, one load, one party, one bank."""

    def setUp(self):
        self.product = Product.objects.create(
            name='سیب',
            tare_weight='1.000',
            sticker='apple',
            background='#2E7D32',
        )
        self.other_product = Product.objects.create(
            name='خیار', tare_weight='0.500', sticker='cucumber', background='#2E7D32'
        )
        self.load = Load.objects.create(
            product=self.product, label='درجه یک', tare_weight='1.000'
        )
        self.other_load = Load.objects.create(
            product=self.other_product, label='الف', tare_weight='0.500'
        )
        self.party = Party.objects.create(name='رضایی', label='همسایه')
        self.bank = Bank.objects.create(name='بانک ملت')

        self.porterage_settings = get_porterage_settings()
        self.porterage_settings.works_with_porters = True
        # Zero by default so the money assertions stay readable; the porterage
        # tests opt into a rate of their own.
        self.porterage_settings.rate_per_kg = 0
        self.porterage_settings.round_enabled = False
        self.porterage_settings.save()

    def use_porterage(self, rate_per_kg=4000, round_enabled=False, works=True):
        self.porterage_settings.works_with_porters = works
        self.porterage_settings.rate_per_kg = rate_per_kg
        self.porterage_settings.round_enabled = round_enabled
        self.porterage_settings.save()

    # -- helpers ---------------------------------------------------------
    def new_sale(self):
        response = self.client.post(
            reverse('sale-list-create'), {}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        return response.data['id']

    def detail_url(self, sale_id=None):
        return reverse('sale-detail', args=[sale_id or self.sale_id])

    def add_line(self, sale_id=None, **payload):
        return self.client.post(
            reverse('sale-line-create', args=[sale_id or self.sale_id]),
            payload,
            format='json',
        )

    def line_url(self, line_id, sale_id=None):
        return reverse('sale-line-detail', args=[sale_id or self.sale_id, line_id])

    def pay(self, method='cash', amount=1000, bank=None, sale_id=None):
        payload = {'method': method, 'amount': amount}
        if bank is not None:
            payload['bank'] = bank
        return self.client.post(
            reverse('sale-payment-create', args=[sale_id or self.sale_id]),
            payload,
            format='json',
        )

    def put_porterage(self, amount, sale_id=None):
        return self.client.put(
            reverse('sale-porterage', args=[sale_id or self.sale_id]),
            {'amount': amount},
            format='json',
        )

    def set_account(self, amount, sale_id=None, party=None):
        return self.client.put(
            reverse('sale-account', args=[sale_id or self.sale_id]),
            {'party': (party or self.party).id, 'amount': amount},
            format='json',
        )

    def finalize(self, sale_id=None):
        return self.client.post(
            reverse('sale-finalize', args=[sale_id or self.sale_id])
        )

    def settle_exactly(self, sale_id=None):
        """Pay the whole total with one cash payment and no account."""
        sale_id = sale_id or self.sale_id
        self.client.delete(reverse('sale-account', args=[sale_id]))
        self.put_porterage(0, sale_id)
        total = self.client.get(self.detail_url(sale_id)).data['total_amount']
        return self.pay(amount=total, sale_id=sale_id)


class SaleLineTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.sale_id = self.new_sale()

    def test_weights_and_line_total_are_computed_by_the_server(self):
        response = self.add_line(
            load=self.load.id, gross_weight='103.500', quantity=5, rate=450000
        )
        self.assertEqual(response.status_code, 201)
        line = response.data['lines'][0]
        # 103.500 - (1.000 * 5) = 98.500 ; 98.500 * 450000 = 44325000
        self.assertEqual(line['gross_weight'], '103.500')
        self.assertEqual(line['net_weight'], '98.500')
        self.assertEqual(line['line_total'], 44325000)
        self.assertEqual(line['product'], self.product.id)
        self.assertEqual(line['product_name'], 'سیب')
        self.assertEqual(line['label'], 'درجه یک')
        self.assertEqual(response.data['total_amount'], 44325000)

    def test_zero_quantity_leaves_the_gross_weight_as_the_net(self):
        response = self.add_line(
            load=self.load.id, gross_weight='50.000', quantity=0, rate=1000
        )
        self.assertEqual(response.data['lines'][0]['net_weight'], '50.000')
        self.assertEqual(response.data['lines'][0]['line_total'], 50000)

    def test_half_is_rounded_up(self):
        response = self.add_line(
            load=self.load.id, gross_weight='10.001', quantity=0, rate=1
        )
        # 10.001 * 1 -> 10
        self.assertEqual(response.data['lines'][0]['line_total'], 10)

    def test_net_weight_of_zero_or_less_is_rejected(self):
        # 2.000 gross with a 1.000 tare and quantity 2 nets exactly zero.
        for quantity in [2, 5]:
            with self.subTest(quantity=quantity):
                response = self.add_line(
                    load=self.load.id,
                    gross_weight='2.000',
                    quantity=quantity,
                    rate=1000,
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn('net_weight', response.data)

    def test_gross_weight_must_be_positive(self):
        response = self.add_line(
            load=self.load.id, gross_weight='0.000', quantity=0, rate=1000
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('gross_weight', response.data)

    def test_negative_quantity_and_rate_are_rejected(self):
        for field in ['quantity', 'rate']:
            with self.subTest(field=field):
                payload = {
                    'load': self.load.id,
                    'gross_weight': '10.000',
                    'quantity': 1,
                    'rate': 1000,
                }
                payload[field] = -1
                response = self.add_line(**payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_several_lines_on_the_same_load_are_allowed(self):
        first = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        second = self.add_line(
            load=self.load.id, gross_weight='20.000', quantity=2, rate=1000
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(len(second.data['lines']), 2)
        # The first line is untouched and the new one is appended.
        self.assertEqual(
            [line['id'] for line in second.data['lines']],
            [
                first.data['lines'][0]['id'],
                second.data['lines'][1]['id'],
            ],
        )
        self.assertNotEqual(
            first.data['lines'][0]['id'], second.data['lines'][1]['id']
        )

    def test_a_finished_load_is_refused(self):
        Load.objects.filter(pk=self.load.pk).update(
            finished_at='2026-01-01T10:00:00Z'
        )
        response = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'load_finished')

    def test_lines_ordered_by_creation(self):
        for gross in ['10.000', '20.000', '30.000']:
            self.add_line(
                load=self.load.id, gross_weight=gross, quantity=1, rate=1000
            )
        lines = self.client.get(self.detail_url()).data['lines']
        self.assertEqual(
            [line['gross_weight'] for line in lines],
            ['10.000', '20.000', '30.000'],
        )

    def test_patch_recalculates_the_line(self):
        created = self.add_line(
            load=self.load.id, gross_weight='103.500', quantity=5, rate=450000
        )
        line_id = created.data['lines'][0]['id']
        response = self.client.patch(
            self.line_url(line_id), {'gross_weight': '50.000'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        line = response.data['lines'][0]
        # 50.000 - 5.000 = 45.000 ; 45.000 * 450000 = 20250000
        self.assertEqual(line['net_weight'], '45.000')
        self.assertEqual(line['line_total'], 20250000)

    def test_patch_can_move_the_line_to_another_load(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=2, rate=1000
        )
        line_id = created.data['lines'][0]['id']
        response = self.client.patch(
            self.line_url(line_id), {'load': self.other_load.id}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        line = response.data['lines'][0]
        self.assertEqual(line['load'], self.other_load.id)
        self.assertEqual(line['product'], self.other_product.id)
        # 10.000 - (0.500 * 2) = 9.000
        self.assertEqual(line['net_weight'], '9.000')

    def test_patch_to_a_finished_load_is_refused(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        Load.objects.filter(pk=self.other_load.pk).update(
            finished_at='2026-01-01T10:00:00Z'
        )
        response = self.client.patch(
            self.line_url(created.data['lines'][0]['id']),
            {'load': self.other_load.id},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'load_finished')

    def test_patch_to_an_empty_net_weight_is_rejected(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        response = self.client.patch(
            self.line_url(created.data['lines'][0]['id']),
            {'quantity': 50},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('net_weight', response.data)

    def test_delete_returns_the_full_sale(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        response = self.client.delete(self.line_url(created.data['lines'][0]['id']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data.keys()),
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
        self.assertEqual(response.data['lines'], [])
        self.assertEqual(response.data['total_amount'], 0)

    def test_line_of_another_sale_is_not_reachable(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        line_id = created.data['lines'][0]['id']
        other_sale = self.new_sale()
        self.assertEqual(
            self.client.delete(self.line_url(line_id, other_sale)).status_code, 404
        )


class PorterageTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.sale_id = self.new_sale()
        self.use_porterage(4000)

    def porterage_of(self, response):
        return response.data['porterage']['amount']

    def test_adding_a_line_adds_the_gross_weight_delta(self):
        # 16.500 * 4000 = 66000
        response = self.add_line(
            load=self.load.id, gross_weight='16.500', quantity=1, rate=1000
        )
        self.assertEqual(self.porterage_of(response), 66000)
        # 10.000 * 4000 = 40000 on top
        response = self.add_line(
            load=self.other_load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        self.assertEqual(self.porterage_of(response), 106000)

    def test_rounding_is_applied_to_the_running_amount(self):
        self.use_porterage(4000, round_enabled=True)
        self.put_porterage(400000)
        response = self.add_line(
            load=self.load.id, gross_weight='16.500', quantity=1, rate=1000
        )
        # 400000 + 66000 = 466000 -> 450000
        self.assertEqual(self.porterage_of(response), 450000)

    def test_rounding_is_skipped_when_disabled(self):
        self.put_porterage(400000)
        response = self.add_line(
            load=self.load.id, gross_weight='16.500', quantity=1, rate=1000
        )
        self.assertEqual(self.porterage_of(response), 466000)

    def test_deleting_a_line_subtracts_the_delta(self):
        created = self.add_line(
            load=self.load.id, gross_weight='16.500', quantity=1, rate=1000
        )
        response = self.client.delete(
            self.line_url(created.data['lines'][0]['id'])
        )
        self.assertEqual(self.porterage_of(response), 0)

    def test_porterage_never_goes_below_zero(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        self.put_porterage(1000)
        response = self.client.delete(
            self.line_url(created.data['lines'][0]['id'])
        )
        self.assertEqual(self.porterage_of(response), 0)

    def test_editing_a_quantity_or_rate_moves_nothing(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        before = self.porterage_of(created)
        response = self.client.patch(
            self.line_url(created.data['lines'][0]['id']),
            {'quantity': 4, 'rate': 9999},
            format='json',
        )
        self.assertEqual(self.porterage_of(response), before)

    def test_editing_the_weight_applies_only_the_difference(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        before = self.porterage_of(created)
        # 20.000 - 10.000 = 10.000 more kilos * 4000 = 40000
        response = self.client.patch(
            self.line_url(created.data['lines'][0]['id']),
            {'gross_weight': '20.000'},
            format='json',
        )
        self.assertEqual(self.porterage_of(response), before + 40000)
        # And back down again.
        response = self.client.patch(
            self.line_url(created.data['lines'][0]['id']),
            {'gross_weight': '5.000'},
            format='json',
        )
        self.assertEqual(self.porterage_of(response), before - 20000)

    def test_moving_a_line_to_another_load_applies_the_difference(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        before = self.porterage_of(created)
        response = self.client.patch(
            self.line_url(created.data['lines'][0]['id']),
            {'load': self.other_load.id},
            format='json',
        )
        # The gross weight did not change, so neither does the fee.
        self.assertEqual(self.porterage_of(response), before)

    def test_without_porters_nothing_moves(self):
        self.use_porterage(4000, works=False)
        response = self.add_line(
            load=self.load.id, gross_weight='16.500', quantity=1, rate=1000
        )
        self.assertEqual(self.porterage_of(response), 0)

    def test_without_porters_a_manual_amount_survives_a_new_line(self):
        self.use_porterage(4000, works=False)
        self.put_porterage(75000)
        response = self.add_line(
            load=self.load.id, gross_weight='16.500', quantity=1, rate=1000
        )
        self.assertEqual(self.porterage_of(response), 75000)

    def test_a_manual_amount_becomes_the_base_for_later_deltas(self):
        self.put_porterage(100000)
        response = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        # 100000 + 40000 = 140000
        self.assertEqual(self.porterage_of(response), 140000)

    def test_manual_amount_is_stored_exactly_without_rounding(self):
        self.use_porterage(4000, round_enabled=True)
        response = self.put_porterage(123456)
        self.assertEqual(self.porterage_of(response), 123456)

    def test_negative_manual_amount_is_rejected(self):
        response = self.put_porterage(-1)
        self.assertEqual(response.status_code, 400)
        self.assertIn('amount', response.data)

    def test_porterage_is_part_of_the_total(self):
        response = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        self.assertEqual(response.data['total_amount'], 9000 + 40000)


class RoundPorterageTests(SalesTestCase):
    def test_documented_examples(self):
        self.assertEqual(round_porterage(120000), 100000)
        self.assertEqual(round_porterage(126000), 150000)
        self.assertEqual(round_porterage(125000), 150000)
        self.assertEqual(round_porterage(20000), 50000)

    def test_non_positive_amounts_are_zero(self):
        self.assertEqual(round_porterage(0), 0)
        self.assertEqual(round_porterage(-1), 0)

    def test_exact_multiples_are_unchanged(self):
        self.assertEqual(round_porterage(50000), 50000)
        self.assertEqual(round_porterage(150000), 150000)


class SettlementTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.sale_id = self.new_sale()
        # 10.000 * 100 = 1000, so the total is exactly the spec's example.
        self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=0, rate=100
        )
        self.put_porterage(0)

    def test_summary_math_with_cash_and_a_negative_account(self):
        # total 1000, paid 1500 cash, we owe the buyer 500 -> nothing remains
        self.pay(amount=1500)
        self.set_account(-500)
        summary = self.client.get(self.detail_url()).data['summary']
        self.assertEqual(summary['total'], 1000)
        self.assertEqual(summary['paid'], 1500)
        self.assertEqual(summary['accounted'], -500)
        self.assertEqual(summary['remaining'], 0)

    def test_remaining_counts_payments_and_account(self):
        summary = self.client.get(self.detail_url()).data['summary']
        self.assertEqual(summary['remaining'], 1000)
        self.pay(amount=400)
        self.set_account(600)
        summary = self.client.get(self.detail_url()).data['summary']
        self.assertEqual(summary['remaining'], 0)

    def test_bank_is_required_for_pos_and_card_transfer(self):
        for method in ['pos', 'card_transfer']:
            with self.subTest(method=method):
                response = self.pay(method=method)
                self.assertEqual(response.status_code, 400)
                self.assertIn('bank', response.data)

    def test_bank_must_be_absent_for_cheque_and_cash(self):
        for method in ['cheque', 'cash']:
            with self.subTest(method=method):
                response = self.pay(method=method, bank=self.bank.id)
                self.assertEqual(response.status_code, 400)
                self.assertIn('bank', response.data)

    def test_valid_method_and_bank_combinations(self):
        for method, bank in [
            ('pos', self.bank.id),
            ('card_transfer', self.bank.id),
            ('cheque', None),
            ('cash', None),
        ]:
            with self.subTest(method=method):
                self.assertEqual(self.pay(method=method, bank=bank).status_code, 201)

    def test_payment_amount_must_be_positive(self):
        response = self.pay(amount=0)
        self.assertEqual(response.status_code, 400)
        self.assertIn('amount', response.data)

    def test_account_put_sets_buyer_and_amount(self):
        response = self.set_account(750)
        self.assertEqual(
            response.data['account'],
            {
                'party': {'id': self.party.id, 'name': 'رضایی', 'label': 'همسایه'},
                'amount': 750,
            },
        )
        invoice = Invoice.objects.get(sale_id=self.sale_id)
        self.assertEqual(invoice.buyer_id, self.party.id)
        self.assertEqual(invoice.buyer_amount, 750)

    def test_account_amount_must_not_be_zero(self):
        response = self.set_account(0)
        self.assertEqual(response.status_code, 400)
        self.assertIn('amount', response.data)

    def test_account_delete_clears_the_buyer(self):
        self.set_account(750)
        response = self.client.delete(
            reverse('sale-account', args=[self.sale_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['account'])
        invoice = Invoice.objects.get(sale_id=self.sale_id)
        self.assertIsNone(invoice.buyer_id)
        self.assertEqual(invoice.buyer_amount, 0)

    def test_payment_patch_and_delete(self):
        created = self.pay(method='pos', bank=self.bank.id, amount=1000)
        payment_id = created.data['payments'][0]['id']
        patched = self.client.patch(
            reverse('sale-payment-detail', args=[self.sale_id, payment_id]),
            {'amount': 250},
            format='json',
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data['payments'][0]['amount'], 250)
        self.assertEqual(patched.data['payments'][0]['bank_name'], 'بانک ملت')

        patched = self.client.patch(
            reverse('sale-payment-detail', args=[self.sale_id, payment_id]),
            {'method': 'cash', 'bank': None},
            format='json',
        )
        self.assertEqual(patched.status_code, 200)
        self.assertIsNone(patched.data['payments'][0]['bank'])

        deleted = self.client.delete(
            reverse('sale-payment-detail', args=[self.sale_id, payment_id])
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.data['payments'], [])

    def test_patch_to_a_method_that_needs_a_bank_is_rejected(self):
        created = self.pay(method='cash', amount=100)
        payment_id = created.data['payments'][0]['id']
        response = self.client.patch(
            reverse('sale-payment-detail', args=[self.sale_id, payment_id]),
            {'method': 'pos'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('bank', response.data)


class FinalizeTests(SalesTestCase):
    def test_no_lines_is_a_409(self):
        sale_id = self.new_sale()
        response = self.finalize(sale_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'no_lines')

    def test_unsettled_is_a_409_that_carries_the_remaining(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000)
        self.put_porterage(0, sale_id)
        response = self.finalize(sale_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'not_settled')
        self.assertEqual(response.json()['remaining'], 10000)

    def test_settled_without_a_buyer_is_final(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000)
        self.put_porterage(0, sale_id)
        self.settle_exactly(sale_id)
        response = self.finalize(sale_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'final')
        self.assertIsNotNone(response.data['finalized_at'])

    def test_a_positive_buyer_amount_makes_it_credit(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000)
        self.put_porterage(0, sale_id)
        self.set_account(10000, sale_id)
        response = self.finalize(sale_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'credit')

    def test_a_negative_buyer_amount_stays_final(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000)
        self.put_porterage(0, sale_id)
        # Pay more than the total and owe the buyer the difference.
        self.pay(amount=15000, sale_id=sale_id)
        self.set_account(-5000, sale_id)
        response = self.finalize(sale_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'final')

    def test_finalizing_twice_changes_nothing(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000)
        self.put_porterage(0, sale_id)
        self.settle_exactly(sale_id)
        first = self.finalize(sale_id)
        stamp = Sale.objects.get(pk=sale_id).finalized_at
        second = self.finalize(sale_id)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['status'], first.data['status'])
        self.assertEqual(Sale.objects.get(pk=sale_id).finalized_at, stamp)


class ReopenTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.sale_id = self.new_sale()
        self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=0, rate=1000
        )
        self.put_porterage(0)
        self.settle_exactly()
        self.assertEqual(self.finalize().status_code, 200)

    def assert_draft(self):
        sale = Sale.objects.get(pk=self.sale_id)
        self.assertEqual(sale.status, 'draft')
        self.assertIsNone(sale.finalized_at)

    def test_adding_a_line_reopens_the_sale(self):
        response = self.add_line(
            load=self.other_load.id, gross_weight='5.000', quantity=1, rate=1000
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'draft')
        self.assert_draft()

    def test_editing_a_line_reopens_the_sale(self):
        line_id = InvoiceLine.objects.get(invoice__sale_id=self.sale_id).id
        self.client.patch(
            self.line_url(line_id), {'rate': 2000}, format='json'
        )
        self.assert_draft()

    def test_deleting_a_line_reopens_the_sale(self):
        line_id = InvoiceLine.objects.get(invoice__sale_id=self.sale_id).id
        self.client.delete(self.line_url(line_id))
        self.assert_draft()

    def test_a_payment_reopens_the_sale(self):
        self.pay(amount=10)
        self.assert_draft()

    def test_editing_a_payment_reopens_the_sale(self):
        payment_id = Payment.objects.get(sale_id=self.sale_id).id
        self.client.patch(
            reverse('sale-payment-detail', args=[self.sale_id, payment_id]),
            {'amount': 20},
            format='json',
        )
        self.assert_draft()

    def test_deleting_a_payment_reopens_the_sale(self):
        payment_id = Payment.objects.get(sale_id=self.sale_id).id
        self.client.delete(
            reverse('sale-payment-detail', args=[self.sale_id, payment_id])
        )
        self.assert_draft()

    def test_setting_the_porterage_reopens_the_sale(self):
        self.put_porterage(500)
        self.assert_draft()

    def test_setting_the_account_reopens_the_sale(self):
        self.set_account(1)
        self.assert_draft()

    def test_reading_does_not_reopen_the_sale(self):
        self.client.get(self.detail_url())
        self.client.get(reverse('sale-list-create'))
        sale = Sale.objects.get(pk=self.sale_id)
        self.assertEqual(sale.status, 'final')
        self.assertIsNotNone(sale.finalized_at)


class SaleDeletionTests(SalesTestCase):
    def test_a_draft_cascades(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=1, rate=1000)
        self.pay(amount=100, sale_id=sale_id)
        response = self.client.delete(self.detail_url(sale_id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Sale.objects.filter(pk=sale_id).exists())
        self.assertFalse(Invoice.objects.filter(sale_id=sale_id).exists())
        self.assertFalse(Porterage.objects.filter(sale_id=sale_id).exists())
        self.assertFalse(Payment.objects.filter(sale_id=sale_id).exists())
        self.assertFalse(
            InvoiceLine.objects.filter(invoice__sale_id=sale_id).exists()
        )

    def test_a_final_sale_is_refused(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000)
        self.put_porterage(0, sale_id)
        self.settle_exactly(sale_id)
        self.finalize(sale_id)
        response = self.client.delete(self.detail_url(sale_id))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'not_deletable')
        self.assertTrue(Sale.objects.filter(pk=sale_id).exists())

    def test_a_credit_sale_is_refused(self):
        sale_id = self.new_sale()
        self.add_line(sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000)
        self.put_porterage(0, sale_id)
        self.set_account(10000, sale_id)
        self.finalize(sale_id)
        self.assertEqual(
            self.client.delete(self.detail_url(sale_id)).json()['code'],
            'not_deletable',
        )


class SaleListTests(SalesTestCase):
    def make_sales(self, count, buyer=None):
        ids = []
        for index in range(count):
            sale_id = self.new_sale()
            self.add_line(
                sale_id,
                load=self.load.id,
                gross_weight='10.000',
                quantity=0,
                rate=1000,
            )
            if buyer is not None:
                self.set_account(100, sale_id, party=buyer)
            ids.append(sale_id)
        return ids

    def stamp(self, sale_id, moment):
        Sale.objects.filter(pk=sale_id).update(created_at=moment)

    def test_shape_of_an_item(self):
        self.make_sales(1)
        response = self.client.get(reverse('sale-list-create'))
        self.assertEqual(
            sorted(response.data.keys()), ['next', 'previous', 'results']
        )
        item = response.data['results'][0]
        self.assertEqual(
            sorted(item.keys()),
            ['created_at', 'id', 'party', 'products', 'status', 'total_amount'],
        )

    def test_order_is_created_at_then_id_descending(self):
        from datetime import datetime, timedelta, timezone

        ids = self.make_sales(3)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Same timestamp for two of them, so the id decides.
        self.stamp(ids[0], base)
        self.stamp(ids[1], base + timedelta(seconds=1))
        self.stamp(ids[2], base)
        response = self.client.get(reverse('sale-list-create'))
        self.assertEqual(
            [item['id'] for item in response.data['results']], [ids[1], ids[2], ids[0]]
)

    def test_status_filter(self):
        draft_id = self.make_sales(1)[0]
        settled_id = self.make_sales(1)[0]
        self.settle_exactly(settled_id)
        self.finalize(settled_id)
        response = self.client.get(
            reverse('sale-list-create'), {'status': 'draft'}
        )
        self.assertEqual([item['id'] for item in response.data['results']], [draft_id])
        response = self.client.get(
            reverse('sale-list-create'), {'status': 'final'}
        )
        self.assertEqual(
            [item['id'] for item in response.data['results']], [settled_id]
        )
        response = self.client.get(
            reverse('sale-list-create'), {'status': 'credit'}
        )
        self.assertEqual(response.data['results'], [])

    def test_invalid_status_is_a_400(self):
        response = self.client.get(
            reverse('sale-list-create'), {'status': 'nonsense'}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('status', response.data)

    def test_party_filter(self):
        other = Party.objects.create(name='کریمی', label='دکان')
        with_party = self.make_sales(1, buyer=self.party)[0]
        self.make_sales(1, buyer=other)
        response = self.client.get(
            reverse('sale-list-create'), {'party': self.party.id}
        )
        self.assertEqual([item['id'] for item in response.data['results']], [with_party])

    def test_products_are_distinct_and_in_line_order(self):
        sale_id = self.new_sale()
        third = Product.objects.create(
            name='گوجه', sticker='tomato', background='#C62828'
        )
        third_load = Load.objects.create(
            product=third, label='الف', tare_weight='0.000'
        )
        for load in [self.other_load, self.load, self.other_load, third_load]:
            self.add_line(
                sale_id, load=load.id, gross_weight='10.000', quantity=0, rate=1000
            )
        item = self.client.get(reverse('sale-list-create')).data['results'][0]
        self.assertEqual(
            item['products'],
            [
                {'id': self.other_product.id, 'sticker': 'cucumber', 'background': '#2E7D32'},
                {'id': self.product.id, 'sticker': 'apple', 'background': '#2E7D32'},
                {'id': third.id, 'sticker': 'tomato', 'background': '#C62828'},
            ],
        )

    def test_party_is_the_invoice_buyer(self):
        sale_id = self.new_sale()
        self.set_account(500, sale_id)
        item = self.client.get(reverse('sale-list-create')).data['results'][0]
        self.assertEqual(
            item['party'],
            {'id': self.party.id, 'name': 'رضایی', 'label': 'همسایه'},
        )

    def count_queries(self):
        url = reverse('sale-list-create')
        self.client.get(url)
        with CaptureQueriesContext(connection) as context:
            self.client.get(url)
        return len(context.captured_queries)

    def test_query_count_is_constant_across_page_sizes(self):
        self.make_sales(1)
        with_one = self.count_queries()
        self.make_sales(24)
        with_twenty_five = self.count_queries()
        self.assertEqual(with_one, with_twenty_five)

    def test_cursor_paging_survives_a_sale_created_in_between(self):
        from datetime import datetime, timedelta, timezone

        ids = self.make_sales(35)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index, sale_id in enumerate(ids):
            self.stamp(sale_id, base + timedelta(seconds=index))

        first = self.client.get(reverse('sale-list-create'))
        self.assertEqual(len(first.data['results']), 30)
        self.assertIsNotNone(first.data['next'])

        # A new (newest) sale appears between the two page requests.
        inserted = self.new_sale()
        self.stamp(inserted, base + timedelta(seconds=100))

        second = self.client.get(first.data['next'])
        self.assertEqual(second.status_code, 200)
        first_ids = [item['id'] for item in first.data['results']]
        second_ids = [item['id'] for item in second.data['results']]
        self.assertEqual(len(second_ids), 5)
        # Nothing repeated and nothing skipped.
        self.assertEqual(set(first_ids) & set(second_ids), set())
        self.assertEqual(sorted(first_ids + second_ids), sorted(ids))
        self.assertNotIn(inserted, first_ids + second_ids)


class PorterageSettingsEndpointTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('porterage-settings')

    def test_get_returns_the_singleton(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        # The base fixture leaves the rate at zero.
        self.assertEqual(
            response.data,
            {
                'works_with_porters': True,
                'rate_per_kg': 0,
                'round_enabled': False,
            },
        )

    def test_the_row_is_created_once_at_pk_one(self):
        PorterageSettings.objects.all().delete()
        self.client.get(self.url)
        self.client.get(self.url)
        self.assertEqual(PorterageSettings.objects.count(), 1)
        self.assertEqual(PorterageSettings.objects.get().pk, 1)

    def test_patch_updates_the_singleton(self):
        response = self.client.patch(
            self.url,
            {'rate_per_kg': 2500, 'round_enabled': True, 'works_with_porters': False},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rate_per_kg'], 2500)
        self.assertTrue(response.data['round_enabled'])
        self.assertFalse(response.data['works_with_porters'])

    def test_negative_rate_is_rejected(self):
        response = self.client.patch(self.url, {'rate_per_kg': -1}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('rate_per_kg', response.data)

    def test_only_the_singleton_row_can_exist(self):
        from django.db import transaction

        PorterageSettings.objects.all().delete()
        self.client.get(self.url)
        # A second row is forced onto pk=1 and so cannot be inserted.
        with self.assertRaises(Exception):
            # The inner block keeps the failed insert from poisoning the
            # surrounding transaction.
            with transaction.atomic():
                PorterageSettings.objects.create(rate_per_kg=7)
        self.assertEqual(PorterageSettings.objects.count(), 1)
        # Updating through the model still works.
        row = PorterageSettings.objects.get()
        row.rate_per_kg = 7
        row.save()
        self.assertEqual(PorterageSettings.objects.get().rate_per_kg, 7)
        self.assertEqual(PorterageSettings.objects.count(), 1)

    def test_the_row_cannot_be_deleted_through_the_model(self):
        row = get_porterage_settings()
        with self.assertRaises(ValueError):
            row.delete()

    def test_only_get_and_patch_are_allowed(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)


class SaleCreationTests(SalesTestCase):
    def test_a_new_sale_is_an_empty_draft(self):
        response = self.client.post(
            reverse('sale-list-create'), {}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        sale_id = response.data['id']
        self.assertEqual(response.data['status'], 'draft')
        self.assertEqual(response.data['total_amount'], 0)
        self.assertEqual(response.data['lines'], [])
        self.assertEqual(response.data['payments'], [])
        self.assertEqual(response.data['porterage'], {'amount': 0})
        self.assertIsNone(response.data['account'])
        self.assertEqual(
            response.data['summary'],
            {'total': 0, 'paid': 0, 'accounted': 0, 'remaining': 0},
        )
        # The invoice and the porterage arrive with it.
        self.assertEqual(Invoice.objects.filter(sale_id=sale_id).count(), 1)
        self.assertEqual(Porterage.objects.filter(sale_id=sale_id).count(), 1)

    def test_totals_are_maintained_by_the_server(self):
        sale_id = self.new_sale()
        first = self.add_line(
            sale_id, load=self.load.id, gross_weight='10.000', quantity=0, rate=1000
        )
        second = self.add_line(
            sale_id, load=self.other_load.id, gross_weight='4.000', quantity=0, rate=500
        )
        self.assertEqual(second.data['total_amount'], 10000 + 2000)
        deleted = self.client.delete(
            self.line_url(second.data['lines'][-1]['id'], sale_id)
        )
        self.assertEqual(deleted.data['total_amount'], 10000)


class LoadInteractionTests(SalesTestCase):
    """A load that has been sold can never be removed."""

    def setUp(self):
        super().setUp()
        self.sale_id = self.new_sale()

    def test_deleting_a_used_load_is_a_409(self):
        self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        response = self.client.delete(
            reverse('load-detail', args=[self.load.id])
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'in_use')
        self.assertIn('detail', response.json())
        self.assertTrue(Load.objects.filter(pk=self.load.pk).exists())

    def test_an_unused_load_can_still_be_deleted(self):
        response = self.client.delete(
            reverse('load-detail', args=[self.other_load.id])
        )
        self.assertEqual(response.status_code, 204)

    def test_finishing_a_load_after_it_was_sold_leaves_its_lines_alone(self):
        created = self.add_line(
            load=self.load.id, gross_weight='10.000', quantity=1, rate=1000
        )
        line_id = created.data['lines'][0]['id']
        # Finish it through the inventory endpoint.
        self.assertEqual(
            self.client.post(reverse('load-finish', args=[self.load.id])).status_code,
            200,
        )
        # The existing line is untouched.
        response = self.client.get(self.detail_url())
        self.assertEqual(len(response.data['lines']), 1)
        self.assertEqual(response.data['lines'][0]['id'], line_id)
        # But no new line may join it.
        refused = self.add_line(
            load=self.load.id, gross_weight='5.000', quantity=1, rate=1000
        )
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()['code'], 'load_finished')
