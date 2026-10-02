from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from config.text import normalize_digits, normalize_text

from .models import Party
from .validators import validate_details, validate_national_code


class PartyListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ['id', 'name', 'label']


class PartySerializer(serializers.ModelSerializer):
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
    description = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Party
        fields = [
            'id',
            'name',
            'label',
            'phone',
            'national_code',
            'commission',
            'description',
            'details',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        value = normalize_text(value)
        if not value:
            raise serializers.ValidationError(_('نام الزامی است.'))
        return value

    def validate_label(self, value):
        value = normalize_text(value)
        if not value:
            raise serializers.ValidationError(_('برچسب الزامی است.'))
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