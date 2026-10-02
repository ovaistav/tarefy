from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from accounting.models import Bank
from inventory.models import Load
from parties.models import Party

from .models import InvoiceLine, Payment, PorterageSettings, Sale
from .services import line_amounts


def party_brief(party):
    """The trimmed party shape the app uses everywhere."""
    if party is None:
        return None
    return {'id': party.id, 'name': party.name, 'label': party.label}


class SaleLineSerializer(serializers.ModelSerializer):
    product = serializers.IntegerField(source='load.product_id', read_only=True)
    product_name = serializers.CharField(source='load.product.name', read_only=True)
    label = serializers.CharField(source='load.label', read_only=True)

    class Meta:
        model = InvoiceLine
        fields = [
            'id',
            'load',
            'product',
            'product_name',
            'label',
            'quantity',
            'gross_weight',
            'net_weight',
            'rate',
            'line_total',
        ]
        read_only_fields = fields


class SalePaymentSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(
        source='bank.name', read_only=True, allow_null=True
    )

    class Meta:
        model = Payment
        fields = ['id', 'method', 'bank', 'bank_name', 'amount']
        read_only_fields = fields


class SaleDetailSerializer(serializers.ModelSerializer):
    # The lines hang off the invoice, so the source has to say so; otherwise
    # DRF silently drops the field.
    lines = SaleLineSerializer(
        many=True, read_only=True, source='invoice.lines'
    )
    porterage = serializers.SerializerMethodField()
    payments = SalePaymentSerializer(many=True, read_only=True)
    account = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            'id',
            'status',
            'total_amount',
            'created_at',
            'finalized_at',
            'lines',
            'porterage',
            'payments',
            'account',
            'summary',
        ]
        read_only_fields = fields

    def get_porterage(self, sale):
        return {'amount': int(sale.porterage.amount)}

    def get_account(self, sale):
        # The account is absent until the sale is tied to a party.
        if sale.invoice.buyer_id is None:
            return None
        return {
            'party': party_brief(sale.invoice.buyer),
            'amount': int(sale.invoice.buyer_amount or 0),
        }

    def get_summary(self, sale):
        from .services import sale_summary

        return sale_summary(sale)


class SaleListItemSerializer(serializers.ModelSerializer):
    party = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = ['id', 'status', 'total_amount', 'created_at', 'party', 'products']
        read_only_fields = fields

    def get_party(self, sale):
        return party_brief(sale.invoice.buyer)

    def get_products(self, sale):
        from .services import distinct_products

        return [
            {
                'id': product.id,
                'sticker': product.sticker,
                'background': product.background,
            }
            for product in distinct_products(sale)
        ]


def _positive_gross_weight(value):
    if value <= 0:
        raise serializers.ValidationError(_('وزن ناخالص باید بزرگ‌تر از صفر باشد.'))
    return value


class SaleLineCreateSerializer(serializers.Serializer):
    load = serializers.PrimaryKeyRelatedField(queryset=Load.objects.all())
    gross_weight = serializers.DecimalField(
        max_digits=10, decimal_places=3, min_value=0
    )
    quantity = serializers.IntegerField(min_value=0)
    rate = serializers.IntegerField(min_value=0)

    def validate_gross_weight(self, value):
        return _positive_gross_weight(value)

    def validate(self, attrs):
        _reject_empty_net(attrs['load'], attrs['gross_weight'], attrs['quantity'],
                          attrs['rate'])
        return attrs


class SaleLinePatchSerializer(serializers.Serializer):
    """Only the keys the client sends actually change."""

    load = serializers.PrimaryKeyRelatedField(
        queryset=Load.objects.all(), required=False
    )
    gross_weight = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, min_value=0
    )
    quantity = serializers.IntegerField(required=False, min_value=0)
    rate = serializers.IntegerField(required=False, min_value=0)

    def validate_gross_weight(self, value):
        return _positive_gross_weight(value)

    def validate(self, attrs):
        line = self.context['line']
        _reject_empty_net(
            attrs.get('load', line.load),
            attrs.get('gross_weight', line.gross_weight),
            attrs.get('quantity', line.quantity),
            attrs.get('rate', line.rate),
        )
        return attrs


def _reject_empty_net(load, gross_weight, quantity, rate):
    """The net weight is derived, so it is reported as its own field error."""
    net_weight, _ = line_amounts(load, gross_weight, quantity, rate)
    if net_weight <= 0:
        raise serializers.ValidationError(
            {'net_weight': [_('وزن خالص باید بزرگ‌تر از صفر باشد.')]}
        )


class PorterageWriteSerializer(serializers.Serializer):
    """Stored exactly as sent: a manual amount is the base for later deltas."""

    amount = serializers.IntegerField(min_value=0)


class PaymentRulesMixin:
    """pos and card_transfer name a bank; cheque and cash must not."""

    @property
    def current_payment(self):
        """The stored payment, when this is a PATCH."""
        if hasattr(self, 'instance'):
            return self.instance
        return self.context.get('payment')

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(_('مبلغ پرداخت باید بزرگ‌تر از صفر باشد.'))
        return value

    def validate(self, attrs):
        current = self.current_payment
        method = attrs.get('method', getattr(current, 'method', None))
        bank = attrs['bank'] if 'bank' in attrs else getattr(current, 'bank', None)

        needs_bank = method in (Payment.Method.POS, Payment.Method.CARD_TRANSFER)
        if needs_bank and bank is None:
            raise serializers.ValidationError(
                {'bank': [_('برای این روش پرداخت انتخاب بانک الزامی است.')]}
            )
        if not needs_bank and bank is not None:
            raise serializers.ValidationError(
                {'bank': [_('برای این روش پرداخت نباید بانکی انتخاب شود.')]}
            )
        return attrs


class PaymentCreateSerializer(PaymentRulesMixin, serializers.Serializer):
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    bank = serializers.PrimaryKeyRelatedField(
        queryset=Bank.objects.all(), required=False, allow_null=True
    )
    amount = serializers.IntegerField()


class PaymentPatchSerializer(PaymentRulesMixin, serializers.Serializer):
    method = serializers.ChoiceField(choices=Payment.Method.choices, required=False)
    bank = serializers.PrimaryKeyRelatedField(
        queryset=Bank.objects.all(), required=False, allow_null=True
    )
    amount = serializers.IntegerField(required=False)


class AccountWriteSerializer(serializers.Serializer):
    party = serializers.PrimaryKeyRelatedField(queryset=Party.objects.all())
    # Positive: the party owes us. Negative: we owe the party. Never zero.
    amount = serializers.IntegerField()

    def validate_amount(self, value):
        if value == 0:
            raise serializers.ValidationError(_('مبلغ حساب نمی‌تواند صفر باشد.'))
        return value


class PorterageSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PorterageSettings
        fields = ['works_with_porters', 'rate_per_kg', 'round_enabled']

    def validate_rate_per_kg(self, value):
        if value < 0:
            raise serializers.ValidationError(
                _('نرخ هر کیلوگرم نمی‌تواند منفی باشد.')
            )
        return value