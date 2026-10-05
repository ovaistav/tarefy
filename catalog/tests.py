import io
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Product


def make_image(name='product.png'):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), color='green').save(buffer, format='PNG')
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type='image/png')


class ProductListTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_root = Path(tempfile.mkdtemp(prefix='catalog-test-media-'))
        cls.settings_override = override_settings(MEDIA_ROOT=cls.media_root)
        cls.settings_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.settings_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)

    def setUp(self):
        self.url = reverse('product-list')

    def test_products_are_ordered_by_updated_at_then_name(self):
        Product.objects.create(name='خیار')
        Product.objects.create(name='گوجه')
        Product.objects.filter(name='خیار').update(
            updated_at='2026-01-01T10:00:00Z'
        )
        Product.objects.filter(name='گوجه').update(
            updated_at='2026-02-01T10:00:00Z'
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        names = [item['name'] for item in response.data]
        self.assertEqual(names, ['گوجه', 'خیار'])

    def test_image_url_is_null_without_image(self):
        Product.objects.create(name='خیار')
        response = self.client.get(self.url)
        self.assertIsNone(response.data[0]['image_url'])

    def test_image_url_uses_image_updated_at_version(self):
        product = Product.objects.create(
            name='خیار',
            image=make_image('a.png'),
            image_updated_at='2026-01-01T10:00:00Z',
        )
        response = self.client.get(self.url)
        url = response.data[0]['image_url']
        self.assertTrue(url.startswith('http://testserver/media/products/'))
        self.assertIn(f'?v={int(product.image_updated_at.timestamp())}', url)

    def test_changing_the_image_changes_the_version(self):
        product = Product.objects.create(name='خیار', image=make_image('a.png'))
        first_url = self.client.get(self.url).data[0]['image_url']
        first_version = first_url.split('?v=')[1]

        # Pin the clock: the ?v= value has one-second resolution.
        later = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        with mock.patch('catalog.models.timezone.now', return_value=later):
            product.image = make_image('b.png')
            product.save()

        second_url = self.client.get(self.url).data[0]['image_url']
        self.assertNotEqual(first_version, second_url.split('?v=')[1])
        self.assertEqual(second_url.split('?v=')[1], str(int(later.timestamp())))

    def test_changing_only_the_name_keeps_the_version(self):
        product = Product.objects.create(
            name='خیار', image=make_image('a.png')
        )
        first_url = self.client.get(self.url).data[0]['image_url']

        product.name = 'خیار سبز'
        product.save()
        second_url = self.client.get(self.url).data[0]['image_url']
        self.assertEqual(first_url, second_url)


class ProductImageTimestampTests(APITestCase):
    def test_image_updated_at_is_set_on_first_image_only(self):
        first_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        product = Product.objects.create(name='خیار')
        self.assertIsNone(product.image_updated_at)

        with mock.patch(
            'catalog.models.timezone.now', return_value=first_time
        ):
            product.image = make_image('a.png')
            product.save()
        product.refresh_from_db()
        self.assertEqual(product.image_updated_at, first_time)

        # Saving again without touching the image must not move the timestamp.
        product.save()
        self.assertEqual(
            Product.objects.get(pk=product.pk).image_updated_at, first_time
        )

        second_time = datetime(2026, 5, 1, tzinfo=timezone.utc)
        with mock.patch(
            'catalog.models.timezone.now', return_value=second_time
        ):
            product.image = make_image('b.png')
            product.save()
        self.assertEqual(
            Product.objects.get(pk=product.pk).image_updated_at, second_time
        )


class ProductStickerTests(APITestCase):
    def setUp(self):
        self.url = reverse('product-list')

    def test_blank_sticker_is_allowed(self):
        Product.objects.create(name='خیار')
        self.assertEqual(Product.objects.get().sticker, '')

    def test_allowed_characters_are_accepted(self):
        Product.objects.create(name='خیار', sticker='cucumber_green-2')
        self.assertEqual(Product.objects.get().sticker, 'cucumber_green-2')

    def test_uppercase_is_rejected(self):
        product = Product(name='خیار', sticker='Cucumber')
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_persian_is_rejected(self):
        product = Product(name='خیار', sticker='خیار')
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_spaces_and_dots_are_rejected(self):
        for sticker in ['a b', 'a.b', 'a/b']:
            with self.subTest(sticker=sticker):
                with self.assertRaises(ValidationError):
                    Product(name='خیار', sticker=sticker).full_clean()

    def test_too_long_sticker_is_rejected(self):
        with self.assertRaises(ValidationError):
            Product(name='خیار', sticker='a' * 41).full_clean()

    def test_list_returns_the_sticker(self):
        Product.objects.create(name='خیار', sticker='cucumber')
        response = self.client.get(self.url)
        self.assertEqual(response.data[0]['sticker'], 'cucumber')


class ProductNameUniquenessTests(APITestCase):
    """Clients group loads by product name, so a name identifies one product."""

    def setUp(self):
        self.product = Product.objects.create(name='خیار')

    def test_a_second_product_with_the_same_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            Product(name='خیار').full_clean()

    def test_the_name_is_normalized_before_the_check(self):
        Product.objects.create(name='  گوجه  ')
        with self.assertRaises(ValidationError):
            Product(name='گوجه').full_clean()
        self.assertEqual(Product.objects.get(name='گوجه').pk, self.product.pk + 1)

    def test_different_names_are_allowed(self):
        Product.objects.create(name='گوجه')
        self.assertEqual(Product.objects.count(), 2)

    def test_resaving_a_product_with_its_own_name_is_allowed(self):
        self.product.sticker = 'cucumber'
        self.product.full_clean()
        self.product.save()
        self.assertEqual(Product.objects.count(), 1)

    def test_the_database_rejects_a_duplicate_name(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(name='خیار')

    def test_renaming_a_product_onto_another_name_is_rejected(self):
        other = Product.objects.create(name='گوجه')
        with self.assertRaises(ValidationError):
            other.name = 'خیار'
            other.full_clean()


class ProductBackgroundTests(APITestCase):
    def setUp(self):
        self.url = reverse('product-list')

    def test_blank_is_allowed(self):
        Product.objects.create(name='خیار')
        self.assertEqual(Product.objects.get().background, '')

    def test_six_digit_hex_is_stored_uppercase(self):
        Product.objects.create(name='خیار', background='#2E7D32')
        self.assertEqual(Product.objects.get().background, '#2E7D32')

    def test_hash_is_optional(self):
        Product.objects.create(name='خیار', background='2e7d32')
        self.assertEqual(Product.objects.get().background, '#2E7D32')

    def test_three_digit_hex_is_expanded(self):
        Product.objects.create(name='خیار', background='#abc')
        self.assertEqual(Product.objects.get().background, '#AABBCC')

    def test_surrounding_whitespace_is_ignored(self):
        Product.objects.create(name='خیار', background='  #2E7D32  ')
        self.assertEqual(Product.objects.get().background, '#2E7D32')

    def test_invalid_values_are_rejected(self):
        for value in ['red', '#12345', '#1234567', '#GGGGGG', 'rgb(1,2,3)']:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    Product(name='خیار', background=value).full_clean()

    def test_list_returns_the_background(self):
        Product.objects.create(name='خیار', background='#2e7d32')
        response = self.client.get(self.url)
        self.assertEqual(response.data[0]['background'], '#2E7D32')

    def test_existing_rows_are_backfilled_to_blank(self):
        product = Product.objects.create(name='پیاز')
        self.assertEqual(self.client.get(self.url).data[0]['background'], '')
