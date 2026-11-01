from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("governance", "0010_secretreference"),
    ]

    operations = [
        migrations.AlterField(
            model_name="secretreference",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("OAUTH_READ_ONLY", "Oauth Read Only"),
                    ("OAUTH_REFRESH", "Oauth Refresh"),
                    ("GITHUB_ISSUE_CREATE", "Github Issue Create"),
                ],
                max_length=32,
            ),
        ),
    ]
