from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from catalog.models import Product
from config.api import StaleStateConflict
from config.text import normalize_text

from .models import Load


class LoadListItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = Load
        fields = ['id', 'product', 'product_name', 'label']


class ExistingLabelSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    label = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )


class LoadCreateSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    label = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    existing_labels = ExistingLabelSerializer(many=True, required=False)

    def validate_label(self, value):
        return normalize_text(value)

    def validate_existing_labels(self, value):
        return [
            {'id': item['id'], 'label': normalize_text(item.get('label'))}
            for item in value
        ]

    def validate(self, attrs):
        product = attrs['product']
        label = attrs.get('label') or ''
        existing = attrs.get('existing_labels', [])

        available = list(Load.objects.filter(product=product, finished_at__isnull=True))
        unlabeled = [load for load in available if load.label == '']
        unlabeled_ids = {load.id for load in unlabeled}

        # The client must describe exactly the loads that currently have no
        # label: no more, no fewer, no duplicates.
        submitted_ids = [item['id'] for item in existing]
        if (
            len(submitted_ids) != len(set(submitted_ids))
            or set(submitted_ids) != unlabeled_ids
        ):
            raise StaleStateConflict()

        if not available:
            # First load of this product: the label is optional.
            return attrs

        errors = {}
        if not label:
            errors['label'] = [_('برچسب بار الزامی است.')]

        final_labels = (
            [load.label for load in available if load.id not in unlabeled_ids]
            + [item['label'] for item in existing]
            + [label]
        )
        if any(not item for item in final_labels):
            errors['label'] = [_('برچسب همه بارهای موجود باید وارد شود.')]
        elif len(set(final_labels)) != len(final_labels):
            errors['label'] = [_('برچسب بارهای یک کالا باید یکتا باشد.')]
        if errors:
            raise serializers.ValidationError(errors)

        return attrs
