from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.engine.contracts import (
    AssignmentPatchInput,
    LeaveRequestInput,
    MonthPlanningInput,
    ShiftInput,
    StationInput,
    WorkerInput,
    WorkerSchedulingProfileInput,
    WorkerWishOffInput,
)
from app.engine.monthly import generate_month_plan


def test_generate_month_plan_builds_deterministic_baseline() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker("W2", name="Casey"),
                _worker("W1", name="Alex"),
                _worker("W9", name="Inactive", is_active=False),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "max_consecutive_days": 2,
            },
        )
    )

    assert [
        (assignment.date.isoformat(), assignment.worker_code, assignment.station_code)
        for assignment in result.assignments[:6]
    ] == [
        ("2026-04-01", "W1", "GRILL"),
        ("2026-04-02", "W2", "GRILL"),
        ("2026-04-03", "W1", "GRILL"),
        ("2026-04-04", "W2", "GRILL"),
        ("2026-04-05", "W1", "GRILL"),
        ("2026-04-06", "W2", "GRILL"),
    ]
    assert result.summary.total_assignments == 30
    assert result.summary.total_warnings == 0
    assert result.summary.assignments_by_worker == {"W1": 15, "W2": 15}
    assert result.summary.paid_hours_by_worker == {
        "W1": Decimal("120"),
        "W2": Decimal("120"),
    }
    assert "W9" not in result.summary.assignments_by_worker
    assert result.metadata.generated_at == dt.datetime(
        2026,
        4,
        1,
        tzinfo=dt.timezone.utc,
    )
    assert result.metadata.source_type == "monthly_planner"
    assert result.evaluation is not None
    assert result.evaluation.schedule_quality_label == "good"


def test_generate_month_plan_skips_workers_on_leave_dates() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker("W1", name="Alex"),
                _worker("W2", name="Casey"),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
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
            },
        )
    )

    assignments_by_date = {
        assignment.date: assignment for assignment in result.assignments[:2]
    }

    assert assignments_by_date[dt.date(2026, 4, 1)].worker_code == "W2"
    assert assignments_by_date[dt.date(2026, 4, 2)].worker_code == "W1"
    assert not any(
        assignment.worker_code == "W1"
        and assignment.date == dt.date(2026, 4, 1)
        for assignment in result.assignments
    )
    assert result.summary.total_warnings == 0


def test_generate_month_plan_respects_fixed_days_off_weekdays() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Alex",
                    scheduling_profile=_profile(fixed_day_off_weekdays=[2]),
                ),
                _worker("W2", name="Casey"),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "max_consecutive_days": 31,
            },
        )
    )

    assignments_by_date = {
        assignment.date: assignment for assignment in result.assignments[:2]
    }

    assert assignments_by_date[dt.date(2026, 4, 1)].worker_code == "W2"
    assert assignments_by_date[dt.date(2026, 4, 2)].worker_code == "W1"


def test_generate_month_plan_respects_ad_hoc_unavailable_dates() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Alex",
                    scheduling_profile=_profile(
                        ad_hoc_unavailable=[dt.date(2026, 4, 1)]
                    ),
                ),
                _worker("W2", name="Casey"),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "max_consecutive_days": 31,
            },
        )
    )

    assert result.assignments[0].date == dt.date(2026, 4, 1)
    assert result.assignments[0].worker_code == "W2"


def test_generate_month_plan_respects_hard_wish_off_dates() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Alex",
                    scheduling_profile=_profile(
                        wish_off_hard=[dt.date(2026, 4, 1)]
                    ),
                ),
                _worker("W2", name="Casey"),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "max_consecutive_days": 31,
            },
        )
    )

    assert result.assignments[0].date == dt.date(2026, 4, 1)
    assert result.assignments[0].worker_code == "W2"


def test_generate_month_plan_uses_soft_wish_off_as_ranking_penalty() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Alex",
                    scheduling_profile=_profile(
                        wish_off_soft=[dt.date(2026, 4, 1)]
                    ),
                ),
                _worker("W2", name="Casey"),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "max_consecutive_days": 31,
            },
        )
    )

    assert result.assignments[0].date == dt.date(2026, 4, 1)
    assert result.assignments[0].worker_code == "W2"


def test_generate_month_plan_soft_wish_off_does_not_block_last_available_worker() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Alex",
                    scheduling_profile=_profile(
                        wish_off_soft=[dt.date(2026, 4, 1)]
                    ),
                )
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

    assert result.assignments[0].date == dt.date(2026, 4, 1)
    assert result.assignments[0].worker_code == "W1"
    assert result.summary.total_assignments == 30


