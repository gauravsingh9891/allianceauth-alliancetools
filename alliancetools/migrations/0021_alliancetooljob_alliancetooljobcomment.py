# Generated by Django 2.0.5 on 2019-02-26 08:02

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('eveonline', '0010_alliance_ticker'),
        ('alliancetools', '0020_auto_20190220_1205'),
    ]

    operations = [
        migrations.CreateModel(
            name='AllianceToolJob',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=500)),
                ('description', models.TextField()),
                ('created', models.DateTimeField()),
                ('completed', models.DateTimeField(default=None, null=True)),
                ('assined_to', models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assined_to', to='eveonline.EveCharacter')),
                ('creator', models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='eveonline.EveCharacter')),
            ],
        ),
        migrations.CreateModel(
            name='AllianceToolJobComment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('comment', models.TextField()),
                ('created', models.DateTimeField()),
                ('commenter', models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commenter', to='eveonline.EveCharacter')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='alliancetools.AllianceToolJob')),
            ],
        ),
    ]