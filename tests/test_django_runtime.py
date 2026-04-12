from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.test import RequestFactory

from app.api.django_runtime import build_django_monthly_schedule_urlpatterns
from app.infra.django_app.models import (
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
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
    DjangoShiftDefinition.objects.all().delete()
    DjangoStation.objects.all().delete()
    DjangoWorker.objects.all().delete()
    DjangoTenant.objects.all().delete()


def test_runtime_slice_registers_only_preview_apply_save_routes() -> None:
    patterns = build_django_monthly_schedule_urlpatterns()

    assert [pattern.name for pattern in patterns] == [
        "preview_month_schedule",
        "apply_month_schedule",
        "save_month_schedule",
    ]
    assert [str(pattern.pattern) for pattern in patterns] == [
        "v2/monthly-schedules/preview",
        "v2/monthly-schedules/apply",
        "v2/monthly-schedules/save",
    ]


def test_django_runtime_preview_apply_save_flow_uses_real_persistence() -> None:
    tenant = _seed_month_context()
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )

    assert preview_payload["request"] == {
        "tenant_slug": tenant.slug,
        "year": 2026,
        "month": 4,
    }
    assert preview_payload["result"]["summary"]["total_assignments"] == 1
    assert preview_payload["result"]["metadata"]["source_type"] == "preview"
    assert preview_payload["result"]["assignments"] == [
        {
            "date": "2026-04-01",
            "worker_code": "W1",
            "shift_code": "DAY",
            "source": "preview",
            "station_code": "GRILL",
            "note": "Temporary Django runtime preview assignment.",
        }
    ]
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0

    apply_payload = _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "result": preview_payload["result"],
        },
    )

    workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    assignment = DjangoMonthlyAssignment.objects.get(workspace=workspace)

    assert apply_payload == {
        "tenant_slug": tenant.slug,
        "year": 2026,
        "month": 4,
        "workspace_id": str(workspace.id),
        "workspace_status": "draft",
        "assignment_count": 1,
        "warning_count": 0,
        "workspace_created": True,
    }
    assert workspace.source_type == "preview"
    assert assignment.assignment_date.isoformat() == "2026-04-01"
    assert assignment.assignment_source == "apply"
    assert assignment.worker.code == "W1"
    assert assignment.shift_definition.code == "DAY"
    assert assignment.station is not None
    assert assignment.station.code == "GRILL"

    save_payload = _post_json(
        views["save_month_schedule"],
        path="/v2/monthly-schedules/save",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "label": "Baseline",
            "note": "Runtime smoke test",
        },
    )

    version = DjangoMonthlyPlanVersion.objects.get(workspace=workspace)

    assert save_payload == {
        "tenant_slug": tenant.slug,
        "year": 2026,
        "month": 4,
        "version_id": str(version.id),
        "version_number": 1,
        "workspace_id": str(workspace.id),
        "assignment_count": 1,
    }
    assert version.summary == "Baseline"
    assert version.snapshot_json["save_metadata"] == {
        "label": "Baseline",
        "note": "Runtime smoke test",
    }
    assert version.snapshot_json["assignments"] == [
        {
            "id": str(assignment.id),
            "worker_id": str(assignment.worker_id),
            "assignment_date": "2026-04-01",
            "shift_definition_id": str(assignment.shift_definition_id),
            "station_id": str(assignment.station_id),
        }
    ]


def _seed_month_context() -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
    )
    DjangoStation.objects.create(
        tenant=tenant,
        code="GRILL",
        name="Grill",
        is_active=True,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    return tenant


def _post_json(view, *, path: str, payload: dict[str, object]) -> dict[str, object]:
    response = view(
        RequestFactory().post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )
    )

    assert response.status_code == 200
    return json.loads(response.content)
