import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor_type", models.CharField(choices=[("HUMAN", "Human"), ("SYSTEM", "System"), ("AGENT", "Agent")], max_length=16)),
                ("actor_id", models.CharField(max_length=128)),
                ("action", models.CharField(max_length=128)),
                ("object_type", models.CharField(max_length=128)),
                ("object_id", models.CharField(max_length=128)),
                ("before_hash", models.CharField(blank=True, max_length=64)),
                ("after_hash", models.CharField(blank=True, max_length=64)),
                ("correlation_id", models.CharField(max_length=128)),
                ("causation_id", models.CharField(blank=True, max_length=128)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "ordering": ["-occurred_at"],
            },
        ),
        migrations.CreateModel(
            name="Rule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("rule_id", models.CharField(max_length=128)),
                ("version", models.PositiveIntegerField()),
                ("name", models.CharField(max_length=200)),
                ("owner", models.CharField(max_length=128)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("VALIDATED", "Validated"), ("TESTED", "Tested"), ("PENDING_APPROVAL", "Pending Approval"), ("ACTIVE", "Active"), ("SUSPENDED", "Suspended"), ("RETIRED", "Retired")], default="DRAFT", max_length=32)),
                ("trigger", models.JSONField(default=dict)),
                ("conditions", models.JSONField(default=dict)),
                ("decision", models.CharField(max_length=32)),
                ("reason_codes", models.JSONField(blank=True, default=list)),
                ("schema_version", models.PositiveIntegerField(default=1)),
                ("approved_by", models.CharField(blank=True, max_length=128)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="RuleEvaluation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_id", models.CharField(max_length=128)),
                ("decision", models.CharField(choices=[("ALLOW", "Allow"), ("ALLOW_AND_NOTIFY", "Allow And Notify"), ("REQUIRE_APPROVAL", "Require Approval"), ("BLOCK", "Block"), ("NEEDS_MORE_DATA", "Needs More Data")], max_length=32)),
                ("matched_paths", models.JSONField(blank=True, default=list)),
                ("reason_codes", models.JSONField(blank=True, default=list)),
                ("input_snapshot_hash", models.CharField(max_length=64)),
                ("evaluated_at", models.DateTimeField(auto_now_add=True)),
                ("rule", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="evaluations", to="governance.rule")),
            ],
        ),
        migrations.AddConstraint(
            model_name="rule",
            constraint=models.UniqueConstraint(fields=("rule_id", "version"), name="unique_rule_version"),
        ),
        migrations.AddConstraint(
            model_name="rule",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "ACTIVE")), fields=("rule_id",), name="unique_active_rule_per_rule_id"),
        ),
    ]
