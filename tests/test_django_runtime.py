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
    assert preview_payload["result"]["summary"]["total_assignments"] == 30
    assert preview_payload["result"]["summary"]["total_warnings"] == 0
    assert preview_payload["result"]["metadata"]["source_type"] == "monthly_planner"
    assert preview_payload["result"]["metadata"]["notes"] == [
        "default_station_coverage",
        "engine_v0_1_baseline",
    ]
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["schedule_quality_label"] == "good"
    assert len(preview_payload["result"]["assignments"]) == 30
    assert preview_payload["result"]["assignments"][0] == {
        "date": "2026-04-01",
        "worker_code": "W1",
        "shift_code": "DAY",
        "source": "monthly_planner",
        "station_code": "GRILL",
        "note": None,
    }
    assert preview_payload["result"]["assignments"][-1] == {
        "date": "2026-04-30",
        "worker_code": "W1",
        "shift_code": "DAY",
        "source": "monthly_planner",
        "station_code": "GRILL",
        "note": None,
    }
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
    assignments = list(
        DjangoMonthlyAssignment.objects.filter(workspace=workspace).order_by(
            "assignment_date",
            "worker_id",
            "id",
        )
    )

    assert apply_payload == {
        "tenant_slug": tenant.slug,
        "year": 2026,
        "month": 4,
        "workspace_id": str(workspace.id),
        "workspace_status": "draft",
        "assignment_count": 30,
        "warning_count": 0,
        "workspace_created": True,
    }
    assert workspace.source_type == "preview"
    assert len(assignments) == 30
    assert assignments[0].assignment_date.isoformat() == "2026-04-01"
    assert assignments[-1].assignment_date.isoformat() == "2026-04-30"
    assert all(assignment.assignment_source == "apply" for assignment in assignments)
    assert all(assignment.worker.code == "W1" for assignment in assignments)
    assert all(assignment.shift_definition.code == "DAY" for assignment in assignments)
    assert all(assignment.station is not None for assignment in assignments)
    assert all(assignment.station.code == "GRILL" for assignment in assignments)

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
        "assignment_count": 30,
    }
    assert version.summary == "Baseline"
    assert version.snapshot_json["save_metadata"] == {
        "label": "Baseline",
        "note": "Runtime smoke test",
    }
    assert len(version.snapshot_json["assignments"]) == 30
    assert version.snapshot_json["assignments"][0]["assignment_date"] == "2026-04-01"
    assert version.snapshot_json["assignments"][-1]["assignment_date"] == "2026-04-30"


def test_django_runtime_preview_returns_planner_warnings_without_persisting() -> None:
    tenant = _seed_month_context(worker_is_active=False)
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

    assert preview_payload["result"]["summary"] == {
        "total_assignments": 0,
        "total_warnings": 30,
        "assignments_by_worker": {},
        "paid_hours_by_worker": {},
        "warnings_by_type": {"understaffed_station_day": 30},
    }
    assert preview_payload["result"]["metadata"]["source_type"] == "monthly_planner"
    assert preview_payload["result"]["warnings"][0] == {
        "type": "understaffed_station_day",
        "message_key": "understaffed_station",
        "worker_code": None,
        "date": "2026-04-01",
        "details": {
            "station_code": "GRILL",
            "required_staff": 1,
            "assigned_staff": 0,
            "missing_staff": 1,
        },
    }
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["understaffed_station_days"] == 30
    assert preview_payload["result"]["evaluation"]["schedule_quality_label"] == (
        "needs_review"
    )
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0


def _seed_month_context(*, worker_is_active: bool = True) -> DjangoTenant:
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
        is_active=worker_is_active,
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
