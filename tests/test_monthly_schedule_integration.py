from __future__ import annotations

import datetime as dt
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
)
from app.engine.monthly import generate_month_plan
from app.monthly_workspace_demo_data import (
    DEMO_TENANT_NAME,
    DEMO_TENANT_SLUG,
    PRIMARY_DEMO_SHIFT,
    PRIMARY_DEMO_STATION,
    PRIMARY_DEMO_WORKER,
)
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
    WorkerStationSkill as DjangoWorkerStationSkill,
)
from app.infra.django_repositories import (
    DjangoConstraintConfigRepository,
    DjangoLeaveRequestRepository,
    DjangoPlanVersionRepository,
    DjangoShiftRepository,
    DjangoStationRepository,
    DjangoTenantRepository,
    DjangoWorkerRepository,
    DjangoWorkspaceRepository,
)
from app.services.apply import ApplyMonthScheduleRequest, ApplyMonthScheduleService
from app.services.preview import PreviewMonthScheduleRequest, PreviewMonthScheduleService
from app.services.save import SaveMonthScheduleRequest, SaveMonthScheduleService


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
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


def test_preview_flow_returns_candidate_result_without_writing_workspace() -> None:
    ctx = _seed_month_context()

    response = _preview_month(
        ctx,
        _build_month_result(ctx, [dt.date(2026, 4, 1)]),
    )

    assert response.candidate_result.assignments
    assert response.candidate_result.summary.total_assignments == 1
    assert response.candidate_result.metadata.source_type == "preview"
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0


def test_preview_flow_with_real_engine_respects_persisted_leave() -> None:
    ctx = _seed_month_context()
    DjangoLeaveRequest.objects.create(
        tenant=ctx.tenant,
        worker=ctx.worker,
        leave_date=dt.date(2026, 4, 1),
        reason="vacation",
    )

    response = _preview_month_with_real_engine(ctx)

    assert response.candidate_result.summary.total_assignments == 29
    assert response.candidate_result.summary.total_warnings == 1
    assert response.candidate_result.metadata.source_type == "monthly_planner"
    assert response.candidate_result.evaluation is not None
    assert response.candidate_result.evaluation.understaffed_station_days == 1
    assert all(
        assignment.date != dt.date(2026, 4, 1)
        for assignment in response.candidate_result.assignments
    )
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0


def test_preview_flow_with_real_engine_uses_persisted_worker_station_skills() -> None:
    tenant = DjangoTenant.objects.create(
        slug=DEMO_TENANT_SLUG,
        name=DEMO_TENANT_NAME,
        default_locale="en-US",
    )
    worker_one = DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="employee",
        is_active=True,
    )
    worker_two = DjangoWorker.objects.create(
        tenant=tenant,
        code="W2",
        name="Casey",
        role="employee",
        is_active=True,
    )
    gateau = DjangoStation.objects.create(
        tenant=tenant,
        code="GATEAU",
        name="Gateau",
        is_active=True,
    )
    petit_four = DjangoStation.objects.create(
        tenant=tenant,
        code="PETIT_FOUR",
        name="Petit Four",
        is_active=True,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=worker_one,
        station=gateau,
    )
    DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=worker_two,
        station=petit_four,
    )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {
                "GATEAU": 1,
                "PETIT_FOUR": 1,
            },
            "min_staff_weekday": 2,
            "min_staff_weekend": 2,
            "max_staff_per_day": 2,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
        },
    )

    response = PreviewMonthScheduleService(
        tenant_repository=DjangoTenantRepository(),
        worker_repository=DjangoWorkerRepository(),
        station_repository=DjangoStationRepository(),
        shift_repository=DjangoShiftRepository(),
        leave_request_repository=DjangoLeaveRequestRepository(),
        constraint_config_repository=DjangoConstraintConfigRepository(),
        engine_runner=generate_month_plan,
    ).preview_month_schedule(
        PreviewMonthScheduleRequest(
            tenant_slug=tenant.slug,
            year=2026,
            month=4,
        )
    )

    first_day_assignments = sorted(
        (
            assignment.station_code,
            assignment.worker_code,
        )
        for assignment in response.candidate_result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    )

    assert first_day_assignments == [
        ("GATEAU", "W1"),
        ("PETIT_FOUR", "W2"),
    ]


