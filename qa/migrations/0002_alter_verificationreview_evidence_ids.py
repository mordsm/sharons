from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qa", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="verificationreview",
            name="evidence_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
