from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from config.text import normalize_text

from .validators import (
    STICKER_MAX_LENGTH,
    normalize_background,
    validate_background,
    validate_sticker,
)


class Product(models.Model):
    name = models.CharField(max_length=100)
    # Default basket weight, copied onto every load created for this product.
    tare_weight = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    image = models.ImageField(upload_to='products/', blank=True)
    image_updated_at = models.DateTimeField(null=True, editable=False)
    # Key of the sticker bundled in the Android app, e.g. "cucumber_1".
    sticker = models.CharField(
        max_length=STICKER_MAX_LENGTH,
        blank=True,
        default='',
        validators=[validate_sticker],
    )
    # Hex color shown behind the sticker, always stored as uppercase #RRGGBB.
    background = models.CharField(
        blank=True, default='', max_length=7, validators=[validate_background]
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', 'name']
        constraints = [
            # Clients group loads by product name, so the name identifies the
            # product and may not be reused.
            models.UniqueConstraint(
                fields=['name'],
                name='uniq_product_name',
                violation_error_message=_('کالایی با این نام وجود دارد.'),
            )
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # image_updated_at doubles as the Android app's image cache key, so it
        # must only move when the image file itself actually changed.
        if self.image and (
            not self.pk or self.image.name != self._loaded_image_name()
        ):
            self.image_updated_at = timezone.now()
        self.name = normalize_text(self.name)
        self.background = normalize_background(self.background)
        super().save(*args, **kwargs)

    def _loaded_image_name(self):
        if not self.pk:
            return None
        return type(self).objects.filter(pk=self.pk).values_list(
            'image', flat=True
        )[:1][0]
