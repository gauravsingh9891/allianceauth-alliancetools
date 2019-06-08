# Generated by Django 2.1.7 on 2019-05-25 04:02

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0027_auto_20190411_0741'),
    ]

    operations = [
        migrations.AddField(
            model_name='poco',
            name='solar_system',
            field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='solar_system', to='alliancetools.MapSolarSystem'),
        ),
    ]