# Generated by Django 2.2.2 on 2019-07-19 09:16

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0036_auto_20190719_0815'),
    ]

    operations = [
        migrations.AlterField(
            model_name='markethistory',
            name='item',
            field=models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, to='alliancetools.TypeName'),
        ),
    ]
