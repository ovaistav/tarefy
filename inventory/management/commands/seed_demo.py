from django.core.management.base import BaseCommand

from accounting.models import Bank
from catalog.models import Product
from config.text import normalize_text
from parties.models import Party
from sales.models import PorterageSettings

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

# The Android app maps the sticker key to an asset it ships with, and tints the
# tile with the background color.
PRODUCT_LOOKS = {
    'خیار': ('cucumber', '#2E7D32'),
    'گوجه': ('tomato', '#C62828'),
    'موز': ('banana', '#F9A825'),
}

BANK_NAMES = ['بانک ملت', 'بانک ملی', 'بانک صادرات']

# (name, label, phone, national_code, account_number)
PARTIES = [
    ('رضایی', 'همسایه', '۰۹۱۲۳۴۵۶۷۸۹', None, None),
    ('کریمی', 'دکان', '۰۹۱۲۹۸۷۶۵۴۳', None, '0123456789012'),
    ('حسینی', 'تعمیرگاه', '۰۹۳۵۱۱۱۲۲۳۳', '0499370899', None),
    ('موسوی', 'انبار', None, None, None),
    ('نوروزی', 'همکار', '۰۹۱۹۸۸۸۷۷۶۶', None, '۰۹۸۷ ۶۵۴ ۳۲۱'),
]


class Command(BaseCommand):
    help = 'Creates a small demo dataset. Safe to run repeatedly.'

    def handle(self, *args, **options):
        created = 0

        for name in PRODUCT_NAMES:
            # Product.save normalizes the name, so look it up the same way.
            product, was_created = Product.objects.get_or_create(
                name=normalize_text(name)
            )
            created += int(was_created)
            sticker, background = PRODUCT_LOOKS.get(name, (None, None))
            if sticker and (product.sticker, product.background) != (sticker, background):
                product.sticker = sticker
                product.background = background
                product.save(update_fields=['sticker', 'background'])

        banks = 0
        for name in BANK_NAMES:
            _, was_created = Bank.objects.get_or_create(name=name)
            banks += int(was_created)

        parties = 0
        for name, label, phone, national_code, account_number in PARTIES:
            _, was_created = Party.objects.get_or_create(
                name=name,
                label=label,
                defaults={
                    'phone': phone,
                    'national_code': national_code,
                    'account_number': account_number,
                    'details': {'origin': 'اصفهان'} if label == 'همسایه' else {},
                },
            )
            parties += int(was_created)

        _, settings_created = PorterageSettings.objects.get_or_create(pk=1)

        self.stdout.write(
            self.style.SUCCESS(
                f'آماده است. {created} کالای جدید، {banks} بانک جدید، '
                f'{parties} طرف حساب جدید ساخته شد '
                f'({Product.objects.count()} کالا، {Bank.objects.count()} بانک، '
                f'{Party.objects.count()} طرف حساب). '
                + ('تنظیمات حمل ساخته شد.' if settings_created else '')
            )
        )