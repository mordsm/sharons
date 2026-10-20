import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("executive_assistant", "0006_executiveemaildraft_review_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExecutiveCalendarEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(default="calendar_readonly", max_length=128)),
                ("external_event_id", models.CharField(max_length=200)),
                ("title", models.CharField(max_length=240)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("organizer", models.EmailField(blank=True, max_length=254)),
                ("attendees", models.JSONField(blank=True, default=list)),
                ("location", models.CharField(blank=True, max_length=240)),
                ("description", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("CONFIRMED", "Confirmed"), ("TENTATIVE", "Tentative"), ("CANCELLED", "Cancelled")],
                        default="CONFIRMED",
                        max_length=24,
                    ),
                ),
                ("no_external_schedule", models.BooleanField(default=True)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["starts_at", "created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="executivecalendarevent",
            constraint=models.UniqueConstraint(fields=("source", "external_event_id"), name="unique_ea_calendar_source_external_id"),
        ),
    ]
