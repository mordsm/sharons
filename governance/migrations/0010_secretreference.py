import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("governance", "0009_ruleengineworkitem"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecretReference",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=128, unique=True)),
                (
                    "purpose",
                    models.CharField(
                        choices=[
                            ("OAUTH_READ_ONLY", "Oauth Read Only"),
                            ("GITHUB_ISSUE_CREATE", "Github Issue Create"),
                        ],
                        max_length=32,
                    ),
                ),
                ("provider", models.CharField(max_length=64)),
                ("env_var_name", models.CharField(max_length=80)),
                ("active", models.BooleanField(default=True)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
    ]
