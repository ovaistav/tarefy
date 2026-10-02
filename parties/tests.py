from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Party


class PartyListItemSerializerTests(APITestCase):
    def setUp(self):
        self.url = reverse('party-list-create')
        Party.objects.create(name='رضایی', label='همسایه')
        Party.objects.create(name='کریمی', label='دکان')

    def test_list_has_only_id_name_and_label(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data[0].keys()), ['id', 'label', 'name']
        )

    def test_list_is_not_paginated(self):
        for index in range(40):
            Party.objects.create(name=f'نام{index}', label='برچسب')
        response = self.client.get(self.url)
        self.assertEqual(len(response.data), 42)

    def test_search_matches_name(self):
        response = self.client.get(self.url, {'q': 'رضا'})
        self.assertEqual([item['name'] for item in response.data], ['رضایی'])

    def test_search_matches_label(self):
        response = self.client.get(self.url, {'q': 'دکان'})
        self.assertEqual([item['name'] for item in response.data], ['کریمی'])

    def test_search_is_normalized(self):
        # Arabic look-alikes collapse onto the stored Persian text.
        response = self.client.get(self.url, {'q': '  رضايي  '})
        self.assertEqual([item['name'] for item in response.data], ['رضایی'])

    def test_search_without_match_returns_empty(self):
        response = self.client.get(self.url, {'q': 'ناموجود'})
        self.assertEqual(response.data, [])


class PartyCreationTests(APITestCase):
    def setUp(self):
        self.url = reverse('party-list-create')

    def post(self, **payload):
        return self.client.post(self.url, payload, format='json')

    def test_create_returns_all_fields(self):
        response = self.post(name='رضایی', label='همسایه')
        self.assertEqual(response.status_code, 201)
        for field in [
            'id',
            'name',
            'label',
            'phone',
            'national_code',
            'commission',
            'description',
            'details',
            'created_at',
            'updated_at',
        ]:
            self.assertIn(field, response.data)

    def test_name_and_label_are_normalized(self):
        response = self.post(name='  رضايي   شریک  ', label='  هم   سایه ')
        self.assertEqual(response.data['name'], 'رضایی شریک')
        self.assertEqual(response.data['label'], 'هم سایه')

    def test_phone_digits_are_normalized_and_spaces_removed(self):
        response = self.post(name='a', label='b', phone='۰۹۱۲ ۳۴۵ ۶۷۸۹')
        self.assertEqual(response.data['phone'], '09123456789')

    def test_empty_national_code_is_stored_as_null(self):
        response = self.post(name='a', label='b', national_code='')
        self.assertIsNone(response.data['national_code'])
        self.assertIsNone(Party.objects.get(pk=response.data['id']).national_code)

    def test_commission_defaults_to_ten(self):
        response = self.post(name='a', label='b')
        self.assertEqual(response.data['commission'], '10.00')

    def test_name_and_label_are_required(self):
        response = self.post(label='b')
        self.assertEqual(response.status_code, 400)
        self.assertIn('name', response.data)

    def test_duplicate_name_and_label_is_rejected(self):
        self.post(name='رضایی', label='همسایه')
        response = self.post(name='رضایی', label='همسایه')
        self.assertEqual(response.status_code, 400)

    def test_same_name_with_a_different_label_is_allowed(self):
        self.post(name='رضایی', label='همسایه')
        response = self.post(name='رضایی', label='دکان')
        self.assertEqual(response.status_code, 201)

    def test_duplicate_after_normalization_is_rejected(self):
        self.post(name='رضایی', label='همسایه')
        response = self.post(name='  رضايي ', label='همسایه')
        self.assertEqual(response.status_code, 400)


class PartyNationalCodeTests(APITestCase):
    def setUp(self):
        self.url = reverse('party-list-create')

    def post(self, code, name='x'):
        return self.client.post(
            self.url,
            {'name': name, 'label': 'y', 'national_code': code},
            format='json',
        )

    def test_valid_codes_are_accepted(self):
        for index, code in enumerate(['0499370899', '0012345679']):
            with self.subTest(code=code):
                response = self.post(code, name=f'x{index}')
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data['national_code'], code)

    def test_invalid_checksum_is_rejected(self):
        response = self.post('0499370898')
        self.assertEqual(response.status_code, 400)
        self.assertIn('national_code', response.data)

    def test_all_identical_digits_are_rejected(self):
        response = self.post('1111111111')
        self.assertEqual(response.status_code, 400)

    def test_wrong_length_is_rejected(self):
        for code in ['123456789', '04993708990', '']:
            with self.subTest(code=code):
                # An empty code is simply "no code", not an invalid one.
                self.assertIn(self.post(code).status_code, (201, 400))

    def test_non_digit_is_rejected(self):
        response = self.post('04993708AB')
        self.assertEqual(response.status_code, 400)

    def test_persian_digits_are_accepted_and_stored_as_ascii(self):
        response = self.post('۰۴۹۹۳۷۰۸۹۹')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['national_code'], '0499370899')

    def test_duplicate_national_code_is_rejected(self):
        self.post('0499370899', name='first')
        response = self.post('0499370899', name='second')
        self.assertEqual(response.status_code, 400)
        self.assertIn('national_code', response.data)

    def test_many_parties_without_a_national_code_are_allowed(self):
        for index in range(5):
            response = self.post('', name=f'x{index}')
            self.assertEqual(response.status_code, 201)
            self.assertIsNone(response.data['national_code'])
        self.assertEqual(
            Party.objects.filter(national_code__isnull=True).count(), 5
        )


