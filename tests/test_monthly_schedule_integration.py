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
from app.infra.django_app.models import (
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
)
from app.infra.django_repositories import (
    DjangoPlanVersionRepository,
    DjangoShiftRepository,
    DjangoStationRepository,
    DjangoTenantRepository,
    DjangoWorkerRepository,
    DjangoWorkspaceRepository,
)
from app.infra.models import ConstraintConfig
from app.services.apply import ApplyMonthScheduleRequest, ApplyMonthScheduleService
from app.services.preview import PreviewMonthScheduleRequest, PreviewMonthScheduleService
from app.services.save import SaveMonthScheduleRequest, SaveMonthScheduleService


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
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

    assert response.result.assignments
    assert response.result.summary.total_assignments == 1
    assert response.result.metadata.source_type == "preview"
    assert DjangoMonthlyWorkspace.objects.count() == 0
    assert DjangoMonthlyAssignment.objects.count() == 0


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

    response = _apply_month(ctx, preview_response.result)

    workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=ctx.tenant,
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
    first_apply = _apply_month(ctx, first_preview.result)
    first_assignment_ids = set(
        DjangoMonthlyAssignment.objects.values_list("id", flat=True)
    )

    second_preview = _preview_month(
        ctx,
        _build_month_result(ctx, [dt.date(2026, 4, 3)]),
    )
    second_apply = _apply_month(ctx, second_preview.result)

    workspace = DjangoMonthlyWorkspace.objects.get(pk=int(second_apply.workspace_id))
    remaining_assignments = list(
        DjangoMonthlyAssignment.objects.filter(workspace=workspace).order_by(
            "assignment_date",
            "worker_id",
            "id",
        )
    )

    assert first_apply.workspace_id == second_apply.workspace_id
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
    first_apply = _apply_month(ctx, first_preview.result)
    first_save = _save_month(ctx, label="Baseline")
    first_version = DjangoMonthlyPlanVersion.objects.get(pk=int(first_save.version_id))
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
    second_apply = _apply_month(ctx, second_preview.result)
    second_save = _save_month(ctx, note="Updated current workspace")

    versions = list(
        DjangoMonthlyPlanVersion.objects.filter(
            workspace_id=int(first_apply.workspace_id)
        ).order_by("version_number", "id")
    )
    first_version.refresh_from_db()

    assert first_save.version_number == 1
    assert second_save.version_number == 2
    assert first_apply.workspace_id == second_apply.workspace_id
    assert [version.version_number for version in versions] == [1, 2]
    assert first_version.snapshot_json == first_snapshot
    assert [
        row["assignment_date"] for row in first_version.snapshot_json["assignments"]
    ] == [
        "2026-04-01",
    ]
    assert [
        row["assignment_date"] for row in versions[1].snapshot_json["assignments"]
    ] == [
        "2026-04-02",
        "2026-04-03",
    ]


def test_save_flow_requires_current_workspace_to_exist() -> None:
    ctx = _seed_month_context()

    with pytest.raises(
        LookupError,
        match=r"No current workspace found for 'tenant-a' 2026-04\.",
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
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    worker = DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code="GRILL",
        name="Grill",
        is_active=True,
    )
    shift = DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    return _SeedContext(
        tenant=tenant,
        worker=worker,
        station=station,
        shift=shift,
    )


def _preview_month(
    ctx: _SeedContext,
    engine_result: MonthPlanningResult,
):
    service = PreviewMonthScheduleService(
        tenant_repository=DjangoTenantRepository(),
        worker_repository=DjangoWorkerRepository(),
        station_repository=DjangoStationRepository(),
        shift_repository=DjangoShiftRepository(),
        leave_request_repository=_NoOpLeaveRequestRepository(),
        constraint_config_repository=_FixedConstraintConfigRepository(),
        engine_runner=_FixedEngine(engine_result),
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
    result: MonthPlanningResult,
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
            result=result,
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


class _NoOpLeaveRequestRepository:
    def list_for_month(
        self,
        tenant_id: str,
        year: int,
        month: int,
    ) -> list[object]:
        del tenant_id, year, month
        return []


class _FixedConstraintConfigRepository:
    def get_resolved_for_month(
        self,
        tenant_id: str,
        year: int,
        month: int,
    ) -> ConstraintConfig:
        return ConstraintConfig(
            tenant_id=tenant_id,
            scope_type="monthly",
            year=year,
            month=month,
            config_json={"max_weekly_hours": 40},
        )
