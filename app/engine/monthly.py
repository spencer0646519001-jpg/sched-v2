"""Deterministic month planner for the first real V2 engine baseline.

The planner intentionally stays small and explicit:
- pure-function only, consuming validated dataclass inputs
- deterministic worker, station, and shift ordering
- narrow v0.1 config support for daily staffing and simple rest limits
- small post-baseline adjustment patch overlay
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.engine.contracts import (
    AssignmentOutput,
    AssignmentPatchInput,
    MonthPlanningInput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
    ShiftInput,
    WarningOutput,
    WorkerInput,
)
from app.engine.evaluation import attach_month_planning_evaluation
from app.engine.validators import validate_month_planning_input

_SOURCE_TYPE = "monthly_planner"
_BASELINE_NOTE = "engine_v0_1_baseline"
_PATCH_APPLIED_NOTE = "adjustment_patch_applied"
_DEFAULT_STATION_NOTE = "default_station_coverage"
_INACTIVE_PATCH_NOTE = "inactive_worker_patch_ignored"
_UNSUPPORTED_PATCH_NOTE = "unsupported_adjustment_patch_ignored"
_MISSING_SHIFT_PATCH_NOTE = "adjustment_patch_missing_shift_ignored"

_PATCH_SET_OPERATIONS = frozenset({"set", "replace"})
_PATCH_REMOVE_OPERATIONS = frozenset({"remove", "delete", "unset"})


@dataclass(frozen=True, slots=True)
class _PlannerSettings:
    station_minimums: dict[str, int]
    min_staff_weekday: int | None
    min_staff_weekend: int | None
    max_staff_per_day: int | None
    min_rest_days_per_month: int | None
    max_consecutive_days: int | None


def generate_month_plan(planning_input: MonthPlanningInput) -> MonthPlanningResult:
    """Generate one deterministic monthly plan from normalized engine input."""

    planning_input = validate_month_planning_input(planning_input)

    active_workers = sorted(
        (worker for worker in planning_input.workers if worker.is_active),
        key=lambda worker: worker.worker_code,
    )
    active_worker_codes = {worker.worker_code for worker in active_workers}
    active_station_codes = sorted(
        station.station_code
        for station in planning_input.stations
        if station.is_active
    )
    shifts_by_code = {
        shift.shift_code: shift for shift in planning_input.shifts
    }
    working_shifts = sorted(
        (shift for shift in planning_input.shifts if not shift.is_off_shift),
        key=lambda shift: shift.shift_code,
    )
    primary_shift = working_shifts[0] if working_shifts else None
    leave_dates_by_worker = _build_leave_dates_by_worker(planning_input)
    settings = _build_planner_settings(
        planning_input.constraint_config,
        active_station_codes=active_station_codes,
    )

    notes = {_BASELINE_NOTE}
    if not settings.station_minimums and active_station_codes:
        notes.add(_DEFAULT_STATION_NOTE)

    assignments, warnings = _build_baseline_assignments(
        planning_input=planning_input,
        active_workers=active_workers,
        active_station_codes=active_station_codes,
        primary_shift=primary_shift,
        leave_dates_by_worker=leave_dates_by_worker,
        settings=settings,
    )

    if planning_input.adjustment_patch:
        notes.add(_PATCH_APPLIED_NOTE)
        assignments, patch_warnings, patch_notes = _apply_adjustment_patch(
            assignments,
            adjustment_patch=planning_input.adjustment_patch,
            active_worker_codes=active_worker_codes,
            active_station_codes=active_station_codes,
            leave_dates_by_worker=leave_dates_by_worker,
            primary_shift=primary_shift,
            shifts_by_code=shifts_by_code,
        )
        warnings.extend(patch_warnings)
        notes.update(patch_notes)

    warnings.extend(
        _build_min_days_off_warnings(
            assignments,
            active_workers=active_workers,
            shifts_by_code=shifts_by_code,
            year=planning_input.year,
            month=planning_input.month,
            min_rest_days_per_month=settings.min_rest_days_per_month,
        )
    )

    assignments = _sort_assignments(assignments)
    warnings = _sort_warnings(warnings)
    summary = _build_summary(
        assignments,
        warnings=warnings,
        active_workers=active_workers,
        shifts_by_code=shifts_by_code,
    )

    result = MonthPlanningResult(
        assignments=assignments,
        warnings=warnings,
        summary=summary,
        metadata=MonthPlanningMetadata(
            generated_at=dt.datetime(
                planning_input.year,
                planning_input.month,
                1,
                tzinfo=dt.timezone.utc,
            ),
            source_type=_SOURCE_TYPE,
            refinement_applied=bool(planning_input.adjustment_patch),
            notes=sorted(notes) or None,
        ),
    )
    return attach_month_planning_evaluation(result)


def _build_planner_settings(
    constraint_config: dict[str, object],
    *,
    active_station_codes: list[str],
) -> _PlannerSettings:
    return _PlannerSettings(
        station_minimums=_resolve_station_minimums(
            constraint_config.get("stations"),
            active_station_codes=active_station_codes,
        ),
        min_staff_weekday=_coerce_non_negative_int(
            constraint_config.get("min_staff_weekday")
        ),
        min_staff_weekend=_coerce_non_negative_int(
            constraint_config.get("min_staff_weekend")
        ),
        max_staff_per_day=_coerce_non_negative_int(
            constraint_config.get("max_staff_per_day")
        ),
        min_rest_days_per_month=_coerce_non_negative_int(
            constraint_config.get("min_rest_days_per_month")
        ),
        max_consecutive_days=_coerce_non_negative_int(
            constraint_config.get("max_consecutive_days")
        ),
    )


def _build_baseline_assignments(
    *,
    planning_input: MonthPlanningInput,
    active_workers: list[WorkerInput],
    active_station_codes: list[str],
    primary_shift: ShiftInput | None,
    leave_dates_by_worker: dict[str, set[dt.date]],
    settings: _PlannerSettings,
) -> tuple[list[AssignmentOutput], list[WarningOutput]]:
    assignments: list[AssignmentOutput] = []
    warnings: list[WarningOutput] = []

    assignment_counts = {
        worker.worker_code: 0 for worker in active_workers
    }
    assigned_dates_by_worker = {
        worker.worker_code: set() for worker in active_workers
    }

    for assignment_date in _iter_month_dates(planning_input.year, planning_input.month):
        required_station_slots = _build_required_station_slots(
            assignment_date,
            active_station_codes=active_station_codes,
            settings=settings,
        )
        fillable_station_slots = list(required_station_slots)
        if settings.max_staff_per_day is not None:
            fillable_station_slots = fillable_station_slots[
                : settings.max_staff_per_day
            ]
        if primary_shift is None or not active_station_codes:
            fillable_station_slots = []

        assigned_today: set[str] = set()
        assigned_station_counts: Counter[str] = Counter()

        for station_code in fillable_station_slots:
            worker = _select_worker_for_station_slot(
                assignment_date,
                station_code=station_code,
                active_workers=active_workers,
                assigned_today=assigned_today,
                assignment_counts=assignment_counts,
                assigned_dates_by_worker=assigned_dates_by_worker,
                leave_dates_by_worker=leave_dates_by_worker,
                max_consecutive_days=settings.max_consecutive_days,
            )
            if worker is None or primary_shift is None:
                continue

            assignments.append(
                AssignmentOutput(
                    date=assignment_date,
                    worker_code=worker.worker_code,
                    shift_code=primary_shift.shift_code,
                    source=_SOURCE_TYPE,
                    station_code=station_code,
                    note=None,
                )
            )
            assigned_today.add(worker.worker_code)
            assigned_station_counts[station_code] += 1
            assignment_counts[worker.worker_code] += 1
            assigned_dates_by_worker[worker.worker_code].add(assignment_date)

        warnings.extend(
            _build_understaffed_station_warnings(
                assignment_date,
                required_station_slots=required_station_slots,
                assigned_station_counts=assigned_station_counts,
            )
        )

    return assignments, warnings


def _build_required_station_slots(
    assignment_date: dt.date,
    *,
    active_station_codes: list[str],
    settings: _PlannerSettings,
) -> list[str]:
    if not active_station_codes:
        return []

    target_headcount = _resolve_daily_minimum_staff(
        assignment_date,
        min_staff_weekday=settings.min_staff_weekday,
        min_staff_weekend=settings.min_staff_weekend,
    )

    if settings.station_minimums:
        station_slots = [
            station_code
            for station_code in active_station_codes
            for _ in range(settings.station_minimums.get(station_code, 0))
        ]
        if target_headcount > len(station_slots):
            station_index = 0
            while len(station_slots) < target_headcount:
                station_slots.append(
                    active_station_codes[
                        station_index % len(active_station_codes)
                    ]
                )
                station_index += 1
        return station_slots

    default_target = target_headcount if target_headcount > 0 else 1
    return [active_station_codes[0]] * default_target


def _resolve_daily_minimum_staff(
    assignment_date: dt.date,
    *,
    min_staff_weekday: int | None,
    min_staff_weekend: int | None,
) -> int:
    if assignment_date.weekday() >= 5:
        return min_staff_weekend or 0
    return min_staff_weekday or 0


def _select_worker_for_station_slot(
    assignment_date: dt.date,
    *,
    station_code: str,
    active_workers: list[WorkerInput],
    assigned_today: set[str],
    assignment_counts: dict[str, int],
    assigned_dates_by_worker: dict[str, set[dt.date]],
    leave_dates_by_worker: dict[str, set[dt.date]],
    max_consecutive_days: int | None,
) -> WorkerInput | None:
    candidates = [
        worker
        for worker in active_workers
        if worker.worker_code not in assigned_today
        and assignment_date
        not in leave_dates_by_worker.get(worker.worker_code, set())
        and not _has_reached_consecutive_limit(
            assignment_date,
            assigned_dates=assigned_dates_by_worker[worker.worker_code],
            max_consecutive_days=max_consecutive_days,
        )
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda worker: (
            0 if station_code in worker.station_skills else 1,
            assignment_counts[worker.worker_code],
            _current_consecutive_streak(
                assignment_date,
                assigned_dates_by_worker[worker.worker_code],
            ),
            worker.worker_code,
        )
    )
    return candidates[0]


def _has_reached_consecutive_limit(
    assignment_date: dt.date,
    *,
    assigned_dates: set[dt.date],
    max_consecutive_days: int | None,
) -> bool:
    if max_consecutive_days is None or max_consecutive_days <= 0:
        return False
    return (
        _current_consecutive_streak(assignment_date, assigned_dates)
        >= max_consecutive_days
    )


def _current_consecutive_streak(
    assignment_date: dt.date,
    assigned_dates: set[dt.date],
) -> int:
    streak = 0
    current_date = assignment_date - dt.timedelta(days=1)
    while current_date in assigned_dates:
        streak += 1
        current_date -= dt.timedelta(days=1)
    return streak


def _build_understaffed_station_warnings(
    assignment_date: dt.date,
    *,
    required_station_slots: list[str],
    assigned_station_counts: Counter[str],
) -> list[WarningOutput]:
    warnings: list[WarningOutput] = []
    required_station_counts = Counter(required_station_slots)
    for station_code in sorted(required_station_counts):
        required_staff = required_station_counts[station_code]
        assigned_staff = assigned_station_counts.get(station_code, 0)
        if assigned_staff >= required_staff:
            continue
        warnings.append(
            WarningOutput(
                type="understaffed_station_day",
                message_key="understaffed_station",
                worker_code=None,
                date=assignment_date,
                details={
                    "station_code": station_code,
                    "required_staff": required_staff,
                    "assigned_staff": assigned_staff,
                    "missing_staff": required_staff - assigned_staff,
                },
            )
        )
    return warnings


def _apply_adjustment_patch(
    assignments: list[AssignmentOutput],
    *,
    adjustment_patch: list[AssignmentPatchInput],
    active_worker_codes: set[str],
    active_station_codes: list[str],
    leave_dates_by_worker: dict[str, set[dt.date]],
    primary_shift: ShiftInput | None,
    shifts_by_code: dict[str, ShiftInput],
) -> tuple[list[AssignmentOutput], list[WarningOutput], set[str]]:
    updated_assignments = list(assignments)
    warnings: list[WarningOutput] = []
    notes: set[str] = set()

    for patch in adjustment_patch:
        operation = patch.operation.strip().lower()
        assignment_key = (patch.date, patch.worker_code)
        existing_assignments = [
            assignment
            for assignment in updated_assignments
            if (assignment.date, assignment.worker_code) == assignment_key
        ]

        if patch.worker_code not in active_worker_codes:
            notes.add(_INACTIVE_PATCH_NOTE)
            continue

        if operation in _PATCH_REMOVE_OPERATIONS:
            if len(existing_assignments) > 1:
                warnings.append(
                    _build_duplicate_assignment_warning(
                        patch,
                        assignment_count=len(existing_assignments),
                    )
                )
            updated_assignments = [
                assignment
                for assignment in updated_assignments
                if (assignment.date, assignment.worker_code) != assignment_key
            ]
            continue

        if operation not in _PATCH_SET_OPERATIONS:
            notes.add(_UNSUPPORTED_PATCH_NOTE)
            continue

        if patch.date in leave_dates_by_worker.get(patch.worker_code, set()):
            warnings.append(
                WarningOutput(
                    type="worker_on_leave_conflict",
                    message_key="worker_on_leave_conflict",
                    worker_code=patch.worker_code,
                    date=patch.date,
                    details={
                        "operation": operation,
                        "shift_code": patch.shift_code,
                        "station_code": patch.station_code,
                    },
                )
            )
            continue

        shift_code = _resolve_patch_shift_code(
            patch,
            existing_assignments=existing_assignments,
            primary_shift=primary_shift,
        )
        if shift_code is None:
            notes.add(_MISSING_SHIFT_PATCH_NOTE)
            continue

        if len(existing_assignments) > 1:
            warnings.append(
                _build_duplicate_assignment_warning(
                    patch,
                    assignment_count=len(existing_assignments),
                )
            )
        updated_assignments = [
            assignment
            for assignment in updated_assignments
            if (assignment.date, assignment.worker_code) != assignment_key
        ]

        station_code = _resolve_patch_station_code(
            patch,
            existing_assignments=existing_assignments,
            active_station_codes=active_station_codes,
        )
        shift = shifts_by_code[shift_code]
        if shift.is_off_shift:
            station_code = None

        updated_assignments.append(
            AssignmentOutput(
                date=patch.date,
                worker_code=patch.worker_code,
                shift_code=shift_code,
                source="adjustment_patch",
                station_code=station_code,
                note=patch.note,
            )
        )

    return updated_assignments, warnings, notes


def _resolve_patch_shift_code(
    patch: AssignmentPatchInput,
    *,
    existing_assignments: list[AssignmentOutput],
    primary_shift: ShiftInput | None,
) -> str | None:
    if patch.shift_code is not None:
        return patch.shift_code
    if existing_assignments:
        return existing_assignments[0].shift_code
    if primary_shift is not None:
        return primary_shift.shift_code
    return None


def _resolve_patch_station_code(
    patch: AssignmentPatchInput,
    *,
    existing_assignments: list[AssignmentOutput],
    active_station_codes: list[str],
) -> str | None:
    if patch.station_code is not None:
        return patch.station_code
    if existing_assignments:
        return existing_assignments[0].station_code
    if active_station_codes:
        return active_station_codes[0]
    return None


def _build_duplicate_assignment_warning(
    patch: AssignmentPatchInput,
    *,
    assignment_count: int,
) -> WarningOutput:
    return WarningOutput(
        type="duplicate_assignment_conflict",
        message_key="duplicate_assignment_conflict",
        worker_code=patch.worker_code,
        date=patch.date,
        details={
            "operation": patch.operation,
            "assignment_count": assignment_count,
        },
    )


def _build_min_days_off_warnings(
    assignments: list[AssignmentOutput],
    *,
    active_workers: list[WorkerInput],
    shifts_by_code: dict[str, ShiftInput],
    year: int,
    month: int,
    min_rest_days_per_month: int | None,
) -> list[WarningOutput]:
    if min_rest_days_per_month is None:
        return []

    worked_dates_by_worker = {
        worker.worker_code: set() for worker in active_workers
    }
    for assignment in assignments:
        shift = shifts_by_code[assignment.shift_code]
        if shift.is_off_shift:
            continue
        worker_dates = worked_dates_by_worker.get(assignment.worker_code)
        if worker_dates is not None:
            worker_dates.add(assignment.date)

    days_in_month = calendar.monthrange(year, month)[1]
    warnings: list[WarningOutput] = []
    for worker in active_workers:
        actual_days_off = days_in_month - len(
            worked_dates_by_worker[worker.worker_code]
        )
        if actual_days_off >= min_rest_days_per_month:
            continue
        warnings.append(
            WarningOutput(
                type="worker_below_min_days_off",
                message_key="worker_below_min_days_off",
                worker_code=worker.worker_code,
                date=None,
                details={
                    "minimum_days_off": min_rest_days_per_month,
                    "actual_days_off": actual_days_off,
                },
            )
        )
    return warnings


def _build_summary(
    assignments: list[AssignmentOutput],
    *,
    warnings: list[WarningOutput],
    active_workers: list[WorkerInput],
    shifts_by_code: dict[str, ShiftInput],
) -> MonthPlanningSummary:
    assignment_counts = Counter(
        assignment.worker_code for assignment in assignments
    )
    assignments_by_worker = {
        worker.worker_code: assignment_counts.get(worker.worker_code, 0)
        for worker in active_workers
    }

    paid_hours_by_worker = {
        worker.worker_code: Decimal("0") for worker in active_workers
    }
    for assignment in assignments:
        shift = shifts_by_code[assignment.shift_code]
        paid_hours_by_worker[assignment.worker_code] = (
            paid_hours_by_worker.get(assignment.worker_code, Decimal("0"))
            + shift.paid_hours
        )

    return MonthPlanningSummary(
        total_assignments=len(assignments),
        total_warnings=len(warnings),
        assignments_by_worker=assignments_by_worker,
        paid_hours_by_worker=paid_hours_by_worker,
        warnings_by_type=dict(Counter(warning.type for warning in warnings)),
    )


def _build_leave_dates_by_worker(
    planning_input: MonthPlanningInput,
) -> dict[str, set[dt.date]]:
    leave_dates_by_worker: dict[str, set[dt.date]] = {}
    for leave_request in planning_input.leave_requests:
        leave_dates_by_worker.setdefault(leave_request.worker_code, set()).add(
            leave_request.date
        )
    return leave_dates_by_worker


def _resolve_station_minimums(
    raw_stations_config: object,
    *,
    active_station_codes: list[str],
) -> dict[str, int]:
    if not isinstance(raw_stations_config, dict):
        return {}

    station_minimums: dict[str, int] = {}
    for station_code in active_station_codes:
        raw_value = raw_stations_config.get(station_code)
        minimum = _coerce_non_negative_int(raw_value)
        if minimum is None and isinstance(raw_value, dict):
            minimum = _coerce_non_negative_int(raw_value.get("min_staff"))
        if minimum is None or minimum <= 0:
            continue
        station_minimums[station_code] = minimum
    return station_minimums


def _coerce_non_negative_int(raw_value: object) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value if raw_value >= 0 else None
    if isinstance(raw_value, float) and raw_value.is_integer():
        return int(raw_value) if raw_value >= 0 else None
    return None


def _iter_month_dates(year: int, month: int) -> list[dt.date]:
    days_in_month = calendar.monthrange(year, month)[1]
    return [
        dt.date(year, month, day_number)
        for day_number in range(1, days_in_month + 1)
    ]


def _sort_assignments(
    assignments: list[AssignmentOutput],
) -> list[AssignmentOutput]:
    return sorted(
        assignments,
        key=lambda assignment: (
            assignment.date,
            assignment.worker_code,
            assignment.station_code or "",
            assignment.shift_code,
            assignment.source,
            assignment.note or "",
        ),
    )


def _sort_warnings(
    warnings: list[WarningOutput],
) -> list[WarningOutput]:
    max_date = dt.date.max
    return sorted(
        warnings,
        key=lambda warning: (
            warning.date or max_date,
            warning.type,
            warning.worker_code or "",
            warning.message_key,
        ),
    )


__all__ = ["generate_month_plan"]
