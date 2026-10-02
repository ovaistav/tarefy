from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListCreateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api import (
    LoadFinishedConflict,
    NoLinesConflict,
    NotDeletableConflict,
    NotSettledConflict,
)

from .models import InvoiceLine, Payment, Sale, get_porterage_settings
from .pagination import SaleCursorPagination
from .serializers import (
    AccountWriteSerializer,
    PaymentCreateSerializer,
    PaymentPatchSerializer,
    PorterageSettingsSerializer,
    PorterageWriteSerializer,
    SaleDetailSerializer,
    SaleLineCreateSerializer,
    SaleLinePatchSerializer,
    SaleListItemSerializer,
)
from .services import (
    create_sale,
    detail_queryset,
    filter_sales,
    line_amounts,
    list_queryset,
    locked_sale,
    refresh_totals,
    reopen_for_edit,
    apply_porterage_delta,
    sale_summary,
    validate_status_filter,
)


def detail_response(sale_id, http_status):
    """Every create, update and nested delete answers with the full sale."""
    sale = detail_queryset().get(pk=sale_id)
    return Response(SaleDetailSerializer(sale).data, status=http_status)


def get_line(sale, line_id):
    return get_object_or_404(InvoiceLine, pk=line_id, invoice_id=sale.invoice.pk)


def get_payment(sale, payment_id):
    return get_object_or_404(Payment, pk=payment_id, sale_id=sale.pk)


def assert_load_is_open(load):
    """A finished load is history and can never be sold again."""
    if load.finished_at is not None:
        raise LoadFinishedConflict()


class SaleListCreateView(ListCreateAPIView):
    # Registered here rather than globally: only the sales list is paged.
    pagination_class = SaleCursorPagination

    def get_serializer_class(self):
        return (
            SaleListItemSerializer
            if self.request.method == 'GET'
            else SaleDetailSerializer
        )

    def get_queryset(self):
        validate_status_filter(self.request)
        return filter_sales(list_queryset(), self.request)

    def create(self, request, *args, **kwargs):
        sale = create_sale()
        return detail_response(sale.pk, status.HTTP_201_CREATED)


class SaleDetailView(APIView):
    def get(self, request, pk):
        return detail_response(pk, status.HTTP_200_OK)

    def delete(self, request, pk):
        with locked_sale(pk) as sale:
            if sale.status != Sale.Status.DRAFT:
                # A finalized sale is a receipt; drafts are throwaway.
                raise NotDeletableConflict()
            sale.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SaleLineCreateView(APIView):
    def post(self, request, pk):
        serializer = SaleLineCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with locked_sale(pk) as sale:
            assert_load_is_open(data['load'])
            reopen_for_edit(sale)
            net_weight, line_total = line_amounts(
                data['load'], data['gross_weight'], data['quantity'], data['rate']
            )
            InvoiceLine.objects.create(
                invoice=sale.invoice,
                load=data['load'],
                gross_weight=data['gross_weight'],
                net_weight=net_weight,
                quantity=data['quantity'],
                rate=data['rate'],
                line_total=line_total,
            )
            apply_porterage_delta(sale, 0, data['gross_weight'])
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_201_CREATED)


class SaleLineDetailView(APIView):
    def patch(self, request, pk, line_id):
        with locked_sale(pk) as sale:
            line = get_line(sale, line_id)
            serializer = SaleLinePatchSerializer(
                data=request.data, context={'line': line}
            )
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            load = data.get('load', line.load)
            assert_load_is_open(load)
            old_gross = line.gross_weight
            new_gross = data.get('gross_weight', old_gross)

            reopen_for_edit(sale)
            net_weight, line_total = line_amounts(
                load,
                new_gross,
                data.get('quantity', line.quantity),
                data.get('rate', line.rate),
            )
            line.load = load
            line.gross_weight = new_gross
            line.net_weight = net_weight
            line.quantity = data.get('quantity', line.quantity)
            line.rate = data.get('rate', line.rate)
            line.line_total = line_total
            line.save()

            # Porterage follows the gross weight only, so a quantity or rate
            # edit on its own moves nothing.
            apply_porterage_delta(sale, old_gross, new_gross)
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_200_OK)

    def delete(self, request, pk, line_id):
        with locked_sale(pk) as sale:
            line = get_line(sale, line_id)
            reopen_for_edit(sale)
            old_gross = line.gross_weight
            line.delete()
            apply_porterage_delta(sale, old_gross, 0)
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_200_OK)


