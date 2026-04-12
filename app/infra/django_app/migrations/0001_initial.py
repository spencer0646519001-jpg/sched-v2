# Generated manually for the first real V2 Django persistence slice.

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Tenant",
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
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("default_locale", models.CharField(max_length=32)),
            ],
        ),
        migrations.CreateModel(
            name="MonthlyWorkspace",
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
                ("year", models.PositiveIntegerField()),
                ("month", models.PositiveSmallIntegerField()),
                ("status", models.CharField(max_length=32)),
                ("source_type", models.CharField(max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="monthly_workspaces",
                        to="scheduler_infra.tenant",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "year", "month"),
                        name="sched_workspace_tenant_period_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(year__gte=1),
                        name="sched_workspace_year_gte_1",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(month__gte=1, month__lte=12),
                        name="sched_workspace_month_valid",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ShiftDefinition",
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
                ("code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("paid_hours", models.DecimalField(decimal_places=2, max_digits=5)),
                ("is_off_shift", models.BooleanField(default=False)),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("end_time", models.TimeField(blank=True, null=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="shift_definitions",
                        to="scheduler_infra.tenant",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "code"),
                        name="sched_shift_tenant_code_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(paid_hours__gte=0),
                        name="sched_shift_paid_hours_gte_0",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Station",
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
                ("code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="stations",
                        to="scheduler_infra.tenant",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "code"),
                        name="sched_station_tenant_code_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Worker",
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
                ("code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("role", models.CharField(max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="workers",
                        to="scheduler_infra.tenant",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "code"),
                        name="sched_worker_tenant_code_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MonthlyPlanVersion",
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
                ("version_number", models.PositiveIntegerField()),
                ("label", models.CharField(blank=True, max_length=255, null=True)),
                ("summary", models.TextField(blank=True, null=True)),
                ("snapshot_json", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="plan_versions",
                        to="scheduler_infra.tenant",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="plan_versions",
                        to="scheduler_infra.monthlyworkspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace", "version_number"),
                        name="sched_plan_version_workspace_number_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(version_number__gte=1),
                        name="sched_plan_version_number_gte_1",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MonthlyAssignment",
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
                ("assignment_date", models.DateField()),
                ("assignment_source", models.CharField(max_length=32)),
                ("note", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "shift_definition",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="monthly_assignments",
                        to="scheduler_infra.shiftdefinition",
                    ),
                ),
                (
                    "station",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.PROTECT,
                        related_name="monthly_assignments",
                        to="scheduler_infra.station",
                    ),
                ),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="monthly_assignments",
                        to="scheduler_infra.worker",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="assignments",
                        to="scheduler_infra.monthlyworkspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace", "assignment_date", "worker"),
                        name="sched_assignment_workspace_date_worker_uniq",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="monthlyworkspace",
            name="source_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="derived_workspaces",
                to="scheduler_infra.monthlyplanversion",
            ),
        ),
    ]
