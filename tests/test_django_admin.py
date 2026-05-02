from __future__ import annotations

from django.contrib.admin.sites import AdminSite

from app.infra.django_app import admin as scheduler_admin
from app.infra.django_app.models import (
    ConstraintConfig,
    LeaveRequest,
    MonthlyAssignment,
    MonthlyCandidatePreview,
    MonthlyPlanVersion,
    MonthlyWorkspace,
    RefineRequest,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
    WorkerStationSkill,
)


def test_internal_admin_registers_core_tenant_data_models() -> None:
    internal_site = AdminSite(name="scheduler-internal-test-admin")

    scheduler_admin.register_scheduler_models(internal_site)

    registered_models = set(internal_site._registry)

    assert {
        Tenant,
        Worker,
        Station,
        ShiftDefinition,
        WorkerStationSkill,
        LeaveRequest,
        ConstraintConfig,
        MonthlyWorkspace,
        MonthlyAssignment,
        MonthlyPlanVersion,
        MonthlyCandidatePreview,
    }.issubset(registered_models)
    assert RefineRequest not in registered_models