class SalePorterageView(APIView):
    def put(self, request, pk):
        serializer = PorterageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with locked_sale(pk) as sale:
            reopen_for_edit(sale)
            # Exactly what was asked for: no rounding, no delta.
            porterage = sale.porterage
            porterage.amount = serializer.validated_data['amount']
            porterage.save(update_fields=['amount'])
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_200_OK)


class SalePaymentCreateView(APIView):
    def post(self, request, pk):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with locked_sale(pk) as sale:
            reopen_for_edit(sale)
            Payment.objects.create(
                sale=sale,
                method=data['method'],
                bank=data.get('bank'),
                amount=data['amount'],
            )
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_201_CREATED)


class SalePaymentDetailView(APIView):
    def patch(self, request, pk, payment_id):
        with locked_sale(pk) as sale:
            payment = get_payment(sale, payment_id)
            serializer = PaymentPatchSerializer(
                data=request.data, context={'payment': payment}
            )
            serializer.is_valid(raise_exception=True)
            reopen_for_edit(sale)
            # A plain serializer has no update(), so apply the keys given.
            for field, value in serializer.validated_data.items():
                setattr(payment, field, value)
            payment.save()
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_200_OK)

    def delete(self, request, pk, payment_id):
        with locked_sale(pk) as sale:
            payment = get_payment(sale, payment_id)
            reopen_for_edit(sale)
            payment.delete()
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_200_OK)


class SaleAccountView(APIView):
    def put(self, request, pk):
        serializer = AccountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with locked_sale(pk) as sale:
            reopen_for_edit(sale)
            invoice = sale.invoice
            invoice.buyer = data['party']
            invoice.buyer_amount = data['amount']
            invoice.save(update_fields=['buyer', 'buyer_amount'])
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_200_OK)

    def delete(self, request, pk):
        with locked_sale(pk) as sale:
            reopen_for_edit(sale)
            invoice = sale.invoice
            invoice.buyer = None
            invoice.buyer_amount = 0
            invoice.save(update_fields=['buyer', 'buyer_amount'])
            refresh_totals(sale)

        return detail_response(pk, status.HTTP_200_OK)


class SaleFinalizeView(APIView):
    def post(self, request, pk):
        with locked_sale(pk) as sale:
            if sale.status == Sale.Status.DRAFT:
                self._finalize(sale)

        return detail_response(pk, status.HTTP_200_OK)

    @staticmethod
    def _finalize(sale):
        if not InvoiceLine.objects.filter(invoice_id=sale.invoice.pk).exists():
            raise NoLinesConflict()

        sale.porterage.refresh_from_db()
        sale.invoice.refresh_from_db()
        refresh_totals(sale)

        summary = sale_summary(sale)
        if summary['remaining'] != 0:
            raise NotSettledConflict(remaining=summary['remaining'])

        sale.status = (
            # Money still owed by the buyer makes it a credit sale.
            Sale.Status.CREDIT
            if sale.invoice.buyer_amount > 0
            else Sale.Status.FINAL
        )
        sale.finalized_at = timezone.now()
        sale.save(update_fields=['status', 'finalized_at', 'updated_at'])


class PorterageSettingsView(APIView):
    def get(self, request):
        settings_row = get_porterage_settings()
        return Response(PorterageSettingsSerializer(settings_row).data)

    def patch(self, request):
        settings_row = get_porterage_settings()
        serializer = PorterageSettingsSerializer(
            settings_row, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(PorterageSettingsSerializer(serializer.instance).data)
