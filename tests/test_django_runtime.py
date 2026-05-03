from __future__ import annotations

import csv
import datetime as dt
import io
import json
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.test import RequestFactory

from app.api.django_runtime import build_django_monthly_schedule_urlpatterns
from app.monthly_workspace_demo_data import (
    DEMO_TENANT_NAME,
    DEMO_TENANT_SLUG,
    PRIMARY_DEMO_SHIFT,
    PRIMARY_DEMO_STATION,
    PRIMARY_DEMO_WORKER,
    SECONDARY_DEMO_WORKER,
)
from app.infra.django_app.models import (
    ConstraintConfig as DjangoConstraintConfig,
    LeaveRequest as DjangoLeaveRequest,
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyCandidatePreview as DjangoMonthlyCandidatePreview,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    RefineRequest as DjangoRefineRequest,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
    WorkerStationSkill as DjangoWorkerStationSkill,
)


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoMonthlyCandidatePreview.objects.all().delete()
    DjangoRefineRequest.objects.all().delete()
    DjangoLeaveRequest.objects.all().delete()
    DjangoConstraintConfig.objects.all().delete()
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
    DjangoWorkerStationSkill.objects.all().delete()
    DjangoShiftDefinition.objects.all().delete()
    DjangoStation.objects.all().delete()
    DjangoWorker.objects.all().delete()
    DjangoTenant.objects.all().delete()


