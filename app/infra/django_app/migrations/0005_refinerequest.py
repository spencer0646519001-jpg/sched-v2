# Generated manually for bounded refine-request persistence.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler_infra", "0004_worker_scheduling_profile_json"),
    ]

    operations = [
        migrations.CreateModel(
            name="RefineRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("request_text", models.TextField()),
                ("status", models.CharField(max_length=32)),
                ("parsed_intent_json", models.JSONField(blank=True, null=True)),
                ("result_preview_json", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refine_requests",
                        to="scheduler_infra.tenant",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refine_requests",
                        to="scheduler_infra.monthlyworkspace",
                    ),
                ),
            ],
        ),
    ]
