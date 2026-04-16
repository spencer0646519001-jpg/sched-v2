# Generated manually for persisted leave requests and resolved constraint config.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler_infra", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConstraintConfig",
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
                ("scope_type", models.CharField(max_length=32)),
                ("year", models.PositiveIntegerField(blank=True, null=True)),
                ("month", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("config_json", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="constraint_configs",
                        to="scheduler_infra.tenant",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(scope_type="default"),
                        fields=("tenant", "scope_type"),
                        name="sched_constraint_config_default_scope_uniq",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(scope_type="monthly"),
                        fields=("tenant", "scope_type", "year", "month"),
                        name="sched_constraint_config_monthly_scope_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(scope_type__in=("default", "monthly")),
                        name="sched_constraint_config_scope_valid",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                scope_type="default",
                                year__isnull=True,
                                month__isnull=True,
                            )
                            | models.Q(
                                scope_type="monthly",
                                year__isnull=False,
                                year__gte=1,
                                month__isnull=False,
                                month__gte=1,
                                month__lte=12,
                            )
                        ),
                        name="sched_constraint_config_scope_shape_valid",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="LeaveRequest",
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
                ("leave_date", models.DateField()),
                ("reason", models.CharField(blank=True, max_length=255, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="leave_requests",
                        to="scheduler_infra.tenant",
                    ),
                ),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="leave_requests",
                        to="scheduler_infra.worker",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "worker", "leave_date"),
                        name="sched_leave_request_tenant_worker_date_uniq",
                    ),
                ],
            },
        ),
    ]
