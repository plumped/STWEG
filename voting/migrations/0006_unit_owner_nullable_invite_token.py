"""
0006_unit_owner_nullable_invite_token

Changes:
  1. Unit.owner  → nullable (null=True, blank=True, on_delete=SET_NULL)
     Allows admin to create units without an owner first, then invite owners
     via the new InviteToken flow.

  2. InviteToken model added.
     Single-use, community-scoped invitation links for self-registration.
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voting', '0005_membership_vote_manual'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── 1. Make Unit.owner nullable ────────────────────────────────────
        migrations.AlterField(
            model_name='unit',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='units',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # ── 2. Add InviteToken ─────────────────────────────────────────────
        migrations.CreateModel(
            name='InviteToken',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name='ID',
                )),
                ('token', models.UUIDField(
                    default=uuid.uuid4, editable=False, unique=True,
                )),
                ('email', models.EmailField(
                    blank=True,
                    help_text='Optional: E-Mail-Adresse vorausfüllen',
                )),
                ('role', models.CharField(
                    choices=[
                        ('owner',   'Eigentümer'),
                        ('manager', 'Verwalter'),
                        ('board',   'Beirat'),
                    ],
                    default='owner',
                    max_length=10,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(
                    blank=True,
                    help_text='Leer = kein Ablaufdatum',
                    null=True,
                )),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='Deaktivieren = Link sofort ungültig',
                )),
                ('community', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invite_tokens',
                    to='voting.community',
                )),
                ('created_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_invites',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('unit', models.ForeignKey(
                    blank=True,
                    help_text='Optional: Einheit automatisch zuweisen (nur bei Rolle Eigentümer)',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='invite_tokens',
                    to='voting.unit',
                )),
                ('used_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='used_invites',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name':        'Einladung',
                'verbose_name_plural': 'Einladungen',
                'ordering':            ['-created_at'],
            },
        ),
    ]