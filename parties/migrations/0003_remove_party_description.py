"""Drop Party.description.

Destructive: any text stored in the column is lost. ``details`` is where free-form
notes live now, and ``label`` (shown to the app as "توصیف") is the short
nickname. Reversing this restores an empty column, not the old text.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('parties', '0002_party_account_number'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='party',
            name='description',
        ),
    ]