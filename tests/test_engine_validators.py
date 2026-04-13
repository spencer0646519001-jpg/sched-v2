from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest

from app.engine.contracts import (
    AssignmentPatchInput,
    LeaveRequestInput,
    MonthPlanningInput,
    ShiftInput,
    StationInput,
    WorkerInput,
)
from app.engine.validators import (
    DuplicateCodeError,
    InvalidMonthPlanningInputError,
    UnknownReferenceError,
    validate_month_planning_input,
)


def test_validator_rejects_duplicate_worker_codes() -> None:
    planning_input = replace(
        _build_month_planning_input(),
        workers=[
            _worker("W1", name="Alex"),
            _worker("W1", name="Casey"),
        ],
    )

    with pytest.raises(DuplicateCodeError, match=r"Duplicate worker codes: 'W1'\."):
        validate_month_planning_input(planning_input)


def test_validator_rejects_duplicate_station_codes() -> None:
    planning_input = replace(
        _build_month_planning_input(),
        stations=[
            _station("GRILL", name="Grill"),
            _station("GRILL", name="Prep"),
        ],
    )

    with pytest.raises(DuplicateCodeError, match=r"Duplicate station codes: 'GRILL'\."):
        validate_month_planning_input(planning_input)


def test_validator_rejects_duplicate_shift_codes() -> None:
    planning_input = replace(
        _build_month_planning_input(),
        shifts=[
            _shift("DAY", name="Day"),
            _shift("DAY", name="Backup Day"),
        ],
    )

    with pytest.raises(DuplicateCodeError, match=r"Duplicate shift codes: 'DAY'\."):
        validate_month_planning_input(planning_input)


def test_validator_rejects_leave_requests_for_unknown_workers() -> None:
    planning_input = replace(
        _build_month_planning_input(),
        leave_requests=[
            LeaveRequestInput(
                worker_code="W404",
                date=dt.date(2026, 4, 2),
                leave_type="pto",
            )
        ],
    )

    with pytest.raises(
        UnknownReferenceError,
        match=r"Leave requests reference unknown worker codes: 'W404'\.",
    ):
        validate_month_planning_input(planning_input)


def test_validator_rejects_adjustment_patch_with_unknown_references() -> None:
    planning_input = replace(
        _build_month_planning_input(),
        adjustment_patch=[
            AssignmentPatchInput(
                operation="set",
                date=dt.date(2026, 4, 3),
                worker_code="W404",
                shift_code="NIGHT",
                station_code="FISH",
                note="Unknown references",
            )
        ],
    )

    with pytest.raises(
        UnknownReferenceError,
        match=(
            r"Adjustment patch references unknown worker codes: 'W404'; "
            r"unknown shift codes: 'NIGHT'; unknown station codes: 'FISH'\."
        ),
    ):
        validate_month_planning_input(planning_input)


@pytest.mark.parametrize(
    ("year", "month", "message"),
    [
        (0, 4, r"Month planning input year must be between 1 and 9999\."),
        (2026, 13, r"Month planning input month must be between 1 and 12\."),
    ],
)
def test_validator_rejects_invalid_year_or_month(
    year: int,
    month: int,
    message: str,
) -> None:
    planning_input = replace(
        _build_month_planning_input(),
        year=year,
        month=month,
    )

    with pytest.raises(InvalidMonthPlanningInputError, match=message):
        validate_month_planning_input(planning_input)


@pytest.mark.parametrize(
    ("field_name", "message"),
    [
        ("workers", r"Month planning input must include at least one worker\."),
        ("stations", r"Month planning input must include at least one station\."),
        ("shifts", r"Month planning input must include at least one shift\."),
    ],
)
def test_validator_rejects_empty_planning_collections(
    field_name: str,
    message: str,
) -> None:
    planning_input = replace(_build_month_planning_input(), **{field_name: []})

    with pytest.raises(InvalidMonthPlanningInputError, match=message):
        validate_month_planning_input(planning_input)


def test_validator_returns_valid_input_unchanged() -> None:
    planning_input = replace(
        _build_month_planning_input(),
        leave_requests=[
            LeaveRequestInput(
                worker_code="W1",
                date=dt.date(2026, 4, 2),
                leave_type="pto",
            )
        ],
        adjustment_patch=[
            AssignmentPatchInput(
                operation="set",
                date=dt.date(2026, 4, 3),
                worker_code="W1",
                shift_code="DAY",
                station_code="GRILL",
                note="Known references",
            )
        ],
    )

    validated = validate_month_planning_input(planning_input)

    assert validated is planning_input


def _build_month_planning_input() -> MonthPlanningInput:
    return MonthPlanningInput(
        tenant_code="tenant-a",
        year=2026,
        month=4,
        workers=[_worker("W1", name="Alex")],
        stations=[_station("GRILL", name="Grill")],
        shifts=[_shift("DAY", name="Day")],
        leave_requests=[],
        constraint_config={"max_weekly_hours": 40},
        adjustment_patch=None,
    )


def _worker(worker_code: str, *, name: str) -> WorkerInput:
    return WorkerInput(
        worker_code=worker_code,
        name=name,
        role="cook",
        is_active=True,
        station_skills=["GRILL"],
        metadata_json=None,
    )


def _station(station_code: str, *, name: str) -> StationInput:
    return StationInput(
        station_code=station_code,
        name=name,
        is_active=True,
        metadata_json=None,
    )


def _shift(shift_code: str, *, name: str) -> ShiftInput:
    return ShiftInput(
        shift_code=shift_code,
        name=name,
        paid_hours=Decimal("8"),
        is_off_shift=False,
        start_time=None,
        end_time=None,
        metadata_json=None,
    )
