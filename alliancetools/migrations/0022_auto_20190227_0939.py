# Generated by Django 2.0.5 on 2019-02-27 09:39

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('alliancetools', '0021_alliancetooljob_alliancetooljobcomment'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='alliancetoolcharacter',
            options={'permissions': (('access_alliance_tools', 'Can access alliance_tools'), ('access_alliance_tools_structures', 'Can access structures'), ('access_alliance_tools_structure_fittings', 'Can access structure fittings'), ('access_alliance_tools_structures_renter', 'Can access renter structures'), ('access_alliance_tools_structure_fittings_renter', 'Can access structure renter fittings'), ('admin_alliance_tools', 'Can add tokens to alliance tools'))},
        ),
    ]