def test_preview_flow_with_real_engine_uses_multiple_ordinary_shifts_from_persisted_inputs() -> None:
    tenant = _seed_multi_shift_month_context()

    response = PreviewMonthScheduleService(
        tenant_repository=DjangoTenantRepository(),
        worker_repository=DjangoWorkerRepository(),
        station_repository=DjangoStationRepository(),
        shift_repository=DjangoShiftRepository(),
        leave_request_repository=DjangoLeaveRequestRepository(),
        constraint_config_repository=DjangoConstraintConfigRepository(),
        engine_runner=generate_month_plan,
    ).preview_month_schedule(
        PreviewMonthScheduleRequest(
            tenant_slug=tenant.slug,
            year=2026,
            month=4,
        )
    )

    first_day_shift_codes = [
        assignment.shift_code
        for assignment in response.candidate_result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    ]

    assert response.candidate_result.summary.total_warnings == 0
    assert first_day_shift_codes == ["M1", "DAY", "EVE"]


def test_apply_flow_creates_current_workspace_from_preview_result() -> None:
    ctx = _seed_month_context()
    preview_response = _preview_month(
        ctx,
        _build_month_result(
            ctx,
            [
                dt.date(2026, 4, 1),
                dt.date(2026, 4, 2),
            ],
        ),
    )

    response = _apply_month(ctx, preview_response.candidate_result)

    workspace = DjangoMonthlyWorkspace.objects.get(pk=int(response.current_workspace_id))
    assignments = list(
        DjangoMonthlyAssignment.objects.filter(workspace=workspace).order_by(
            "assignment_date",
            "worker_id",
            "id",
        )
    )

    assert response.workspace_created is True
    assert response.assignment_count == 2
    assert DjangoMonthlyWorkspace.objects.filter(
        tenant=ctx.tenant,
        year=2026,
        month=4,
    ).count() == 1
    assert workspace.status == "draft"
    assert [row.assignment_date for row in assignments] == [
        dt.date(2026, 4, 1),
        dt.date(2026, 4, 2),
    ]
    assert all(row.worker_id == ctx.worker.id for row in assignments)
    assert all(row.shift_definition_id == ctx.shift.id for row in assignments)
    assert all(row.station_id == ctx.station.id for row in assignments)
    assert [row.note for row in assignments] == [
        "Integration assignment 1",
        "Integration assignment 2",
    ]


def test_apply_flow_replaces_assignments_instead_of_appending() -> None:
    ctx = _seed_month_context()

    first_preview = _preview_month(
        ctx,
        _build_month_result(
            ctx,
            [
                dt.date(2026, 4, 1),
                dt.date(2026, 4, 2),
            ],
        ),
    )
    first_apply = _apply_month(ctx, first_preview.candidate_result)
    first_assignment_ids = set(
        DjangoMonthlyAssignment.objects.values_list("id", flat=True)
    )

    second_preview = _preview_month(
        ctx,
        _build_month_result(ctx, [dt.date(2026, 4, 3)]),
    )
    second_apply = _apply_month(ctx, second_preview.candidate_result)

    workspace = DjangoMonthlyWorkspace.objects.get(
        pk=int(second_apply.current_workspace_id)
    )
    remaining_assignments = list(
        DjangoMonthlyAssignment.objects.filter(workspace=workspace).order_by(
            "assignment_date",
            "worker_id",
            "id",
        )
    )

    assert first_apply.current_workspace_id == second_apply.current_workspace_id
    assert second_apply.workspace_created is False
    assert DjangoMonthlyWorkspace.objects.filter(
        tenant=ctx.tenant,
        year=2026,
        month=4,
    ).count() == 1
    assert [row.assignment_date for row in remaining_assignments] == [
        dt.date(2026, 4, 3),
    ]
    assert first_assignment_ids.isdisjoint({row.id for row in remaining_assignments})


