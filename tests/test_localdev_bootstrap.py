from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from app.infra.django_app.models import (
    ConstraintConfig as DjangoConstraintConfig,
    LeaveRequest as DjangoLeaveRequest,
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
)


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoLeaveRequest.objects.all().delete()
    DjangoConstraintConfig.objects.all().delete()
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
    DjangoShiftDefinition.objects.all().delete()
    DjangoStation.objects.all().delete()
    DjangoWorker.objects.all().delete()
    DjangoTenant.objects.all().delete()


def test_localdev_urlconf_exposes_monthly_workspace_page() -> None:
    from app.localdev_urls import urlpatterns

    assert [pattern.name for pattern in urlpatterns] == ["monthly_schedule_workspace"]
    assert [str(pattern.pattern) for pattern in urlpatterns] == ["v2/monthly-workspace"]


def test_seed_monthly_workspace_demo_is_idempotent_and_reviewable() -> None:
    stdout = StringIO()

    call_command("seed_monthly_workspace_demo", stdout=stdout)
    call_command("seed_monthly_workspace_demo", stdout=stdout)

    assert DjangoTenant.objects.filter(slug="demo-restaurant").count() == 1
    assert DjangoWorker.objects.filter(tenant__slug="demo-restaurant").count() == 3
    assert DjangoStation.objects.filter(
        tenant__slug="demo-restaurant",
        code="GRILL",
    ).count() == 1
    assert DjangoShiftDefinition.objects.filter(
        tenant__slug="demo-restaurant",
        code="DAY",
    ).count() == 1
    assert DjangoConstraintConfig.objects.filter(
        tenant__slug="demo-restaurant",
        scope_type="default",
    ).count() == 1
    assert (
        "http://127.0.0.1:8000/v2/monthly-workspace"
        "?tenant_slug=demo-restaurant&month_scope=2026-04"
    ) in stdout.getvalue()
