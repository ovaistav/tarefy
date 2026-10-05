from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from catalog.models import Product

from .models import Load


class LoadCreationTests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(name='خیار')
        self.other_product = Product.objects.create(name='گوجه')
        self.url = reverse('load-list-create')

    def post(self, **payload):
        return self.client.post(self.url, payload, format='json')

    def test_first_load_without_label_is_created_with_empty_label(self):
        response = self.post(product=self.product.id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['label'], '')
        self.assertEqual(response.data['product'], self.product.id)
        self.assertEqual(response.data['product_name'], 'خیار')

    def test_second_post_without_existing_labels_is_stale(self):
        self.post(product=self.product.id)
        response = self.post(product=self.product.id, label='الف')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'stale_state')
        self.assertIn('detail', response.json())

    def test_second_post_with_existing_labels_labels_both_loads(self):
        first = self.post(product=self.product.id)
        second = self.post(
            product=self.product.id,
            label='الف',
            existing_labels=[{'id': first.data['id'], 'label': 'ب'}],
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data['label'], 'الف')
        self.assertEqual(
            sorted(
                Load.objects.filter(product=self.product).values_list(
                    'label', flat=True
                )
            ),
            ['الف', 'ب'],
        )

    def test_third_post_with_only_a_new_label(self):
        first = self.post(product=self.product.id)
        self.post(
            product=self.product.id,
            label='الف',
            existing_labels=[{'id': first.data['id'], 'label': 'ب'}],
        )
        third = self.post(product=self.product.id, label='ج')
        self.assertEqual(third.status_code, 201)
        self.assertEqual(Load.objects.filter(finished_at__isnull=True).count(), 3)

    def test_duplicate_label_for_same_product_is_rejected(self):
        first = self.post(product=self.product.id)
        self.post(
            product=self.product.id,
            label='ب',
            existing_labels=[{'id': first.data['id'], 'label': 'الف'}],
        )
        # Both available loads are labeled now, so no existing_labels is sent.
        duplicate = self.post(product=self.product.id, label='ب')
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('label', duplicate.data)

    def test_same_label_on_a_different_product_is_accepted(self):
        self.post(product=self.product.id, label='الف')
        response = self.post(product=self.other_product.id, label='الف')
        self.assertEqual(response.status_code, 201)

    def test_missing_label_when_loads_exist_is_rejected(self):
        first = self.post(product=self.product.id)
        response = self.post(
            product=self.product.id,
            existing_labels=[{'id': first.data['id'], 'label': 'ب'}],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('label', response.data)

    def test_existing_labels_with_wrong_id_is_stale(self):
        first = self.post(product=self.product.id)
        other = self.post(product=self.other_product.id)
        response = self.post(
            product=self.product.id,
            label='الف',
            existing_labels=[{'id': other.data['id'], 'label': 'ب'}],
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'stale_state')

    def test_existing_labels_with_extra_id_is_stale(self):
        first = self.post(product=self.product.id)
        extra = self.post(product=self.other_product.id, label='ج')
        response = self.post(
            product=self.product.id,
            label='الف',
            existing_labels=[
                {'id': first.data['id'], 'label': 'ب'},
                {'id': extra.data['id'], 'label': 'د'},
            ],
        )
        self.assertEqual(response.status_code, 409)

    def test_duplicate_ids_in_existing_labels_are_stale(self):
        first = self.post(product=self.product.id)
        response = self.post(
            product=self.product.id,
            label='الف',
            existing_labels=[
                {'id': first.data['id'], 'label': 'ب'},
                {'id': first.data['id'], 'label': 'ج'},
            ],
        )
        self.assertEqual(response.status_code, 409)

    def test_arabic_and_persian_labels_are_duplicates(self):
        first = self.post(product=self.product.id, label='يک')
        # 'يک' is stored normalized to 'یک'.
        self.assertEqual(Load.objects.get(pk=first.data['id']).label, 'یک')

    def test_arabic_and_persian_variants_of_the_same_label_collide(self):
        first = self.post(product=self.product.id)
        # The submitted label normalizes to 'یک' and the new Arabic label
        # normalizes to the same string, so the two collide.
        response = self.post(
            product=self.product.id,
            label='  يک  ',
            existing_labels=[{'id': first.data['id'], 'label': 'یک'}],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('label', response.data)

    def test_arabic_and_persian_variants_of_kaf_collide(self):
        first = self.post(product=self.product.id)
        response = self.post(
            product=self.product.id,
            label='كدام',
            existing_labels=[{'id': first.data['id'], 'label': 'کدام'}],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('label', response.data)

    def test_label_is_normalized_before_saving(self):
        response = self.post(product=self.product.id, label='  بار   ي  ')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['label'], 'بار ی')


class LoadFinishTests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(name='خیار')
        self.load = Load.objects.create(product=self.product, label='الف')

    def test_finish_is_idempotent(self):
        url = reverse('load-finish', args=[self.load.id])
        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        finished_at = Load.objects.get(pk=self.load.id).finished_at
        self.assertIsNotNone(finished_at)

        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Load.objects.get(pk=self.load.id).finished_at, finished_at)

    def test_finish_unknown_id_returns_404(self):
        response = self.client.post(reverse('load-finish', args=[999999]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['detail'], 'موردی با این مشخصات یافت نشد.')

    def test_same_label_allowed_after_finish(self):
        self.client.post(reverse('load-finish', args=[self.load.id]))
        response = self.client.post(
            reverse('load-list-create'),
            {'product': self.product.id, 'label': 'الف'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)


class LoadRestoreTests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(name='خیار')
        # One finished load and one available load share the same label.
        self.finished = Load.objects.create(
            product=self.product, label='الف', finished_at='2026-01-01T10:00:00Z'
        )
        self.blocker = Load.objects.create(product=self.product, label='الف')

    def finish(self, load):
        Load.objects.filter(pk=load.pk).update(
            finished_at='2026-01-01T10:00:00Z'
        )

    def test_restore_conflicts_with_available_same_label(self):
        self.finish(self.finished)
        response = self.client.post(reverse('load-restore', args=[self.finished.id]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'restore_conflict')
        self.assertIn('برچسب', response.json()['detail'])

    def test_restore_succeeds_after_the_other_load_is_finished(self):
        self.finish(self.finished)
        self.client.post(reverse('load-finish', args=[self.blocker.id]))
        response = self.client.post(reverse('load-restore', args=[self.finished.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(Load.objects.get(pk=self.finished.id).finished_at)

    def test_restoring_an_available_load_is_ok(self):
        self.finish(self.blocker)
        response = self.client.post(reverse('load-restore', args=[self.blocker.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(Load.objects.get(pk=self.blocker.id).finished_at)

    def test_restore_unknown_id_returns_404(self):
        response = self.client.post(reverse('load-restore', args=[999999]))
        self.assertEqual(response.status_code, 404)


class LoadListTests(APITestCase):
    def setUp(self):
        self.product_a = Product.objects.create(
            name='آلو', sticker='apple', background='#2E7D32'
        )
        self.product_b = Product.objects.create(name='پیاز')
        self.available = Load.objects.create(product=self.product_a, label='الف')
        self.second_available = Load.objects.create(product=self.product_a, label='ب')
        self.finished = Load.objects.create(
            product=self.product_b, label='ب', finished_at='2026-01-01T10:00:00Z'
        )
        self.url = reverse('load-list-create')

    def load_ids(self, response, name):
        return [item['id'] for item in response.data[name]['loads']]

    def test_list_is_grouped_by_product_name(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(response.data.keys()), ['آلو', 'پیاز'])

    def test_group_carries_the_sticker_and_background_of_its_product(self):
        response = self.client.get(self.url)
        self.assertEqual(
            response.data['آلو'],
            {
                'product': self.product_a.id,
                'sticker': 'apple',
                'background': '#2E7D32',
                'loads': response.data['آلو']['loads'],
            },
        )
        self.assertEqual(response.data['پیاز']['sticker'], '')
        self.assertEqual(response.data['پیاز']['background'], '')

    def test_group_loads_keep_the_list_item_shape(self):
        response = self.client.get(self.url)
        self.assertEqual(
            sorted(response.data['آلو']['loads'][0].keys()),
            ['id', 'label', 'product', 'product_name', 'tare_weight'],
        )

    def test_all_loads_of_a_product_land_in_one_group(self):
        response = self.client.get(self.url)
        self.assertEqual(
            self.load_ids(response, 'آلو'), [self.available.id, self.second_available.id]
        )

    def test_list_without_filter_returns_finished_loads_too(self):
        response = self.client.get(self.url)
        self.assertEqual(self.load_ids(response, 'پیاز'), [self.finished.id])

    def test_available_true_filters_finished_loads(self):
        response = self.client.get(self.url, {'available': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.data.keys()), ['آلو'])
        self.assertEqual(
            self.load_ids(response, 'آلو'), [self.available.id, self.second_available.id]
        )

    def test_a_product_without_any_load_has_no_group(self):
        Product.objects.create(name='گوجه', sticker='tomato')
        response = self.client.get(self.url)
        self.assertNotIn('گوجه', response.data)

    def test_list_is_ordered_by_product_name_then_id(self):
        response = self.client.get(self.url)
        self.assertEqual(list(response.data.keys()), ['آلو', 'پیاز'])
        self.assertEqual(
            self.load_ids(response, 'آلو'), [self.available.id, self.second_available.id]
        )


class ProductTouchTests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(name='خیار')
        self.other = Product.objects.create(name='گوجه')
        self.url = reverse('load-list-create')
        self.catalog_url = reverse('product-list')

    def test_creating_a_load_touches_the_product(self):
        before = Product.objects.get(pk=self.product.id).updated_at
        self.client.post(
            self.url, {'product': self.product.id, 'label': 'الف'}, format='json'
        )
        self.assertGreater(
            Product.objects.get(pk=self.product.id).updated_at, before
        )

    def test_recently_used_product_comes_first_in_the_catalog(self):
        self.client.post(
            self.url, {'product': self.product.id, 'label': 'الف'}, format='json'
        )
        response = self.client.get(self.catalog_url)
        self.assertEqual([item['id'] for item in response.data], [self.product.id, self.other.id])


class DatabaseConstraintTests(TestCase):
    """The partial unique constraint is enforced by the database itself."""

    def setUp(self):
        from django.db import IntegrityError, transaction

        self.Product = Product
        self.transaction = transaction
        self.IntegrityError = IntegrityError
        self.product = Product.objects.create(name='خیار')

    def test_two_available_loads_with_the_same_label_are_rejected(self):
        Load.objects.create(product=self.product, label='الف')
        with self.assertRaises(self.IntegrityError):
            with self.transaction.atomic():
                Load.objects.create(product=self.product, label='الف')

    def test_two_available_loads_with_empty_label_are_rejected(self):
        Load.objects.create(product=self.product, label='')
        with self.assertRaises(self.IntegrityError):
            with self.transaction.atomic():
                Load.objects.create(product=self.product, label='')

    def test_finished_loads_are_excluded_from_the_constraint(self):
        Load.objects.create(
            product=self.product, label='الف', finished_at='2026-01-01T10:00:00Z'
        )
        second = Load.objects.create(product=self.product, label='الف')
        self.assertIsNone(second.finished_at)


class LoadTareWeightTests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(name='خیار', tare_weight='1.500')
        self.url = reverse('load-list-create')

    def test_tare_is_copied_from_the_product_on_creation(self):
        response = self.client.post(
            self.url, {'product': self.product.id, 'label': 'الف'}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tare_weight'], '1.500')
        self.assertEqual(
            str(Load.objects.get(pk=response.data['id']).tare_weight), '1.500'
        )

    def test_changing_the_product_default_does_not_rewrite_existing_loads(self):
        created = self.client.post(
            self.url, {'product': self.product.id, 'label': 'الف'}, format='json'
        )
        Product.objects.filter(pk=self.product.pk).update(tare_weight='9.000')
        # The load keeps the copy it was created with.
        self.assertEqual(
            str(Load.objects.get(pk=created.data['id']).tare_weight), '1.500'
        )

def test_list_items_include_the_tare(self):
        self.client.post(self.url, {'product': self.product.id}, format='json')
        response = self.client.get(self.url)
        self.assertEqual(
            sorted(response.data['خیار']['loads'][0].keys()),
            ['id', 'label', 'product', 'product_name', 'tare_weight'],
        )


class LoadPatchTests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(name='خیار', tare_weight='1.000')
        self.other = Product.objects.create(name='گوجه')
        self.load = Load.objects.create(
product=self.product, label='الف', tare_weight='1.000'
        )
        self.url = reverse('load-detail', args=[self.load.id])

    def patch(self, **payload):
        return self.client.patch(self.url, payload, format='json')

    def test_label_is_normalized_and_returned_in_the_list_shape(self):
        response = self.patch(label='  ب  الف ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['label'], 'ب الف')
        self.assertEqual(
            sorted(response.data.keys()),
            ['id', 'label', 'product', 'product_name', 'tare_weight'],
        )

    def test_tare_weight_can_be_changed(self):
        response = self.patch(tare_weight='2.250')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['tare_weight'], '2.250')
        self.assertEqual(
            str(Load.objects.get(pk=self.load.id).tare_weight), '2.250'
        )

    def test_negative_tare_is_rejected(self):
        self.assertEqual(self.patch(tare_weight='-1').status_code, 400)

    def test_product_is_immutable(self):
        response = self.patch(product=self.other.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn('product', response.data)
        self.assertEqual(Load.objects.get(pk=self.load.id).product_id, self.product.id)

    def test_resending_the_same_product_is_accepted(self):
        response = self.patch(product=self.product.id, tare_weight='3')
        self.assertEqual(response.status_code, 200)

    def test_duplicate_label_among_available_loads_is_a_field_error(self):
        Load.objects.create(product=self.product, label='ب')
        response = self.patch(label='ب')
        self.assertEqual(response.status_code, 400)
        self.assertIn('label', response.data)

    def test_blank_label_is_allowed_when_it_is_the_only_available_load(self):
        response = self.patch(label='')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['label'], '')

    def test_blank_label_is_rejected_while_a_sibling_exists(self):
        Load.objects.create(product=self.product, label='ب')
        response = self.patch(label='')
        self.assertEqual(response.status_code, 400)
        self.assertIn('label', response.data)

    def test_label_can_repeat_a_finished_load_label(self):
        Load.objects.create(
            product=self.product, label='ب', finished_at='2026-01-01T10:00:00Z'
        )
        response = self.patch(label='ب')
        self.assertEqual(response.status_code, 200)

    def test_unknown_field_is_rejected(self):
        self.assertEqual(self.patch(weight='5').status_code, 400)

    def test_unknown_load_returns_404(self):
        self.assertEqual(
            self.client.patch(
                reverse('load-detail', args=[999999]), {'label': 'ب'}, format='json'
            ).status_code,
            404,
        )


class LoadDeleteTests(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(name='خیار')
        self.load = Load.objects.create(product=self.product, label='الف')
        self.url = reverse('load-detail', args=[self.load.id])

    def test_delete_returns_204_and_removes_the_load(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Load.objects.filter(pk=self.load.id).exists())

    def test_deleting_an_unknown_load_returns_404(self):
        self.assertEqual(
            self.client.delete(reverse('load-detail', args=[999999])).status_code, 404
        )
