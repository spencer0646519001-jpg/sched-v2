"""Repository interfaces for persistence access in the V2 scheduler.

These abstractions define how services read and write persistence models
without binding the application to a concrete database framework. Services can
compose repositories to assemble persistence-side bundles and later translate
those bundles into pure engine contracts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.infra.models import (
    ConstraintConfig,
    JsonObject,
    LeaveRequest,
    MonthlyAssignment,
    MonthlyPlanVersion,
    MonthlyWorkspace,
    RecordId,
    RefineRequest,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
    WorkerStationSkill,
)


@dataclass(slots=True)
class MonthlyPlanningPersistenceBundle:
    """Persistence-side month data loaded before service-to-engine translation."""

    tenant: Tenant
    year: int
    month: int
    workers: list[Worker]
    worker_station_skills: list[WorkerStationSkill]
    stations: list[Station]
    shifts: list[ShiftDefinition]
    leave_requests: list[LeaveRequest]
    constraint_config: ConstraintConfig


@dataclass(slots=True)
class CurrentWorkspaceState:
    """Current mutable workspace row together with its assignment rows."""

    workspace: MonthlyWorkspace
    assignments: list[MonthlyAssignment]


class TenantRepository(Protocol):
    """Load tenant identity records used to scope all other repositories."""

    def get_by_id(self, tenant_id: RecordId) -> Tenant | None:
        ...

    def get_by_slug(self, slug: str) -> Tenant | None:
        ...


class WorkerRepository(Protocol):
    """Read worker master data and worker-to-station capability mappings."""

    def list_for_tenant(self, tenant_id: RecordId) -> list[Worker]:
        ...

    def list_station_skills(self, tenant_id: RecordId) -> list[WorkerStationSkill]:
        ...


class StationRepository(Protocol):
    """Read tenant-scoped station master data."""

    def list_for_tenant(self, tenant_id: RecordId) -> list[Station]:
        ...


class ShiftRepository(Protocol):
    """Read tenant-scoped shift definition master data."""

    def list_for_tenant(self, tenant_id: RecordId) -> list[ShiftDefinition]:
        ...


class LeaveRequestRepository(Protocol):
    """Read approved worker leave rows for a target planning month."""

    def list_for_month(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> list[LeaveRequest]:
        ...


class ConstraintConfigRepository(Protocol):
    """Load the single resolved full constraint config for a target month."""

    def get_resolved_for_month(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> ConstraintConfig | None:
        ...


class WorkspaceRepository(Protocol):
    """Manage the mutable current workspace and its assignment rows."""

    def load_current(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> CurrentWorkspaceState | None:
        ...

    def save_current_workspace(self, workspace: MonthlyWorkspace) -> MonthlyWorkspace:
        """Create or update the single current workspace row for a month."""
        ...

    def replace_assignments(
        self,
        workspace_id: RecordId,
        assignments: Sequence[MonthlyAssignment],
    ) -> list[MonthlyAssignment]:
        """Replace the current assignment set for one workspace."""
        ...


class PlanVersionRepository(Protocol):
    """Persist immutable monthly plan snapshots and expose version history."""

    def get_next_version_number(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> int:
        ...

    def save(self, version: MonthlyPlanVersion) -> MonthlyPlanVersion:
        ...

    def list_for_month(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> list[MonthlyPlanVersion]:
        ...

    def get_by_id(self, version_id: RecordId) -> MonthlyPlanVersion | None:
        ...


class RefineRequestRepository(Protocol):
    """Create, list, and later enrich refine requests with parsed preview data."""

    def create(self, request: RefineRequest) -> RefineRequest:
        ...

    def list_for_workspace(self, workspace_id: RecordId) -> list[RefineRequest]:
        ...

    def update_parsed_preview(
        self,
        refine_request_id: RecordId,
        *,
        status: str,
        parsed_intent_json: JsonObject | None = None,
        result_preview_json: JsonObject | None = None,
    ) -> RefineRequest | None:
        ...


__all__ = [
    "ConstraintConfigRepository",
    "CurrentWorkspaceState",
    "LeaveRequestRepository",
    "MonthlyPlanningPersistenceBundle",
    "PlanVersionRepository",
    "RefineRequestRepository",
    "ShiftRepository",
    "StationRepository",
    "TenantRepository",
    "WorkerRepository",
    "WorkspaceRepository",
]
