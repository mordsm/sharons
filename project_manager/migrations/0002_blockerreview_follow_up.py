import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0007_taskdependency"),
        ("project_manager", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="blockerreview",
            name="approval_request_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="blockerreview",
            name="follow_up_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="blocker_follow_ups",
                to="operations.task",
            ),
        ),
    ]
