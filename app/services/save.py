"""Save orchestration for immutable monthly plan history snapshots.

The save service reads the existing mutable workspace for a tenant/month,
captures its current state into a placeholder snapshot payload, and persists a
new immutable version record. It does not recompute assignments, mutate the
workspace, or restore prior versions.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.infra.models import (
    JsonObject,
    MonthlyAssignment,
    MonthlyPlanVersion,
    MonthlyWorkspace,
    RecordId,
)
from app.infra.repositories import (
    CurrentWorkspaceState,
    PlanVersionRepository,
    TenantRepository,
    WorkspaceRepository,
)


@dataclass(slots=True)
class SaveMonthScheduleRequest:
    """Service-layer request for snapshotting one current monthly workspace."""

    tenant_slug: str
    year: int
    month: int
    label: str | None = None
    note: str | None = None


@dataclass(slots=True)
class SaveMonthScheduleResponse:
    """Small save result returned after a version snapshot is persisted."""

    tenant_slug: str
    year: int
    month: int
    version_id: RecordId
    version_number: int
    workspace_id: RecordId
    assignment_count: int


@dataclass(slots=True)
class SaveMonthScheduleService:
    """Coordinates current-workspace reads into immutable saved versions.

    Apply owns mutations to the single current workspace. Save only reads that
    current state, asks the version repository for the next version number, and
    persists an immutable `MonthlyPlanVersion` snapshot.
    """

    tenant_repository: TenantRepository
    workspace_repository: WorkspaceRepository
    plan_version_repository: PlanVersionRepository

    def save_month_schedule(
        self,
        request: SaveMonthScheduleRequest,
    ) -> SaveMonthScheduleResponse:
        """Snapshot the current workspace state into immutable history."""

        _validate_request(request)

        tenant = self.tenant_repository.get_by_slug(request.tenant_slug)
        if tenant is None:
            raise LookupError(f"Tenant not found: {request.tenant_slug!r}")

        tenant_id = _require_record_id(tenant.id, label="tenant.id")
        current_state = self.workspace_repository.load_current(
            tenant_id,
            request.year,
            request.month,
        )
        if current_state is None:
            raise LookupError(
                f"No current workspace found for {tenant.slug!r} "
                f"{request.year}-{request.month:02d}."
            )

        workspace_id = _require_record_id(
            current_state.workspace.id,
            label="workspace.id",
        )
        next_version_number = self.plan_version_repository.get_next_version_number(
            tenant_id,
            request.year,
            request.month,
        )
        snapshot_json = _build_snapshot_payload(
            tenant_slug=tenant.slug,
            current_state=current_state,
            label=request.label,
            note=request.note,
        )

        # Save intentionally snapshots the existing mutable workspace as-is. It
        # does not modify the current workspace or assignment set.
        persisted_version = self.plan_version_repository.save(
            MonthlyPlanVersion(
                tenant_id=tenant_id,
                year=request.year,
                month=request.month,
                version_number=next_version_number,
                snapshot_json=snapshot_json,
                workspace_id=workspace_id,
                summary=_build_version_summary(
                    label=request.label,
                    note=request.note,
                ),
            )
        )
        version_id = _require_record_id(persisted_version.id, label="version.id")

        return SaveMonthScheduleResponse(
            tenant_slug=tenant.slug,
            year=request.year,
            month=request.month,
            version_id=version_id,
            version_number=persisted_version.version_number,
            workspace_id=workspace_id,
            assignment_count=len(current_state.assignments),
        )


def save_month_schedule(
    request: SaveMonthScheduleRequest,
    *,
    service: SaveMonthScheduleService,
) -> SaveMonthScheduleResponse:
    """Thin functional wrapper around the save service boundary."""

    return service.save_month_schedule(request)


def _build_snapshot_payload(
    *,
    tenant_slug: str,
    current_state: CurrentWorkspaceState,
    label: str | None,
    note: str | None,
) -> JsonObject:
    """Build a small JSON-like history snapshot from the current workspace."""

    workspace = current_state.workspace
    return {
        "schema_version": 1,
        "tenant_slug": tenant_slug,
        "period": {
            "year": workspace.year,
            "month": workspace.month,
        },
        "save_metadata": {
            "label": label,
            "note": note,
        },
        "workspace": _serialize_workspace(workspace),
        "assignments": [
            _serialize_assignment(assignment)
            for assignment in current_state.assignments
        ],
    }


def _serialize_workspace(workspace: MonthlyWorkspace) -> JsonObject:
    """Serialize the mutable workspace row into placeholder history data."""

    return {
        "id": workspace.id,
        "year": workspace.year,
        "month": workspace.month,
        "status": workspace.status,
        "is_current": workspace.is_current,
        "source_version_id": workspace.source_version_id,
    }


def _serialize_assignment(assignment: MonthlyAssignment) -> JsonObject:
    """Serialize one persisted assignment row for snapshot history."""

    return {
        "id": assignment.id,
        "worker_id": assignment.worker_id,
        "assignment_date": assignment.assignment_date.isoformat(),
        "shift_definition_id": assignment.shift_definition_id,
        "station_id": assignment.station_id,
    }


def _build_version_summary(*, label: str | None, note: str | None) -> str | None:
    """Pick a small human-facing summary for the saved version row."""

    return label or note


def _validate_request(request: SaveMonthScheduleRequest) -> None:
    """Guard the save service boundary against invalid calendar inputs."""

    if request.year < 1:
        raise ValueError("Save year must be greater than zero.")
    if request.month < 1 or request.month > 12:
        raise ValueError("Save month must be between 1 and 12.")


def _require_record_id(record_id: RecordId | None, *, label: str) -> RecordId:
    """Ensure repository-loaded records are usable for downstream saves."""

    if record_id is None:
        raise ValueError(f"{label} must be populated on repository results.")
    return record_id


__all__ = [
    "SaveMonthScheduleRequest",
    "SaveMonthScheduleResponse",
    "SaveMonthScheduleService",
    "save_month_schedule",
]
