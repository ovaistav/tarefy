from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'tare_weight', 'image', 'updated_at']
    search_fields = ['name']
    readonly_fields = ['image_updated_at', 'updated_at']