def test_runtime_slice_registers_preview_apply_save_explain_refine_and_export_routes() -> None:
    patterns = build_django_monthly_schedule_urlpatterns()

    assert [pattern.name for pattern in patterns] == [
        "preview_month_schedule",
        "apply_month_schedule",
        "save_month_schedule",
        "explain_day_schedule",
        "refine_month_schedule",
        "export_month_schedule",
    ]
    assert [str(pattern.pattern) for pattern in patterns] == [
        "v2/monthly-schedules/preview",
        "v2/monthly-schedules/apply",
        "v2/monthly-schedules/save",
        "v2/monthly-schedules/explain-day",
        "v2/monthly-schedules/refine",
        "v2/monthly-schedules/export",
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
    assert preview_payload["candidate_id"]
    assert preview_payload["result"]["summary"]["total_assignments"] == 30
    assert preview_payload["result"]["summary"]["total_warnings"] == 0
    assert preview_payload["result"]["metadata"]["source_type"] == "monthly_planner"
    assert preview_payload["result"]["metadata"]["notes"] == ["engine_v0_1_baseline"]
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["schedule_quality_label"] == "good"
    assert len(preview_payload["result"]["assignments"]) == 30
    assert preview_payload["result"]["assignments"][0] == {
        "date": "2026-04-01",
        "worker_code": PRIMARY_DEMO_WORKER.code,
        "shift_code": PRIMARY_DEMO_SHIFT.code,
        "source": "monthly_planner",
        "station_code": PRIMARY_DEMO_STATION.code,
        "note": None,
    }
    assert preview_payload["result"]["assignments"][-1] == {
        "date": "2026-04-30",
        "worker_code": PRIMARY_DEMO_WORKER.code,
        "shift_code": PRIMARY_DEMO_SHIFT.code,
        "source": "monthly_planner",
        "station_code": PRIMARY_DEMO_STATION.code,
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
            "candidate_id": preview_payload["candidate_id"],
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
    assert all(
        assignment.worker.code == PRIMARY_DEMO_WORKER.code for assignment in assignments
    )
    assert all(
        assignment.shift_definition.code == PRIMARY_DEMO_SHIFT.code
        for assignment in assignments
    )
    assert all(assignment.station is not None for assignment in assignments)
    assert all(
        assignment.station.code == PRIMARY_DEMO_STATION.code
        for assignment in assignments
    )

    export_payload = _post_json(
        views["export_month_schedule"],
        path="/v2/monthly-schedules/export",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )

    assert export_payload["tenant_slug"] == tenant.slug
    assert export_payload["year"] == 2026
    assert export_payload["month"] == 4
    assert export_payload["workspace_id"] == str(workspace.id)
    assert export_payload["workspace_status"] == "draft"
    assert export_payload["row_count"] == 30
    assert export_payload["rows"][0] == {
        "assignment_date": "2026-04-01",
        "worker_code": PRIMARY_DEMO_WORKER.code,
        "worker_name": PRIMARY_DEMO_WORKER.name,
        "worker_role": PRIMARY_DEMO_WORKER.role,
        "shift_code": PRIMARY_DEMO_SHIFT.code,
        "shift_name": PRIMARY_DEMO_SHIFT.name,
        "station_code": PRIMARY_DEMO_STATION.code,
        "station_name": PRIMARY_DEMO_STATION.name,
    }
    csv_rows = list(csv.reader(io.StringIO(export_payload["csv_text"])))
    assert csv_rows[0][:4] == ["worker", "role", "4/1", "4/2"]
    assert csv_rows[0][-1] == "4/30"
    assert csv_rows[1][:4] == [
        PRIMARY_DEMO_WORKER.name,
        PRIMARY_DEMO_WORKER.role,
        f"{PRIMARY_DEMO_SHIFT.code} / Gateau",
        f"{PRIMARY_DEMO_SHIFT.code} / Gateau",
    ]

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


def test_django_runtime_apply_rejects_candidate_from_other_tenant_scope() -> None:
    tenant = _seed_named_month_context(
        slug="tenant-a",
        name="Tenant A",
        worker_code="ALEX_A",
        worker_name="Alex A",
        station_code="GRILL_A",
        station_name="Grill A",
        shift_code="DAY_A",
        shift_name="Day A",
    )
    other_tenant = _seed_named_month_context(
        slug="tenant-b",
        name="Tenant B",
        worker_code="BLAIR_B",
        worker_name="Blair B",
        station_code="GRILL_B",
        station_name="Grill B",
        shift_code="DAY_B",
        shift_name="Day B",
    )
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    other_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )
    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": other_preview_payload["candidate_id"],
        },
    )

    assert response.status_code == 404
    assert "Candidate preview not found" in response.content.decode()
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_django_runtime_apply_rejects_off_month_candidate_payload() -> None:
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
    candidate_preview = DjangoMonthlyCandidatePreview.objects.get(
        pk=int(preview_payload["candidate_id"])
    )
    candidate_preview.result_json["assignments"][0]["date"] = "2026-05-01"
    candidate_preview.save(update_fields=["result_json"])

    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": preview_payload["candidate_id"],
        },
    )

    assert response.status_code == 400
    assert (
        json.loads(response.content)["detail"]
        == "Apply result assignment_date 2026-05-01 must stay within target month 2026-04."
    )
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()
    assert DjangoMonthlyAssignment.objects.count() == 0


def test_django_runtime_apply_rejects_unknown_candidate_id() -> None:
    tenant = _seed_month_context()
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": "999999",
        },
    )

    assert response.status_code == 404
    assert "Candidate preview not found" in response.content.decode()
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_django_runtime_apply_rejects_candidate_from_other_month_scope() -> None:
    tenant = _seed_month_context()
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }
    may_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 5,
        },
    )

    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": may_preview_payload["candidate_id"],
        },
    )

    assert response.status_code == 404
    assert "Candidate preview not found" in response.content.decode()
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_django_runtime_apply_rejects_stale_candidate_after_leave_changes() -> None:
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
    worker = DjangoWorker.objects.get(tenant=tenant, code=PRIMARY_DEMO_WORKER.code)
    DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=worker,
        leave_date=dt.date(2026, 4, 10),
        reason="vacation",
    )

    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": preview_payload["candidate_id"],
        },
    )

    assert response.status_code == 400
    assert "Candidate preview is stale" in response.content.decode()
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_django_runtime_apply_rejects_stale_candidate_after_workspace_changes() -> None:
    tenant = _seed_month_context()
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }
    stale_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )
    fresh_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": fresh_preview_payload["candidate_id"],
        },
    )

    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": stale_preview_payload["candidate_id"],
        },
    )

    assert response.status_code == 400
    assert "Candidate preview is stale" in response.content.decode()
    assert DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).count() == 1
    assert DjangoMonthlyAssignment.objects.count() == 30


