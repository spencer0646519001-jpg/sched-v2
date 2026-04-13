"""Pure dataclass contracts for monthly scheduling engine inputs and outputs.

These types define the boundary between application services and the pure
scheduling engine. Persistence models, API schemas, and AI-layer payloads
should translate into these contracts rather than being passed through
directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal, TypeAlias

WorkerCode: TypeAlias = str
StationCode: TypeAlias = str
ShiftCode: TypeAlias = str
JsonObject: TypeAlias = dict[str, Any]
ScheduleQualityLabel: TypeAlias = Literal["good", "needs_review", "invalid"]


@dataclass(slots=True)
class WorkerInput:
    """Worker master data required by the monthly planning engine."""

    worker_code: WorkerCode
    name: str
    role: str
    is_active: bool
    station_skills: list[StationCode]
    metadata_json: JsonObject | None = None


@dataclass(slots=True)
class StationInput:
    """Station master data that workers may be assigned to cover."""

    station_code: StationCode
    name: str
    is_active: bool
    metadata_json: JsonObject | None = None


@dataclass(slots=True)
class ShiftInput:
    """Shift definition used by the engine when building month assignments."""

    shift_code: ShiftCode
    name: str
    paid_hours: Decimal
    is_off_shift: bool
    start_time: time | None = None
    end_time: time | None = None
    metadata_json: JsonObject | None = None


@dataclass(slots=True)
class LeaveRequestInput:
    """Approved worker leave for a specific day inside the planning month."""

    worker_code: WorkerCode
    date: date
    leave_type: str


@dataclass(slots=True)
class AssignmentPatchInput:
    """Structured refine-layer adjustment that can overlay engine planning."""

    operation: str
    date: date
    worker_code: WorkerCode
    shift_code: ShiftCode | None = None
    station_code: StationCode | None = None
    note: str | None = None


@dataclass(slots=True)
class MonthPlanningInput:
    """Complete engine input for one tenant and one calendar month."""

    tenant_code: str
    year: int
    month: int
    workers: list[WorkerInput]
    stations: list[StationInput]
    shifts: list[ShiftInput]
    leave_requests: list[LeaveRequestInput]
    # Resolved full config for the target scope; service-layer code chooses it.
    constraint_config: JsonObject
    adjustment_patch: list[AssignmentPatchInput] | None = None


@dataclass(slots=True)
class AssignmentOutput:
    """One assignment emitted by the engine or later refinement layers."""

    date: date
    worker_code: WorkerCode
    shift_code: ShiftCode
    source: str
    station_code: StationCode | None = None
    note: str | None = None


@dataclass(slots=True)
class WarningOutput:
    """Structured planning warning that callers can map to UI or logs later."""

    type: str
    message_key: str
    worker_code: WorkerCode | None = None
    date: date | None = None
    details: JsonObject | None = None


@dataclass(slots=True)
class MonthPlanningSummary:
    """Small aggregate view for preview, review, export, and audit flows."""

    total_assignments: int
    total_warnings: int
    assignments_by_worker: dict[WorkerCode, int]
    paid_hours_by_worker: dict[WorkerCode, Decimal]
    warnings_by_type: dict[str, int]


@dataclass(slots=True)
class MonthPlanningEvaluation:
    """Minimal reviewer-facing evaluation summary for one candidate schedule."""

    duplicate_assignment_conflicts: int
    workspace_state_integrity_violations: int
    understaffed_station_days: int
    workers_below_min_days_off: int
    total_warnings: int
    warnings_by_type: dict[str, int]
    assignments_by_worker: dict[WorkerCode, int]
    paid_hours_by_worker: dict[WorkerCode, Decimal]
    max_minus_min_assignment_gap: int
    max_minus_min_paid_hours_gap: Decimal
    covered_station_days: int
    hard_constraints_passed: bool
    soft_warnings_present: bool
    schedule_quality_label: ScheduleQualityLabel


@dataclass(slots=True)
class MonthPlanningMetadata:
    """Execution metadata describing how the result payload was produced."""

    generated_at: datetime
    source_type: str
    refinement_applied: bool
    notes: list[str] | None = None


@dataclass(slots=True)
class MonthPlanningResult:
    """Top-level result returned by the monthly scheduling engine."""

    assignments: list[AssignmentOutput]
    warnings: list[WarningOutput]
    summary: MonthPlanningSummary
    metadata: MonthPlanningMetadata
    evaluation: MonthPlanningEvaluation | None = None


__all__ = [
    "AssignmentOutput",
    "AssignmentPatchInput",
    "JsonObject",
    "LeaveRequestInput",
    "MonthPlanningInput",
    "MonthPlanningEvaluation",
    "MonthPlanningMetadata",
    "MonthPlanningResult",
    "MonthPlanningSummary",
    "ScheduleQualityLabel",
    "ShiftCode",
    "ShiftInput",
    "StationCode",
    "StationInput",
    "WarningOutput",
    "WorkerCode",
    "WorkerInput",
]
