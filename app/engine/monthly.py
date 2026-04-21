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
_REQUIRED_CHEF_NOTE = "required_chef"
_FALLBACK_STATION_NOTE = "fallback_station_skill_mismatch"

_PATCH_SET_OPERATIONS = frozenset({"set", "replace"})
_PATCH_REMOVE_OPERATIONS = frozenset({"remove", "delete", "unset"})


@dataclass(frozen=True, slots=True)
class _RequiredStationSlot:
    station_code: str
    requires_morning: bool


@dataclass(frozen=True, slots=True)
class _StationSlotPriority:
    slot_index: int
    slot: _RequiredStationSlot
    skilled_candidate_count: int
    min_other_skill_option_count: int
    total_other_skill_option_count: int


@dataclass(frozen=True, slots=True)
class _StationWorkerSelection:
    worker: WorkerInput
    note: str | None = None


@dataclass(frozen=True, slots=True)
class _WorkerSchedulingState:
    preferred_shift_codes: frozenset[str]
    fixed_day_off_weekdays: frozenset[int]
    hard_blocked_dates: frozenset[dt.date]
    soft_off_dates: frozenset[dt.date]
    core: bool


@dataclass(frozen=True, slots=True)
class _PlannerSettings:
    station_minimums: dict[str, int]
    morning_shift_codes: tuple[str, ...]
    morning_station_requirements: dict[str, int]
    min_staff_weekday: int | None
    min_staff_weekend: int | None
    max_staff_per_day: int | None
    min_rest_days_per_month: int | None
    max_consecutive_days: int | None
    require_one_chef: bool
    count_chefs_in_headcount: bool
    chefs_have_no_shift: bool


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
    worker_scheduling_states = _build_worker_scheduling_states(active_workers)
    settings = _build_planner_settings(
        planning_input.constraint_config,
        active_station_codes=active_station_codes,
        available_shift_codes=[shift.shift_code for shift in working_shifts],
    )
    morning_shift = _resolve_morning_shift(
        settings.morning_shift_codes,
        shifts_by_code=shifts_by_code,
    )
    ordinary_shift_pool = _resolve_ordinary_shift_pool(
        working_shifts,
        morning_shift_codes=settings.morning_shift_codes,
    )

    notes = {_BASELINE_NOTE}
    if (
        not settings.station_minimums
        and not settings.morning_station_requirements
        and active_station_codes
    ):
        notes.add(_DEFAULT_STATION_NOTE)

    assignments, warnings = _build_baseline_assignments(
        planning_input=planning_input,
        active_workers=active_workers,
        active_station_codes=active_station_codes,
        primary_shift=primary_shift,
        morning_shift=morning_shift,
        ordinary_shift_pool=ordinary_shift_pool,
        leave_dates_by_worker=leave_dates_by_worker,
        worker_scheduling_states=worker_scheduling_states,
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
            worker_scheduling_states=worker_scheduling_states,
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
    available_shift_codes: list[str],
) -> _PlannerSettings:
    return _PlannerSettings(
        station_minimums=_resolve_station_minimums(
            constraint_config.get("stations"),
            active_station_codes=active_station_codes,
        ),
        morning_shift_codes=_resolve_morning_shift_codes(
            constraint_config.get("morning_shifts"),
            available_shift_codes=available_shift_codes,
        ),
        morning_station_requirements=_resolve_morning_station_requirements(
            constraint_config.get("stations_require_morning"),
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
        require_one_chef=_coerce_bool(
            constraint_config.get("require_one_chef")
        ),
        count_chefs_in_headcount=_coerce_bool(
            constraint_config.get("count_chefs_in_headcount")
        ),
        chefs_have_no_shift=_coerce_bool(
            constraint_config.get("chefs_have_no_shift")
        ),
    )


def _build_baseline_assignments(
    *,
    planning_input: MonthPlanningInput,
    active_workers: list[WorkerInput],
    active_station_codes: list[str],
    primary_shift: ShiftInput | None,
    morning_shift: ShiftInput | None,
    ordinary_shift_pool: tuple[ShiftInput, ...],
    leave_dates_by_worker: dict[str, set[dt.date]],
    worker_scheduling_states: dict[str, _WorkerSchedulingState],
    settings: _PlannerSettings,
) -> tuple[list[AssignmentOutput], list[WarningOutput]]:
    assignments: list[AssignmentOutput] = []
    warnings: list[WarningOutput] = []
    chef_workers = [
        worker for worker in active_workers if _is_chef_worker(worker)
    ]
    assignable_station_workers = (
        [worker for worker in active_workers if not _is_chef_worker(worker)]
        if settings.chefs_have_no_shift
        else active_workers
    )
    morning_shift_codes = set(settings.morning_shift_codes)

    assignment_counts = {
        worker.worker_code: 0 for worker in active_workers
    }
    assigned_dates_by_worker = {
        worker.worker_code: set() for worker in active_workers
    }

    for assignment_date in _iter_month_dates(planning_input.year, planning_input.month):
        assigned_today: set[str] = set()
        assigned_station_counts: Counter[str] = Counter()
        assigned_morning_station_counts: Counter[str] = Counter()
        chef_assignment_counted_in_headcount = 0
        ordinary_shift_index = 0

        if settings.require_one_chef and settings.chefs_have_no_shift:
            chef_worker = _select_worker(
                assignment_date,
                candidate_workers=chef_workers,
                assigned_today=assigned_today,
                assignment_counts=assignment_counts,
                assigned_dates_by_worker=assigned_dates_by_worker,
                leave_dates_by_worker=leave_dates_by_worker,
                worker_scheduling_states=worker_scheduling_states,
                max_consecutive_days=settings.max_consecutive_days,
                shift_code=primary_shift.shift_code if primary_shift is not None else None,
            )
            if chef_worker is None or primary_shift is None:
                warnings.append(
                    _build_missing_required_chef_warning(assignment_date)
                )
            else:
                _append_assignment(
                    assignments,
                    assignment_date=assignment_date,
                    worker=chef_worker,
                    shift=primary_shift,
                    station_code=None,
                    note=_REQUIRED_CHEF_NOTE,
                    assigned_today=assigned_today,
                    assigned_station_counts=assigned_station_counts,
                    assigned_morning_station_counts=assigned_morning_station_counts,
                    assignment_counts=assignment_counts,
                    assigned_dates_by_worker=assigned_dates_by_worker,
                    morning_shift_codes=morning_shift_codes,
                )
                if settings.count_chefs_in_headcount:
                    chef_assignment_counted_in_headcount = 1

        required_station_slots = _build_required_station_slots(
            assignment_date,
            active_station_codes=active_station_codes,
            settings=settings,
            headcount_credit=chef_assignment_counted_in_headcount,
        )
        fillable_station_slots = list(required_station_slots)
        effective_max_staff = _resolve_effective_max_staff(
            settings.max_staff_per_day,
            headcount_credit=chef_assignment_counted_in_headcount,
        )
        if effective_max_staff is not None:
            fillable_station_slots = fillable_station_slots[:effective_max_staff]
        if primary_shift is None or not active_station_codes:
            fillable_station_slots = []

        remaining_station_slots = fillable_station_slots

        if settings.require_one_chef and not settings.chefs_have_no_shift:
            if fillable_station_slots:
                eligible_chef_workers = _build_eligible_workers(
                    assignment_date,
                    candidate_workers=chef_workers,
                    assigned_today=assigned_today,
                    assigned_dates_by_worker=assigned_dates_by_worker,
                    leave_dates_by_worker=leave_dates_by_worker,
                    worker_scheduling_states=worker_scheduling_states,
                    max_consecutive_days=settings.max_consecutive_days,
                )
                chef_slot_priority = _select_next_station_slot(
                    remaining_station_slots=fillable_station_slots,
                    eligible_workers=eligible_chef_workers,
                )
                if chef_slot_priority is None:
                    warnings.append(
                        _build_missing_required_chef_warning(assignment_date)
                    )
                    remaining_station_slots = fillable_station_slots
                else:
                    chef_slot = chef_slot_priority.slot
                    chef_shift = _resolve_station_slot_shift(
                        chef_slot,
                        assignment_date=assignment_date,
                        ordinary_shift_index=ordinary_shift_index,
                        morning_shift=morning_shift,
                        ordinary_shift_pool=ordinary_shift_pool,
                    )
                    chef_selection = _select_station_worker(
                        assignment_date,
                        station_slot=chef_slot,
                        slot_index=chef_slot_priority.slot_index,
                        eligible_workers=eligible_chef_workers,
                        remaining_station_slots=fillable_station_slots,
                        assignment_counts=assignment_counts,
                        assigned_dates_by_worker=assigned_dates_by_worker,
                        worker_scheduling_states=worker_scheduling_states,
                        slot_shift_code=(
                            chef_shift.shift_code if chef_shift is not None else None
                        ),
                    )
                    remaining_station_slots = (
                        fillable_station_slots[: chef_slot_priority.slot_index]
                        + fillable_station_slots[chef_slot_priority.slot_index + 1 :]
                    )
                    if chef_selection is None or chef_shift is None:
                        warnings.append(
                            _build_missing_required_chef_warning(assignment_date)
                        )
                    else:
                        _append_assignment(
                            assignments,
                            assignment_date=assignment_date,
                            worker=chef_selection.worker,
                            shift=chef_shift,
                            station_code=chef_slot.station_code,
                            note=chef_selection.note,
                            assigned_today=assigned_today,
                            assigned_station_counts=assigned_station_counts,
                            assigned_morning_station_counts=assigned_morning_station_counts,
                            assignment_counts=assignment_counts,
                            assigned_dates_by_worker=assigned_dates_by_worker,
                            morning_shift_codes=morning_shift_codes,
                        )
                        if not _slot_uses_configured_morning_shift(
                            chef_slot,
                            morning_shift=morning_shift,
                        ):
                            ordinary_shift_index += 1
            else:
                warnings.append(
                    _build_missing_required_chef_warning(assignment_date)
                )

        while remaining_station_slots:
            eligible_station_workers = _build_eligible_workers(
                assignment_date,
                candidate_workers=assignable_station_workers,
                assigned_today=assigned_today,
                assigned_dates_by_worker=assigned_dates_by_worker,
                leave_dates_by_worker=leave_dates_by_worker,
                worker_scheduling_states=worker_scheduling_states,
                max_consecutive_days=settings.max_consecutive_days,
            )
            if not eligible_station_workers:
                break

            station_slot_priority = _select_next_station_slot(
                remaining_station_slots=remaining_station_slots,
                eligible_workers=eligible_station_workers,
            )
            if station_slot_priority is None:
                break

            station_slot = station_slot_priority.slot
            shift = _resolve_station_slot_shift(
                station_slot,
                assignment_date=assignment_date,
                ordinary_shift_index=ordinary_shift_index,
                morning_shift=morning_shift,
                ordinary_shift_pool=ordinary_shift_pool,
            )
            worker_selection = _select_station_worker(
                assignment_date,
                station_slot=station_slot,
                slot_index=station_slot_priority.slot_index,
                eligible_workers=eligible_station_workers,
                remaining_station_slots=remaining_station_slots,
                assignment_counts=assignment_counts,
                assigned_dates_by_worker=assigned_dates_by_worker,
                worker_scheduling_states=worker_scheduling_states,
                slot_shift_code=shift.shift_code if shift is not None else None,
            )
            remaining_station_slots = (
                remaining_station_slots[: station_slot_priority.slot_index]
                + remaining_station_slots[station_slot_priority.slot_index + 1 :]
            )
            if not _slot_uses_configured_morning_shift(
                station_slot,
                morning_shift=morning_shift,
            ):
                ordinary_shift_index += 1
            if worker_selection is None or shift is None:
                continue

            _append_assignment(
                assignments,
                assignment_date=assignment_date,
                worker=worker_selection.worker,
                shift=shift,
                station_code=station_slot.station_code,
                note=worker_selection.note,
                assigned_today=assigned_today,
                assigned_station_counts=assigned_station_counts,
                assigned_morning_station_counts=assigned_morning_station_counts,
                assignment_counts=assignment_counts,
                assigned_dates_by_worker=assigned_dates_by_worker,
                morning_shift_codes=morning_shift_codes,
            )

        warnings.extend(
            _build_understaffed_station_warnings(
                assignment_date,
                required_station_slots=required_station_slots,
                assigned_station_counts=assigned_station_counts,
            )
        )
        warnings.extend(
            _build_missing_morning_station_warnings(
                assignment_date,
                morning_station_requirements=settings.morning_station_requirements,
                assigned_morning_station_counts=assigned_morning_station_counts,
            )
        )

    return assignments, warnings


def _build_required_station_slots(
    assignment_date: dt.date,
    *,
    active_station_codes: list[str],
    settings: _PlannerSettings,
    headcount_credit: int = 0,
) -> list[_RequiredStationSlot]:
    if not active_station_codes:
        return []

    target_headcount = max(
        _resolve_daily_minimum_staff(
            assignment_date,
            min_staff_weekday=settings.min_staff_weekday,
            min_staff_weekend=settings.min_staff_weekend,
        )
        - headcount_credit,
        0,
    )

    if settings.station_minimums or settings.morning_station_requirements:
        morning_slots: list[_RequiredStationSlot] = []
        ordinary_slots: list[_RequiredStationSlot] = []
        for station_code in active_station_codes:
            morning_requirement = settings.morning_station_requirements.get(
                station_code, 0
            )
            station_minimum = settings.station_minimums.get(station_code, 0)
            total_station_slots = max(station_minimum, morning_requirement)
            morning_slots.extend(
                _RequiredStationSlot(
                    station_code=station_code,
                    requires_morning=True,
                )
                for _ in range(morning_requirement)
            )
            ordinary_slots.extend(
                _RequiredStationSlot(
                    station_code=station_code,
                    requires_morning=False,
                )
                for _ in range(max(total_station_slots - morning_requirement, 0))
            )

        station_slots = morning_slots + ordinary_slots
        if target_headcount > len(station_slots):
            station_index = 0
            while len(station_slots) < target_headcount:
                station_slots.append(
                    _RequiredStationSlot(
                        station_code=active_station_codes[
                            station_index % len(active_station_codes)
                        ],
                        requires_morning=False,
                    )
                )
                station_index += 1
        return station_slots

    default_target = target_headcount if target_headcount > 0 else 1
    return [
        _RequiredStationSlot(
            station_code=active_station_codes[0],
            requires_morning=False,
        )
        for _ in range(default_target)
    ]


def _resolve_daily_minimum_staff(
    assignment_date: dt.date,
    *,
    min_staff_weekday: int | None,
    min_staff_weekend: int | None,
) -> int:
    if assignment_date.weekday() >= 5:
        return min_staff_weekend or 0
    return min_staff_weekday or 0


def _resolve_station_slot_shift(
    station_slot: _RequiredStationSlot,
    *,
    assignment_date: dt.date,
    ordinary_shift_index: int,
    morning_shift: ShiftInput | None,
    ordinary_shift_pool: tuple[ShiftInput, ...],
) -> ShiftInput | None:
    if _slot_uses_configured_morning_shift(
        station_slot,
        morning_shift=morning_shift,
    ):
        return morning_shift
    return _select_ordinary_shift_for_slot(
        assignment_date,
        ordinary_shift_index=ordinary_shift_index,
        ordinary_shift_pool=ordinary_shift_pool,
    )


def _slot_uses_configured_morning_shift(
    station_slot: _RequiredStationSlot,
    *,
    morning_shift: ShiftInput | None,
) -> bool:
    return station_slot.requires_morning and morning_shift is not None


def _select_ordinary_shift_for_slot(
    assignment_date: dt.date,
    *,
    ordinary_shift_index: int,
    ordinary_shift_pool: tuple[ShiftInput, ...],
) -> ShiftInput | None:
    if not ordinary_shift_pool:
        return None
    shift_index = (
        (assignment_date.day - 1) + ordinary_shift_index
    ) % len(ordinary_shift_pool)
    return ordinary_shift_pool[shift_index]


def _resolve_ordinary_shift_pool(
    working_shifts: list[ShiftInput],
    *,
    morning_shift_codes: tuple[str, ...],
) -> tuple[ShiftInput, ...]:
    morning_shift_code_set = set(morning_shift_codes)
    ordered_working_shifts = _sort_slot_shift_candidates(working_shifts)
    ordinary_shifts = tuple(
        shift
        for shift in ordered_working_shifts
        if shift.shift_code not in morning_shift_code_set
    )
    if ordinary_shifts:
        return ordinary_shifts
    return tuple(ordered_working_shifts)


def _sort_slot_shift_candidates(
    shifts: list[ShiftInput],
) -> list[ShiftInput]:
    return sorted(
        shifts,
        key=lambda shift: (
            shift.start_time is None,
            shift.start_time or dt.time.max,
            shift.shift_code,
        ),
    )


def _build_eligible_workers(
    assignment_date: dt.date,
    *,
    candidate_workers: list[WorkerInput],
    assigned_today: set[str],
    assigned_dates_by_worker: dict[str, set[dt.date]],
    leave_dates_by_worker: dict[str, set[dt.date]],
    worker_scheduling_states: dict[str, _WorkerSchedulingState],
    max_consecutive_days: int | None,
) -> list[WorkerInput]:
    return [
        worker
        for worker in candidate_workers
        if worker.worker_code not in assigned_today
        and not _is_worker_unavailable(
            assignment_date,
            worker_code=worker.worker_code,
            leave_dates_by_worker=leave_dates_by_worker,
            worker_scheduling_states=worker_scheduling_states,
        )
        and not _has_reached_consecutive_limit(
            assignment_date,
            assigned_dates=assigned_dates_by_worker[worker.worker_code],
            max_consecutive_days=max_consecutive_days,
        )
    ]


def _select_next_station_slot(
    *,
    remaining_station_slots: list[_RequiredStationSlot],
    eligible_workers: list[WorkerInput],
) -> _StationSlotPriority | None:
    if not remaining_station_slots or not eligible_workers:
        return None

    fallback_priority_count = len(remaining_station_slots) + 1
    slot_priorities: list[_StationSlotPriority] = []
    for slot_index, station_slot in enumerate(remaining_station_slots):
        skilled_workers = [
            worker
            for worker in eligible_workers
            if station_slot.station_code in worker.station_skills
        ]
        if skilled_workers:
            other_skill_option_counts = [
                _count_other_skill_slot_options(
                    worker,
                    remaining_station_slots=remaining_station_slots,
                    exclude_slot_index=slot_index,
                )
                for worker in skilled_workers
            ]
            slot_priorities.append(
                _StationSlotPriority(
                    slot_index=slot_index,
                    slot=station_slot,
                    skilled_candidate_count=len(skilled_workers),
                    min_other_skill_option_count=min(other_skill_option_counts),
                    total_other_skill_option_count=sum(other_skill_option_counts),
                )
            )
            continue

        slot_priorities.append(
            _StationSlotPriority(
                slot_index=slot_index,
                slot=station_slot,
                skilled_candidate_count=0,
                min_other_skill_option_count=fallback_priority_count,
                total_other_skill_option_count=fallback_priority_count,
            )
        )

    slot_priorities.sort(
        key=lambda priority: (
            0 if priority.slot.requires_morning else 1,
            0 if priority.skilled_candidate_count > 0 else 1,
            (
                priority.skilled_candidate_count
                if priority.skilled_candidate_count > 0
                else fallback_priority_count
            ),
            priority.min_other_skill_option_count,
            priority.total_other_skill_option_count,
            priority.slot.station_code,
            priority.slot_index,
        )
    )
    return slot_priorities[0]


def _select_station_worker(
    assignment_date: dt.date,
    *,
    station_slot: _RequiredStationSlot,
    slot_index: int,
    eligible_workers: list[WorkerInput],
    remaining_station_slots: list[_RequiredStationSlot],
    assignment_counts: dict[str, int],
    assigned_dates_by_worker: dict[str, set[dt.date]],
    worker_scheduling_states: dict[str, _WorkerSchedulingState],
    slot_shift_code: str | None,
) -> _StationWorkerSelection | None:
    if not eligible_workers:
        return None

    skilled_candidates = [
        worker
        for worker in eligible_workers
        if station_slot.station_code in worker.station_skills
    ]
    fallback_note: str | None = None
    candidate_pool = skilled_candidates
    if not candidate_pool:
        candidate_pool = list(eligible_workers)
        fallback_note = _FALLBACK_STATION_NOTE

    candidate_pool.sort(
        key=lambda worker: (
            _count_other_skill_slot_options(
                worker,
                remaining_station_slots=remaining_station_slots,
                exclude_slot_index=slot_index,
            ),
            *_build_worker_selection_key(
                worker,
                assignment_date=assignment_date,
                shift_code=slot_shift_code,
                assignment_counts=assignment_counts,
                assigned_dates_by_worker=assigned_dates_by_worker,
                worker_scheduling_states=worker_scheduling_states,
            ),
        )
    )
    return _StationWorkerSelection(
        worker=candidate_pool[0],
        note=fallback_note,
    )


def _count_other_skill_slot_options(
    worker: WorkerInput,
    *,
    remaining_station_slots: list[_RequiredStationSlot],
    exclude_slot_index: int,
) -> int:
    return sum(
        1
        for slot_position, station_slot in enumerate(remaining_station_slots)
        if slot_position != exclude_slot_index
        and station_slot.station_code in worker.station_skills
    )


def _select_worker(
    assignment_date: dt.date,
    *,
    candidate_workers: list[WorkerInput],
    assigned_today: set[str],
    assignment_counts: dict[str, int],
    assigned_dates_by_worker: dict[str, set[dt.date]],
    leave_dates_by_worker: dict[str, set[dt.date]],
    worker_scheduling_states: dict[str, _WorkerSchedulingState],
    max_consecutive_days: int | None,
    station_code: str | None = None,
    shift_code: str | None = None,
) -> WorkerInput | None:
    candidates = _build_eligible_workers(
        assignment_date,
        candidate_workers=candidate_workers,
        assigned_today=assigned_today,
        assigned_dates_by_worker=assigned_dates_by_worker,
        leave_dates_by_worker=leave_dates_by_worker,
        worker_scheduling_states=worker_scheduling_states,
        max_consecutive_days=max_consecutive_days,
    )
    if not candidates:
        return None

    candidates.sort(
        key=lambda worker: (
            0
            if station_code is None or station_code in worker.station_skills
            else 1,
            *_build_worker_selection_key(
                worker,
                assignment_date=assignment_date,
                shift_code=shift_code,
                assignment_counts=assignment_counts,
                assigned_dates_by_worker=assigned_dates_by_worker,
                worker_scheduling_states=worker_scheduling_states,
            ),
        )
    )
    return candidates[0]


def _build_worker_scheduling_states(
    active_workers: list[WorkerInput],
) -> dict[str, _WorkerSchedulingState]:
    return {
        worker.worker_code: _WorkerSchedulingState(
            preferred_shift_codes=frozenset(worker.scheduling_profile.shift_prefs),
            fixed_day_off_weekdays=frozenset(
                worker.scheduling_profile.fixed_day_off_weekdays
            ),
            hard_blocked_dates=frozenset(
                [
                    *worker.scheduling_profile.ad_hoc_unavailable,
                    *worker.scheduling_profile.wish_off.hard,
                ]
            ),
            soft_off_dates=frozenset(worker.scheduling_profile.wish_off.soft),
            core=worker.scheduling_profile.core,
        )
        for worker in active_workers
    }


def _is_worker_unavailable(
    assignment_date: dt.date,
    *,
    worker_code: str,
    leave_dates_by_worker: dict[str, set[dt.date]],
    worker_scheduling_states: dict[str, _WorkerSchedulingState],
) -> bool:
    if assignment_date in leave_dates_by_worker.get(worker_code, set()):
        return True
    worker_state = worker_scheduling_states.get(worker_code)
    if worker_state is None:
        return False
    if assignment_date.weekday() in worker_state.fixed_day_off_weekdays:
        return True
    return assignment_date in worker_state.hard_blocked_dates


def _build_worker_selection_key(
    worker: WorkerInput,
    *,
    assignment_date: dt.date,
    shift_code: str | None,
    assignment_counts: dict[str, int],
    assigned_dates_by_worker: dict[str, set[dt.date]],
    worker_scheduling_states: dict[str, _WorkerSchedulingState],
) -> tuple[int, int, int, int, int, str]:
    worker_state = worker_scheduling_states.get(worker.worker_code)
    soft_off_penalty = 0
    shift_pref_penalty = 0
    core_penalty = 1
    if worker_state is not None:
        soft_off_penalty = (
            1 if assignment_date in worker_state.soft_off_dates else 0
        )
        shift_pref_penalty = (
            1
            if shift_code is not None
            and worker_state.preferred_shift_codes
            and shift_code not in worker_state.preferred_shift_codes
            else 0
        )
        core_penalty = 0 if worker_state.core else 1

    return (
        assignment_counts[worker.worker_code],
        soft_off_penalty,
        shift_pref_penalty,
        _current_consecutive_streak(
            assignment_date,
            assigned_dates_by_worker[worker.worker_code],
        ),
        core_penalty,
        worker.worker_code,
    )


def _append_assignment(
    assignments: list[AssignmentOutput],
    *,
    assignment_date: dt.date,
    worker: WorkerInput,
    shift: ShiftInput,
    station_code: str | None,
    note: str | None,
    assigned_today: set[str],
    assigned_station_counts: Counter[str],
    assigned_morning_station_counts: Counter[str],
    assignment_counts: dict[str, int],
    assigned_dates_by_worker: dict[str, set[dt.date]],
    morning_shift_codes: set[str],
) -> None:
    assignments.append(
        AssignmentOutput(
            date=assignment_date,
            worker_code=worker.worker_code,
            shift_code=shift.shift_code,
            source=_SOURCE_TYPE,
            station_code=station_code,
            note=note,
        )
    )
    assigned_today.add(worker.worker_code)
    assignment_counts[worker.worker_code] += 1
    assigned_dates_by_worker[worker.worker_code].add(assignment_date)

    if station_code is None:
        return

    assigned_station_counts[station_code] += 1
    if shift.shift_code in morning_shift_codes:
        assigned_morning_station_counts[station_code] += 1


def _resolve_effective_max_staff(
    max_staff_per_day: int | None,
    *,
    headcount_credit: int,
) -> int | None:
    if max_staff_per_day is None:
        return None
    return max(max_staff_per_day - headcount_credit, 0)


def _build_missing_required_chef_warning(
    assignment_date: dt.date,
) -> WarningOutput:
    return WarningOutput(
        type="missing_required_chef",
        message_key="missing_required_chef",
        worker_code=None,
        date=assignment_date,
        details={"required_role": "chef"},
    )


def _build_missing_morning_station_warnings(
    assignment_date: dt.date,
    *,
    morning_station_requirements: dict[str, int],
    assigned_morning_station_counts: Counter[str],
) -> list[WarningOutput]:
    warnings: list[WarningOutput] = []
    for station_code in sorted(morning_station_requirements):
        required_staff = morning_station_requirements[station_code]
        assigned_staff = assigned_morning_station_counts.get(station_code, 0)
        if assigned_staff >= required_staff:
            continue
        warnings.append(
            WarningOutput(
                type="missing_morning_station_coverage",
                message_key="missing_morning_station_coverage",
                worker_code=None,
                date=assignment_date,
                details={
                    "station_code": station_code,
                    "required_morning_staff": required_staff,
                    "assigned_morning_staff": assigned_staff,
                    "missing_morning_staff": required_staff - assigned_staff,
                },
            )
        )
    return warnings


def _resolve_morning_shift(
    morning_shift_codes: tuple[str, ...],
    *,
    shifts_by_code: dict[str, ShiftInput],
) -> ShiftInput | None:
    for shift_code in morning_shift_codes:
        shift = shifts_by_code.get(shift_code)
        if shift is not None and not shift.is_off_shift:
            return shift
    return None


def _is_chef_worker(worker: WorkerInput) -> bool:
    # Keep chef-role detection narrow and explicit for this engine slice.
    return worker.role.strip().casefold() == "chef"


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
    required_station_slots: list[_RequiredStationSlot],
    assigned_station_counts: Counter[str],
) -> list[WarningOutput]:
    warnings: list[WarningOutput] = []
    required_station_counts = Counter(
        station_slot.station_code for station_slot in required_station_slots
    )
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
    worker_scheduling_states: dict[str, _WorkerSchedulingState],
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

        if _is_worker_unavailable(
            patch.date,
            worker_code=patch.worker_code,
            leave_dates_by_worker=leave_dates_by_worker,
            worker_scheduling_states=worker_scheduling_states,
        ):
            warnings.append(
                WarningOutput(
                    type="worker_unavailable_conflict",
                    message_key="worker_unavailable_conflict",
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


def _resolve_morning_shift_codes(
    raw_morning_shifts: object,
    *,
    available_shift_codes: list[str],
) -> tuple[str, ...]:
    if not isinstance(raw_morning_shifts, list):
        return ()

    allowed_shift_codes = set(available_shift_codes)
    seen_shift_codes: set[str] = set()
    morning_shift_codes: list[str] = []
    for raw_shift_code in raw_morning_shifts:
        if not isinstance(raw_shift_code, str):
            continue
        shift_code = raw_shift_code.strip()
        if not shift_code or shift_code in seen_shift_codes:
            continue
        if shift_code not in allowed_shift_codes:
            continue
        seen_shift_codes.add(shift_code)
        morning_shift_codes.append(shift_code)
    return tuple(morning_shift_codes)


def _resolve_morning_station_requirements(
    raw_station_config: object,
    *,
    active_station_codes: list[str],
) -> dict[str, int]:
    if not isinstance(raw_station_config, dict):
        return {}

    morning_station_requirements: dict[str, int] = {}
    for station_code in active_station_codes:
        morning_requirement = _coerce_non_negative_int(
            raw_station_config.get(station_code)
        )
        if morning_requirement is None or morning_requirement <= 0:
            continue
        morning_station_requirements[station_code] = morning_requirement
    return morning_station_requirements


def _coerce_non_negative_int(raw_value: object) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value if raw_value >= 0 else None
    if isinstance(raw_value, float) and raw_value.is_integer():
        return int(raw_value) if raw_value >= 0 else None
    return None


def _coerce_bool(raw_value: object) -> bool:
    return raw_value if isinstance(raw_value, bool) else False


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
