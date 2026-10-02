from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from config.text import normalize_digits, normalize_text

from .validators import validate_details, validate_national_code


class Party(models.Model):
    """A customer, supplier or any other counterparty.

    ``name`` and ``label`` together identify a party ("رضایی" / "همسایه"), which
    is why they form a unique pair: the same name may legitimately appear more
    than once as long as the labels differ.
    """

    name = models.CharField(max_length=100)
    label = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, null=True, blank=True)
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
    description = models.TextField(blank=True)
    # Free-form string map; the server never interprets the keys.
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
        self.phone = normalize_digits(self.phone).replace(' ', '').strip()
        code = normalize_digits(self.national_code).strip()
        # An empty national code is stored as NULL, never as "", so that the
        # conditional unique constraint keeps allowing many parties without one.
        self.national_code = code or None
        super().save(*args, **kwargs)