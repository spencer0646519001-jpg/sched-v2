from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.engine.contracts import (
    LeaveRequestInput,
    MonthPlanningInput,
    MonthPlanningResult,
    ShiftInput,
    StationInput,
    WarningOutput,
    WorkerInput,
)
from app.engine.monthly import generate_month_plan


def test_reviewer_story_baseline_sanity_is_clean_and_deterministic() -> None:
    planning_input = _build_planning_input(
        workers=[
            _worker("W1", name="Alex", station_skills=["GRILL"]),
            _worker("W2", name="Casey", station_skills=["GRILL"]),
        ],
        stations=[_station("GRILL", name="Grill")],
        shifts=[_shift("DAY", name="Day", paid_hours="8")],
        constraint_config={
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
        },
    )

    first_result = generate_month_plan(planning_input)
    second_result = generate_month_plan(planning_input)

    assert first_result == second_result
    assert _assignment_pairs(first_result, dt.date(2026, 4, 1)) == [
        ("W1", "DAY", "GRILL", None),
    ]
    assert (
        _warning_dates_on(
            first_result.warnings,
            "missing_morning_station_coverage",
            dt.date(2026, 4, 1),
        )
        == []
    )
    assert (
        _warning_dates_on(
            first_result.warnings,
            "missing_required_chef",
            dt.date(2026, 4, 1),
        )
        == []
    )
    assert first_result.evaluation is not None
    assert first_result.evaluation.schedule_quality_label == "good"


def test_reviewer_story_morning_policy_bundle_changes_assignment_behavior() -> None:
    baseline_result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("W1", name="Pat", station_skills=["GATEAU"])],
            stations=[_station("GATEAU", name="Gateau")],
            shifts=[
                _shift("DAY", name="Day", paid_hours="8"),
                _shift("M1", name="Morning 1", paid_hours="8"),
            ],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
            },
        )
    )
    morning_required_result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("W1", name="Pat", station_skills=["GATEAU"])],
            stations=[_station("GATEAU", name="Gateau")],
            shifts=[
                _shift("DAY", name="Day", paid_hours="8"),
                _shift("M1", name="Morning 1", paid_hours="8"),
            ],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "morning_shifts": ["M1"],
                "stations_require_morning": {"GATEAU": 1},
            },
        )
    )

    assert _assignment_pairs(baseline_result, dt.date(2026, 4, 1)) == [
        ("W1", "DAY", "GATEAU", None),
    ]
    assert _assignment_pairs(morning_required_result, dt.date(2026, 4, 1)) == [
        ("W1", "M1", "GATEAU", None),
    ]
    assert (
        _warning_dates_on(
            morning_required_result.warnings,
            "missing_morning_station_coverage",
            dt.date(2026, 4, 1),
        )
        == []
    )
    assert morning_required_result.evaluation is not None
    assert morning_required_result.evaluation.schedule_quality_label == "good"


def test_reviewer_story_morning_requirement_fails_honestly_when_leave_removes_coverage() -> None:
    covered_result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("W1", name="Pat", station_skills=["GATEAU"])],
            stations=[_station("GATEAU", name="Gateau")],
            shifts=[
                _shift("DAY", name="Day", paid_hours="8"),
                _shift("M1", name="Morning 1", paid_hours="8"),
            ],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "morning_shifts": ["M1"],
                "stations_require_morning": {"GATEAU": 1},
            },
        )
    )
    uncovered_result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("W1", name="Pat", station_skills=["GATEAU"])],
            stations=[_station("GATEAU", name="Gateau")],
            shifts=[
                _shift("DAY", name="Day", paid_hours="8"),
                _shift("M1", name="Morning 1", paid_hours="8"),
            ],
            leave_requests=[
                LeaveRequestInput(
                    worker_code="W1",
                    date=dt.date(2026, 4, 1),
                    leave_type="pto",
                )
            ],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "morning_shifts": ["M1"],
                "stations_require_morning": {"GATEAU": 1},
            },
        )
    )

    assert _assignment_pairs(covered_result, dt.date(2026, 4, 1)) == [
        ("W1", "M1", "GATEAU", None),
    ]
    assert _assignment_pairs(uncovered_result, dt.date(2026, 4, 1)) == []
    assert (
        _warning_dates_on(
            covered_result.warnings,
            "missing_morning_station_coverage",
            dt.date(2026, 4, 1),
        )
        == []
    )
    assert _warning_dates_on(
        uncovered_result.warnings,
        "missing_morning_station_coverage",
        dt.date(2026, 4, 1),
    ) == [dt.date(2026, 4, 1)]
    assert uncovered_result.evaluation is not None
    assert uncovered_result.evaluation.schedule_quality_label == "needs_review"


