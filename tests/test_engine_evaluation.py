from __future__ import annotations

import datetime as dt
from collections import Counter
from decimal import Decimal

from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
    WarningOutput,
)
from app.engine.evaluation import evaluate_month_planning_result


def test_evaluator_marks_duplicate_assignment_conflicts_invalid() -> None:
    result = _build_result(
        assignments=[
            _assignment(dt.date(2026, 4, 1), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 1), worker_code="W1", station_code="FRY"),
        ],
        warnings=[],
    )

    evaluation = evaluate_month_planning_result(result)

    assert evaluation.duplicate_assignment_conflicts == 1
    assert evaluation.workspace_state_integrity_violations == 0
    assert evaluation.hard_constraints_passed is False
    assert evaluation.schedule_quality_label == "invalid"


def test_evaluator_keeps_understaffing_and_low_days_off_as_review_warnings() -> None:
    result = _build_result(
        assignments=[
            _assignment(dt.date(2026, 4, 1), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 1), worker_code="W2", station_code="FRY"),
        ],
        warnings=[
            _warning(
                "understaffed_station_day",
                warning_date=dt.date(2026, 4, 2),
            ),
            _warning(
                "worker_below_min_days_off",
                worker_code="W1",
                warning_date=dt.date(2026, 4, 3),
            ),
            _warning(
                "worker_below_min_days_off",
                worker_code="W1",
                warning_date=dt.date(2026, 4, 4),
            ),
        ],
        assignments_by_worker={"W1": 1, "W2": 1},
        paid_hours_by_worker={"W1": Decimal("8"), "W2": Decimal("8")},
    )

    evaluation = evaluate_month_planning_result(result)

    assert evaluation.understaffed_station_days == 1
    assert evaluation.workers_below_min_days_off == 1
    assert evaluation.total_warnings == 3
    assert evaluation.hard_constraints_passed is True
    assert evaluation.soft_warnings_present is True
    assert evaluation.schedule_quality_label == "needs_review"


def test_evaluator_marks_large_assignment_and_hours_gaps_for_review() -> None:
    result = _build_result(
        assignments=[
            _assignment(dt.date(2026, 4, 1), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 2), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 3), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 4), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 5), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 1), worker_code="W2", station_code="FRY"),
            _assignment(dt.date(2026, 4, 2), worker_code="W2", station_code="FRY"),
        ],
        warnings=[],
        assignments_by_worker={"W1": 5, "W2": 2},
        paid_hours_by_worker={"W1": Decimal("40"), "W2": Decimal("16")},
    )

    evaluation = evaluate_month_planning_result(result)

    assert evaluation.max_minus_min_assignment_gap == 3
    assert evaluation.max_minus_min_paid_hours_gap == Decimal("24")
    assert evaluation.soft_warnings_present is True
    assert evaluation.schedule_quality_label == "needs_review"


def test_evaluator_marks_explicit_workspace_integrity_violations_invalid() -> None:
    result = _build_result(
        assignments=[
            _assignment(dt.date(2026, 4, 1), worker_code="W1", station_code="GRILL"),
        ],
        warnings=[
            _warning(
                "workspace_state_integrity_violation",
                warning_date=dt.date(2026, 4, 1),
            )
        ],
    )

    evaluation = evaluate_month_planning_result(result)

    assert evaluation.workspace_state_integrity_violations == 1
    assert evaluation.hard_constraints_passed is False
    assert evaluation.schedule_quality_label == "invalid"


def test_evaluator_marks_balanced_clean_result_good() -> None:
    result = _build_result(
        assignments=[
            _assignment(dt.date(2026, 4, 1), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 1), worker_code="W2", station_code="FRY"),
            _assignment(dt.date(2026, 4, 2), worker_code="W1", station_code="GRILL"),
            _assignment(dt.date(2026, 4, 2), worker_code="W2", station_code="FRY"),
        ],
        warnings=[],
        assignments_by_worker={"W1": 2, "W2": 2},
        paid_hours_by_worker={"W1": Decimal("16"), "W2": Decimal("16")},
    )

    evaluation = evaluate_month_planning_result(result)

    assert evaluation.covered_station_days == 4
    assert evaluation.max_minus_min_assignment_gap == 0
    assert evaluation.max_minus_min_paid_hours_gap == Decimal("0")
    assert evaluation.hard_constraints_passed is True
    assert evaluation.soft_warnings_present is False
    assert evaluation.schedule_quality_label == "good"


def _build_result(
    *,
    assignments: list[AssignmentOutput],
    warnings: list[WarningOutput],
    assignments_by_worker: dict[str, int] | None = None,
    paid_hours_by_worker: dict[str, Decimal] | None = None,
) -> MonthPlanningResult:
    assignment_summary = assignments_by_worker or dict(
        Counter(assignment.worker_code for assignment in assignments)
    )
    warning_summary = dict(Counter(warning.type for warning in warnings))

    if paid_hours_by_worker is None:
        paid_hours_by_worker = {
            worker_code: Decimal(assignment_count * 8)
            for worker_code, assignment_count in assignment_summary.items()
        }

    return MonthPlanningResult(
        assignments=assignments,
        warnings=warnings,
        summary=MonthPlanningSummary(
            total_assignments=len(assignments),
            total_warnings=len(warnings),
            assignments_by_worker=assignment_summary,
            paid_hours_by_worker=paid_hours_by_worker,
            warnings_by_type=warning_summary,
        ),
        metadata=MonthPlanningMetadata(
            generated_at=dt.datetime(2026, 4, 13, tzinfo=dt.timezone.utc),
            source_type="preview",
            refinement_applied=False,
            notes=["evaluation-test"],
        ),
    )


def _assignment(
    assignment_date: dt.date,
    *,
    worker_code: str,
    station_code: str | None,
) -> AssignmentOutput:
    return AssignmentOutput(
        date=assignment_date,
        worker_code=worker_code,
        shift_code="DAY",
        station_code=station_code,
        source="preview",
        note=None,
    )


def _warning(
    warning_type: str,
    *,
    worker_code: str | None = None,
    warning_date: dt.date | None = None,
) -> WarningOutput:
    return WarningOutput(
        type=warning_type,
        message_key=warning_type,
        worker_code=worker_code,
        date=warning_date,
        details=None,
    )
