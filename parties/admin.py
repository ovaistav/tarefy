from django.contrib import admin

from .models import Party


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'label', 'phone', 'national_code', 'commission']
    search_fields = ['name', 'label', 'phone', 'national_code']
    readonly_fields = ['created_at', 'updated_at']