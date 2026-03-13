from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('voting', '0004_proxy_document_quorum'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- Vote: manual / cast_by fields ---
        migrations.AddField(
            model_name='vote',
            name='cast_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cast_votes',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Erfasst durch',
            ),
        ),
        migrations.AddField(
            model_name='vote',
            name='is_manual',
            field=models.BooleanField(default=False, verbose_name='Schriftliche Stimmabgabe'),
        ),
        migrations.AddField(
            model_name='vote',
            name='manual_source',
            field=models.CharField(
                blank=True,
                max_length=200,
                verbose_name='Quellenangabe',
                help_text="z.B. 'Briefpost vom 12.3.2026', 'E-Mail', 'Telefonisch bestätigt'",
            ),
        ),

        # --- CommunityMembership ---
        migrations.CreateModel(
            name='CommunityMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(
                    choices=[('manager', 'Verwalter'), ('board', 'Beirat')],
                    default='manager',
                    max_length=10,
                )),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('added_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='added_memberships',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('community', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='memberships',
                    to='voting.community',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='community_memberships',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Mitgliedschaft',
                'verbose_name_plural': 'Mitgliedschaften',
                'ordering': ['role', 'user__last_name'],
                'unique_together': {('community', 'user')},
            },
        ),
    ]