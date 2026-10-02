from django.db import models

from config.text import normalize_text


class Bank(models.Model):
    """A bank name only — bank accounts come later."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = normalize_text(self.name)
        super().save(*args, **kwargs)