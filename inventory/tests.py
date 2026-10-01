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
        self.product_a = Product.objects.create(name='آلو')
        self.product_b = Product.objects.create(name='پیاز')
        self.available = Load.objects.create(product=self.product_a, label='الف')
        self.finished = Load.objects.create(
            product=self.product_b, label='ب', finished_at='2026-01-01T10:00:00Z'
        )
        self.url = reverse('load-list-create')

    def test_list_without_filter_returns_all_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_available_true_filters_finished_loads(self):
        response = self.client.get(self.url, {'available': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data], [self.available.id])
        self.assertEqual(response.data[0]['product_name'], 'آلو')

    def test_list_is_ordered_by_product_name_then_id(self):
        response = self.client.get(self.url)
        self.assertEqual(
            [item['product_name'] for item in response.data], ['آلو', 'پیاز']
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
