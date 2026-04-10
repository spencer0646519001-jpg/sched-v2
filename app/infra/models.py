"""Persistence-facing storage records for the V2 scheduler.

These dataclasses describe row shapes and relationships without committing the
project to an ORM. Future repositories should translate them into domain and
engine contracts so the scheduling engine stays storage-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal, TypeAlias

RecordId: TypeAlias = str
JsonObject: TypeAlias = dict[str, Any]
ConstraintScopeType: TypeAlias = Literal["default", "monthly"]


@dataclass(slots=True)
class Tenant:
    """Top-level tenant boundary for all master data, plans, and history."""

    slug: str
    name: str
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Worker:
    """Tenant-scoped worker master data used to build monthly assignments."""

    tenant_id: RecordId
    name: str
    role: str
    code: str | None = None
    is_active: bool = True
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Station:
    """Tenant-scoped station or role that a worker may cover on a shift."""

    tenant_id: RecordId
    name: str
    code: str | None = None
    is_active: bool = True
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class ShiftDefinition:
    """Tenant-scoped shift template, including paid hours and off-shift rows."""

    tenant_id: RecordId
    code: str
    name: str
    paid_hours: Decimal
    start_time: time | None = None
    end_time: time | None = None
    is_off_shift: bool = False
    is_active: bool = True
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class WorkerStationSkill:
    """Capability mapping that links a worker to a station they can cover."""

    tenant_id: RecordId
    worker_id: RecordId
    station_id: RecordId
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class LeaveRequest:
    """Approved date-based worker unavailability used as scheduling input."""

    tenant_id: RecordId
    worker_id: RecordId
    leave_date: date
    reason: str | None = None
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class ConstraintConfig:
    """One complete constraint config for a scope, not composable fragments."""

    tenant_id: RecordId
    scope_type: ConstraintScopeType
    config_json: JsonObject
    year: int | None = None
    month: int | None = None
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class MonthlyWorkspace:
    """Mutable working state for one tenant/month; intended to have one current row."""

    tenant_id: RecordId
    year: int
    month: int
    status: str = "draft"
    is_current: bool = True
    source_version_id: RecordId | None = None
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class MonthlyAssignment:
    """Assignment row that belongs to a monthly workspace."""

    workspace_id: RecordId
    worker_id: RecordId
    assignment_date: date
    shift_definition_id: RecordId
    station_id: RecordId | None = None
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class MonthlyPlanVersion:
    """Immutable saved snapshot of a monthly plan for history and restore flows."""

    tenant_id: RecordId
    year: int
    month: int
    version_number: int
    snapshot_json: JsonObject
    workspace_id: RecordId | None = None
    summary: str | None = None
    id: RecordId | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class RefineRequest:
    """One refine instruction plus parsed intent and preview result, not a chat log."""

    tenant_id: RecordId
    workspace_id: RecordId
    request_text: str
    status: str
    parsed_intent_json: JsonObject | None = None
    result_preview_json: JsonObject | None = None
    id: RecordId | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = [
    "ConstraintConfig",
    "ConstraintScopeType",
    "JsonObject",
    "LeaveRequest",
    "MonthlyAssignment",
    "MonthlyPlanVersion",
    "MonthlyWorkspace",
    "RecordId",
    "RefineRequest",
    "ShiftDefinition",
    "Station",
    "Tenant",
    "Worker",
    "WorkerStationSkill",
]
