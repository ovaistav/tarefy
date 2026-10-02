from django.conf import settings
from django.db import models

from accounting.models import Bank
from inventory.models import Load
from parties.models import Party

# Porterage is always rounded to a multiple of this, in Rial.
PORTERAGE_ROUND_STEP = 50000


class Sale(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'draft'
        CREDIT = 'credit', 'credit'
        FINAL = 'final', 'final'

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    # Maintained by the server: sum(line_total) + porterage.amount.
    total_amount = models.BigIntegerField(default=0)
    finalized_at = models.DateTimeField(null=True, blank=True)
    # Unused for now; authentication comes later.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sales',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(
                fields=['status', '-created_at', '-id'], name='sale_status_created_idx'
            ),
            models.Index(fields=['-created_at', '-id'], name='sale_created_idx'),
        ]

    def __str__(self):
        return f'Sale #{self.pk} ({self.status})'


class Invoice(models.Model):
    """One per sale; holds the single account the sale is settled against."""

    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name='invoice')
    buyer = models.ForeignKey(
        Party,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='invoices',
    )
    # Signed: positive means the party owes us, negative means we owe them.
    buyer_amount = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Invoice #{self.pk}'


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    # A load that has been sold is history and can never be deleted.
    load = models.ForeignKey(Load, on_delete=models.PROTECT, related_name='invoice_lines')
    gross_weight = models.DecimalField(max_digits=10, decimal_places=3)
    net_weight = models.DecimalField(max_digits=10, decimal_places=3)
    quantity = models.PositiveIntegerField()
    rate = models.BigIntegerField()
    line_total = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'Line #{self.pk}'


class Porterage(models.Model):
    """One per sale; the cartage fee owed to the porters."""

    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name='porterage')
    amount = models.BigIntegerField(default=0)

    def __str__(self):
        return f'Porterage #{self.pk}'


class Payment(models.Model):
    class Method(models.TextChoices):
        POS = 'pos', 'pos'
        CHEQUE = 'cheque', 'cheque'
        CARD_TRANSFER = 'card_transfer', 'card_transfer'
        CASH = 'cash', 'cash'

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments')
    method = models.CharField(max_length=20, choices=Method.choices)
    # Required for pos and card_transfer, empty for cheque and cash.
    bank = models.ForeignKey(
        Bank,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    amount = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'Payment #{self.pk}'


class PorterageSettings(models.Model):
    """A single row, always at pk=1."""

    works_with_porters = models.BooleanField(default=True)
    rate_per_kg = models.BigIntegerField(default=4000)
    round_enabled = models.BooleanField(default=False)

    def __str__(self):
        return 'تنظیمات حمل'

    def save(self, *args, **kwargs):
        # Force the singleton row so there can only ever be one.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # The row is configuration, not data.
        raise ValueError('تنظیمات حمل قابل حذف نیست.')


PORTERAGE_SETTINGS_PK = 1


def get_porterage_settings():
    """Return the singleton, creating it with its defaults if needed."""
    settings_row, _ = PorterageSettings.objects.get_or_create(
        pk=PORTERAGE_SETTINGS_PK
    )
    return settings_row