def test_django_runtime_apply_rejects_full_client_result_payload() -> None:
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
    preview_payload["result"]["assignments"][0]["date"] = "2026-05-01"

    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "result": preview_payload["result"],
        },
    )

    assert response.status_code == 400
    assert "full result apply is not accepted" in response.content.decode()
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_django_runtime_apply_rejects_candidate_id_with_client_result_payload() -> None:
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
    preview_payload["result"]["assignments"][0]["date"] = "2026-05-01"

    response = _post_json_response(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": preview_payload["candidate_id"],
            "result": preview_payload["result"],
        },
    )

    assert response.status_code == 400
    assert "candidate_id only" in response.content.decode()
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_django_runtime_save_does_not_read_other_tenant_current_workspace() -> None:
    tenant = _seed_named_month_context(
        slug="tenant-a",
        name="Tenant A",
        worker_code="ALEX_A",
        worker_name="Alex A",
        station_code="GRILL_A",
        station_name="Grill A",
        shift_code="DAY_A",
        shift_name="Day A",
    )
    other_tenant = _seed_named_month_context(
        slug="tenant-b",
        name="Tenant B",
        worker_code="BLAIR_B",
        worker_name="Blair B",
        station_code="GRILL_B",
        station_name="Grill B",
        shift_code="DAY_B",
        shift_name="Day B",
    )
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    other_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": other_preview_payload["candidate_id"],
        },
    )
    response = _post_json_response(
        views["save_month_schedule"],
        path="/v2/monthly-schedules/save",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "label": "Should fail",
        },
    )

    assert response.status_code == 404
    assert "No current workspace found" in response.content.decode()
    assert not DjangoMonthlyPlanVersion.objects.filter(tenant=tenant).exists()


def test_django_runtime_refine_returns_candidate_preview_without_mutating_current_workspace() -> None:
    tenant = _seed_month_context()
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
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
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": preview_payload["candidate_id"],
        },
    )
    refine_request_text = (
        f"\u8bf7\u628a {PRIMARY_DEMO_WORKER.code} "
        f"\u5b89\u6392\u5230 2026-04-01 \u7684 EVE \u5728 "
        f"{PRIMARY_DEMO_STATION.code}"
    )

    refine_payload = _post_json(
        views["refine_month_schedule"],
        path="/v2/monthly-schedules/refine",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "request_text": refine_request_text,
        },
    )

    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    current_first_assignment = DjangoMonthlyAssignment.objects.get(
        workspace=current_workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker__code=PRIMARY_DEMO_WORKER.code,
    )
    refine_request = DjangoRefineRequest.objects.get(
        workspace=current_workspace,
    )
    refined_first_day_assignment = next(
        assignment
        for assignment in refine_payload["candidate_result"]["assignments"]
        if assignment["date"] == "2026-04-01"
        and assignment["worker_code"] == PRIMARY_DEMO_WORKER.code
    )

    assert refine_payload["status"] == "completed"
    assert refine_payload["request_language"] == "zh"
    assert refine_payload["outcome"]["status"] == "preview_ready"
    assert refine_payload["outcome"]["message_key"] == "refine_preview_ready_set"
    assert refine_payload["parsed_intent_json"]["intent_type"] == "set_assignment"
    assert refine_payload["parsed_intent_json"]["preview_executed"] is True
    assert refine_payload["candidate_result"]["metadata"]["refinement_applied"] is True
    assert refine_payload["preview_diff"] == {
        "added": [],
        "removed": [],
        "changed": [
            {
                "date": "2026-04-01",
                "worker_code": PRIMARY_DEMO_WORKER.code,
                "worker_name": PRIMARY_DEMO_WORKER.name,
                "before": {
                    "station_code": PRIMARY_DEMO_STATION.code,
                    "shift_code": PRIMARY_DEMO_SHIFT.code,
                    "source": "current_workspace",
                    "note": None,
                },
                "after": {
                    "station_code": PRIMARY_DEMO_STATION.code,
                    "shift_code": "EVE",
                    "source": "adjustment_patch",
                    "note": "langgraph_refine_preview",
                },
            }
        ],
    }
    assert refined_first_day_assignment == {
        "date": "2026-04-01",
        "worker_code": PRIMARY_DEMO_WORKER.code,
        "shift_code": "EVE",
        "source": "adjustment_patch",
        "station_code": PRIMARY_DEMO_STATION.code,
        "note": "langgraph_refine_preview",
    }
    assert current_first_assignment.shift_definition.code == PRIMARY_DEMO_SHIFT.code
    assert current_first_assignment.assignment_source == "apply"
    assert (
        DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count()
        == 30
    )
    assert refine_request.result_preview_json is not None


