"""Internal Django admin registrations for tenant scheduling data."""

from __future__ import annotations

from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AdminSite, AlreadyRegistered

from app.infra.django_app.models import (
    ConstraintConfig,
    LeaveRequest,
    MonthlyAssignment,
    MonthlyCandidatePreview,
    MonthlyPlanVersion,
    MonthlyWorkspace,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
    WorkerStationSkill,
)


class TenantAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "default_locale")
    search_fields = ("slug", "name")


class WorkerAdmin(admin.ModelAdmin):
    list_display = ("tenant", "code", "name", "role", "is_active")
    list_filter = ("is_active", "role")
    raw_id_fields = ("tenant",)
    search_fields = ("code", "name", "tenant__slug")


class StationAdmin(admin.ModelAdmin):
    list_display = ("tenant", "code", "name", "is_active")
    list_filter = ("is_active",)
    raw_id_fields = ("tenant",)
    search_fields = ("code", "name", "tenant__slug")


class ShiftDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "code",
        "name",
        "paid_hours",
        "is_off_shift",
        "start_time",
        "end_time",
    )
    list_filter = ("is_off_shift",)
    raw_id_fields = ("tenant",)
    search_fields = ("code", "name", "tenant__slug")


class WorkerStationSkillAdmin(admin.ModelAdmin):
    list_display = ("tenant", "worker", "station", "updated_at")
    raw_id_fields = ("tenant", "worker", "station")
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("tenant__slug", "worker__code", "worker__name", "station__code")


class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("tenant", "worker", "leave_date", "reason", "updated_at")
    date_hierarchy = "leave_date"
    raw_id_fields = ("tenant", "worker")
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("tenant__slug", "worker__code", "worker__name", "reason")


class ConstraintConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "scope_type", "year", "month", "updated_at")
    list_filter = ("scope_type", "year", "month")
    raw_id_fields = ("tenant",)
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("tenant__slug", "scope_type")


class MonthlyWorkspaceAdmin(admin.ModelAdmin):
    list_display = ("tenant", "year", "month", "status", "source_type", "updated_at")
    list_filter = ("status", "source_type", "year", "month")
    raw_id_fields = ("tenant", "source_version")
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("tenant__slug", "status", "source_type")


class MonthlyAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "workspace",
        "assignment_date",
        "worker",
        "shift_definition",
        "station",
        "assignment_source",
    )
    date_hierarchy = "assignment_date"
    list_filter = ("assignment_source",)
    raw_id_fields = ("workspace", "worker", "shift_definition", "station")
    readonly_fields = ("created_at", "updated_at")
    search_fields = (
        "workspace__tenant__slug",
        "worker__code",
        "worker__name",
        "shift_definition__code",
        "station__code",
        "note",
    )


class MonthlyPlanVersionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "workspace", "version_number", "label", "created_at")
    list_filter = ("version_number",)
    raw_id_fields = ("workspace", "tenant")
    readonly_fields = ("created_at",)
    search_fields = ("tenant__slug", "label", "summary")


class MonthlyCandidatePreviewAdmin(admin.ModelAdmin):
    list_display = ("tenant", "year", "month", "input_fingerprint", "created_at")
    list_filter = ("year", "month")
    raw_id_fields = ("tenant",)
    readonly_fields = ("created_at",)
    search_fields = ("tenant__slug", "input_fingerprint")


def register_scheduler_models(site: AdminSite) -> None:
    """Register scheduler models on a caller-provided internal admin site."""

    model_admin_pairs = (
        (Tenant, TenantAdmin),
        (Worker, WorkerAdmin),
        (Station, StationAdmin),
        (ShiftDefinition, ShiftDefinitionAdmin),
        (WorkerStationSkill, WorkerStationSkillAdmin),
        (LeaveRequest, LeaveRequestAdmin),
        (ConstraintConfig, ConstraintConfigAdmin),
        (MonthlyWorkspace, MonthlyWorkspaceAdmin),
        (MonthlyAssignment, MonthlyAssignmentAdmin),
        (MonthlyPlanVersion, MonthlyPlanVersionAdmin),
        (MonthlyCandidatePreview, MonthlyCandidatePreviewAdmin),
    )
    for model, model_admin in model_admin_pairs:
        try:
            site.register(model, model_admin)
        except AlreadyRegistered:
            continue


if apps.apps_ready and apps.is_installed("django.contrib.admin"):
    register_scheduler_models(admin.site)
