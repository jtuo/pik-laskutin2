# Generated by Django 5.1.3 on 2024-12-04 22:16

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('invoicing', '0001_initial'),
        ('operations', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='accountentry',
            name='event',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='account_entries', to='operations.baseevent'),
        ),
        migrations.AddField(
            model_name='accountentrytag',
            name='entry',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tags', to='invoicing.accountentry'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='account',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoices', to='invoicing.account'),
        ),
        migrations.AddField(
            model_name='accountentry',
            name='invoice',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='entries', to='invoicing.invoice'),
        ),
        migrations.AddIndex(
            model_name='accountentrytag',
            index=models.Index(fields=['value'], name='account_ent_value_ffae03_idx'),
        ),
        migrations.AddConstraint(
            model_name='accountentrytag',
            constraint=models.UniqueConstraint(fields=('entry', 'value'), name='unique_entry_tag'),
        ),
    ]
