"""Real Django persistence models for the first V2 monthly planning slice."""

from __future__ import annotations

from django.db import models
from django.db.models import Q


class Tenant(models.Model):
    """Top-level tenant boundary for all persisted V2 scheduling data."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    default_locale = models.CharField(max_length=32)


class Worker(models.Model):
    """Tenant-scoped worker master data used to build monthly plans."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="workers",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "code"),
                name="sched_worker_tenant_code_uniq",
            ),
        ]


class Station(models.Model):
    """Tenant-scoped station master data for assignment destinations."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="stations",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "code"),
                name="sched_station_tenant_code_uniq",
            ),
        ]


class ShiftDefinition(models.Model):
    """Tenant-scoped shift templates, including off-shift placeholders."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="shift_definitions",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    paid_hours = models.DecimalField(max_digits=5, decimal_places=2)
    is_off_shift = models.BooleanField(default=False)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "code"),
                name="sched_shift_tenant_code_uniq",
            ),
            models.CheckConstraint(
                condition=Q(paid_hours__gte=0),
                name="sched_shift_paid_hours_gte_0",
            ),
        ]


class LeaveRequest(models.Model):
    """Approved single-day worker leave used as month-planning input."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    leave_date = models.DateField()
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "worker", "leave_date"),
                name="sched_leave_request_tenant_worker_date_uniq",
            ),
        ]


class ConstraintConfig(models.Model):
    """Resolved full planner config stored by scope for one tenant."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="constraint_configs",
    )
    scope_type = models.CharField(max_length=32)
    year = models.PositiveIntegerField(null=True, blank=True)
    month = models.PositiveSmallIntegerField(null=True, blank=True)
    config_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "scope_type"),
                condition=Q(scope_type="default"),
                name="sched_constraint_config_default_scope_uniq",
            ),
            models.UniqueConstraint(
                fields=("tenant", "scope_type", "year", "month"),
                condition=Q(scope_type="monthly"),
                name="sched_constraint_config_monthly_scope_uniq",
            ),
            models.CheckConstraint(
                condition=Q(scope_type__in=("default", "monthly")),
                name="sched_constraint_config_scope_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        scope_type="default",
                        year__isnull=True,
                        month__isnull=True,
                    )
                    | Q(
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
        ]


class MonthlyWorkspace(models.Model):
    """The single mutable planning container for one tenant and month."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="monthly_workspaces",
    )
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=32)
    source_type = models.CharField(max_length=32)
    source_version = models.ForeignKey(
        "MonthlyPlanVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="derived_workspaces",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "year", "month"),
                name="sched_workspace_tenant_period_uniq",
            ),
            models.CheckConstraint(
                condition=Q(year__gte=1),
                name="sched_workspace_year_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12),
                name="sched_workspace_month_valid",
            ),
        ]


class MonthlyAssignment(models.Model):
    """One persisted worker assignment attached to a mutable workspace."""

    workspace = models.ForeignKey(
        MonthlyWorkspace,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    assignment_date = models.DateField()
    worker = models.ForeignKey(
        Worker,
        on_delete=models.PROTECT,
        related_name="monthly_assignments",
    )
    shift_definition = models.ForeignKey(
        ShiftDefinition,
        on_delete=models.PROTECT,
        related_name="monthly_assignments",
    )
    station = models.ForeignKey(
        Station,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="monthly_assignments",
    )
    assignment_source = models.CharField(max_length=32)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "assignment_date", "worker"),
                name="sched_assignment_workspace_date_worker_uniq",
            ),
        ]


class MonthlyPlanVersion(models.Model):
    """Immutable saved snapshot of a monthly workspace state."""

    workspace = models.ForeignKey(
        MonthlyWorkspace,
        on_delete=models.PROTECT,
        related_name="plan_versions",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="plan_versions",
    )
    version_number = models.PositiveIntegerField()
    label = models.CharField(max_length=255, null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    snapshot_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "version_number"),
                name="sched_plan_version_workspace_number_uniq",
            ),
            models.CheckConstraint(
                condition=Q(version_number__gte=1),
                name="sched_plan_version_number_gte_1",
            ),
        ]
