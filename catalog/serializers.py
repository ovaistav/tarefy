from rest_framework import serializers

from .models import Product
from .validators import (
    STICKER_MAX_LENGTH,
    normalize_background,
    validate_sticker,
)


class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    sticker = serializers.CharField(
        max_length=STICKER_MAX_LENGTH,
        required=False,
        allow_blank=True,
        validators=[validate_sticker],
    )
    background = serializers.CharField(
        max_length=7, required=False, allow_blank=True
    )

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'image_url',
            'sticker',
            'background',
            'updated_at',
        ]
        read_only_fields = ['id', 'image_url', 'updated_at']

    def validate_background(self, value):
        # Stored canonically so the app can compare colors without parsing.
        return normalize_background(value)

    def get_image_url(self, product):
        if not product.image:
            return None
        request = self.context.get('request')
        url = product.image.url
        if request is not None:
            url = request.build_absolute_uri(url)
        # The app uses this as an image cache key, so it must follow
        # image_updated_at (not updated_at, which changes on every save).
        version = 0
        if product.image_updated_at is not None:
            version = int(product.image_updated_at.timestamp())
        return f'{url}?v={version}'