def test_django_runtime_refine_without_preview_returns_empty_preview_diff() -> None:
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
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": preview_payload["candidate_id"],
        },
    )

    refine_payload = _post_json(
        views["refine_month_schedule"],
        path="/v2/monthly-schedules/refine",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "request_text": "Write me a poem",
        },
    )

    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    refine_request = DjangoRefineRequest.objects.get(workspace=current_workspace)

    assert refine_payload["status"] == "completed"
    assert refine_payload["outcome"]["status"] == "non_scheduling"
    assert refine_payload["parsed_intent_json"]["preview_executed"] is False
    assert refine_payload["candidate_result"] is None
    assert refine_payload["candidate_id"] is None
    assert refine_payload["preview_diff"] == {
        "added": [],
        "removed": [],
        "changed": [],
    }
    assert refine_request.result_preview_json is None
    assert (
        DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count()
        == 30
    )


def test_django_runtime_refine_change_shift_keeps_station_without_mutating_current() -> None:
    tenant = _seed_month_context()
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
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
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": preview_payload["candidate_id"],
        },
    )

    refine_payload = _post_json(
        views["refine_month_schedule"],
        path="/v2/monthly-schedules/refine",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "request_text": (
                f"4/1 {PRIMARY_DEMO_WORKER.code} "
                f"\u73ed\u5225\u6539 EVE"
            ),
        },
    )

    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    current_first_assignment = DjangoMonthlyAssignment.objects.get(
        workspace=current_workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker__code=PRIMARY_DEMO_WORKER.code,
    )
    refined_first_day_assignment = next(
        assignment
        for assignment in refine_payload["candidate_result"]["assignments"]
        if assignment["date"] == "2026-04-01"
        and assignment["worker_code"] == PRIMARY_DEMO_WORKER.code
    )

    assert refine_payload["outcome"]["status"] == "preview_ready"
    assert refine_payload["parsed_intent_json"]["intent_type"] == "change_shift"
    assert refined_first_day_assignment["shift_code"] == "EVE"
    assert refined_first_day_assignment["station_code"] == PRIMARY_DEMO_STATION.code
    assert refined_first_day_assignment["source"] == "adjustment_patch"
    assert current_first_assignment.shift_definition.code == PRIMARY_DEMO_SHIFT.code
    assert current_first_assignment.station.code == PRIMARY_DEMO_STATION.code
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_django_runtime_refine_does_not_read_other_tenant_current_workspace() -> None:
    tenant = _seed_named_month_context(
        slug="tenant-a",
        name="Tenant A",
        worker_code="ALEX_A",
        worker_name="Alex A",
        station_code="GRILL_A",
        station_name="Grill A",
        shift_code="DAY_A",
        shift_name="Day A",
    )
    other_tenant = _seed_named_month_context(
        slug="tenant-b",
        name="Tenant B",
        worker_code="BLAIR_B",
        worker_name="Blair B",
        station_code="GRILL_B",
        station_name="Grill B",
        shift_code="DAY_B",
        shift_name="Day B",
    )
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    other_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": other_preview_payload["candidate_id"],
        },
    )
    response = _post_json_response(
        views["refine_month_schedule"],
        path="/v2/monthly-schedules/refine",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "request_text": "Please move Alex.",
        },
    )

    assert response.status_code == 404
    assert "No current workspace found" in response.content.decode()
    assert not DjangoRefineRequest.objects.filter(tenant=tenant).exists()


