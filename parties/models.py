from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from config.text import normalize_digits, normalize_text

from .validators import validate_details, validate_national_code


def normalize_number(value):
    """Digits only, for the optional contact numbers.

    Persian and Arabic-Indic digits become ASCII and every space is dropped, so
    "۰۹۱۲ ۳۴۵" and "0912 345" end up as the same string.

    Both fields behave the same way for a missing value: None becomes "", because
    ``normalize_digits`` returns "" for None. So "absent" is stored as an empty
    string, not as NULL, and a client cannot tell "never filled in" apart from
    "explicitly cleared".
    """
    return normalize_digits(value).replace(' ', '').strip()


class Party(models.Model):
    """A customer, supplier or any other counterparty.

    ``name`` and ``label`` together identify a party ("رضایی" / "همسایه"), which
    is why they form a unique pair: the same name may legitimately appear more
    than once as long as the descriptions differ.

    The field is still called ``label`` in code and in the API, because renaming
    it would break every client. What the app shows for it is "توصیف". Free-form
    notes go in ``details``; this field is a short nickname, not a paragraph.
    """

    name = models.CharField(max_length=100)
    label = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, null=True, blank=True)
    # Bank account number, for counterparties the shop settles with directly.
    # Optional and never unique: one account may serve several parties, and most
    # cash customers have none.
    account_number = models.CharField(max_length=20, null=True, blank=True)
    national_code = models.CharField(
        max_length=10, null=True, blank=True, validators=[validate_national_code]
    )
    # A percentage, not a money amount.
    commission = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    # Free-form string map; the server never interprets the keys. This is where
    # long notes live now that Party has no separate description column.
    details = models.JSONField(default=dict, validators=[validate_details])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'label']
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'label'], name='uniq_party_name_label'
            ),
            models.UniqueConstraint(
                fields=['national_code'],
                condition=Q(national_code__isnull=False),
                name='uniq_party_national_code',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.label})'

    def save(self, *args, **kwargs):
        # Normalize before saving so the database constraints compare the
        # canonical form and "يک"/"یک" can never be stored as two parties.
        self.name = normalize_text(self.name)
        self.label = normalize_text(self.label)
        self.phone = normalize_number(self.phone)
        self.account_number = normalize_number(self.account_number)
        code = normalize_digits(self.national_code).strip()
        # An empty national code is stored as NULL, never as "", so that the
        # conditional unique constraint keeps allowing many parties without one.
        self.national_code = code or None
        super().save(*args, **kwargs)