def test_generate_month_plan_prefers_matching_shift_preferences_for_ordinary_slots() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Day Pref",
                    scheduling_profile=_profile(shift_prefs=["DAY"]),
                ),
                _worker(
                    "W2",
                    name="Evening Pref",
                    scheduling_profile=_profile(shift_prefs=["EVE"]),
                ),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[
                _shift("DAY", name="Day", paid_hours="8"),
                _shift("EVE", name="Evening", paid_hours="6"),
            ],
            constraint_config={
                "stations": {"GRILL": 2},
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
                "max_consecutive_days": 31,
            },
        )
    )

    first_day_assignments = [
        (assignment.worker_code, assignment.shift_code)
        for assignment in result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    ]

    assert first_day_assignments == [
        ("W1", "DAY"),
        ("W2", "EVE"),
    ]


def test_generate_month_plan_prefers_core_worker_as_late_tie_breaker() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker("W1", name="Non Core"),
                _worker(
                    "W2",
                    name="Core",
                    scheduling_profile=_profile(core=True),
                ),
            ],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "max_consecutive_days": 31,
            },
        )
    )

    assert result.assignments[0].date == dt.date(2026, 4, 1)
    assert result.assignments[0].worker_code == "W2"


def test_generate_month_plan_emits_understaffed_station_warnings() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("W1", name="Alex")],
            stations=[_station("GRILL", name="Grill")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "stations": {"GRILL": 2},
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
            },
        )
    )

    first_warning = result.warnings[0]

    assert result.summary.total_assignments == 30
    assert result.summary.total_warnings == 30
    assert first_warning.type == "understaffed_station_day"
    assert first_warning.message_key == "understaffed_station"
    assert first_warning.date == dt.date(2026, 4, 1)
    assert first_warning.details == {
        "station_code": "GRILL",
        "required_staff": 2,
        "assigned_staff": 1,
        "missing_staff": 1,
    }
    assert result.evaluation is not None
    assert result.evaluation.understaffed_station_days == 30
    assert result.evaluation.schedule_quality_label == "needs_review"


def test_generate_month_plan_prefers_skilled_worker_over_off_skill_candidate() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                WorkerInput(
                    worker_code="W1",
                    name="Fallback",
                    role="cook",
                    is_active=True,
                    station_skills=[],
                ),
                _worker(
                    "W2",
                    name="Skilled",
                    station_skills=["PREP"],
                ),
            ],
            stations=[_station("PREP", name="Prep")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "stations": {"PREP": 1},
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "max_consecutive_days": 31,
            },
        )
    )

    first_assignment = result.assignments[0]

    assert first_assignment.date == dt.date(2026, 4, 1)
    assert first_assignment.worker_code == "W2"
    assert first_assignment.station_code == "PREP"
    assert first_assignment.note is None


def test_generate_month_plan_preserves_only_viable_worker_for_scarce_later_slot() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Scarce",
                    station_skills=["APPLE", "ZULU"],
                ),
                _worker(
                    "W2",
                    name="Common",
                    station_skills=["APPLE"],
                ),
            ],
            stations=[
                _station("APPLE", name="Apple"),
                _station("ZULU", name="Zulu"),
            ],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "stations": {
                    "APPLE": 1,
                    "ZULU": 1,
                },
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
                "max_consecutive_days": 31,
            },
        )
    )

    first_day_assignments = [
        (
            assignment.worker_code,
            assignment.station_code,
            assignment.note,
        )
        for assignment in result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    ]

    assert first_day_assignments == [
        ("W1", "ZULU", None),
        ("W2", "APPLE", None),
    ]
    assert result.summary.total_warnings == 0


def test_generate_month_plan_marks_fallback_station_assignments_explicitly() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Skilled",
                    station_skills=["GRILL"],
                ),
                WorkerInput(
                    worker_code="W2",
                    name="Fallback",
                    role="cook",
                    is_active=True,
                    station_skills=[],
                ),
            ],
            stations=[
                _station("GRILL", name="Grill"),
                _station("PREP", name="Prep"),
            ],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "stations": {
                    "GRILL": 1,
                    "PREP": 1,
                },
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
                "max_consecutive_days": 31,
            },
        )
    )

    first_day_assignments = [
        (
            assignment.worker_code,
            assignment.station_code,
            assignment.note,
        )
        for assignment in result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    ]
    fallback_assignments = [
        assignment
        for assignment in result.assignments
        if assignment.note == "fallback_station_skill_mismatch"
    ]

    assert first_day_assignments == [
        ("W1", "GRILL", None),
        ("W2", "PREP", "fallback_station_skill_mismatch"),
    ]
    assert len(fallback_assignments) == 30
    assert result.summary.total_warnings == 0


