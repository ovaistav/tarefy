"""Copy each product's default basket weight onto its existing loads.

The column was added with a default of 0, so pre-existing loads would otherwise
keep a tare of 0 and produce a wrong net weight if they are ever sold.
"""

from django.db import migrations


def copy_product_tare_to_loads(apps, schema_editor):
    Load = apps.get_model('inventory', 'Load')
    Product = apps.get_model('catalog', 'Product')
    for product in Product.objects.all().iterator():
        # Only fill in the zero default; never overwrite a real value.
        Load.objects.filter(product_id=product.pk, tare_weight=0).update(
            tare_weight=product.tare_weight
        )


def noop(apps, schema_editor):
    """The reverse direction cannot know the original per-load values."""


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0002_product_background_product_sticker'),
        ('inventory', '0002_alter_load_supplier_load_tare_weight_delete_supplier'),
    ]

    operations = [
        migrations.RunPython(copy_product_tare_to_loads, noop),
    ]