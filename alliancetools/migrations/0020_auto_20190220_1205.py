# Generated by Django 2.0.5 on 2019-02-20 12:05

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0019_structure_type_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='EveName',
            fields=[
                ('eve_id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=500)),
                ('category', models.CharField(max_length=500)),
                ('corp', models.CharField(default=None, max_length=500, null=True)),
                ('alliance', models.CharField(default=None, max_length=500, null=True)),
            ],
        ),
        migrations.AddField(
            model_name='corporationwalletjournalentry',
            name='first_party_name',
            field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='first_party_evename', to='alliancetools.EveName'),
        ),
        migrations.AddField(
            model_name='corporationwalletjournalentry',
            name='second_party_name',
            field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='second_party_evename', to='alliancetools.EveName'),
        ),
    ]