def test_generate_month_plan_require_one_chef_can_add_extra_daily_assignment() -> None:
    baseline_result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "CHEF1",
                    name="Morgan",
                    role="chef",
                    station_skills=["GRILL"],
                ),
                _worker(
                    "COOK1",
                    name="Alex",
                    station_skills=["GRILL"],
                ),
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
                _worker(
                    "COOK1",
                    name="Alex",
                    station_skills=["GRILL"],
                ),
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

    first_day_assignments = [
        (
            assignment.worker_code,
            assignment.shift_code,
            assignment.station_code,
            assignment.note,
        )
        for assignment in chef_required_result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    ]

    assert baseline_result.summary.total_assignments == 30
    assert chef_required_result.summary.total_assignments == 60
    assert first_day_assignments == [
        ("CHEF1", "DAY", None, "required_chef"),
        ("COOK1", "DAY", "GRILL", None),
    ]
    assert chef_required_result.summary.assignments_by_worker == {
        "CHEF1": 30,
        "COOK1": 30,
    }
    assert chef_required_result.summary.total_warnings == 0


def test_generate_month_plan_uses_configured_morning_shift_for_required_station() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Pat",
                    station_skills=["GATEAU"],
                )
            ],
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

    first_assignment = result.assignments[0]

    assert first_assignment.date == dt.date(2026, 4, 1)
    assert first_assignment.worker_code == "W1"
    assert first_assignment.shift_code == "M1"
    assert first_assignment.station_code == "GATEAU"
    assert result.summary.total_warnings == 0


def test_generate_month_plan_warns_when_morning_station_cannot_be_covered() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker(
                    "W1",
                    name="Pat",
                    station_skills=["GATEAU"],
                )
            ],
            stations=[_station("GATEAU", name="Gateau")],
            shifts=[_shift("DAY", name="Day", paid_hours="8")],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "morning_shifts": ["M1"],
                "stations_require_morning": {"GATEAU": 1},
            },
        )
    )

    morning_warnings = [
        warning
        for warning in result.warnings
        if warning.type == "missing_morning_station_coverage"
    ]

    assert result.summary.total_assignments == 30
    assert len(morning_warnings) == 30
    assert morning_warnings[0].date == dt.date(2026, 4, 1)
    assert morning_warnings[0].details == {
        "station_code": "GATEAU",
        "required_morning_staff": 1,
        "assigned_morning_staff": 0,
        "missing_morning_staff": 1,
    }
    assert result.summary.warnings_by_type == {
        "missing_morning_station_coverage": 30,
    }


def test_generate_month_plan_rotates_non_morning_shifts_across_ordinary_slots() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker("W1", name="Alex", station_skills=["GATEAU", "PREP"]),
                _worker("W2", name="Casey", station_skills=["GATEAU", "PREP"]),
                _worker("W3", name="Jordan", station_skills=["GATEAU", "PREP"]),
            ],
            stations=[
                _station("GATEAU", name="Gateau"),
                _station("PREP", name="Prep"),
            ],
            shifts=[
                _shift("DAY", name="Day", paid_hours="8"),
                _shift("EVE", name="Evening", paid_hours="6"),
                _shift("M1", name="Morning 1", paid_hours="8"),
            ],
            constraint_config={
                "stations": {
                    "GATEAU": 2,
                    "PREP": 1,
                },
                "min_staff_weekday": 3,
                "min_staff_weekend": 3,
                "max_staff_per_day": 3,
                "morning_shifts": ["M1"],
                "stations_require_morning": {"GATEAU": 1},
                "max_consecutive_days": 31,
            },
        )
    )

    first_day_assignments = [
        (
            assignment.worker_code,
            assignment.shift_code,
            assignment.station_code,
        )
        for assignment in result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    ]
    second_day_assignments = [
        (
            assignment.worker_code,
            assignment.shift_code,
            assignment.station_code,
        )
        for assignment in result.assignments
        if assignment.date == dt.date(2026, 4, 2)
    ]

    assert first_day_assignments == [
        ("W1", "M1", "GATEAU"),
        ("W2", "DAY", "GATEAU"),
        ("W3", "EVE", "PREP"),
    ]
    assert second_day_assignments == [
        ("W1", "M1", "GATEAU"),
        ("W2", "EVE", "GATEAU"),
        ("W3", "DAY", "PREP"),
    ]
    assert result.summary.total_warnings == 0


def test_generate_month_plan_warns_when_required_chef_is_impossible() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("W1", name="Alex")],
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

    chef_warnings = [
        warning for warning in result.warnings if warning.type == "missing_required_chef"
    ]

    assert result.summary.total_assignments == 30
    assert len(chef_warnings) == 30
    assert chef_warnings[0].date == dt.date(2026, 4, 1)
    assert chef_warnings[0].message_key == "missing_required_chef"
    assert chef_warnings[0].details == {"required_role": "chef"}


