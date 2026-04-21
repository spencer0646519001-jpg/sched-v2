"""Offline monthly parity evaluation helpers.

This module is intentionally narrow:
- pure, deterministic metric calculation only
- no file I/O
- no sched-mvp imports
- no scheduling behavior changes

It compares a normalized baseline snapshot against a normalized candidate
snapshot built from the current V2 month-planning result.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections import Counter
from dataclasses import dataclass

from app.engine.contracts import MonthPlanningInput, MonthPlanningResult


@dataclass(frozen=True, slots=True)
class MonthlyParityAssignment:
    """One normalized assignment row used by offline parity evaluation."""

    date: dt.date
    worker_code: str
    shift_code: str
    station_code: str | None = None


@dataclass(frozen=True, slots=True)
class MonthlyParityWarning:
    """One normalized warning row used by offline parity evaluation."""

    type: str
    date: dt.date | None = None
    worker_code: str | None = None


@dataclass(frozen=True, slots=True)
class MonthlyParitySnapshot:
    """Normalized monthly snapshot for one engine/baseline output."""

    assignments: tuple[MonthlyParityAssignment, ...]
    warnings: tuple[MonthlyParityWarning, ...]


@dataclass(frozen=True, slots=True)
class MonthlyParityContext:
    """Static month context required to score comparable parity metrics."""

    fixture_id: str
    year: int
    month: int
    worker_codes: tuple[str, ...]
    worker_skills_by_code: dict[str, frozenset[str]]
    worker_hard_unavailable_dates_by_code: dict[str, frozenset[dt.date]]
    station_codes: tuple[str, ...]
    month_dates: tuple[dt.date, ...]


@dataclass(frozen=True, slots=True)
class MonthlyParityMetrics:
    """Stable aggregate metrics used for baseline/candidate comparisons."""

    total_assignments: int
    shift_histogram: dict[str, int]
    off_skill_assignment_count: int
    station_day_coverage_counts: dict[str, dict[int, int]]
    warning_counts_by_type: dict[str, int]
    per_worker_assignment_totals: dict[str, int]
    worker_profile_hard_conflict_count: int


@dataclass(frozen=True, slots=True)
class MonthlyParityMetricDeltas:
    """Candidate-minus-baseline deltas for the parity metrics."""

    total_assignments: int
    shift_histogram: dict[str, int]
    off_skill_assignment_count: int
    station_day_coverage_counts: dict[str, dict[int, int]]
    warning_counts_by_type: dict[str, int]
    per_worker_assignment_totals: dict[str, int]
    worker_profile_hard_conflict_count: int


@dataclass(frozen=True, slots=True)
class MonthlyParityReport:
    """Offline parity report for one frozen month fixture."""

    fixture_id: str
    year: int
    month: int
    baseline_metrics: MonthlyParityMetrics
    candidate_metrics: MonthlyParityMetrics
    metric_deltas: MonthlyParityMetricDeltas
    baseline_assignment_count: int
    candidate_assignment_count: int
    baseline_warning_count: int
    candidate_warning_count: int


def build_monthly_parity_context(
    planning_input: MonthPlanningInput,
    *,
    fixture_id: str,
) -> MonthlyParityContext:
    """Build the static month context from one normalized planning input."""

    active_workers = sorted(
        (worker for worker in planning_input.workers if worker.is_active),
        key=lambda worker: worker.worker_code,
    )
    active_stations = sorted(
        station.station_code
        for station in planning_input.stations
        if station.is_active
    )
    month_dates = tuple(_iter_month_dates(planning_input.year, planning_input.month))
    month_date_set = set(month_dates)

    return MonthlyParityContext(
        fixture_id=fixture_id,
        year=planning_input.year,
        month=planning_input.month,
        worker_codes=tuple(worker.worker_code for worker in active_workers),
        worker_skills_by_code={
            worker.worker_code: frozenset(worker.station_skills)
            for worker in active_workers
        },
        worker_hard_unavailable_dates_by_code={
            worker.worker_code: _build_worker_hard_unavailable_dates(
                worker,
                month_dates=month_date_set,
            )
            for worker in active_workers
        },
        station_codes=tuple(active_stations),
        month_dates=month_dates,
    )


def snapshot_month_planning_result(
    result: MonthPlanningResult,
) -> MonthlyParitySnapshot:
    """Normalize one V2 month-planning result into parity rows."""

    assignments = tuple(
        MonthlyParityAssignment(
            date=assignment.date,
            worker_code=assignment.worker_code,
            shift_code=assignment.shift_code,
            station_code=assignment.station_code,
        )
        for assignment in result.assignments
    )
    warnings = tuple(
        MonthlyParityWarning(
            type=warning.type,
            date=warning.date,
            worker_code=warning.worker_code,
        )
        for warning in result.warnings
    )
    return MonthlyParitySnapshot(assignments=assignments, warnings=warnings)


def calculate_monthly_parity_metrics(
    context: MonthlyParityContext,
    snapshot: MonthlyParitySnapshot,
) -> MonthlyParityMetrics:
    """Calculate stable aggregate parity metrics for one normalized snapshot."""

    _validate_snapshot(context, snapshot)

    shift_histogram = dict(
        sorted(
            Counter(assignment.shift_code for assignment in snapshot.assignments).items()
        )
    )
    warning_counts_by_type = dict(
        sorted(Counter(warning.type for warning in snapshot.warnings).items())
    )

    worker_assignment_counts = Counter(
        assignment.worker_code for assignment in snapshot.assignments
    )
    per_worker_assignment_totals = {
        worker_code: worker_assignment_counts.get(worker_code, 0)
        for worker_code in context.worker_codes
    }

    assignments_per_station_day = Counter(
        (assignment.date, assignment.station_code)
        for assignment in snapshot.assignments
        if assignment.station_code is not None
    )
    station_day_coverage_counts: dict[str, dict[int, int]] = {}
    for station_code in context.station_codes:
        coverage_counts: Counter[int] = Counter()
        for month_date in context.month_dates:
            coverage_counts[assignments_per_station_day.get((month_date, station_code), 0)] += 1
        station_day_coverage_counts[station_code] = dict(
            sorted(coverage_counts.items())
        )

    off_skill_assignment_count = sum(
        1
        for assignment in snapshot.assignments
        if assignment.station_code is not None
        and assignment.station_code
        not in context.worker_skills_by_code[assignment.worker_code]
    )
    worker_profile_hard_conflict_count = sum(
        1
        for assignment in snapshot.assignments
        if assignment.date
        in context.worker_hard_unavailable_dates_by_code[assignment.worker_code]
    )

    return MonthlyParityMetrics(
        total_assignments=len(snapshot.assignments),
        shift_histogram=shift_histogram,
        off_skill_assignment_count=off_skill_assignment_count,
        station_day_coverage_counts=station_day_coverage_counts,
        warning_counts_by_type=warning_counts_by_type,
        per_worker_assignment_totals=per_worker_assignment_totals,
        worker_profile_hard_conflict_count=worker_profile_hard_conflict_count,
    )


def evaluate_monthly_parity(
    context: MonthlyParityContext,
    *,
    baseline_snapshot: MonthlyParitySnapshot,
    candidate_snapshot: MonthlyParitySnapshot,
) -> MonthlyParityReport:
    """Compare a frozen baseline snapshot against the current candidate."""

    baseline_metrics = calculate_monthly_parity_metrics(context, baseline_snapshot)
    candidate_metrics = calculate_monthly_parity_metrics(context, candidate_snapshot)

    return MonthlyParityReport(
        fixture_id=context.fixture_id,
        year=context.year,
        month=context.month,
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        metric_deltas=MonthlyParityMetricDeltas(
            total_assignments=(
                candidate_metrics.total_assignments - baseline_metrics.total_assignments
            ),
            shift_histogram=_subtract_flat_counts(
                baseline_metrics.shift_histogram,
                candidate_metrics.shift_histogram,
            ),
            off_skill_assignment_count=(
                candidate_metrics.off_skill_assignment_count
                - baseline_metrics.off_skill_assignment_count
            ),
            station_day_coverage_counts=_subtract_nested_counts(
                baseline_metrics.station_day_coverage_counts,
                candidate_metrics.station_day_coverage_counts,
            ),
            warning_counts_by_type=_subtract_flat_counts(
                baseline_metrics.warning_counts_by_type,
                candidate_metrics.warning_counts_by_type,
            ),
            per_worker_assignment_totals=_subtract_flat_counts(
                baseline_metrics.per_worker_assignment_totals,
                candidate_metrics.per_worker_assignment_totals,
            ),
            worker_profile_hard_conflict_count=(
                candidate_metrics.worker_profile_hard_conflict_count
                - baseline_metrics.worker_profile_hard_conflict_count
            ),
        ),
        baseline_assignment_count=len(baseline_snapshot.assignments),
        candidate_assignment_count=len(candidate_snapshot.assignments),
        baseline_warning_count=len(baseline_snapshot.warnings),
        candidate_warning_count=len(candidate_snapshot.warnings),
    )


def _validate_snapshot(
    context: MonthlyParityContext,
    snapshot: MonthlyParitySnapshot,
) -> None:
    month_dates = set(context.month_dates)
    worker_codes = set(context.worker_codes)
    station_codes = set(context.station_codes)

    for assignment in snapshot.assignments:
        if assignment.date not in month_dates:
            raise ValueError(
                f"Assignment date {assignment.date.isoformat()} falls outside the "
                f"frozen month {context.year}-{context.month:02d}."
            )
        if assignment.worker_code not in worker_codes:
            raise ValueError(
                f"Unknown worker_code in parity snapshot: {assignment.worker_code!r}."
            )
        if not assignment.shift_code.strip():
            raise ValueError("Parity assignments require a non-blank shift_code.")
        if (
            assignment.station_code is not None
            and assignment.station_code not in station_codes
        ):
            raise ValueError(
                f"Unknown station_code in parity snapshot: {assignment.station_code!r}."
            )

    for warning in snapshot.warnings:
        if warning.date is not None and warning.date not in month_dates:
            raise ValueError(
                f"Warning date {warning.date.isoformat()} falls outside the "
                f"frozen month {context.year}-{context.month:02d}."
            )
        if warning.worker_code is not None and warning.worker_code not in worker_codes:
            raise ValueError(
                f"Unknown warning worker_code in parity snapshot: "
                f"{warning.worker_code!r}."
            )
        if not warning.type.strip():
            raise ValueError("Parity warnings require a non-blank type.")


def _subtract_flat_counts(
    baseline_counts: dict[str, int],
    candidate_counts: dict[str, int],
) -> dict[str, int]:
    all_keys = sorted(set(baseline_counts) | set(candidate_counts))
    return {
        key: candidate_counts.get(key, 0) - baseline_counts.get(key, 0)
        for key in all_keys
    }


def _subtract_nested_counts(
    baseline_counts: dict[str, dict[int, int]],
    candidate_counts: dict[str, dict[int, int]],
) -> dict[str, dict[int, int]]:
    nested_deltas: dict[str, dict[int, int]] = {}
    for outer_key in sorted(set(baseline_counts) | set(candidate_counts)):
        baseline_nested = baseline_counts.get(outer_key, {})
        candidate_nested = candidate_counts.get(outer_key, {})
        all_nested_keys = sorted(set(baseline_nested) | set(candidate_nested))
        nested_deltas[outer_key] = {
            nested_key: candidate_nested.get(nested_key, 0)
            - baseline_nested.get(nested_key, 0)
            for nested_key in all_nested_keys
        }
    return nested_deltas


def _iter_month_dates(year: int, month: int) -> list[dt.date]:
    days_in_month = calendar.monthrange(year, month)[1]
    return [
        dt.date(year, month, day_number)
        for day_number in range(1, days_in_month + 1)
    ]


def _build_worker_hard_unavailable_dates(
    worker,
    *,
    month_dates: set[dt.date],
) -> frozenset[dt.date]:
    scheduling_profile = worker.scheduling_profile
    blocked_dates = {
        *scheduling_profile.ad_hoc_unavailable,
        *scheduling_profile.wish_off.hard,
    }
    blocked_dates.update(
        month_date
        for month_date in month_dates
        if month_date.weekday() in scheduling_profile.fixed_day_off_weekdays
    )
    return frozenset(month_date for month_date in blocked_dates if month_date in month_dates)


__all__ = [
    "MonthlyParityAssignment",
    "MonthlyParityContext",
    "MonthlyParityMetricDeltas",
    "MonthlyParityMetrics",
    "MonthlyParityReport",
    "MonthlyParitySnapshot",
    "MonthlyParityWarning",
    "build_monthly_parity_context",
    "calculate_monthly_parity_metrics",
    "evaluate_monthly_parity",
    "snapshot_month_planning_result",
]
