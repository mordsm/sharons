import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("governance", "0005_outboxmessage_inboxevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="RuleTestCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("input_event", models.JSONField(default=dict)),
                (
                    "expected_decision",
                    models.CharField(
                        choices=[
                            ("ALLOW", "Allow"),
                            ("ALLOW_AND_NOTIFY", "Allow And Notify"),
                            ("REQUIRE_APPROVAL", "Require Approval"),
                            ("BLOCK", "Block"),
                            ("NEEDS_MORE_DATA", "Needs More Data"),
                        ],
                        max_length=32,
                    ),
                ),
                ("expected_match", models.BooleanField(default=True)),
                ("passed", models.BooleanField(default=False)),
                ("actual_decision", models.CharField(blank=True, max_length=32)),
                ("matched_paths", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "rule",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="test_cases", to="governance.rule"),
                ),
            ],
        ),
    ]
