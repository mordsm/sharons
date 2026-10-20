import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MockPaymentCustomer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("external_customer_id", models.CharField(max_length=128, unique=True)),
                ("email", models.EmailField(max_length=254)),
                ("name", models.CharField(blank=True, max_length=160)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="MockPaymentWebhookEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(default="mock_payment", max_length=128)),
                ("external_event_id", models.CharField(max_length=200)),
                ("event_type", models.CharField(max_length=80)),
                ("payload", models.JSONField(default=dict)),
                ("status", models.CharField(choices=[("RECEIVED", "Received"), ("DUPLICATE", "Duplicate"), ("OUT_OF_ORDER", "Out Of Order"), ("UNSUPPORTED", "Unsupported")], default="RECEIVED", max_length=32)),
                ("correlation_id", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="MockPaymentSubscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("external_subscription_id", models.CharField(max_length=128, unique=True)),
                ("plan_name", models.CharField(max_length=120)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="ILS", max_length=3)),
                ("billing_interval", models.CharField(choices=[("MONTHLY", "Monthly"), ("ANNUAL", "Annual")], max_length=16)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("CANCELLED", "Cancelled")], default="ACTIVE", max_length=16)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="subscriptions", to="payments.mockpaymentcustomer")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="MockPaymentTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("external_transaction_id", models.CharField(max_length=128, unique=True)),
                ("transaction_type", models.CharField(choices=[("CHARGE", "Charge"), ("REFUND", "Refund")], max_length=16)),
                ("status", models.CharField(choices=[("SUCCEEDED", "Succeeded"), ("FAILED", "Failed"), ("TIMEOUT", "Timeout")], max_length=16)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="ILS", max_length=3)),
                ("reason", models.CharField(blank=True, max_length=200)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="payments.mockpaymentcustomer")),
                ("subscription", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="payments.mockpaymentsubscription")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="mockpaymentwebhookevent",
            constraint=models.UniqueConstraint(fields=("source", "external_event_id"), name="unique_mock_payment_source_external_event"),
        ),
    ]
