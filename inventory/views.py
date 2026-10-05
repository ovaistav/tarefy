from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListCreateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Product
from config.api import InUseConflict, RestoreConflict, StaleStateConflict

from .models import Load
from .serializers import (
    LoadCreateSerializer,
    LoadListItemSerializer,
    LoadPatchSerializer,
)


def parse_available_flag(request):
    raw = request.query_params.get('available')
    if raw is None:
        return False
    return raw.strip().lower() in {'true', '1', 'yes'}


class LoadListCreateView(ListCreateAPIView):
    def get_serializer_class(self):
        return (
            LoadCreateSerializer
            if self.request.method == 'POST'
            else LoadListItemSerializer
        )

    def get_queryset(self):
        queryset = Load.objects.select_related('product').order_by(
            'product__name', 'id'
        )
        if parse_available_flag(self.request):
            queryset = queryset.filter(finished_at__isnull=True)
        return queryset

    def list(self, request, *args, **kwargs):
        # The app renders one tile per product, so the list is grouped by
        # product name and each group carries the sticker the tile is drawn with.
        # Product.name is unique, so the key identifies exactly one product.
        loads = list(self.get_queryset())
        serializer = LoadListItemSerializer(loads, many=True)
        grouped = {}
        for load, item in zip(loads, serializer.data):
            product = load.product
            group = grouped.setdefault(
                product.name,
                {
                    'product': product.id,
                    'sticker': product.sticker,
                    'background': product.background,
                    'loads': [],
                },
            )
            group['loads'].append(item)
        return Response(grouped)

    def create(self, request, *args, **kwargs):
        serializer = LoadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = data['product']
        now = timezone.now()

        try:
            with transaction.atomic():
                for item in data.get('existing_labels', []):
                    Load.objects.filter(
                        pk=item['id'], finished_at__isnull=True
                    ).update(label=item['label'], updated_at=now)
                load = Load.objects.create(
                    product=product,
                    label=data.get('label') or '',
                    # The product's tare is the *default* basket weight; the
                    # load keeps its own copy so later product edits are safe.
                    tare_weight=product.tare_weight,
                )
                # Recently used products float to the top of the catalog list.
                Product.objects.filter(pk=product.pk).update(updated_at=now)
        except IntegrityError:
            # A concurrent request won the race; the client must refetch.
            raise StaleStateConflict()

        load.refresh_from_db()
        return Response(
            LoadListItemSerializer(load).data, status=status.HTTP_201_CREATED
        )


class LoadDetailView(APIView):
    def patch(self, request, pk):
        load = get_object_or_404(Load, pk=pk)
        serializer = LoadPatchSerializer(
            data=request.data, context={'load': load}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        now = timezone.now()
        try:
            with transaction.atomic():
                if 'label' in data:
                    load.label = data['label'] or ''
                if 'tare_weight' in data:
                    load.tare_weight = data['tare_weight']
                load.save()
                load.updated_at = now
        except IntegrityError:
            # Another available load grabbed the label first; refetch and retry.
            raise StaleStateConflict()

        load.refresh_from_db()
        return Response(LoadListItemSerializer(load).data)

    def delete(self, request, pk):
        load = get_object_or_404(Load, pk=pk)
        try:
            # A load that appears on an invoice line is history.
            with transaction.atomic():
                load.delete()
        except ProtectedError:
            raise InUseConflict()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LoadFinishView(APIView):
    def post(self, request, pk):
        load = get_object_or_404(Load, pk=pk)
        now = timezone.now()
        # Idempotent: only the first call actually changes anything.
        Load.objects.filter(pk=load.pk, finished_at__isnull=True).update(
            finished_at=now, updated_at=now
        )
        load.refresh_from_db()
        return Response(LoadListItemSerializer(load).data)


class LoadRestoreView(APIView):
    def post(self, request, pk):
        load = get_object_or_404(Load, pk=pk)
        if load.finished_at is not None:
            now = timezone.now()
            try:
                with transaction.atomic():
                    Load.objects.filter(pk=load.pk).update(
                        finished_at=None, updated_at=now
                    )
            except IntegrityError:
                # Another available load already holds this (product, label).
                raise RestoreConflict()
        load.refresh_from_db()
        return Response(LoadListItemSerializer(load).data)