def test_save_flow_creates_immutable_version_snapshots() -> None:
    ctx = _seed_month_context()

    first_preview = _preview_month(
        ctx,
        _build_month_result(ctx, [dt.date(2026, 4, 1)]),
    )
    first_apply = _apply_month(ctx, first_preview.candidate_result)
    first_save = _save_month(ctx, label="Baseline")
    first_version = DjangoMonthlyPlanVersion.objects.get(
        pk=int(first_save.saved_version_id)
    )
    first_snapshot = deepcopy(first_version.snapshot_json)

    second_preview = _preview_month(
        ctx,
        _build_month_result(
            ctx,
            [
                dt.date(2026, 4, 2),
                dt.date(2026, 4, 3),
            ],
        ),
    )
    second_apply = _apply_month(ctx, second_preview.candidate_result)
    second_save = _save_month(ctx, note="Updated current workspace")

    versions = list(
        DjangoMonthlyPlanVersion.objects.filter(
            workspace_id=int(first_apply.current_workspace_id)
        ).order_by("version_number", "id")
    )
    first_version.refresh_from_db()

    assert first_save.version_number == 1
    assert second_save.version_number == 2
    assert first_apply.current_workspace_id == second_apply.current_workspace_id
    assert [version.version_number for version in versions] == [1, 2]
    assert first_version.snapshot_json == first_snapshot
    assert [
        row["assignment_date"] for row in first_version.snapshot_json["assignments"]
    ] == [
        "2026-04-01",
    ]
    assert [row["note"] for row in first_version.snapshot_json["assignments"]] == [
        "Integration assignment 1",
    ]
    assert [
        row["assignment_date"] for row in versions[1].snapshot_json["assignments"]
    ] == [
        "2026-04-02",
        "2026-04-03",
    ]
    assert [row["note"] for row in versions[1].snapshot_json["assignments"]] == [
        "Integration assignment 1",
        "Integration assignment 2",
    ]


def test_workspace_state_story_keeps_candidate_current_and_saved_state_distinct() -> None:
    ctx = _seed_month_context()
    tenant_id = str(ctx.tenant.id)
    workspace_repository = DjangoWorkspaceRepository()
    version_repository = DjangoPlanVersionRepository()

    baseline_preview = _preview_month(
        ctx,
        _build_month_result(ctx, [dt.date(2026, 4, 1)]),
    )

    assert _assignment_dates_from_result(baseline_preview.candidate_result) == [
        "2026-04-01",
    ]
    assert workspace_repository.load_current(tenant_id, 2026, 4) is None
    assert version_repository.list_for_month(tenant_id, 2026, 4) == []

    baseline_apply = _apply_month(ctx, baseline_preview.candidate_result)
    current_after_baseline_apply = workspace_repository.load_current(
        tenant_id,
        2026,
        4,
    )

    assert current_after_baseline_apply is not None
    assert (
        baseline_apply.current_workspace_id
        == current_after_baseline_apply.workspace.id
    )
    assert _assignment_dates_from_current_state(current_after_baseline_apply) == [
        "2026-04-01",
    ]

    baseline_save = _save_month(ctx, label="Baseline")
    saved_baseline = version_repository.get_by_id(baseline_save.saved_version_id)

    assert saved_baseline is not None
    assert baseline_save.workspace_id == current_after_baseline_apply.workspace.id
    assert _assignment_dates_from_snapshot(saved_baseline.snapshot_json) == [
        "2026-04-01",
    ]

    candidate_preview = _preview_month(
        ctx,
        _build_month_result(
            ctx,
            [
                dt.date(2026, 4, 2),
                dt.date(2026, 4, 3),
            ],
        ),
    )
    current_after_candidate_preview = workspace_repository.load_current(
        tenant_id,
        2026,
        4,
    )
    reloaded_saved_baseline = version_repository.get_by_id(
        baseline_save.saved_version_id
    )

    assert _assignment_dates_from_result(candidate_preview.candidate_result) == [
        "2026-04-02",
        "2026-04-03",
    ]
    assert current_after_candidate_preview is not None
    assert _assignment_dates_from_current_state(current_after_candidate_preview) == [
        "2026-04-01",
    ]
    assert reloaded_saved_baseline is not None
    assert _assignment_dates_from_snapshot(reloaded_saved_baseline.snapshot_json) == [
        "2026-04-01",
    ]
    assert [version.version_number for version in version_repository.list_for_month(
        tenant_id,
        2026,
        4,
    )] == [1]

    candidate_apply = _apply_month(ctx, candidate_preview.candidate_result)
    current_after_candidate_apply = workspace_repository.load_current(
        tenant_id,
        2026,
        4,
    )
    saved_baseline_after_candidate_apply = version_repository.get_by_id(
        baseline_save.saved_version_id
    )

    assert current_after_candidate_apply is not None
    assert candidate_apply.current_workspace_id == baseline_apply.current_workspace_id
    assert _assignment_dates_from_current_state(current_after_candidate_apply) == [
        "2026-04-02",
        "2026-04-03",
    ]
    assert saved_baseline_after_candidate_apply is not None
    assert _assignment_dates_from_snapshot(
        saved_baseline_after_candidate_apply.snapshot_json
    ) == [
        "2026-04-01",
    ]

    candidate_save = _save_month(ctx, note="Candidate promoted to current")
    saved_versions = version_repository.list_for_month(tenant_id, 2026, 4)

    assert candidate_save.version_number == 2
    assert [version.version_number for version in saved_versions] == [1, 2]
    assert _assignment_dates_from_snapshot(saved_versions[0].snapshot_json) == [
        "2026-04-01",
    ]
    assert _assignment_dates_from_snapshot(saved_versions[1].snapshot_json) == [
        "2026-04-02",
        "2026-04-03",
    ]


