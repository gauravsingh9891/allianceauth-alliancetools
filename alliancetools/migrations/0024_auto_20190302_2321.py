# Generated by Django 2.0.5 on 2019-03-02 23:21

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0023_auto_20190301_0851'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationalert',
            name='corporation',
            field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='eveonline.EveCorporationInfo'),
        ),
    ]
