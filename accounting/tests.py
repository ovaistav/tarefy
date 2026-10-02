from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Bank


class BankListTests(APITestCase):
    def setUp(self):
        self.url = reverse('bank-list')

    def test_list_is_ordered_by_name(self):
        Bank.objects.create(name='بانک ملت')
        Bank.objects.create(name='بانک ملی')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['name'] for item in response.data], ['بانک ملت', 'بانک ملی']
        )

    def test_items_have_only_id_and_name(self):
        Bank.objects.create(name='بانک ملت')
        item = self.client.get(self.url).data[0]
        self.assertEqual(sorted(item.keys()), ['id', 'name'])

    def test_names_are_normalized(self):
        bank = Bank.objects.create(name='  بانک  ملت ')
        self.assertEqual(bank.name, 'بانک ملت')

    def test_duplicate_names_are_rejected_by_the_database(self):
        Bank.objects.create(name='بانک ملت')
        with self.assertRaises(Exception):
            Bank.objects.create(name='بانک ملت')

    def test_endpoints_are_read_only(self):
        response = self.client.post(self.url, {'name': 'بانک صادرات'}, format='json')
        self.assertEqual(response.status_code, 405)
        self.assertEqual(Bank.objects.count(), 0)


class BankAdminTests(TestCase):
    def test_bank_is_registered_in_the_admin(self):
        from django.contrib import admin

        self.assertIn(Bank, admin.site._registry)