def test_save_flow_requires_current_workspace_to_exist() -> None:
    ctx = _seed_month_context()

    with pytest.raises(
        LookupError,
        match=rf"No current workspace found for '{DEMO_TENANT_SLUG}' 2026-04\.",
    ):
        _save_month(ctx)


def test_only_one_current_workspace_is_allowed_per_tenant_month() -> None:
    ctx = _seed_month_context()

    DjangoMonthlyWorkspace.objects.create(
        tenant=ctx.tenant,
        year=2026,
        month=4,
        status="draft",
        source_type="preview",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DjangoMonthlyWorkspace.objects.create(
                tenant=ctx.tenant,
                year=2026,
                month=4,
                status="draft",
                source_type="preview",
            )

    assert DjangoMonthlyWorkspace.objects.filter(
        tenant=ctx.tenant,
        year=2026,
        month=4,
    ).count() == 1


@dataclass(slots=True)
class _SeedContext:
    tenant: DjangoTenant
    worker: DjangoWorker
    station: DjangoStation
    shift: DjangoShiftDefinition


def _seed_month_context() -> _SeedContext:
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
        is_active=True,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code=PRIMARY_DEMO_STATION.code,
        name=PRIMARY_DEMO_STATION.name,
        is_active=True,
    )
    shift = DjangoShiftDefinition.objects.create(
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
    return _SeedContext(
        tenant=tenant,
        worker=worker,
        station=station,
        shift=shift,
    )


def _seed_multi_shift_month_context() -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug="multi-shift-demo",
        name="Multi Shift Demo",
        default_locale="en-US",
    )
    worker_codes = ("W1", "W2", "W3")
    station_codes = ("GATEAU", "PREP")
    workers_by_code: dict[str, DjangoWorker] = {}
    stations_by_code: dict[str, DjangoStation] = {}

    for worker_code in worker_codes:
        workers_by_code[worker_code] = DjangoWorker.objects.create(
            tenant=tenant,
            code=worker_code,
            name=worker_code,
            role="employee",
            is_active=True,
        )
    for station_code in station_codes:
        stations_by_code[station_code] = DjangoStation.objects.create(
            tenant=tenant,
            code=station_code,
            name=station_code.title(),
            is_active=True,
        )
    for worker in workers_by_code.values():
        for station in stations_by_code.values():
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
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
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
            "stations": {
                "GATEAU": 2,
                "PREP": 1,
            },
            "morning_shifts": ["M1"],
            "stations_require_morning": {"GATEAU": 1},
            "min_staff_weekday": 3,
            "min_staff_weekend": 3,
            "max_staff_per_day": 3,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
        },
    )
    return tenant