def test_django_runtime_explain_day_returns_bounded_day_explanation() -> None:
    tenant = _seed_month_context()
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
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
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": preview_payload["candidate_id"],
        },
    )
    refine_payload = _post_json(
        views["refine_month_schedule"],
        path="/v2/monthly-schedules/refine",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "request_text": (
                f"请把 {PRIMARY_DEMO_WORKER.code} "
                f"安排到 2026-04-01 的 EVE 在 {PRIMARY_DEMO_STATION.code}"
            ),
        },
    )

    explain_payload = _post_json(
        views["explain_day_schedule"],
        path="/v2/monthly-schedules/explain-day",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "target_date": "2026-04-01",
            "request_text": "What changed in this refine preview?",
            "response_language": "en",
            "candidate_result": refine_payload["candidate_result"],
        },
    )

    assert explain_payload["status"] == "ready"
    assert explain_payload["request_language"] == "en"
    assert explain_payload["response_language"] == "en"
    assert explain_payload["outcome"]["message_key"] == "explain_ready"
    assert explain_payload["parsed_request_json"]["request_category"] == (
        "refine_change_summary"
    )
    assert explain_payload["context_facts"]["source_mode"] == "candidate_preview"
    assert explain_payload["context_facts"]["comparison"]["has_comparison"] is True
    assert explain_payload["explanation"] is not None
    assert explain_payload["explanation"]["headline"]


def test_django_runtime_explain_rejects_candidate_from_other_tenant_scope() -> None:
    tenant = _seed_named_month_context(
        slug="tenant-a",
        name="Tenant A",
        worker_code="ALEX_A",
        worker_name="Alex A",
        station_code="GRILL_A",
        station_name="Grill A",
        shift_code="DAY_A",
        shift_name="Day A",
    )
    other_tenant = _seed_named_month_context(
        slug="tenant-b",
        name="Tenant B",
        worker_code="BLAIR_B",
        worker_name="Blair B",
        station_code="GRILL_B",
        station_name="Grill B",
        shift_code="DAY_B",
        shift_name="Day B",
    )
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    other_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )
    response = _post_json_response(
        views["explain_day_schedule"],
        path="/v2/monthly-schedules/explain-day",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "target_date": "2026-04-01",
            "request_text": "What changed in this refine preview?",
            "response_language": "en",
            "candidate_result": other_preview_payload["result"],
        },
    )

    assert response.status_code == 404
    assert "outside the selected tenant scope" in response.content.decode()


def test_django_runtime_explain_day_rejects_non_scheduling_requests() -> None:
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

    explain_payload = _post_json(
        views["explain_day_schedule"],
        path="/v2/monthly-schedules/explain-day",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
            "target_date": "2026-04-01",
            "request_text": "Write a marketing slogan for my restaurant.",
            "response_language": "en",
            "candidate_result": preview_payload["result"],
        },
    )

    assert explain_payload["status"] == "unsupported"
    assert explain_payload["outcome"]["message_key"] == "explain_unsupported_request"
    assert explain_payload["parsed_request_json"]["reason_code"] == "unsupported_request"
    assert explain_payload["explanation"] is None


def test_django_runtime_export_does_not_read_other_tenant_current_workspace() -> None:
    tenant = _seed_named_month_context(
        slug="tenant-a",
        name="Tenant A",
        worker_code="ALEX_A",
        worker_name="Alex A",
        station_code="GRILL_A",
        station_name="Grill A",
        shift_code="DAY_A",
        shift_name="Day A",
    )
    other_tenant = _seed_named_month_context(
        slug="tenant-b",
        name="Tenant B",
        worker_code="BLAIR_B",
        worker_name="Blair B",
        station_code="GRILL_B",
        station_name="Grill B",
        shift_code="DAY_B",
        shift_name="Day B",
    )
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    other_preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )
    _post_json(
        views["apply_month_schedule"],
        path="/v2/monthly-schedules/apply",
        payload={
            "tenant_slug": other_tenant.slug,
            "year": 2026,
            "month": 4,
            "candidate_id": other_preview_payload["candidate_id"],
        },
    )
    response = _post_json_response(
        views["export_month_schedule"],
        path="/v2/monthly-schedules/export",
        payload={
            "tenant_slug": tenant.slug,
            "year": 2026,
            "month": 4,
        },
    )

    assert response.status_code == 404
    assert "No current workspace found" in response.content.decode()


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
            "station_code": PRIMARY_DEMO_STATION.code,
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
    assert preview_payload["result"]["metadata"]["notes"] == ["engine_v0_1_baseline"]
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0


