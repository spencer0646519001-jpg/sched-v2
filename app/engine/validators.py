"""Validation helpers for pure engine inputs.

The monthly engine only accepts normalized dataclass inputs. These helpers
guard basic integrity and structural invariants before planning logic runs.
"""

from __future__ import annotations

from collections import Counter

from app.engine.contracts import MonthPlanningInput


class MonthPlanningValidationError(ValueError):
    """Base error raised when month planning input is structurally invalid."""


class InvalidMonthPlanningInputError(MonthPlanningValidationError):
    """Raised for broken month metadata or clearly unusable field values."""


class DuplicateCodeError(MonthPlanningValidationError):
    """Raised when normalized code identifiers are not unique."""


class UnknownReferenceError(MonthPlanningValidationError):
    """Raised when a nested record references an unknown normalized code."""


def validate_month_planning_input(
    planning_input: MonthPlanningInput,
) -> MonthPlanningInput:
    """Validate normalized engine input and return it unchanged on success."""

    _validate_month_metadata(planning_input)
    _validate_required_collections(planning_input)

    worker_codes = _validate_worker_codes(planning_input)
    station_codes = _validate_station_codes(planning_input)
    shift_codes = _validate_shift_codes(planning_input)

    _validate_leave_requests(planning_input, worker_codes)
    _validate_adjustment_patch(
        planning_input,
        worker_codes=worker_codes,
        station_codes=station_codes,
        shift_codes=shift_codes,
    )
    return planning_input


def _validate_month_metadata(planning_input: MonthPlanningInput) -> None:
    if not planning_input.tenant_code.strip():
        raise InvalidMonthPlanningInputError(
            "Month planning input tenant_code must not be blank."
        )
    if planning_input.year < 1 or planning_input.year > 9999:
        raise InvalidMonthPlanningInputError(
            "Month planning input year must be between 1 and 9999."
        )
    if planning_input.month < 1 or planning_input.month > 12:
        raise InvalidMonthPlanningInputError(
            "Month planning input month must be between 1 and 12."
        )


def _validate_required_collections(planning_input: MonthPlanningInput) -> None:
    if not planning_input.workers:
        raise InvalidMonthPlanningInputError(
            "Month planning input must include at least one worker."
        )
    if not planning_input.stations:
        raise InvalidMonthPlanningInputError(
            "Month planning input must include at least one station."
        )
    if not planning_input.shifts:
        raise InvalidMonthPlanningInputError(
            "Month planning input must include at least one shift."
        )


def _validate_worker_codes(planning_input: MonthPlanningInput) -> set[str]:
    worker_codes: list[str] = []
    for worker in planning_input.workers:
        _require_non_blank_text(worker.worker_code, label="Worker code")
        worker_codes.append(worker.worker_code)

    _raise_if_duplicate_codes(worker_codes, label="worker")
    return set(worker_codes)


def _validate_station_codes(planning_input: MonthPlanningInput) -> set[str]:
    station_codes: list[str] = []
    for station in planning_input.stations:
        _require_non_blank_text(station.station_code, label="Station code")
        station_codes.append(station.station_code)

    _raise_if_duplicate_codes(station_codes, label="station")
    return set(station_codes)


def _validate_shift_codes(planning_input: MonthPlanningInput) -> set[str]:
    shift_codes: list[str] = []
    for shift in planning_input.shifts:
        _require_non_blank_text(shift.shift_code, label="Shift code")
        if shift.paid_hours < 0:
            raise InvalidMonthPlanningInputError(
                f"Shift {shift.shift_code!r} paid_hours must be zero or greater."
            )
        shift_codes.append(shift.shift_code)

    _raise_if_duplicate_codes(shift_codes, label="shift")
    return set(shift_codes)


def _validate_leave_requests(
    planning_input: MonthPlanningInput,
    worker_codes: set[str],
) -> None:
    unknown_worker_codes: set[str] = set()

    for leave_request in planning_input.leave_requests:
        _require_non_blank_text(
            leave_request.worker_code,
            label="Leave request worker_code",
        )
        _validate_date_in_planning_month(
            leave_request.date,
            planning_input=planning_input,
            label=f"Leave request for worker {leave_request.worker_code!r}",
        )
        if leave_request.worker_code not in worker_codes:
            unknown_worker_codes.add(leave_request.worker_code)

    if unknown_worker_codes:
        raise UnknownReferenceError(
            "Leave requests reference unknown worker codes: "
            f"{_format_codes(unknown_worker_codes)}."
        )


def _validate_adjustment_patch(
    planning_input: MonthPlanningInput,
    *,
    worker_codes: set[str],
    station_codes: set[str],
    shift_codes: set[str],
) -> None:
    if planning_input.adjustment_patch is None:
        return

    unknown_worker_codes: set[str] = set()
    unknown_station_codes: set[str] = set()
    unknown_shift_codes: set[str] = set()

    for patch in planning_input.adjustment_patch:
        _require_non_blank_text(
            patch.operation,
            label="Adjustment patch operation",
        )
        _require_non_blank_text(
            patch.worker_code,
            label="Adjustment patch worker_code",
        )
        _validate_date_in_planning_month(
            patch.date,
            planning_input=planning_input,
            label=f"Adjustment patch for worker {patch.worker_code!r}",
        )

        if patch.worker_code not in worker_codes:
            unknown_worker_codes.add(patch.worker_code)
        if patch.shift_code is not None:
            _require_non_blank_text(
                patch.shift_code,
                label="Adjustment patch shift_code",
            )
            if patch.shift_code not in shift_codes:
                unknown_shift_codes.add(patch.shift_code)
        if patch.station_code is not None:
            _require_non_blank_text(
                patch.station_code,
                label="Adjustment patch station_code",
            )
            if patch.station_code not in station_codes:
                unknown_station_codes.add(patch.station_code)

    error_parts: list[str] = []
    if unknown_worker_codes:
        error_parts.append(
            f"unknown worker codes: {_format_codes(unknown_worker_codes)}"
        )
    if unknown_shift_codes:
        error_parts.append(
            f"unknown shift codes: {_format_codes(unknown_shift_codes)}"
        )
    if unknown_station_codes:
        error_parts.append(
            f"unknown station codes: {_format_codes(unknown_station_codes)}"
        )

    if error_parts:
        raise UnknownReferenceError(
            "Adjustment patch references " + "; ".join(error_parts) + "."
        )


def _validate_date_in_planning_month(
    value_date,
    *,
    planning_input: MonthPlanningInput,
    label: str,
) -> None:
    if (
        value_date.year != planning_input.year
        or value_date.month != planning_input.month
    ):
        raise InvalidMonthPlanningInputError(
            f"{label} must stay within planning month "
            f"{planning_input.year:04d}-{planning_input.month:02d}."
        )


def _require_non_blank_text(value: str, *, label: str) -> None:
    if not value.strip():
        raise InvalidMonthPlanningInputError(f"{label} must not be blank.")


def _raise_if_duplicate_codes(codes: list[str], *, label: str) -> None:
    duplicates = sorted(
        code for code, count in Counter(codes).items() if count > 1
    )
    if duplicates:
        raise DuplicateCodeError(
            f"Duplicate {label} codes: {_format_codes(duplicates)}."
        )


def _format_codes(codes: set[str] | list[str]) -> str:
    return ", ".join(repr(code) for code in sorted(codes))


__all__ = [
    "DuplicateCodeError",
    "InvalidMonthPlanningInputError",
    "MonthPlanningValidationError",
    "UnknownReferenceError",
    "validate_month_planning_input",
]