def test_reviewer_story_chef_required_policy_mode_changes_assignment_shape() -> None:
    baseline_result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "CHEF1",
                    name="Morgan",
                    role="chef",
                    station_skills=["GRILL"],
                ),
                _worker("COOK1", name="Alex", station_skills=["GRILL"]),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
            },
        )
    )
    chef_required_result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "CHEF1",
                    name="Morgan",
                    role="chef",
                    station_skills=["GRILL"],
                ),
                _worker("COOK1", name="Alex", station_skills=["GRILL"]),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "require_one_chef": True,
                "count_chefs_in_headcount": False,
                "chefs_have_no_shift": True,
            },
        )
    )

    assert _assignment_pairs(baseline_result, dt.date(2026, 4, 1)) == [
        ("CHEF1", "DAY", "GRILL", None),
    ]
    assert _assignment_pairs(chef_required_result, dt.date(2026, 4, 1)) == [
        ("CHEF1", "DAY", None, "required_chef"),
        ("COOK1", "DAY", "GRILL", None),
    ]
    assert (
        _warning_dates_on(
            chef_required_result.warnings,
            "missing_required_chef",
            dt.date(2026, 4, 1),
        )
        == []
    )
    assert chef_required_result.evaluation is not None
    assert chef_required_result.evaluation.schedule_quality_label == "good"


def test_reviewer_story_require_one_chef_changes_warning_semantics_when_chef_is_missing() -> None:
    chef_not_required_result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("COOK1", name="Alex", station_skills=["GRILL"])],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
            },
        )
    )
    chef_required_result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("COOK1", name="Alex", station_skills=["GRILL"])],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "require_one_chef": True,
                "count_chefs_in_headcount": False,
                "chefs_have_no_shift": True,
            },
        )
    )

    assert (
        _warning_dates_on(
            chef_not_required_result.warnings,
            "missing_required_chef",
            dt.date(2026, 4, 1),
        )
        == []
    )
    assert _warning_dates_on(
        chef_required_result.warnings,
        "missing_required_chef",
        dt.date(2026, 4, 1),
    ) == [dt.date(2026, 4, 1)]
    assert chef_not_required_result.evaluation is not None
    assert chef_required_result.evaluation is not None
    assert chef_not_required_result.evaluation.schedule_quality_label == "good"
    assert chef_required_result.evaluation.schedule_quality_label == "needs_review"


def test_reviewer_story_count_chefs_in_headcount_changes_coverage_interpretation() -> None:
    not_counted_result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "CHEF1",
                    name="Morgan",
                    role="chef",
                    station_skills=["GRILL"],
                ),
                _worker("COOK1", name="Alex", station_skills=["GRILL"]),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
                "require_one_chef": True,
                "count_chefs_in_headcount": False,
                "chefs_have_no_shift": True,
            },
        )
    )
    counted_result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "CHEF1",
                    name="Morgan",
                    role="chef",
                    station_skills=["GRILL"],
                ),
                _worker("COOK1", name="Alex", station_skills=["GRILL"]),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
                "require_one_chef": True,
                "count_chefs_in_headcount": True,
                "chefs_have_no_shift": True,
            },
        )
    )

    assert _assignment_pairs(not_counted_result, dt.date(2026, 4, 1)) == [
        ("CHEF1", "DAY", None, "required_chef"),
        ("COOK1", "DAY", "GRILL", None),
    ]
    assert _assignment_pairs(counted_result, dt.date(2026, 4, 1)) == [
        ("CHEF1", "DAY", None, "required_chef"),
        ("COOK1", "DAY", "GRILL", None),
    ]
    assert _warning_dates_on(
        not_counted_result.warnings,
        "understaffed_station_day",
        dt.date(2026, 4, 1),
    ) == [dt.date(2026, 4, 1)]
    assert (
        _warning_dates_on(
            counted_result.warnings,
            "understaffed_station_day",
            dt.date(2026, 4, 1),
        )
        == []
    )
    assert not_counted_result.evaluation is not None
    assert counted_result.evaluation is not None
    assert not_counted_result.evaluation.schedule_quality_label == "needs_review"
    assert counted_result.evaluation.schedule_quality_label == "good"


