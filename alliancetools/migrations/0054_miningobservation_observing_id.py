# Generated by Django 2.2.2 on 2019-09-03 09:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0053_auto_20190902_0909'),
    ]

    operations = [
        migrations.AddField(
            model_name='miningobservation',
            name='observing_id',
            field=models.BigIntegerField(blank=True, default=None, null=True),
        ),
    ]