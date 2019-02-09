# Generated by Django 2.0.5 on 2019-02-09 05:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0007_auto_20190206_1409'),
    ]

    operations = [
        migrations.CreateModel(
            name='BridgeOzoneLevel',
            fields=[
                ('station_id', models.CharField(max_length=500)),
                ('quantity', models.BigIntegerField(primary_key=True, serialize=False)),
                ('date', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
