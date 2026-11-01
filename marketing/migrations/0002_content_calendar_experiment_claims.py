import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("marketing", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentCalendarItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("LANDING_DRAFT", "Landing Draft"),
                            ("EMAIL_DRAFT", "Email Draft"),
                            ("SOCIAL_DRAFT", "Social Draft"),
                        ],
                        max_length=32,
                    ),
                ),
                ("planned_on", models.DateField()),
                ("body", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("DRAFT", "Draft"), ("ACKNOWLEDGED", "Acknowledged"), ("REJECTED", "Rejected")],
                        default="DRAFT",
                        max_length=32,
                    ),
                ),
                ("will_publish", models.BooleanField(default=False)),
                ("will_send", models.BooleanField(default=False)),
                ("created_by", models.CharField(default="marketing", max_length=128)),
                ("correlation_id", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="calendar_items",
                        to="marketing.marketingrequest",
                    ),
                ),
            ],
            options={"ordering": ["planned_on", "created_at"]},
        ),
        migrations.CreateModel(
            name="MarketingExperiment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("hypothesis", models.TextField()),
                ("metric", models.CharField(max_length=128)),
                ("notes", models.TextField(blank=True)),
                ("sample_size", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("PROPOSED", "Proposed"), ("ACKNOWLEDGED", "Acknowledged"), ("REJECTED", "Rejected")],
                        default="PROPOSED",
                        max_length=32,
                    ),
                ),
                ("will_spend", models.BooleanField(default=False)),
                ("significance_claimed", models.BooleanField(default=False)),
                ("created_by", models.CharField(default="marketing", max_length=128)),
                ("correlation_id", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="experiments",
                        to="marketing.marketingrequest",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="MarketingClaim",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("text", models.TextField()),
                ("evidence_note", models.TextField(blank=True)),
                ("supported", models.BooleanField(default=False)),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("NEEDS_REVIEW", "Needs Review"),
                            ("ACCEPTED", "Accepted"),
                            ("ACKNOWLEDGED_UNSUPPORTED", "Acknowledged Unsupported"),
                            ("REJECTED", "Rejected"),
                        ],
                        default="NEEDS_REVIEW",
                        max_length=32,
                    ),
                ),
                ("created_by", models.CharField(default="marketing", max_length=128)),
                ("correlation_id", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="claims",
                        to="marketing.marketingrequest",
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
