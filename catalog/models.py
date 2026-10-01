from django.db import models
from django.utils import timezone


class Product(models.Model):
    name = models.CharField(max_length=100)
    tare_weight = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    image = models.ImageField(upload_to='products/', blank=True)
    image_updated_at = models.DateTimeField(null=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # image_updated_at doubles as the Android app's image cache key, so it
        # must only move when the image file itself actually changed.
        if self.image and (
            not self.pk or self.image.name != self._loaded_image_name()
        ):
            self.image_updated_at = timezone.now()
        super().save(*args, **kwargs)

    def _loaded_image_name(self):
        if not self.pk:
            return None
        return type(self).objects.filter(pk=self.pk).values_list(
            'image', flat=True
        )[:1][0]
