from django.contrib import admin

from .models import Bank


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']