"""All the money and weight math of a sale.

Everything here is authoritative: the client never sends a computed value, and
every mutation calls :func:`refresh_totals` again inside its own transaction.
"""

from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Prefetch, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from .models import (
    PORTERAGE_ROUND_STEP,
    Invoice,
    InvoiceLine,
    Payment,
    Porterage,
    Sale,
    get_porterage_settings,
)

ONE = Decimal('1')


def round_half_up(value) -> int:
    """Decimal -> Rial, with halves rounded away from zero (0.5 -> 1)."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def round_porterage(amount: int) -> int:
    """Snap a porterage amount to the nearest step.

    Anything that rounds down to zero still becomes one full step, because a
    non-zero delivery always costs something.
    """
    if amount <= 0:
        return 0
    # floor((amount + step / 2) / step) * step, in integer arithmetic.
    rounded = ((amount * 2 + PORTERAGE_ROUND_STEP) // (2 * PORTERAGE_ROUND_STEP)) * (
        PORTERAGE_ROUND_STEP
    )
    return rounded or PORTERAGE_ROUND_STEP


def compute_net_weight(load, gross_weight, quantity) -> Decimal:
    """Net = gross - this load's basket weight, once per item."""
    return Decimal(gross_weight) - (Decimal(load.tare_weight) * Decimal(quantity))


def line_amounts(load, gross_weight, quantity, rate):
    """Return (net_weight, line_total) for the given line inputs."""
    net_weight = compute_net_weight(load, gross_weight, quantity)
    return net_weight, round_half_up(net_weight * rate)


def create_sale():
    """A sale always arrives with its invoice and porterage in place."""
    with transaction.atomic():
        sale = Sale.objects.create()
        Invoice.objects.create(sale=sale)
        Porterage.objects.create(sale=sale)
    return sale


@contextmanager
def locked_sale(sale_id):
    """Serialize concurrent edits of one sale by locking its row."""
    get_object_or_404(Sale, pk=sale_id)
    with transaction.atomic():
        sale = (
            Sale.objects.select_for_update()
            .select_related('invoice')
            .get(pk=sale_id)
        )
        yield sale


def reopen_for_edit(sale):
    """Any edit drags a finalized sale back to draft, in the same transaction."""
    if sale.status != Sale.Status.DRAFT:
        sale.status = Sale.Status.DRAFT
        sale.finalized_at = None
        sale.save(update_fields=['status', 'finalized_at', 'updated_at'])


def apply_porterage_delta(sale, old_gross, new_gross):
    """Move porterage by the *gross* weight difference.

    Editing a quantity or a rate leaves porterage alone; adding or removing a
    line adds or subtracts its whole gross weight.
    """
    settings_row = get_porterage_settings()
    porterage = sale.porterage
    if not settings_row.works_with_porters:
        # The seller runs the cart themselves; the app never touches the fee.
        return
    change = Decimal(new_gross) - Decimal(old_gross)
    delta = round_half_up(change * settings_row.rate_per_kg)
    amount = max(0, porterage.amount + delta)
    if settings_row.round_enabled:
        amount = round_porterage(amount)
    if amount != porterage.amount:
        porterage.amount = amount
        porterage.save(update_fields=['amount'])


def refresh_totals(sale):
    """The one function that writes a sale's derived total."""
    lines_total = (
        InvoiceLine.objects.filter(invoice_id=sale.invoice.pk).aggregate(
            total=Coalesce(Sum('line_total'), 0)
        )['total']
    )
    total = int(lines_total) + int(sale.porterage.amount)
    if sale.total_amount != total:
        sale.total_amount = total
        sale.save(update_fields=['total_amount', 'updated_at'])
    return total


def sale_summary(sale):
    invoice = sale.invoice
    paid = int(
        Payment.objects.filter(sale_id=sale.pk).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )
    accounted = int(invoice.buyer_amount or 0)
    total = int(sale.total_amount)
    return {
        'total': total,
        'paid': paid,
        'accounted': accounted,
        'remaining': total - paid - accounted,
    }


def detail_queryset():
    """Everything the detail serializer needs, in a fixed number of queries."""
    return Sale.objects.select_related('invoice__buyer', 'porterage').prefetch_related(
        Prefetch(
            'invoice__lines',
            queryset=InvoiceLine.objects.select_related('load__product').order_by('id'),
        ),
        Prefetch(
            'payments',
            queryset=Payment.objects.select_related('bank').order_by('id'),
        ),
    )


def list_queryset():
    """Two queries per page no matter how many sales it holds."""
    return Sale.objects.select_related('invoice__buyer').prefetch_related(
        Prefetch(
            'invoice__lines',
            queryset=InvoiceLine.objects.select_related('load__product').order_by('id'),
        )
    )


def distinct_products(sale):
    """The products of a sale's lines, in line order, without repeats."""
    products = []
    seen = set()
    for line in sale.invoice.lines.all():
        product = line.load.product
        if product.id in seen:
            continue
        seen.add(product.id)
        products.append(product)
    return products


def filter_sales(queryset, request):
    """Apply ?status= and ?party=."""
    status_param = request.query_params.get('status')
    if status_param:
        queryset = queryset.filter(status=status_param)
    party_param = request.query_params.get('party')
    if party_param:
        queryset = queryset.filter(invoice__buyer_id=party_param)
    return queryset


def validate_status_filter(request):
    """Reject a status the app cannot possibly mean."""
    status_param = request.query_params.get('status')
    if status_param and status_param not in Sale.Status.values:
        raise ValidationError({'status': [_('مقدار وضعیت نامعتبر است.')]})