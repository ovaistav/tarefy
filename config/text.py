"""Text normalization shared by every app.

The Android app types Persian text, but it is easy for a keyboard or an OCR
pass to sneak in Arabic look-alikes and non-ASCII digits. Everything that is
compared for equality (labels, names, national codes) is normalized first, so
the database constraint sees the canonical form.
"""

import re

# Arabic letters that look identical to their Persian counterparts.
ARABIC_TO_PERSIAN = {
    'ي': 'ی',  # ARABIC YEH -> FARSI YEH
    'ك': 'ک',  # ARABIC KAF -> KEHEH
}

_ARABIC_TO_PERSIAN_TABLE = str.maketrans(ARABIC_TO_PERSIAN)

# Persian digits (U+06F0..U+06F9) and Arabic-Indic digits (U+0660..U+0669)
# both map onto ASCII '0'..'9'.
_ASCII_ZERO = ord('0')
_PERSIAN_DIGITS = range(0x06F0, 0x06FA)
_ARABIC_INDIC_DIGITS = range(0x0660, 0x066A)
DIGIT_TO_ASCII = str.maketrans(
    {
        code: _ASCII_ZERO + offset
        for block in (_PERSIAN_DIGITS, _ARABIC_INDIC_DIGITS)
        for offset, code in enumerate(block)
    }
)

_WHITESPACE = re.compile(r'\s+')


def normalize_text(value):
    """Trim, collapse whitespace runs, and convert Arabic look-alikes."""
    if value is None:
        return ''
    value = str(value).translate(_ARABIC_TO_PERSIAN_TABLE)
    return _WHITESPACE.sub(' ', value).strip()


def normalize_digits(value):
    """Map Persian and Arabic-Indic digits to ASCII, leaving the rest alone."""
    if value is None:
        return ''
    return str(value).translate(DIGIT_TO_ASCII)