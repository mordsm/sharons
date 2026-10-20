import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FinancialRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "record_type",
                    models.CharField(
                        choices=[
                            ("INCOME", "Income"),
                            ("EXPENSE", "Expense"),
                            ("SUBSCRIPTION_COST", "Subscription Cost"),
                            ("SERVER_COST", "Server Cost"),
                            ("API_COST", "Api Cost"),
                            ("OTHER_COST", "Other Cost"),
                        ],
                        max_length=32,
                    ),
                ),
                ("occurred_on", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="ILS", max_length=3)),
                ("source", models.CharField(max_length=128)),
                ("category", models.CharField(blank=True, max_length=128)),
                ("description", models.CharField(max_length=240)),
                ("external_reference", models.CharField(blank=True, max_length=200)),
                (
                    "reconciliation_status",
                    models.CharField(
                        choices=[
                            ("UNRECONCILED", "Unreconciled"),
                            ("RECONCILED", "Reconciled"),
                            ("DISCREPANCY", "Discrepancy"),
                            ("NEEDS_REVIEW", "Needs Review"),
                        ],
                        default="UNRECONCILED",
                        max_length=32,
                    ),
                ),
                ("reconciliation_notes", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-occurred_on", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="financialrecord",
            constraint=models.UniqueConstraint(
                condition=~models.Q(("external_reference", "")),
                fields=("source", "external_reference"),
                name="unique_financial_external_reference_per_source",
            ),
        ),
    ]
