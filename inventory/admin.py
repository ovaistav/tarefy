from django.contrib import admin

from .models import GoodsReceipt, Load, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = ['id', 'created_at']


@admin.register(Load)
class LoadAdmin(admin.ModelAdmin):
    list_display = ['id', 'product', 'label', 'finished_at']
    list_filter = ['product', ('finished_at', admin.EmptyFieldListFilter)]
    search_fields = ['label']
