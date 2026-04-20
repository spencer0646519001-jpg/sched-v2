# Generated manually for persisted worker-station preview skills.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler_infra", "0002_leave_request_constraint_config"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerStationSkill",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "station",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="worker_skills",
                        to="scheduler_infra.station",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="worker_station_skills",
                        to="scheduler_infra.tenant",
                    ),
                ),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="station_skills",
                        to="scheduler_infra.worker",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "worker", "station"),
                        name="sched_worker_station_skill_tenant_worker_station_uniq",
                    ),
                ],
            },
        ),
    ]
