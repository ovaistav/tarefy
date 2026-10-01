from rest_framework import serializers

from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'name', 'image_url', 'updated_at']

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
