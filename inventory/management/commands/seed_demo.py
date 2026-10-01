from django.core.management.base import BaseCommand

from catalog.models import Product

PRODUCT_NAMES = [
    'خیار',
    'گوجه',
    'موز',
    'سیب',
    'پیاز',
    'هویج',
    'سیب‌زمینی',
    'بادمجان',
    'فلفل دلمه‌ای',
    'کدو',
    'لیمو',
    'هندوانه',
]


class Command(BaseCommand):
    help = 'Creates a small demo product catalog. Safe to run repeatedly.'

    def handle(self, *args, **options):
        created = 0
        for name in PRODUCT_NAMES:
            _, was_created = Product.objects.get_or_create(name=name)
            created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f'آماده است. {created} کالای جدید ساخته شد '
                f'({Product.objects.count()} کالا در کاتالوگ).'
            )
        )
