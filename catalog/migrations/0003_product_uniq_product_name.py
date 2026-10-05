from django.db import migrations, models

from config.text import normalize_text


def normalize_names(apps, schema_editor):
    """Store names in the canonical form the uniqueness check compares."""
    Product = apps.get_model('catalog', 'Product')
    for product in Product.objects.all().iterator():
        name = normalize_text(product.name)
        if name != product.name:
            product.name = name
            product.save(update_fields=['name'])


def merge_duplicate_names(apps, schema_editor):
    """Fold products that share a name into the oldest one.

    Clients address a product by name, so two products called the same thing are
    indistinguishable. Their loads move to the survivor instead of being lost.
    """
    Product = apps.get_model('catalog', 'Product')
    Load = apps.get_model('inventory', 'Load')

    keeper_by_name = {}
    for product in Product.objects.order_by('pk').iterator():
        keeper_by_name.setdefault(product.name, product.pk)

    for product in Product.objects.order_by('pk').iterator():
        keeper_id = keeper_by_name[product.name]
        if keeper_id == product.pk:
            continue
        Load.objects.filter(product_id=product.pk).update(product_id=keeper_id)
        product.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_backfill_load_tare_weight'),
        ('catalog', '0002_product_background_product_sticker'),
    ]

    operations = [
        migrations.RunPython(normalize_names, migrations.RunPython.noop),
        migrations.RunPython(merge_duplicate_names, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.UniqueConstraint(fields=('name',), name='uniq_product_name', violation_error_message='کالایی با این نام وجود دارد.'),
        ),
    ]