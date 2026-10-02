from django.db import models
from django.db.models import Q

from catalog.models import Product
from config.text import normalize_text


class Supplier(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class GoodsReceipt(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'GoodsReceipt #{self.pk}'


class Load(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'pending'
        MATCHED = 'matched', 'matched'

    receipt = models.ForeignKey(
        GoodsReceipt,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='loads',
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    supplier = models.ForeignKey(
        Supplier,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='loads',
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='loads'
    )
    label = models.CharField(max_length=50, blank=True, default='')
    weight = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    rate = models.IntegerField(null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    arrived_at = models.DateField(null=True, blank=True)
    # NULL means the load is still available and offered to the Android app.
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__name', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'label'],
                condition=Q(finished_at__isnull=True),
                name='uniq_available_product_label',
            )
        ]

    def __str__(self):
        return f'{self.product_id} / {self.label or "(no label)"}'

    def save(self, *args, **kwargs):
        self.label = normalize_text(self.label)
        super().save(*args, **kwargs)