def test_reviewer_story_chefs_have_no_shift_changes_chef_assignment_semantics() -> None:
    chef_on_station_result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "CHEF1",
                    name="Morgan",
                    role="chef",
                    station_skills=["GRILL"],
                ),
                _worker("COOK1", name="Alex", station_skills=["GRILL"]),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "require_one_chef": True,
                "count_chefs_in_headcount": False,
                "chefs_have_no_shift": False,
            },
        )
    )
    chef_has_no_shift_result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "CHEF1",
                    name="Morgan",
                    role="chef",
                    station_skills=["GRILL"],
                ),
                _worker("COOK1", name="Alex", station_skills=["GRILL"]),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "require_one_chef": True,
                "count_chefs_in_headcount": False,
                "chefs_have_no_shift": True,
            },
        )
    )

    assert _assignment_pairs(chef_on_station_result, dt.date(2026, 4, 1)) == [
        ("CHEF1", "DAY", "GRILL", None),
    ]
    assert _assignment_pairs(chef_has_no_shift_result, dt.date(2026, 4, 1)) == [
        ("CHEF1", "DAY", None, "required_chef"),
        ("COOK1", "DAY", "GRILL", None),
    ]
    assert chef_has_no_shift_result.evaluation is not None
    assert chef_has_no_shift_result.evaluation.schedule_quality_label == "good"


def _build_planning_input(
    *,
    workers: list[WorkerInput],
    stations: list[StationInput],
    shifts: list[ShiftInput],
    constraint_config: dict[str, object],
    leave_requests: list[LeaveRequestInput] | None = None,
) -> MonthPlanningInput:
    return MonthPlanningInput(
        tenant_code="tenant-a",
        year=2026,
        month=4,
        workers=workers,
        stations=stations,
        shifts=shifts,
        leave_requests=leave_requests or [],
        constraint_config=constraint_config,
        adjustment_patch=None,
    )


def _worker(
    worker_code: str,
    *,
    name: str,
    role: str = "cook",
    station_skills: list[str] | None = None,
) -> WorkerInput:
    return WorkerInput(
        worker_code=worker_code,
        name=name,
        role=role,
        is_active=True,
        station_skills=station_skills or ["GRILL"],
        metadata_json=None,
    )


def _station(
    station_code: str,
    *,
    name: str,
) -> StationInput:
    return StationInput(
        station_code=station_code,
        name=name,
        is_active=True,
        metadata_json=None,
    )


def _shift(
    shift_code: str,
    *,
    name: str,
    paid_hours: str,
) -> ShiftInput:
    return ShiftInput(
        shift_code=shift_code,
        name=name,
        paid_hours=Decimal(paid_hours),
        is_off_shift=False,
        start_time=None,
        end_time=None,
        metadata_json=None,
    )


def _assignment_pairs(
    result: MonthPlanningResult,
    assignment_date: dt.date,
) -> list[tuple[str, str, str | None, str | None]]:
    return [
        (
            assignment.worker_code,
            assignment.shift_code,
            assignment.station_code,
            assignment.note,
        )
        for assignment in result.assignments
        if assignment.date == assignment_date
    ]


def _warning_dates_on(
    warnings: list[WarningOutput],
    warning_type: str,
    warning_date: dt.date,
) -> list[dt.date]:
    return [
        warning.date
        for warning in warnings
        if warning.type == warning_type and warning.date == warning_date
    ]
