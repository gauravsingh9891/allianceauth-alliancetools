# Generated by Django 2.2.2 on 2019-07-16 13:30

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0034_auto_20190702_1005'),
    ]

    operations = [
        migrations.AddField(
            model_name='miningobservation',
            name='char',
            field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='alliancetools.EveName'),
        ),
    ]
