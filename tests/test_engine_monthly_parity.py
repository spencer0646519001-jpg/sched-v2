from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from app.engine.contracts import (
    LeaveRequestInput,
    MonthPlanningInput,
    ShiftInput,
    StationInput,
    WorkerInput,
)
from app.engine.monthly import generate_month_plan
from app.engine.monthly_parity import (
    MonthlyParityAssignment,
    MonthlyParitySnapshot,
    MonthlyParityWarning,
    build_monthly_parity_context,
    calculate_monthly_parity_metrics,
    evaluate_monthly_parity,
    snapshot_month_planning_result,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "monthly_parity"
    / "shared_demo_april_2026"
)


def test_calculate_monthly_parity_metrics_reports_requested_aggregates() -> None:
    planning_input = MonthPlanningInput(
        tenant_code="tenant-a",
        year=2026,
        month=4,
        workers=[
            WorkerInput(
                worker_code="W1",
                name="Alex",
                role="employee",
                is_active=True,
                station_skills=["GRILL"],
            ),
            WorkerInput(
                worker_code="W2",
                name="Casey",
                role="employee",
                is_active=True,
                station_skills=["GRILL", "FRY"],
            ),
        ],
        stations=[
            StationInput(station_code="GRILL", name="Grill", is_active=True),
            StationInput(station_code="FRY", name="Fry", is_active=True),
        ],
        shifts=[
            ShiftInput(
                shift_code="DAY",
                name="Day",
                paid_hours=Decimal("8"),
                is_off_shift=False,
            ),
            ShiftInput(
                shift_code="EVE",
                name="Evening",
                paid_hours=Decimal("6"),
                is_off_shift=False,
            ),
        ],
        leave_requests=[],
        constraint_config={},
        adjustment_patch=None,
    )
    context = build_monthly_parity_context(
        planning_input,
        fixture_id="unit_fixture",
    )
    snapshot = MonthlyParitySnapshot(
        assignments=(
            MonthlyParityAssignment(
                date=dt.date(2026, 4, 1),
                worker_code="W1",
                shift_code="DAY",
                station_code="GRILL",
            ),
            MonthlyParityAssignment(
                date=dt.date(2026, 4, 1),
                worker_code="W2",
                shift_code="EVE",
                station_code="GRILL",
            ),
            MonthlyParityAssignment(
                date=dt.date(2026, 4, 2),
                worker_code="W1",
                shift_code="DAY",
                station_code="FRY",
            ),
        ),
        warnings=(
            MonthlyParityWarning(
                type="understaffed_station_day",
                date=dt.date(2026, 4, 1),
            ),
            MonthlyParityWarning(
                type="understaffed_station_day",
                date=dt.date(2026, 4, 2),
            ),
            MonthlyParityWarning(type="weekly_rest", worker_code="W1"),
        ),
    )

    metrics = calculate_monthly_parity_metrics(context, snapshot)

    assert metrics.total_assignments == 3
    assert metrics.shift_histogram == {"DAY": 2, "EVE": 1}
    assert metrics.off_skill_assignment_count == 1
    assert metrics.station_day_coverage_counts == {
        "FRY": {0: 29, 1: 1},
        "GRILL": {0: 29, 2: 1},
    }
    assert metrics.warning_counts_by_type == {
        "understaffed_station_day": 2,
        "weekly_rest": 1,
    }
    assert metrics.per_worker_assignment_totals == {"W1": 2, "W2": 1}


def test_evaluate_monthly_parity_computes_candidate_minus_baseline_deltas() -> None:
    planning_input = MonthPlanningInput(
        tenant_code="tenant-a",
        year=2026,
        month=4,
        workers=[
            WorkerInput(
                worker_code="W1",
                name="Alex",
                role="employee",
                is_active=True,
                station_skills=["GRILL"],
            ),
            WorkerInput(
                worker_code="W2",
                name="Casey",
                role="employee",
                is_active=True,
                station_skills=["FRY"],
            ),
        ],
        stations=[
            StationInput(station_code="GRILL", name="Grill", is_active=True),
            StationInput(station_code="FRY", name="Fry", is_active=True),
        ],
        shifts=[
            ShiftInput(
                shift_code="DAY",
                name="Day",
                paid_hours=Decimal("8"),
                is_off_shift=False,
            ),
            ShiftInput(
                shift_code="EVE",
                name="Evening",
                paid_hours=Decimal("6"),
                is_off_shift=False,
            ),
        ],
        leave_requests=[],
        constraint_config={},
        adjustment_patch=None,
    )
    context = build_monthly_parity_context(
        planning_input,
        fixture_id="unit_fixture",
    )
    baseline_snapshot = MonthlyParitySnapshot(
        assignments=(
            MonthlyParityAssignment(
                date=dt.date(2026, 4, 1),
                worker_code="W1",
                shift_code="DAY",
                station_code="GRILL",
            ),
        ),
        warnings=(MonthlyParityWarning(type="weekly_rest", worker_code="W1"),),
    )
    candidate_snapshot = MonthlyParitySnapshot(
        assignments=(
            MonthlyParityAssignment(
                date=dt.date(2026, 4, 1),
                worker_code="W1",
                shift_code="DAY",
                station_code="GRILL",
            ),
            MonthlyParityAssignment(
                date=dt.date(2026, 4, 1),
                worker_code="W2",
                shift_code="EVE",
                station_code="FRY",
            ),
        ),
        warnings=(),
    )

    report = evaluate_monthly_parity(
        context,
        baseline_snapshot=baseline_snapshot,
        candidate_snapshot=candidate_snapshot,
    )

    assert report.metric_deltas.total_assignments == 1
    assert report.metric_deltas.shift_histogram == {"DAY": 0, "EVE": 1}
    assert report.metric_deltas.off_skill_assignment_count == 0
    assert report.metric_deltas.warning_counts_by_type == {"weekly_rest": -1}
    assert report.metric_deltas.per_worker_assignment_totals == {"W1": 0, "W2": 1}
    assert report.metric_deltas.station_day_coverage_counts == {
        "FRY": {0: -1, 1: 1},
        "GRILL": {0: 0, 1: 0},
    }


