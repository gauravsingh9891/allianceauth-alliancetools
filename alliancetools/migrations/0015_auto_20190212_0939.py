# Generated by Django 2.0.5 on 2019-02-12 09:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0014_auto_20190212_0857'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='corpasset',
            index=models.Index(fields=['item_id'], name='alliancetoo_item_id_a989ff_idx'),
        ),
        migrations.AddIndex(
            model_name='corpasset',
            index=models.Index(fields=['location_id'], name='alliancetoo_locatio_bc16ae_idx'),
        ),
    ]