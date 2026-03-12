from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('voting', '0003_majority_type_update'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Quorum auf Gemeinschaft
        migrations.AddField(
            model_name='community',
            name='quorum',
            field=models.DecimalField(
                decimal_places=1,
                default=Decimal('0'),
                help_text='Mindest-Beteiligung in Wertquoten ‰ für gültige Abstimmung (0 = kein Quorum)',
                max_digits=5,
                verbose_name='Quorum (‰)',
            ),
        ),
        # Beilagendokumente
        migrations.CreateModel(
            name='ProposalDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Bezeichnung')),
                ('file', models.FileField(upload_to='proposal_docs/', verbose_name='Datei')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('proposal', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents',
                    to='voting.proposal',
                )),
                ('uploaded_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='uploaded_documents',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Dokument',
                'verbose_name_plural': 'Dokumente',
                'ordering': ['uploaded_at'],
            },
        ),
        # Vollmachten
        migrations.CreateModel(
            name='Proxy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('granted_at', models.DateTimeField(auto_now_add=True)),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='Bemerkung')),
                ('delegate', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='received_proxies',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Bevollmächtigte Person',
                )),
                ('granted_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='granted_proxies',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('proposal', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='proxies',
                    to='voting.proposal',
                )),
                ('unit', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='proxies',
                    to='voting.unit',
                )),
            ],
            options={
                'verbose_name': 'Vollmacht',
                'verbose_name_plural': 'Vollmachten',
                'unique_together': {('proposal', 'unit')},
            },
        ),
    ]