def test_frozen_shared_demo_monthly_parity_evaluator_stays_reproducible() -> None:
    fixture_payload = _load_json(FIXTURE_DIR / "planning_input.json")
    planning_input = _parse_month_planning_input_fixture(fixture_payload)
    baseline_artifact = _load_json(FIXTURE_DIR / "v1_baseline.json")
    baseline_snapshot = _parse_v1_baseline_snapshot(baseline_artifact)

    result = generate_month_plan(planning_input)
    context = build_monthly_parity_context(
        planning_input,
        fixture_id=str(fixture_payload["fixture_id"]),
    )
    report = evaluate_monthly_parity(
        context,
        baseline_snapshot=baseline_snapshot,
        candidate_snapshot=snapshot_month_planning_result(result),
    )

    assert baseline_artifact["artifact_version"] == "v1"
    assert baseline_artifact["fixture_id"] == fixture_payload["fixture_id"]
    assert baseline_artifact["fixture_sha256"] == _compute_fixture_sha256(fixture_payload)
    assert baseline_artifact["generated_from"] == {
        "repo": "sched-mvp",
        "commit": "37b2797a900692df573e1cf70e5ac07023bb5f69",
        "entrypoint": "app.generate_week.generate_week",
        "month_rollup": "weekly_chunk_rollup",
    }

    assert report.fixture_id == "shared_demo_april_2026"
    assert report.year == 2026
    assert report.month == 4
    assert report.baseline_assignment_count == 210
    assert report.baseline_warning_count == 8
    assert report.baseline_metrics.warning_counts_by_type == {
        "auto_rest": 4,
        "weekly_rest": 4,
    }

    assert result.metadata.source_type == "monthly_planner"
    assert report.candidate_assignment_count == result.summary.total_assignments
    assert report.candidate_warning_count == len(result.warnings)
    assert sum(report.candidate_metrics.shift_histogram.values()) == len(result.assignments)
    assert report.candidate_metrics.warning_counts_by_type == result.summary.warnings_by_type
    assert set(report.candidate_metrics.per_worker_assignment_totals) == {
        worker.worker_code
        for worker in planning_input.workers
        if worker.is_active
    }
    assert sum(report.candidate_metrics.per_worker_assignment_totals.values()) == len(
        result.assignments
    )

    for coverage_counts in report.baseline_metrics.station_day_coverage_counts.values():
        assert sum(coverage_counts.values()) == 30
    for coverage_counts in report.candidate_metrics.station_day_coverage_counts.values():
        assert sum(coverage_counts.values()) == 30


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _compute_fixture_sha256(fixture_payload: dict[str, object]) -> str:
    canonical = json.dumps(
        fixture_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _parse_month_planning_input_fixture(
    fixture_payload: dict[str, object],
) -> MonthPlanningInput:
    return MonthPlanningInput(
        tenant_code=str(fixture_payload["tenant_code"]),
        year=int(fixture_payload["year"]),
        month=int(fixture_payload["month"]),
        workers=[
            WorkerInput(
                worker_code=str(worker["worker_code"]),
                name=str(worker["name"]),
                role=str(worker["role"]),
                is_active=bool(worker["is_active"]),
                station_skills=[str(code) for code in worker["station_skills"]],
            )
            for worker in fixture_payload["workers"]
        ],
        stations=[
            StationInput(
                station_code=str(station["station_code"]),
                name=str(station["name"]),
                is_active=bool(station["is_active"]),
            )
            for station in fixture_payload["stations"]
        ],
        shifts=[
            ShiftInput(
                shift_code=str(shift["shift_code"]),
                name=str(shift["name"]),
                paid_hours=Decimal(str(shift["paid_hours"])),
                is_off_shift=bool(shift["is_off_shift"]),
                start_time=dt.time.fromisoformat(str(shift["start_time"])),
                end_time=dt.time.fromisoformat(str(shift["end_time"])),
            )
            for shift in fixture_payload["shifts"]
        ],
        leave_requests=[
            LeaveRequestInput(
                worker_code=str(leave_request["worker_code"]),
                date=dt.date.fromisoformat(str(leave_request["date"])),
                leave_type=str(leave_request["leave_type"]),
            )
            for leave_request in fixture_payload["leave_requests"]
        ],
        constraint_config=dict(fixture_payload["constraint_config"]),
        adjustment_patch=None,
    )


def _parse_v1_baseline_snapshot(
    baseline_artifact: dict[str, object],
) -> MonthlyParitySnapshot:
    assignments = tuple(
        MonthlyParityAssignment(
            date=dt.date.fromisoformat(str(assignment["date"])),
            worker_code=str(assignment["worker_code"]),
            shift_code=str(assignment["shift_code"]),
            station_code=str(assignment["station_code"]),
        )
        for assignment in baseline_artifact["assignments"]
    )
    warnings = tuple(
        MonthlyParityWarning(
            type=str(warning["type"]),
            date=(
                dt.date.fromisoformat(str(warning["date"]))
                if warning["date"] is not None
                else None
            ),
            worker_code=(
                str(warning["worker_code"])
                if warning["worker_code"] is not None
                else None
            ),
        )
        for warning in baseline_artifact["warnings"]
    )
    return MonthlyParitySnapshot(assignments=assignments, warnings=warnings)