def test_django_runtime_preview_respects_persisted_leave_requests() -> None:
    tenant = _seed_month_context()
    worker = DjangoWorker.objects.get(tenant=tenant, code=PRIMARY_DEMO_WORKER.code)
    DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=worker,
        leave_date=dt.date(2026, 4, 10),
        reason="vacation",
    )
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

    assert preview_payload["result"]["summary"]["total_assignments"] == 29
    assert preview_payload["result"]["summary"]["total_warnings"] == 1
    assert preview_payload["result"]["warnings"] == [
        {
            "type": "understaffed_station_day",
            "message_key": "understaffed_station",
            "worker_code": None,
            "date": "2026-04-10",
            "details": {
                "station_code": PRIMARY_DEMO_STATION.code,
                "required_staff": 1,
                "assigned_staff": 0,
                "missing_staff": 1,
            },
        }
    ]
    assert all(
        assignment["date"] != "2026-04-10"
        for assignment in preview_payload["result"]["assignments"]
    )
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["understaffed_station_days"] == 1
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0


def test_django_runtime_preview_uses_monthly_constraint_override() -> None:
    tenant = _seed_month_context()
    DjangoWorker.objects.create(
        tenant=tenant,
        code=SECONDARY_DEMO_WORKER.code,
        name=SECONDARY_DEMO_WORKER.name,
        role=SECONDARY_DEMO_WORKER.role,
        is_active=True,
    )
    DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=DjangoWorker.objects.get(
            tenant=tenant,
            code=SECONDARY_DEMO_WORKER.code,
        ),
        station=DjangoStation.objects.get(
            tenant=tenant,
            code=PRIMARY_DEMO_STATION.code,
        ),
    )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="monthly",
        year=2026,
        month=4,
        config_json={
            "stations": {PRIMARY_DEMO_STATION.code: 2},
            "min_staff_weekday": 2,
            "min_staff_weekend": 2,
            "max_staff_per_day": 2,
        },
    )
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

    assert preview_payload["result"]["summary"]["total_assignments"] == 60
    assert preview_payload["result"]["summary"]["total_warnings"] == 0
    assert preview_payload["result"]["summary"]["assignments_by_worker"] == {
        PRIMARY_DEMO_WORKER.code: 30,
        SECONDARY_DEMO_WORKER.code: 30,
    }
    ordered_workers = sorted(
        (PRIMARY_DEMO_WORKER, SECONDARY_DEMO_WORKER),
        key=lambda worker: worker.code,
    )
    assert preview_payload["result"]["assignments"][:2] == [
        {
            "date": "2026-04-01",
            "worker_code": ordered_workers[0].code,
            "shift_code": PRIMARY_DEMO_SHIFT.code,
            "source": "monthly_planner",
            "station_code": PRIMARY_DEMO_STATION.code,
            "note": None,
        },
        {
            "date": "2026-04-01",
            "worker_code": ordered_workers[1].code,
            "shift_code": PRIMARY_DEMO_SHIFT.code,
            "source": "monthly_planner",
            "station_code": PRIMARY_DEMO_STATION.code,
            "note": None,
        },
    ]
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["schedule_quality_label"] == "good"
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0


