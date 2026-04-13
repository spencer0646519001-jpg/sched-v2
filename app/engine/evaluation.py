"""Minimal schedule-evaluation helpers for the first V2 scoring skeleton.

V0.1 intentionally keeps hard failures narrow:
- duplicate worker/day assignments
- explicit workspace-state integrity violations surfaced as warnings

Everything else is treated as a reviewer-facing quality signal rather than a
true engine rejection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from decimal import Decimal

from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningEvaluation,
    MonthPlanningResult,
    ScheduleQualityLabel,
    WarningOutput,
)

_WORKSPACE_STATE_INTEGRITY_WARNING_TYPES = frozenset(
    {
        "workspace_state_integrity_violation",
        "workspace_state_integrity_violations",
    }
)
_UNDERSTAFFED_WARNING_TYPES = frozenset(
    {
        "understaffed_station_day",
        "understaffed_station_days",
    }
)
_LOW_DAYS_OFF_WARNING_TYPES = frozenset(
    {
        "worker_below_min_days_off",
        "workers_below_min_days_off",
    }
)

# Placeholder v0.1 review thresholds. These are intentionally small, easy to
# explain, and not a final fairness policy.
_ASSIGNMENT_GAP_REVIEW_THRESHOLD = 1
_PAID_HOURS_GAP_REVIEW_THRESHOLD = Decimal("8")


def evaluate_month_planning_result(
    result: MonthPlanningResult,
) -> MonthPlanningEvaluation:
    """Build a small structured evaluation for one engine result envelope."""

    warnings_by_type = _coalesce_warnings_by_type(result)
    assignments_by_worker = _coalesce_assignments_by_worker(result)
    paid_hours_by_worker = dict(result.summary.paid_hours_by_worker)

    duplicate_assignment_conflicts = _count_duplicate_assignment_conflicts(
        result.assignments
    )
    workspace_state_integrity_violations = _count_warning_types(
        warnings_by_type,
        _WORKSPACE_STATE_INTEGRITY_WARNING_TYPES,
    )
    understaffed_station_days = _count_warning_types(
        warnings_by_type,
        _UNDERSTAFFED_WARNING_TYPES,
    )
    workers_below_min_days_off = _count_workers_below_min_days_off(
        result.warnings,
        warnings_by_type=warnings_by_type,
    )
    total_warnings = max(
        result.summary.total_warnings,
        len(result.warnings),
        sum(warnings_by_type.values()),
    )

    max_minus_min_assignment_gap = _max_minus_min_gap(assignments_by_worker.values())
    max_minus_min_paid_hours_gap = _max_minus_min_gap(paid_hours_by_worker.values())
    covered_station_days = len(
        {
            (assignment.date, assignment.station_code)
            for assignment in result.assignments
            if assignment.station_code is not None
        }
    )

    hard_constraints_passed = (
        duplicate_assignment_conflicts == 0
        and workspace_state_integrity_violations == 0
    )
    soft_warnings_present = (
        understaffed_station_days > 0
        or workers_below_min_days_off > 0
        or total_warnings > 0
        or max_minus_min_assignment_gap > _ASSIGNMENT_GAP_REVIEW_THRESHOLD
        or max_minus_min_paid_hours_gap > _PAID_HOURS_GAP_REVIEW_THRESHOLD
    )
    schedule_quality_label: ScheduleQualityLabel
    if not hard_constraints_passed:
        schedule_quality_label = "invalid"
    elif soft_warnings_present:
        schedule_quality_label = "needs_review"
    else:
        schedule_quality_label = "good"

    return MonthPlanningEvaluation(
        duplicate_assignment_conflicts=duplicate_assignment_conflicts,
        workspace_state_integrity_violations=workspace_state_integrity_violations,
        understaffed_station_days=understaffed_station_days,
        workers_below_min_days_off=workers_below_min_days_off,
        total_warnings=total_warnings,
        warnings_by_type=warnings_by_type,
        assignments_by_worker=assignments_by_worker,
        paid_hours_by_worker=paid_hours_by_worker,
        max_minus_min_assignment_gap=max_minus_min_assignment_gap,
        max_minus_min_paid_hours_gap=max_minus_min_paid_hours_gap,
        covered_station_days=covered_station_days,
        hard_constraints_passed=hard_constraints_passed,
        soft_warnings_present=soft_warnings_present,
        schedule_quality_label=schedule_quality_label,
    )


def attach_month_planning_evaluation(
    result: MonthPlanningResult,
) -> MonthPlanningResult:
    """Return a result envelope with the v0.1 evaluation attached."""

    return replace(result, evaluation=evaluate_month_planning_result(result))


def _coalesce_warnings_by_type(result: MonthPlanningResult) -> dict[str, int]:
    """Prefer explicit warning rows while tolerating precomputed summary counts."""

    warning_counts = Counter(warning.type for warning in result.warnings if warning.type)
    for warning_type, count in result.summary.warnings_by_type.items():
        warning_counts[warning_type] = max(warning_counts.get(warning_type, 0), count)
    return dict(warning_counts)


def _coalesce_assignments_by_worker(result: MonthPlanningResult) -> dict[str, int]:
    """Fall back to assignment rows when the summary map is still empty."""

    if result.summary.assignments_by_worker:
        return dict(result.summary.assignments_by_worker)

    assignment_counts = Counter(
        assignment.worker_code for assignment in result.assignments
    )
    return dict(assignment_counts)


def _count_duplicate_assignment_conflicts(
    assignments: list[AssignmentOutput],
) -> int:
    """Count worker/day groups with more than one assignment."""

    worker_day_counts = Counter(
        (assignment.date, assignment.worker_code) for assignment in assignments
    )
    return sum(1 for count in worker_day_counts.values() if count > 1)


def _count_warning_types(
    warnings_by_type: dict[str, int],
    warning_types: frozenset[str],
) -> int:
    """Sum warning counts across a small alias set used by the evaluator."""

    return sum(
        count
        for warning_type, count in warnings_by_type.items()
        if warning_type in warning_types
    )


def _count_workers_below_min_days_off(
    warnings: list[WarningOutput],
    *,
    warnings_by_type: dict[str, int],
) -> int:
    """Prefer distinct worker counts when warnings identify affected workers."""

    worker_codes = {
        warning.worker_code
        for warning in warnings
        if warning.type in _LOW_DAYS_OFF_WARNING_TYPES and warning.worker_code
    }
    if worker_codes:
        return len(worker_codes)
    return _count_warning_types(warnings_by_type, _LOW_DAYS_OFF_WARNING_TYPES)


def _max_minus_min_gap(values) -> int | Decimal:
    """Return zero for empty/singleton collections, else max minus min."""

    values = list(values)
    if len(values) < 2:
        return type(values[0])("0") if values else 0
    return max(values) - min(values)


__all__ = [
    "attach_month_planning_evaluation",
    "evaluate_month_planning_result",
]
