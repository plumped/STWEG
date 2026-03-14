"""
0007_fix_unanimous_label

Korrigiert die Anzeige der Einstimmigkeit-Option:
Neu: «alle Eigentümer müssen Ja stimmen» (rechtlich korrekt nach ZGB Art. 648)
Alt: «Enthaltung gilt als Nein» (zu verkürzt / missverständlich)

Keine Datenbankänderung nötig — nur der verbose_name-Wert im CharField.choices
ändert sich. Diese Migration aktualisiert den Choices-Wert in der DB-Übersicht
und triggert keine Schema-Migration.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voting', '0006_unit_owner_nullable_invite_token'),
    ]

    operations = [
        migrations.AlterField(
            model_name='proposal',
            name='majority_type',
            field=models.CharField(
                choices=[
                    ('simple',    'Einfaches Mehr (nur Köpfe)'),
                    ('absolute',  'Absolutes Mehr (Köpfe + Wertquoten)'),
                    ('qualified', 'Qualifiziertes Mehr (2/3 Köpfe + 2/3 Wertquoten)'),
                    ('unanimous', 'Einstimmigkeit (alle Eigentümer müssen Ja stimmen)'),
                ],
                default='absolute',
                max_length=10,
                verbose_name='Mehrheitsart',
            ),
        ),
    ]