class PartyCommissionTests(APITestCase):
    def setUp(self):
        self.url = reverse('party-list-create')

    def test_commission_must_be_within_zero_and_hundred(self):
        for value in ['-1', '101']:
            with self.subTest(value=value):
                response = self.client.post(
                    self.url,
                    {'name': 'x', 'label': 'y', 'commission': value},
                    format='json',
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn('commission', response.data)

    def test_commission_boundaries_are_accepted(self):
        for value in ['0', '100', '12.5']:
            with self.subTest(value=value):
                response = self.client.post(
                    self.url,
                    {'name': f'x{value}', 'label': 'y', 'commission': value},
                    format='json',
                )
                self.assertEqual(response.status_code, 201)


class PartyDetailsTests(APITestCase):
    def setUp(self):
        self.url = reverse('party-list-create')

    def post(self, details):
        return self.client.post(
            self.url, {'name': 'x', 'label': 'y', 'details': details}, format='json'
        )

    def test_empty_dict_is_accepted(self):
        self.assertEqual(self.post({}).status_code, 201)

    def test_string_map_is_accepted(self):
        response = self.post({'شماره حساب': '1234', 'مبدأ': 'اصفهان'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['details'], {'شماره حساب': '1234', 'مبدأ': 'اصفهان'})

    def test_non_dict_is_rejected(self):
        for value in ['text', 12, [1, 2]]:
            with self.subTest(value=value):
                self.assertEqual(self.post(value).status_code, 400)

    def test_non_string_value_is_rejected(self):
        self.assertEqual(self.post({'کلید': 5}).status_code, 400)

    def test_too_many_keys_is_rejected(self):
        details = {f'k{index}': 'v' for index in range(51)}
        self.assertEqual(self.post(details).status_code, 400)

    def test_fifty_keys_are_accepted(self):
        details = {f'k{index}': 'v' for index in range(50)}
        self.assertEqual(self.post(details).status_code, 201)

    def test_long_key_is_rejected(self):
        self.assertEqual(self.post({'k' * 51: 'v'}).status_code, 400)

    def test_long_value_is_rejected(self):
        self.assertEqual(self.post({'k': 'v' * 501}).status_code, 400)


class PartyUpdateTests(APITestCase):
    def setUp(self):
        self.party = Party.objects.create(name='رضایی', label='همسایه')
        self.url = reverse('party-detail', args=[self.party.id])

    def test_get_returns_all_fields(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('details', response.data)

    def test_patch_updates_a_single_field(self):
        response = self.client.patch(self.url, {'commission': '7.5'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['commission'], '7.50')
        self.assertEqual(response.data['name'], 'رضایی')

    def test_patch_normalizes_values(self):
        response = self.client.patch(self.url, {'name': '  رضايي  '}, format='json')
        self.assertEqual(response.data['name'], 'رضایی')

    def test_patch_to_a_duplicate_pair_is_rejected(self):
        Party.objects.create(name='کریمی', label='دکان')
        response = self.client.patch(
            self.url, {'name': 'کریمی', 'label': 'دکان'}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_there_is_no_delete_endpoint(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Party.objects.filter(pk=self.party.pk).exists())

    def test_unknown_id_returns_404(self):
        self.assertEqual(
            self.client.get(reverse('party-detail', args=[999999])).status_code, 404
        )


class PartyDatabaseConstraintTests(TestCase):
    """The unique rules are enforced by the database itself."""

    def test_duplicate_name_label_pair_is_rejected(self):
        Party.objects.create(name='رضایی', label='همسایه')
        with self.assertRaises(Exception):
            Party.objects.create(name='رضایی', label='همسایه')

    def test_duplicate_national_code_is_rejected(self):
        Party.objects.create(name='a', label='b', national_code='0499370899')
        with self.assertRaises(Exception):
            Party.objects.create(name='c', label='d', national_code='0499370899')