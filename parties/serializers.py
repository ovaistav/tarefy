from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from config.text import normalize_digits, normalize_text

from .models import Party
from .validators import validate_details, validate_national_code


class PartyListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ['id', 'name', 'label']


class PartySerializer(serializers.ModelSerializer):
    # ``label`` is the short "توصیف" the app shows next to the name. It keeps its
    # API name so existing clients do not break.
    #
    # allow_blank lets an empty value reach validate_label, which is what turns
    # DRF's generic "این مقدار نباید خاب باشد." into a message that names the
    # field. Nothing blank is ever stored: validate_label still rejects it.
    label = serializers.CharField(max_length=100, allow_blank=True)
    # The model-level validators are reused verbatim so the API and the admin
    # reject the same inputs with the same Persian messages.
    national_code = serializers.CharField(
        max_length=10,
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[validate_national_code],
    )
    commission = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        min_value=0,
        max_value=100,
    )
    details = serializers.JSONField(required=False, validators=[validate_details])
    phone = serializers.CharField(
        max_length=20, required=False, allow_null=True, allow_blank=True
    )
    # Same shape as phone; the digits are normalized when the row is saved.
    account_number = serializers.CharField(
        max_length=20, required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        model = Party
        fields = [
            'id',
            'name',
            'label',
            'phone',
            'account_number',
            'national_code',
            'commission',
            'details',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        # DRF derives a UniqueTogetherValidator for (name, label), but its default
        # message names the fields in English ("فیلدهای name, label باید...").
        # Replaced here with the same Persian wording the IntegrityError path in
        # the view uses, so a duplicate pair always reads the same. A partial
        # update that touches only one of the two fields skips this entirely,
        # which is why PATCH {"commission": ...} is unaffected.
        validators = [
            UniqueTogetherValidator(
                queryset=Party.objects.all(),
                fields=('name', 'label'),
                message=_('طرف حسابی با همین نام و توصیف قبلاً ثبت شده است.'),
            )
        ]

    def validate_name(self, value):
        value = normalize_text(value)
        if not value:
            raise serializers.ValidationError(_('نام الزامی است.'))
        return value

    def validate_label(self, value):
        value = normalize_text(value)
        if not value:
            raise serializers.ValidationError(_('توصیف الزامی است.'))
        return value

    def validate(self, attrs):
        # DRF derives a UniqueTogetherValidator for (name, label), but it skips
        # *conditional* constraints, so national_code needs its own check to
        # fail fast with a readable message. The database remains the authority;
        # the view still maps a racing IntegrityError to the same 400.
        code = attrs.get('national_code')
        if code:
            code = normalize_digits(code).strip()
            clash = Party.objects.filter(national_code=code)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {'national_code': [_('کد ملی قبلاً ثبت شده است.')]}
                )
        return attrs