def test_django_runtime_preview_supports_required_chefs_by_day_kind() -> None:
    tenant = DjangoTenant.objects.create(
        slug="chef-rule-demo",
        name="Chef Rule Demo",
        default_locale="en-US",
    )
    DjangoWorker.objects.create(
        tenant=tenant,
        code="CHEF1",
        name="Morgan",
        role="chef",
        is_active=True,
    )
    DjangoWorker.objects.create(
        tenant=tenant,
        code="CHEF2",
        name="Taylor",
        role="chef",
        is_active=True,
    )
    cook = DjangoWorker.objects.create(
        tenant=tenant,
        code="COOK1",
        name="Alex",
        role="employee",
        is_active=True,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code="GRILL",
        name="Grill",
        is_active=True,
    )
    DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=cook,
        station=station,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="monthly",
        year=2026,
        month=4,
        config_json={
            "stations": {"GRILL": 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
            "required_chefs_weekday": 1,
            "required_chefs_weekend": 2,
            "count_chefs_in_headcount": False,
            "chefs_have_no_shift": True,
        },
    )
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

    assignments = preview_payload["result"]["assignments"]
    weekday_assignments = [
        (
            assignment["worker_code"],
            assignment["shift_code"],
            assignment["station_code"],
            assignment["note"],
        )
        for assignment in assignments
        if assignment["date"] == "2026-04-01"
    ]
    weekend_assignments = [
        (
            assignment["worker_code"],
            assignment["shift_code"],
            assignment["station_code"],
            assignment["note"],
        )
        for assignment in assignments
        if assignment["date"] == "2026-04-04"
    ]

    assert weekday_assignments == [
        ("CHEF1", "DAY", None, "required_chef"),
        ("COOK1", "DAY", "GRILL", None),
    ]
    assert weekend_assignments == [
        ("CHEF1", "DAY", None, "required_chef"),
        ("CHEF2", "DAY", None, "required_chef"),
        ("COOK1", "DAY", "GRILL", None),
    ]
    assert preview_payload["result"]["summary"]["total_assignments"] == 68
    assert preview_payload["result"]["summary"]["total_warnings"] == 0
    assert preview_payload["result"]["summary"]["assignments_by_worker"] == {
        "CHEF1": 19,
        "CHEF2": 19,
        "COOK1": 30,
    }
    assert preview_payload["result"]["warnings"] == []
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["hard_constraints_passed"] is True


def test_django_runtime_preview_seeded_demo_uses_weekday_and_weekend_shift_rules() -> None:
    call_command("seed_monthly_workspace_demo")
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_schedule_urlpatterns()
    }

    preview_payload = _post_json(
        views["preview_month_schedule"],
        path="/v2/monthly-schedules/preview",
        payload={
            "tenant_slug": DEMO_TENANT_SLUG,
            "year": 2026,
            "month": 4,
        },
    )

    assignments = preview_payload["result"]["assignments"]
    numeric_shift_assignments = [
        assignment
        for assignment in assignments
        if assignment["shift_code"] in {"1", "2", "3", "4"}
    ]
    weekday_required_chefs = [
        assignment
        for assignment in assignments
        if assignment["date"] == "2026-04-01"
        and assignment["note"] == "required_chef"
    ]
    weekend_required_chefs = [
        assignment
        for assignment in assignments
        if assignment["date"] == "2026-04-04"
        and assignment["note"] == "required_chef"
    ]

    assert len(weekday_required_chefs) == 1
    assert len(weekend_required_chefs) == 2
    assert all(
        assignment["shift_code"] not in {"1", "2", "3", "4"}
        for assignment in assignments
        if assignment["date"] == "2026-04-01"
    )
    assert numeric_shift_assignments
    assert all(
        dt.date.fromisoformat(assignment["date"]).weekday() >= 5
        for assignment in numeric_shift_assignments
    )


def test_django_runtime_preview_respects_persisted_morning_requirements() -> None:
    tenant = _seed_morning_month_context(include_morning_shift=True)
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

    assert preview_payload["result"]["summary"]["total_assignments"] == 30
    assert preview_payload["result"]["summary"]["total_warnings"] == 0
    assert preview_payload["result"]["warnings"] == []
    assert preview_payload["result"]["assignments"][0] == {
        "date": "2026-04-01",
        "worker_code": "W1",
        "shift_code": "M1",
        "source": "monthly_planner",
        "station_code": "GATEAU",
        "note": None,
    }
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["schedule_quality_label"] == "good"