def _preview_month(
    ctx: _SeedContext,
    engine_result: MonthPlanningResult,
):
    service = PreviewMonthScheduleService(
        tenant_repository=DjangoTenantRepository(),
        worker_repository=DjangoWorkerRepository(),
        station_repository=DjangoStationRepository(),
        shift_repository=DjangoShiftRepository(),
        leave_request_repository=DjangoLeaveRequestRepository(),
        constraint_config_repository=DjangoConstraintConfigRepository(),
        engine_runner=_FixedEngine(engine_result),
    )
    return service.preview_month_schedule(
        PreviewMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
        )
    )


def _preview_month_with_real_engine(ctx: _SeedContext):
    service = PreviewMonthScheduleService(
        tenant_repository=DjangoTenantRepository(),
        worker_repository=DjangoWorkerRepository(),
        station_repository=DjangoStationRepository(),
        shift_repository=DjangoShiftRepository(),
        leave_request_repository=DjangoLeaveRequestRepository(),
        constraint_config_repository=DjangoConstraintConfigRepository(),
        engine_runner=generate_month_plan,
    )
    return service.preview_month_schedule(
        PreviewMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
        )
    )


def _apply_month(
    ctx: _SeedContext,
    candidate_result: MonthPlanningResult,
):
    service = ApplyMonthScheduleService(
        tenant_repository=DjangoTenantRepository(),
        worker_repository=DjangoWorkerRepository(),
        station_repository=DjangoStationRepository(),
        shift_repository=DjangoShiftRepository(),
        workspace_repository=DjangoWorkspaceRepository(),
    )
    return service.apply_month_schedule(
        ApplyMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
            result=candidate_result,
        )
    )


def _save_month(
    ctx: _SeedContext,
    *,
    label: str | None = None,
    note: str | None = None,
):
    service = SaveMonthScheduleService(
        tenant_repository=DjangoTenantRepository(),
        workspace_repository=DjangoWorkspaceRepository(),
        plan_version_repository=DjangoPlanVersionRepository(),
    )
    return service.save_month_schedule(
        SaveMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
            label=label,
            note=note,
        )
    )


def _build_month_result(
    ctx: _SeedContext,
    assignment_dates: list[dt.date],
) -> MonthPlanningResult:
    assignments = [
        AssignmentOutput(
            date=assignment_date,
            worker_code=ctx.worker.code,
            shift_code=ctx.shift.code,
            station_code=ctx.station.code,
            source="preview",
            note=f"Integration assignment {index}",
        )
        for index, assignment_date in enumerate(assignment_dates, start=1)
    ]
    return MonthPlanningResult(
        assignments=assignments,
        warnings=[],
        summary=MonthPlanningSummary(
            total_assignments=len(assignments),
            total_warnings=0,
            assignments_by_worker={ctx.worker.code: len(assignments)},
            paid_hours_by_worker={
                ctx.worker.code: ctx.shift.paid_hours * len(assignments)
            },
            warnings_by_type={},
        ),
        metadata=MonthPlanningMetadata(
            generated_at=dt.datetime(2026, 4, 12, tzinfo=dt.timezone.utc),
            source_type="preview",
            refinement_applied=False,
            notes=["integration-test"],
        ),
    )


class _FixedEngine:
    def __init__(self, result: MonthPlanningResult) -> None:
        self.result = result

    def __call__(self, planning_input) -> MonthPlanningResult:
        del planning_input
        return self.result


def _assignment_dates_from_result(result: MonthPlanningResult) -> list[str]:
    return [assignment.date.isoformat() for assignment in result.assignments]


def _assignment_dates_from_current_state(current_state) -> list[str]:
    return [
        assignment.assignment_date.isoformat()
        for assignment in current_state.assignments
    ]


def _assignment_dates_from_snapshot(snapshot_json: dict[str, object]) -> list[str]:
    assignments = snapshot_json["assignments"]
    assert isinstance(assignments, list)
    return [str(row["assignment_date"]) for row in assignments]
