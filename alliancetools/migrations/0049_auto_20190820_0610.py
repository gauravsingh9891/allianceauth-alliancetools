# Generated by Django 2.2.2 on 2019-08-20 06:10

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('eveonline', '0010_alliance_ticker'),
        ('alliancetools', '0048_rentalinvoice'),
    ]

    operations = [
        migrations.CreateModel(
            name='AllianceContact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contact_id', models.BigIntegerField(default=None, null=True)),
                ('contact_type', models.CharField(choices=[('faction', 'faction'), ('character', 'character'), ('corporation', 'corporation'), ('alliance', 'alliance')], default=None, max_length=15, null=True)),
                ('standing', models.DecimalField(decimal_places=2, default=None, max_digits=5, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='AllianceContactLabel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label_id', models.BigIntegerField()),
                ('label_name', models.CharField(max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CorporateContact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contact_id', models.BigIntegerField(default=None, null=True)),
                ('contact_type', models.CharField(choices=[('faction', 'faction'), ('character', 'character'), ('corporation', 'corporation'), ('alliance', 'alliance')], default=None, max_length=15, null=True)),
                ('standing', models.DecimalField(decimal_places=2, default=None, max_digits=5, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CorporateContactLabel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label_id', models.BigIntegerField()),
                ('label_name', models.CharField(max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='alliancetoolcharacter',
            name='last_update_contact',
            field=models.DateTimeField(default=None, null=True),
        ),
        migrations.AddField(
            model_name='alliancetoolcharacter',
            name='next_update_contact',
            field=models.DateTimeField(default=None, null=True),
        ),
        migrations.AddIndex(
            model_name='corporationwalletjournalentry',
            index=models.Index(fields=['ref_type'], name='alliancetoo_ref_typ_411162_idx'),
        ),
        migrations.AddField(
            model_name='corporatecontactlabel',
            name='corporation',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='eveonline.EveCorporationInfo'),
        ),
        migrations.AddField(
            model_name='corporatecontact',
            name='corp',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='at_corp_contact', to='eveonline.EveCorporationInfo'),
        ),
        migrations.AddField(
            model_name='corporatecontact',
            name='labels',
            field=models.ManyToManyField(to='alliancetools.CorporateContactLabel'),
        ),
        migrations.AddField(
            model_name='alliancecontactlabel',
            name='alliance',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='eveonline.EveAllianceInfo'),
        ),
        migrations.AddField(
            model_name='alliancecontact',
            name='alliance',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='at_alli_contact', to='eveonline.EveAllianceInfo'),
        ),
        migrations.AddField(
            model_name='alliancecontact',
            name='labels',
            field=models.ManyToManyField(to='alliancetools.AllianceContactLabel'),
        ),
    ]