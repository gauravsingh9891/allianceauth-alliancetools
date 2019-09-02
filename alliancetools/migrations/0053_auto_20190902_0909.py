# Generated by Django 2.2.2 on 2019-09-02 09:09

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0052_fuelnotifierfilter_fuelping'),
    ]

    operations = [
        migrations.CreateModel(
            name='StructureCelestial',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('structure_id', models.BigIntegerField()),
                ('celestial_name', models.CharField(default=None, max_length=500, null=True)),
            ],
        ),
        migrations.AddField(
            model_name='structure',
            name='closest_celestial',
            field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='alliancetools.StructureCelestial'),
        ),
    ]