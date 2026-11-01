import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("product", "0004_user_research_and_milestone_objective"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompetitiveAnalysisDraft",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("competitor_label", models.CharField(max_length=160)),
                ("comparison_points", models.JSONField(blank=True, default=list)),
                ("implications", models.TextField()),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("NEEDS_REVIEW", "Needs Review"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                        ],
                        default="NEEDS_REVIEW",
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
                        related_name="competitive_analyses",
                        to="product.productspeccontract",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
