"""Validators shared by the Party model and its serializers.

DRF does not call ``Model.full_clean()``, so the same functions are attached to
the serializer fields as well as to the model fields; that way the Persian
messages are identical whether a row arrives from the API or the admin.
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from config.text import normalize_digits

NATIONAL_CODE_LENGTH = 10

DETAILS_MAX_KEYS = 50
DETAILS_MAX_KEY_LENGTH = 50
DETAILS_MAX_VALUE_LENGTH = 500

_ASCII_DIGITS = frozenset('0123456789')


def validate_national_code(value):
    """Check length, all-identical digits and the official checksum."""
    code = normalize_digits(value).strip()
    if len(code) != NATIONAL_CODE_LENGTH or not set(code) <= _ASCII_DIGITS:
        raise ValidationError(
            _('کد ملی باید دقیقاً ۱۰ رقم باشد.'), code='invalid'
        )
    if len(set(code)) == 1:
        raise ValidationError(_('کد ملی معتبر نیست.'), code='invalid')

    digits = [int(char) for char in code]
    # s = sum(d[i] * (10 - i)) for i in 0..8; r = s mod 11
    total = sum(digit * (NATIONAL_CODE_LENGTH - i) for i, digit in enumerate(digits[:9]))
    remainder = total % 11
    check = digits[9]
    valid = (
        check == remainder
        if remainder < 2
        else check == 11 - remainder
    )
    if not valid:
        raise ValidationError(_('کد ملی معتبر نیست.'), code='invalid')


def validate_details(value):
    """A plain mapping of short strings to short strings; the server is agnostic.

    The keys are never interpreted here — "bank account number", "origin" and
    friends are just suggestions that live in the mobile app.
    """
    if not isinstance(value, dict):
        raise ValidationError(_('جزئیات باید یک شیء باشد.'), code='invalid')
    if len(value) > DETAILS_MAX_KEYS:
        raise ValidationError(
            _('جزئیات حداکثر %s مورد می‌تواند داشته باشد.') % DETAILS_MAX_KEYS,
            code='invalid',
        )
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValidationError(_('کلید جزئیات باید متن باشد.'), code='invalid')
        if len(key) > DETAILS_MAX_KEY_LENGTH:
            raise ValidationError(
                _('کلید جزئیات حداکثر %s نویسه باشد.')
                % DETAILS_MAX_KEY_LENGTH,
                code='invalid',
            )
        if not isinstance(item, str):
            raise ValidationError(_('مقدار جزئیات باید متن باشد.'), code='invalid')
        if len(item) > DETAILS_MAX_VALUE_LENGTH:
            raise ValidationError(
                _('مقدار جزئیات حداکثر %s نویسه باشد.')
                % DETAILS_MAX_VALUE_LENGTH,
                code='invalid',
            )