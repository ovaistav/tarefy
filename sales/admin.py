from django.contrib import admin

from .models import (
    Invoice,
    InvoiceLine,
    Payment,
    Porterage,
    PorterageSettings,
    Sale,
)
from .services import sale_summary


class InvoiceLineInline(admin.TabularInline):
    """Gross, net and line_total are all computed by the server."""

    model = InvoiceLine
    extra = 0
    fields = [
        'load',
        'gross_weight',
        'net_weight',
        'quantity',
        'rate',
        'line_total',
        'created_at',
    ]
    readonly_fields = ['gross_weight', 'net_weight', 'line_total', 'created_at']


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ['method', 'bank', 'amount', 'created_at']
    readonly_fields = ['created_at']


class InvoiceInline(admin.StackedInline):
    """A sale always has exactly one invoice.

    Django has no nested inlines, so the invoice lines are edited one level
    down, on the Invoice that owns them.
    """

    model = Invoice
    extra = 0
    can_delete = False
    # buyer and buyer_amount are managed through PUT /sales/{id}/account/.
    readonly_fields = ['buyer', 'buyer_amount', 'created_at']
    fields = ['buyer', 'buyer_amount', 'created_at']


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'total_amount', 'created_at', 'finalized_at']
    list_filter = ['status']
    date_hierarchy = 'created_at'
    search_fields = ['id']
    inlines = [InvoiceInline, PaymentInline]
    # The server owns status, total_amount and finalized_at.
    readonly_fields = ['status', 'total_amount', 'finalized_at', 'created_at', 'updated_at', 'settlement']
    fields = ['settlement', 'created_by', 'created_at', 'updated_at']

    @admin.display(description='وضعیت حساب')
    def settlement(self, sale):
        if not hasattr(sale, 'invoice'):
            return '—'
        values = sale_summary(sale)
        return ' / '.join(
            f'{key}: {values[key]:,}' for key in ('total', 'paid', 'accounted', 'remaining')
        )


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['id', 'sale', 'buyer', 'buyer_amount']
    readonly_fields = ['sale', 'created_at']
    inlines = [InvoiceLineInline]


@admin.register(Porterage)
class PorterageAdmin(admin.ModelAdmin):
    list_display = ['id', 'sale', 'amount']


@admin.register(PorterageSettings)
class PorterageSettingsAdmin(admin.ModelAdmin):
    """There is only ever one row, so it can neither be added nor removed.

    seed_demo creates it, and the API creates it on the first read.
    """

    list_display = ['works_with_porters', 'rate_per_kg', 'round_enabled']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False