# Generated manually for candidate freshness checks.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler_infra", "0006_monthlycandidatepreview"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlycandidatepreview",
            name="input_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