def test_generate_month_plan_keeps_extra_chefs_out_of_normal_station_slots() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[
                _worker("CHEF1", name="Morgan", role="chef"),
                _worker("CHEF2", name="Taylor", role="chef"),
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

    first_day_assignments = [
        (
            assignment.worker_code,
            assignment.shift_code,
            assignment.station_code,
            assignment.note,
        )
        for assignment in result.assignments
        if assignment.date == dt.date(2026, 4, 1)
    ]

    chef_assignments = [
        assignment
        for assignment in result.assignments
        if assignment.worker_code.startswith("CHEF")
    ]

    assert len(first_day_assignments) == 2
    assert [
        assignment[1:]
        for assignment in first_day_assignments
        if assignment[0].startswith("CHEF")
    ] == [("DAY", None, "required_chef")]
    assert [
        assignment[1:]
        for assignment in first_day_assignments
        if assignment[0] == "COOK1"
    ] == [("DAY", "GRILL", None)]
    assert all(assignment.station_code is None for assignment in chef_assignments)
    assert result.summary.total_warnings == 0


def test_generate_month_plan_remains_deterministic_with_domain_rules() -> None:
    planning_input = _build_planning_input(
        workers=[
            _worker(
                "CHEF1",
                name="Morgan",
                role="chef",
                station_skills=["GATEAU"],
            ),
            _worker(
                "COOK1",
                name="Alex",
                station_skills=["GATEAU"],
            ),
        ],
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
            "require_one_chef": True,
            "count_chefs_in_headcount": False,
            "chefs_have_no_shift": True,
        },
    )

    first_result = generate_month_plan(planning_input)
    second_result = generate_month_plan(planning_input)

    assert first_result == second_result


def test_generate_month_plan_applies_patch_override_after_baseline() -> None:
    result = generate_month_plan(
        _build_planning_input(
            workers=[_worker("W1", name="Alex")],
            stations=[
                _station("PREP", name="Prep"),
                _station("GRILL", name="Grill"),
            ],
            shifts=[
                _shift("DAY", name="Day", paid_hours="8"),
                _shift("EVE", name="Evening", paid_hours="6"),
            ],
            constraint_config={
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
            },
            adjustment_patch=[
                AssignmentPatchInput(
                    operation="set",
                    date=dt.date(2026, 4, 1),
                    worker_code="W1",
                    shift_code="EVE",
                    station_code="PREP",
                    note="manual override",
                )
            ],
        )
    )

    first_assignment = result.assignments[0]

    assert first_assignment.date == dt.date(2026, 4, 1)
    assert first_assignment.worker_code == "W1"
    assert first_assignment.shift_code == "EVE"
    assert first_assignment.station_code == "PREP"
    assert first_assignment.source == "adjustment_patch"
    assert first_assignment.note == "manual override"
    assert result.summary.total_assignments == 30
    expected_paid_hours = sum(
        Decimal("8") if assignment.shift_code == "DAY" else Decimal("6")
        for assignment in result.assignments
    )
    assert result.summary.paid_hours_by_worker == {"W1": expected_paid_hours}
    assert result.metadata.refinement_applied is True
    assert "adjustment_patch_applied" in (result.metadata.notes or [])


def _build_planning_input(
    *,
    workers: list[WorkerInput],
    stations: list[StationInput],
    shifts: list[ShiftInput],
    constraint_config: dict[str, object],
    leave_requests: list[LeaveRequestInput] | None = None,
    adjustment_patch: list[AssignmentPatchInput] | None = None,
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
        adjustment_patch=adjustment_patch,
    )


def _worker(
    worker_code: str,
    *,
    name: str,
    is_active: bool = True,
    role: str = "cook",
    station_skills: list[str] | None = None,
    scheduling_profile: WorkerSchedulingProfileInput | None = None,
) -> WorkerInput:
    return WorkerInput(
        worker_code=worker_code,
        name=name,
        role=role,
        is_active=is_active,
        station_skills=station_skills or ["GRILL", "PREP"],
        scheduling_profile=(
            scheduling_profile
            if scheduling_profile is not None
            else WorkerSchedulingProfileInput()
        ),
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


def _profile(
    *,
    shift_prefs: list[str] | None = None,
    fixed_day_off_weekdays: list[int] | None = None,
    ad_hoc_unavailable: list[dt.date] | None = None,
    wish_off_hard: list[dt.date] | None = None,
    wish_off_soft: list[dt.date] | None = None,
    core: bool = False,
) -> WorkerSchedulingProfileInput:
    return WorkerSchedulingProfileInput(
        shift_prefs=shift_prefs or [],
        fixed_day_off_weekdays=fixed_day_off_weekdays or [],
        ad_hoc_unavailable=ad_hoc_unavailable or [],
        wish_off=WorkerWishOffInput(
            hard=wish_off_hard or [],
            soft=wish_off_soft or [],
        ),
        core=core,
    )
