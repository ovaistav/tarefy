import io
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

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
