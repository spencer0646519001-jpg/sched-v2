# Generated manually for narrow worker scheduling profile support.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler_infra", "0003_workerstationskill"),
    ]

    operations = [
        migrations.AddField(
            model_name="worker",
            name="scheduling_profile_json",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
