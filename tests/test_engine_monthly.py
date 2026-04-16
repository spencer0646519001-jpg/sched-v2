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
    assert result.summary.paid_hours_by_worker == {"W1": Decimal("238")}
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
) -> WorkerInput:
    return WorkerInput(
        worker_code=worker_code,
        name=name,
        role=role,
        is_active=is_active,
        station_skills=station_skills or ["GRILL", "PREP"],
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
