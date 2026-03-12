from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voting', '0002_community_created_by'),
    ]

    operations = [
        # Rename old 'double' values to 'absolute' in existing rows
        migrations.RunSQL(
            sql="UPDATE voting_proposal SET majority_type = 'absolute' WHERE majority_type = 'double';",
            reverse_sql="UPDATE voting_proposal SET majority_type = 'double' WHERE majority_type = 'absolute';",
        ),
        migrations.AlterField(
            model_name='proposal',
            name='majority_type',
            field=models.CharField(
                choices=[
                    ('simple',    'Einfaches Mehr (nur Köpfe)'),
                    ('absolute',  'Absolutes Mehr (Köpfe + Wertquoten)'),
                    ('qualified', 'Qualifiziertes Mehr (2/3 Köpfe + 2/3 Wertquoten)'),
                    ('unanimous', 'Einstimmigkeit (Enthaltung gilt als Nein)'),
                ],
                default='absolute',
                max_length=10,
                verbose_name='Mehrheitsart',
            ),
        ),
    ]