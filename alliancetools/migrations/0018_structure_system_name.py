# Generated by Django 2.0.5 on 2019-02-19 09:59

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0017_auto_20190217_0658'),
    ]

    operations = [
        migrations.AddField(
            model_name='structure',
            name='system_name',
            field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='alliancetools.MapSolarSystem'),
        ),
    ]
