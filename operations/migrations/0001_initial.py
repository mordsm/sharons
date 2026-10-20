import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("portfolio", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Plan",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("version", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("PENDING_APPROVAL", "Pending Approval"), ("ACTIVE", "Active"), ("CLOSED", "Closed")], default="DRAFT", max_length=32)),
                ("assumptions", models.JSONField(blank=True, default=dict)),
                ("risks", models.JSONField(blank=True, default=dict)),
                ("created_by", models.CharField(max_length=128)),
                ("approved_by", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("objective", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="plans", to="portfolio.objective")),
            ],
        ),
        migrations.CreateModel(
            name="Task",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("external_key", models.CharField(blank=True, max_length=128)),
                ("title", models.CharField(max_length=240)),
                ("business_outcome", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("PLANNED", "Planned"), ("PENDING_APPROVAL", "Pending Approval"), ("APPROVED", "Approved"), ("ASSIGNED", "Assigned"), ("IN_PROGRESS", "In Progress"), ("BLOCKED", "Blocked"), ("DELIVERED_UNVERIFIED", "Delivered Unverified"), ("VERIFYING", "Verifying"), ("COMPLETED", "Completed"), ("FAILED", "Failed"), ("CANCELLED", "Cancelled")], default="DRAFT", max_length=32)),
                ("created_by", models.CharField(max_length=128)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("objective", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tasks", to="portfolio.objective")),
                ("plan", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="tasks", to="operations.plan")),
            ],
        ),
        migrations.CreateModel(
            name="AcceptanceCriterion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("description", models.TextField()),
                ("criterion_type", models.CharField(choices=[("MANUAL", "Manual"), ("AUTOMATED", "Automated"), ("EVIDENCE", "Evidence")], default="MANUAL", max_length=16)),
                ("required", models.BooleanField(default=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("PASSED", "Passed"), ("FAILED", "Failed")], default="PENDING", max_length=16)),
                ("verified_by", models.CharField(blank=True, max_length=128)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="acceptance_criteria", to="operations.task")),
            ],
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.UniqueConstraint(condition=models.Q(("external_key", ""), _negated=True), fields=("objective", "external_key"), name="unique_task_external_key_per_objective"),
        ),
    ]
