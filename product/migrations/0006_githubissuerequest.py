import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0003_objectiverisk"),
        ("product", "0005_competitiveanalysisdraft"),
    ]

    operations = [
        migrations.CreateModel(
            name="GithubIssueRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField()),
                ("repository_owner", models.CharField(max_length=128)),
                ("repository_name", models.CharField(max_length=128)),
                ("secret_reference_name", models.CharField(max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("PENDING_APPROVAL", "Pending Approval"),
                            ("CREATED", "Created"),
                            ("FAILED", "Failed"),
                        ],
                        default="DRAFT",
                        max_length=24,
                    ),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("allowed_action", models.CharField(default="create_issue", max_length=32)),
                ("approval_request_id", models.UUIDField(blank=True, null=True)),
                ("issue_number", models.PositiveIntegerField(blank=True, null=True)),
                ("issue_url", models.CharField(blank=True, max_length=300)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="github_issue_requests",
                        to="portfolio.project",
                    ),
                ),
                (
                    "project_connection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="github_issue_requests",
                        to="portfolio.projectconnection",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
