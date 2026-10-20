import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MockEmailMessage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(default="gmail_mock", max_length=128)),
                ("external_event_id", models.CharField(max_length=200)),
                ("sender", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=240)),
                ("body", models.TextField()),
                (
                    "classification",
                    models.CharField(
                        choices=[
                            ("INFORMATION", "Information"),
                            ("TASK", "Task"),
                            ("DECISION", "Decision"),
                            ("INVOICE", "Invoice"),
                            ("SPAM", "Spam"),
                            ("PERSONAL_SENSITIVE", "Personal Sensitive"),
                        ],
                        max_length=32,
                    ),
                ),
                ("proposed_action", models.JSONField(default=dict)),
                ("rule_decision", models.CharField(max_length=32)),
                ("rule_reason_codes", models.JSONField(blank=True, default=list)),
                ("inbox_event_id", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="mockemailmessage",
            constraint=models.UniqueConstraint(fields=("source", "external_event_id"), name="unique_mock_email_source_external_id"),
        ),
    ]
