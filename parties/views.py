from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers, status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response

from config.text import normalize_text

from .models import Party
from .serializers import PartyListItemSerializer, PartySerializer

DUPLICATE_MESSAGES = {
    'national_code': _('کد ملی قبلاً ثبت شده است.'),
    'name': _('طرف حسابی با همین نام و برچسب قبلاً ثبت شده است.'),
}


def unique_conflict(exc):
    """Turn a database unique violation into an ordinary 400 field error.

    The rules are plain uniqueness rules, so they are reported like any other
    validation failure rather than as a 409 conflict.
    """
    text = str(exc)
    if 'national_code' in text or 'uniq_party_national_code' in text:
        field = 'national_code'
    elif 'name' in text and 'label' in text:
        field = 'name'
    else:
        field = None
    raise serializers.ValidationError(
        {field: [DUPLICATE_MESSAGES.get(field, _('این مقدار تکراری است.'))]}
    )


def save_quietly(serializer):
    """Save inside a transaction so a violation can be inspected safely."""
    try:
        with transaction.atomic():
            return serializer.save()
    except IntegrityError as exc:
        unique_conflict(exc)


class PartyListCreateView(ListCreateAPIView):
    """Plain list (no pagination) plus creation.

    ``?q=`` is normalized the same way the stored values are, then matched with
    ``icontains`` against the name or the label.
    """

    def get_queryset(self):
        query = normalize_text(self.request.query_params.get('q') or '')
        if not query:
            return Party.objects.all()
        return Party.objects.filter(Q(name__icontains=query) | Q(label__icontains=query))

    def get_serializer_class(self):
        return (
            PartySerializer
            if self.request.method == 'POST'
            else PartyListItemSerializer
        )

    def create(self, request, *args, **kwargs):
        serializer = PartySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        party = save_quietly(serializer)
        return Response(
            PartySerializer(party).data, status=status.HTTP_201_CREATED
        )


class PartyDetailView(RetrieveUpdateAPIView):
    queryset = Party.objects.all()
    serializer_class = PartySerializer

    def update(self, request, *args, **kwargs):
        # The app only ever sends the fields it wants to change.
        serializer = self.get_serializer(
            self.get_object(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        save_quietly(serializer)
        return Response(PartySerializer(serializer.instance).data)