def test_django_runtime_preview_surfaces_missing_morning_coverage_warning() -> None:
    tenant = _seed_morning_month_context(include_morning_shift=False)
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
        "total_assignments": 30,
        "total_warnings": 30,
        "assignments_by_worker": {"W1": 30},
        "paid_hours_by_worker": {"W1": "240.00"},
        "warnings_by_type": {"missing_morning_station_coverage": 30},
    }
    assert preview_payload["result"]["assignments"][0] == {
        "date": "2026-04-01",
        "worker_code": "W1",
        "shift_code": "DAY",
        "source": "monthly_planner",
        "station_code": "GATEAU",
        "note": None,
    }
    assert preview_payload["result"]["warnings"][0] == {
        "type": "missing_morning_station_coverage",
        "message_key": "missing_morning_station_coverage",
        "worker_code": None,
        "date": "2026-04-01",
        "details": {
            "station_code": "GATEAU",
            "required_morning_staff": 1,
            "assigned_morning_staff": 0,
            "missing_morning_staff": 1,
        },
    }
    assert preview_payload["result"]["evaluation"] is not None
    assert preview_payload["result"]["evaluation"]["schedule_quality_label"] == (
        "needs_review"
    )


def _seed_month_context(*, worker_is_active: bool = True) -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug=DEMO_TENANT_SLUG,
        name=DEMO_TENANT_NAME,
        default_locale="en-US",
    )
    worker = DjangoWorker.objects.create(
        tenant=tenant,
        code=PRIMARY_DEMO_WORKER.code,
        name=PRIMARY_DEMO_WORKER.name,
        role=PRIMARY_DEMO_WORKER.role,
        is_active=worker_is_active,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code=PRIMARY_DEMO_STATION.code,
        name=PRIMARY_DEMO_STATION.name,
        is_active=True,
    )
    DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=worker,
        station=station,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code=PRIMARY_DEMO_SHIFT.code,
        name=PRIMARY_DEMO_SHIFT.name,
        paid_hours=PRIMARY_DEMO_SHIFT.paid_hours,
        start_time=PRIMARY_DEMO_SHIFT.start_time,
        end_time=PRIMARY_DEMO_SHIFT.end_time,
        is_off_shift=False,
    )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {PRIMARY_DEMO_STATION.code: 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
        },
    )
    return tenant


def _seed_named_month_context(
    *,
    slug: str,
    name: str,
    worker_code: str,
    worker_name: str,
    station_code: str,
    station_name: str,
    shift_code: str,
    shift_name: str,
) -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug=slug,
        name=name,
        default_locale="en-US",
    )
    worker = DjangoWorker.objects.create(
        tenant=tenant,
        code=worker_code,
        name=worker_name,
        role="cook",
        is_active=True,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code=station_code,
        name=station_name,
        is_active=True,
    )
    DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=worker,
        station=station,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code=shift_code,
        name=shift_name,
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {station_code: 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
        },
    )
    return tenant


def _seed_morning_month_context(*, include_morning_shift: bool) -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug="morning-demo",
        name="Morning Demo",
        default_locale="en-US",
    )
    worker = DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="employee",
        is_active=True,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code="GATEAU",
        name="Gateau",
        is_active=True,
    )
    DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=worker,
        station=station,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    if include_morning_shift:
        DjangoShiftDefinition.objects.create(
            tenant=tenant,
            code="M1",
            name="Morning 1",
            paid_hours=Decimal("8.00"),
            is_off_shift=False,
        )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {"GATEAU": 1},
            "morning_shifts": ["M1"],
            "stations_require_morning": {"GATEAU": 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
        },
    )
    return tenant


def _post_json(view, *, path: str, payload: dict[str, object]) -> dict[str, object]:
    response = _post_json_response(view, path=path, payload=payload)

    assert response.status_code == 200
    return json.loads(response.content)


def _post_json_response(view, *, path: str, payload: dict[str, object]):
    return view(
        RequestFactory().post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )
    )
