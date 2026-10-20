import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("executive_assistant", "0007_executivecalendarevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExecutiveProviderSyncConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "provider_type",
                    models.CharField(choices=[("EMAIL", "Email"), ("CALENDAR", "Calendar")], max_length=24),
                ),
                ("provider_name", models.CharField(max_length=80)),
                ("source", models.CharField(max_length=128)),
                (
                    "sync_mode",
                    models.CharField(choices=[("READ_ONLY", "Read Only")], default="READ_ONLY", max_length=24),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PLANNED", "Planned"),
                            ("READY_FOR_CONNECTOR", "Ready For Connector"),
                            ("PAUSED", "Paused"),
                            ("ERROR", "Error"),
                        ],
                        default="PLANNED",
                        max_length=32,
                    ),
                ),
                ("scopes", models.JSONField(blank=True, default=list)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("last_sync_at", models.DateTimeField(blank=True, null=True)),
                ("no_external_action", models.BooleanField(default=True)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["provider_type", "provider_name", "source"],
            },
        ),
        migrations.AddConstraint(
            model_name="executiveprovidersyncconfig",
            constraint=models.UniqueConstraint(
                fields=("provider_type", "provider_name", "source"),
                name="unique_ea_provider_sync_config",
            ),
        ),
    ]
