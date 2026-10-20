import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("slug", models.SlugField(unique=True)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("IDEA", "Idea"), ("DISCOVERY", "Discovery"), ("ACTIVE", "Active"), ("PAUSED", "Paused"), ("ARCHIVED", "Archived")], default="IDEA", max_length=16)),
                ("repository_provider", models.CharField(blank=True, max_length=64)),
                ("repository_reference", models.CharField(blank=True, max_length=500)),
                ("default_branch", models.CharField(blank=True, max_length=128)),
                ("owner", models.CharField(max_length=128)),
                ("data_classification", models.CharField(choices=[("PUBLIC", "Public"), ("INTERNAL", "Internal"), ("CONFIDENTIAL", "Confidential"), ("PERSONAL_SENSITIVE", "Personal Sensitive")], default="INTERNAL", max_length=32)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="StrategyVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version", models.PositiveIntegerField(unique=True)),
                ("title", models.CharField(max_length=200)),
                ("content", models.JSONField(default=dict)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("SUPERSEDED", "Superseded")], default="DRAFT", max_length=16)),
                ("approved_by", models.CharField(blank=True, max_length=128)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_until", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="ProjectConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("connection_type", models.CharField(choices=[("REPOSITORY", "Repository"), ("ISSUE_TRACKER", "Issue Tracker"), ("CI", "Ci"), ("DEPLOYMENT", "Deployment"), ("PRODUCT_API", "Product Api")], max_length=32)),
                ("adapter_type", models.CharField(max_length=128)),
                ("capabilities", models.JSONField(blank=True, default=dict)),
                ("permission_mode", models.CharField(choices=[("READ_ONLY", "Read Only"), ("PROPOSE_CHANGES", "Propose Changes"), ("WRITE_APPROVED", "Write Approved")], default="READ_ONLY", max_length=32)),
                ("credential_reference", models.CharField(blank=True, max_length=256)),
                ("contract_version", models.PositiveIntegerField(default=1)),
                ("active", models.BooleanField(default=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="connections", to="portfolio.project")),
            ],
        ),
        migrations.CreateModel(
            name="Objective",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("business_outcome", models.TextField()),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("CLOSED", "Closed"), ("PAUSED", "Paused")], default="DRAFT", max_length=16)),
                ("owner_agent_id", models.CharField(blank=True, max_length=128)),
                ("weight", models.PositiveSmallIntegerField(default=1)),
                ("strategy_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="objectives", to="portfolio.strategyversion")),
            ],
        ),
    ]
