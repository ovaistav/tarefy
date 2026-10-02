"""Validation for the presentation hints the Android app reads off a product."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# The app maps a sticker key to an asset it ships with, so the key stays in a
# narrow, filename-safe alphabet.
STICKER_PATTERN = re.compile(r'^[a-z0-9_-]*$')
STICKER_MAX_LENGTH = 40

# #RGB or #RRGGBB, with or without the leading '#'.
_SHORT_HEX = re.compile(r'^#?([0-9a-fA-F]{3})$')
_LONG_HEX = re.compile(r'^#?([0-9a-fA-F]{6})$')


def validate_sticker(value):
    if not STICKER_PATTERN.match(value or ''):
        raise ValidationError(
            _('برچسب تصویر فقط می‌تواند شامل حروف انگلیسی کوچک، عدد، خط تیره و زیرخط باشد.'),
            code='invalid',
        )


def normalize_background(value):
    """Return the color as uppercase ``#RRGGBB`` (or '' when blank)."""
    value = (value or '').strip()
    if not value:
        return ''
    short = _SHORT_HEX.match(value)
    if short:
        digits = short.group(1)
        return '#' + ''.join(char * 2 for char in digits).upper()
    long_match = _LONG_HEX.match(value)
    if long_match:
        return '#' + long_match.group(1).upper()
    raise ValidationError(
        _('رنگ پس‌زمینه باید به شکل #RRGGBB یا #RGB باشد.'), code='invalid'
    )


def validate_background(value):
    normalize_background(value)