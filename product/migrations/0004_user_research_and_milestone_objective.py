import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0003_objectiverisk"),
        ("product", "0003_productfeature_productfeedback_productmilestone_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="productmilestone",
            name="objective",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="product_milestones",
                to="portfolio.objective",
            ),
        ),
        migrations.CreateModel(
            name="UserResearchContract",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("research_question", models.TextField()),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("INTERVIEW_NOTES", "Interview Notes"),
                            ("USABILITY_NOTES", "Usability Notes"),
                            ("SUPPORT_NOTES", "Support Notes"),
                            ("INTERNAL_SYNTHESIS", "Internal Synthesis"),
                        ],
                        default="INTERVIEW_NOTES",
                        max_length=32,
                    ),
                ),
                ("participant_segment", models.CharField(blank=True, max_length=120)),
                (
                    "status",
                    models.CharField(
                        choices=[("OPEN", "Open"), ("IN_REVIEW", "In Review"), ("CLOSED", "Closed")],
                        default="OPEN",
                        max_length=16,
                    ),
                ),
                ("no_customer_contact", models.BooleanField(default=True)),
                ("no_external_write", models.BooleanField(default=True)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "spec_contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="user_research_contracts",
                        to="product.productspeccontract",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="UserResearchInterview",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("label", models.CharField(max_length=160)),
                ("segment", models.CharField(blank=True, max_length=120)),
                ("summary", models.TextField()),
                ("observations", models.JSONField(blank=True, default=list)),
                ("no_customer_contact", models.BooleanField(default=True)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="interviews",
                        to="product.userresearchcontract",
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="UserResearchFinding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("statement", models.TextField()),
                ("evidence_note", models.TextField(blank=True)),
                (
                    "confidence",
                    models.CharField(
                        choices=[("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")],
                        default="LOW",
                        max_length=16,
                    ),
                ),
                ("related_requirement_id", models.CharField(blank=True, max_length=64)),
                ("no_customer_contact", models.BooleanField(default=True)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="findings",
                        to="product.userresearchcontract",
                    ),
                ),
                (
                    "interview",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="findings",
                        to="product.userresearchinterview",
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="UserResearchQuestion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("question", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("OPEN", "Open"), ("DEFERRED", "Deferred"), ("RESOLVED", "Resolved")],
                        default="OPEN",
                        max_length=16,
                    ),
                ),
                ("resolution_note", models.TextField(blank=True)),
                ("no_customer_contact", models.BooleanField(default=True)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="questions",
                        to="product.userresearchcontract",
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
