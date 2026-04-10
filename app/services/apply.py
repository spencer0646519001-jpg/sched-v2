"""Apply orchestration for mutating the current monthly workspace.

The apply service is the bridge from preview or engine-shaped output into the
single current persisted workspace for a tenant/month. It updates mutable
workspace state and explicitly replaces assignment rows, but it does not create
immutable saved versions or history snapshots.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
    WarningOutput,
)
from app.infra.models import (
    MonthlyAssignment,
    MonthlyWorkspace,
    RecordId,
    ShiftDefinition,
    Station,
    Worker,
)
from app.infra.repositories import (
    CurrentWorkspaceState,
    ShiftRepository,
    StationRepository,
    TenantRepository,
    WorkerRepository,
    WorkspaceRepository,
)


class MonthPlanningResultPayload(Protocol):
    """Structural result shape accepted by the apply service boundary."""

    assignments: Sequence[AssignmentOutput]
    warnings: Sequence[WarningOutput]
    summary: MonthPlanningSummary
    metadata: MonthPlanningMetadata


@dataclass(slots=True)
class ApplyMonthScheduleRequest:
    """Service-layer request for applying one preview into current workspace."""

    tenant_slug: str
    year: int
    month: int
    result: MonthPlanningResult | MonthPlanningResultPayload


@dataclass(slots=True)
class ApplyMonthScheduleResponse:
    """Small apply result returned after current workspace state is updated."""

    tenant_slug: str
    year: int
    month: int
    workspace_id: RecordId
    workspace_status: str
    assignment_count: int
    warning_count: int
    workspace_created: bool


@dataclass(slots=True)
class ApplyMonthScheduleService:
    """Coordinates the preview-to-workspace mutation flow.

    This service loads tenant-scoped reference data, resolves or prepares the
    single current workspace, and replaces its assignments. Version snapshots
    remain a separate save/history concern. Concrete repositories can wrap the
    write path in one transaction when they add database implementations.
    """

    tenant_repository: TenantRepository
    worker_repository: WorkerRepository
    station_repository: StationRepository
    shift_repository: ShiftRepository
    workspace_repository: WorkspaceRepository

    def apply_month_schedule(
        self,
        request: ApplyMonthScheduleRequest,
    ) -> ApplyMonthScheduleResponse:
        """Apply a preview result onto the mutable current workspace."""

        _validate_request(request)

        tenant = self.tenant_repository.get_by_slug(request.tenant_slug)
        if tenant is None:
            raise LookupError(f"Tenant not found: {request.tenant_slug!r}")

        tenant_id = _require_record_id(tenant.id, label="tenant.id")
        planning_result = _coerce_month_planning_result(request.result)

        workers = self.worker_repository.list_for_tenant(tenant_id)
        stations = self.station_repository.list_for_tenant(tenant_id)
        shifts = self.shift_repository.list_for_tenant(tenant_id)

        current_state = self.workspace_repository.load_current(
            tenant_id,
            request.year,
            request.month,
        )
        workspace_to_save = _prepare_workspace_record(
            tenant_id=tenant_id,
            year=request.year,
            month=request.month,
            current_state=current_state,
        )
        workspace_created = current_state is None

        # Apply intentionally updates the mutable workspace row first, then
        # explicitly replaces the attached assignment set.
        persisted_workspace = self.workspace_repository.save_current_workspace(
            workspace_to_save
        )
        workspace_id = _require_record_id(
            persisted_workspace.id,
            label="workspace.id",
        )
        assignment_rows = _translate_engine_assignments_to_persistence_rows(
            planning_result.assignments,
            workspace_id=workspace_id,
            workers=workers,
            stations=stations,
            shifts=shifts,
        )
        persisted_assignments = self.workspace_repository.replace_assignments(
            workspace_id,
            assignment_rows,
        )

        return ApplyMonthScheduleResponse(
            tenant_slug=tenant.slug,
            year=request.year,
            month=request.month,
            workspace_id=workspace_id,
            workspace_status=persisted_workspace.status,
            assignment_count=len(persisted_assignments),
            warning_count=len(planning_result.warnings),
            workspace_created=workspace_created,
        )


def apply_month_schedule(
    request: ApplyMonthScheduleRequest,
    *,
    service: ApplyMonthScheduleService,
) -> ApplyMonthScheduleResponse:
    """Thin functional wrapper around the apply service boundary."""

    return service.apply_month_schedule(request)


def _prepare_workspace_record(
    *,
    tenant_id: RecordId,
    year: int,
    month: int,
    current_state: CurrentWorkspaceState | None,
) -> MonthlyWorkspace:
    """Prepare the mutable workspace row that apply should persist."""

    if current_state is None:
        return MonthlyWorkspace(
            tenant_id=tenant_id,
            year=year,
            month=month,
            status="draft",
            is_current=True,
            source_version_id=None,
        )

    # Applying a fresh preview resets the current workspace back to mutable
    # draft state and clears any future restore linkage.
    return replace(
        current_state.workspace,
        status="draft",
        is_current=True,
        source_version_id=None,
    )


def _translate_engine_assignments_to_persistence_rows(
    assignments: Sequence[AssignmentOutput],
    *,
    workspace_id: RecordId,
    workers: Sequence[Worker],
    stations: Sequence[Station],
    shifts: Sequence[ShiftDefinition],
) -> list[MonthlyAssignment]:
    """Map engine-style assignment identifiers onto persistence row ids."""

    worker_ids_by_code = {
        _resolve_worker_code(worker): _require_record_id(worker.id, label="worker.id")
        for worker in workers
    }
    station_ids_by_code = {
        _resolve_station_code(station): _require_record_id(
            station.id,
            label="station.id",
        )
        for station in stations
    }
    shift_ids_by_code = {
        shift.code: _require_record_id(shift.id, label="shift.id") for shift in shifts
    }

    assignment_rows: list[MonthlyAssignment] = []
    for assignment in assignments:
        worker_id = worker_ids_by_code.get(assignment.worker_code)
        if worker_id is None:
            raise LookupError(
                f"Assignment references unknown worker_code "
                f"{assignment.worker_code!r}."
            )

        shift_definition_id = shift_ids_by_code.get(assignment.shift_code)
        if shift_definition_id is None:
            raise LookupError(
                f"Assignment references unknown shift_code "
                f"{assignment.shift_code!r}."
            )

        station_id: RecordId | None = None
        if assignment.station_code is not None:
            station_id = station_ids_by_code.get(assignment.station_code)
            if station_id is None:
                raise LookupError(
                    f"Assignment references unknown station_code "
                    f"{assignment.station_code!r}."
                )

        assignment_rows.append(
            MonthlyAssignment(
                workspace_id=workspace_id,
                worker_id=worker_id,
                assignment_date=assignment.date,
                shift_definition_id=shift_definition_id,
                station_id=station_id,
            )
        )

    return assignment_rows


def _coerce_month_planning_result(
    result: MonthPlanningResult | MonthPlanningResultPayload,
) -> MonthPlanningResult:
    """Normalize preview or engine-shaped payloads into one result contract."""

    if isinstance(result, MonthPlanningResult):
        return result

    try:
        assignments = list(result.assignments)
        warnings = list(result.warnings)
        summary = result.summary
        metadata = result.metadata
    except AttributeError as exc:
        raise TypeError(
            "Apply result must expose assignments, warnings, summary, and "
            "metadata."
        ) from exc

    return MonthPlanningResult(
        assignments=assignments,
        warnings=warnings,
        summary=summary,
        metadata=metadata,
    )


def _validate_request(request: ApplyMonthScheduleRequest) -> None:
    """Guard the apply service boundary against invalid calendar inputs."""

    if request.year < 1:
        raise ValueError("Apply year must be greater than zero.")
    if request.month < 1 or request.month > 12:
        raise ValueError("Apply month must be between 1 and 12.")


def _resolve_worker_code(worker: Worker) -> str:
    """Choose the engine identifier used to match worker assignments."""

    return _coalesce_engine_code(worker.code, worker.id, label="worker")


def _resolve_station_code(station: Station) -> str:
    """Choose the engine identifier used to match station assignments."""

    return _coalesce_engine_code(station.code, station.id, label="station")


def _coalesce_engine_code(
    code: str | None,
    record_id: RecordId | None,
    *,
    label: str,
) -> str:
    """Prefer business codes, falling back to persisted ids for lookups."""

    if code:
        return code
    if record_id:
        return record_id
    raise ValueError(f"{label.capitalize()} requires either a code or persisted id.")


def _require_record_id(record_id: RecordId | None, *, label: str) -> RecordId:
    """Ensure repository-loaded records are usable for downstream writes."""

    if record_id is None:
        raise ValueError(f"{label} must be populated on repository results.")
    return record_id


__all__ = [
    "ApplyMonthScheduleRequest",
    "ApplyMonthScheduleResponse",
    "ApplyMonthScheduleService",
    "MonthPlanningResultPayload",
    "apply_month_schedule",
]
