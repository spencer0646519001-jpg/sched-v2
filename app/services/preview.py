"""Read-only preview orchestration for monthly schedule generation.

The preview service assembles persistence-side month inputs, translates them
into pure engine contracts, invokes the engine boundary, and returns the
computed preview without mutating workspace state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.engine.contracts import (
    LeaveRequestInput,
    MonthPlanningInput,
    MonthPlanningResult,
    ShiftInput,
    StationInput,
    WorkerInput,
    WorkerSchedulingProfileInput,
    WorkerWishOffInput,
)
from app.engine.evaluation import attach_month_planning_evaluation
from app.infra.models import RecordId, Station, Tenant, Worker
from app.infra.repositories import (
    ConstraintConfigRepository,
    LeaveRequestRepository,
    MonthlyPlanningPersistenceBundle,
    ShiftRepository,
    StationRepository,
    TenantRepository,
    WorkerRepository,
)

_WEEKDAY_LOOKUP = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


class MonthlySchedulePreviewEngine(Protocol):
    """Callable engine boundary consumed by the preview service."""

    def __call__(self, planning_input: MonthPlanningInput) -> MonthPlanningResult:
        ...


@dataclass(slots=True)
class PreviewMonthScheduleRequest:
    """Read-only request for computing one tenant/month preview."""

    tenant_slug: str
    year: int
    month: int


@dataclass(slots=True)
class PreviewMonthScheduleResponse:
    """Preview payload returned by the service layer.

    The persisted contract field remains `result`, but the preview semantics
    are explicitly candidate-oriented because preview does not mutate current
    workspace state.
    """

    request: PreviewMonthScheduleRequest
    result: MonthPlanningResult

    @property
    def candidate_result(self) -> MonthPlanningResult:
        """Expose the preview payload with explicit candidate semantics."""

        return self.result


@dataclass(slots=True)
class PreviewMonthScheduleService:
    """Orchestrates the read/compute-only monthly preview flow.

    This service intentionally depends only on read repositories plus an engine
    callable. It does not load or write mutable workspace state.
    """

    tenant_repository: TenantRepository
    worker_repository: WorkerRepository
    station_repository: StationRepository
    shift_repository: ShiftRepository
    leave_request_repository: LeaveRequestRepository
    constraint_config_repository: ConstraintConfigRepository
    engine_runner: MonthlySchedulePreviewEngine

    def preview_month_schedule(
        self,
        request: PreviewMonthScheduleRequest,
    ) -> PreviewMonthScheduleResponse:
        """Load monthly inputs, invoke the engine, and return a candidate preview."""

        _validate_request(request)

        tenant = self.tenant_repository.get_by_slug(request.tenant_slug)
        if tenant is None:
            raise LookupError(f"Tenant not found: {request.tenant_slug!r}")

        bundle = self._load_monthly_persistence_bundle(
            tenant=tenant,
            year=request.year,
            month=request.month,
        )
        planning_input = _translate_persistence_bundle_to_engine_input(bundle)
        preview_result = attach_month_planning_evaluation(
            self.engine_runner(planning_input)
        )

        return PreviewMonthScheduleResponse(request=request, result=preview_result)

    def _load_monthly_persistence_bundle(
        self,
        *,
        tenant: Tenant,
        year: int,
        month: int,
    ) -> MonthlyPlanningPersistenceBundle:
        """Gather the persistence-side snapshot needed for one preview run."""

        tenant_id = _require_record_id(tenant.id, label="tenant.id")
        constraint_config = self.constraint_config_repository.get_resolved_for_month(
            tenant_id,
            year,
            month,
        )
        if constraint_config is None:
            raise LookupError(
                f"No resolved constraint config found for {tenant.slug!r} "
                f"{year}-{month:02d}."
            )

        return MonthlyPlanningPersistenceBundle(
            tenant=tenant,
            year=year,
            month=month,
            workers=self.worker_repository.list_for_tenant(tenant_id),
            worker_station_skills=self.worker_repository.list_station_skills(tenant_id),
            stations=self.station_repository.list_for_tenant(tenant_id),
            shifts=self.shift_repository.list_for_tenant(tenant_id),
            leave_requests=self.leave_request_repository.list_for_month(
                tenant_id,
                year,
                month,
            ),
            constraint_config=constraint_config,
        )


def preview_month_schedule(
    request: PreviewMonthScheduleRequest,
    *,
    service: PreviewMonthScheduleService,
) -> PreviewMonthScheduleResponse:
    """Thin functional wrapper around the preview service boundary."""

    return service.preview_month_schedule(request)


def _translate_persistence_bundle_to_engine_input(
    bundle: MonthlyPlanningPersistenceBundle,
) -> MonthPlanningInput:
    """Translate persistence records into the pure engine month contract.

    TODO: Extract this translator if additional services need the same
    persistence-to-engine mapping.
    """

    station_codes_by_id = {
        _require_record_id(station.id, label="station.id"): _resolve_station_code(
            station
        )
        for station in bundle.stations
    }

    station_skills_by_worker_id: dict[RecordId, list[str]] = {}
    for skill in bundle.worker_station_skills:
        station_code = station_codes_by_id.get(skill.station_id)
        if station_code is None:
            raise LookupError(
                f"Worker skill references unknown station_id {skill.station_id!r}."
            )
        station_skills_by_worker_id.setdefault(skill.worker_id, []).append(
            station_code
        )

    available_shift_codes = {
        shift.code
        for shift in bundle.shifts
        if shift.is_active and not shift.is_off_shift
    }
    worker_codes_by_id: dict[RecordId, str] = {}
    worker_inputs: list[WorkerInput] = []
    for worker in bundle.workers:
        worker_id = _require_record_id(worker.id, label="worker.id")
        worker_code = _resolve_worker_code(worker)
        worker_codes_by_id[worker_id] = worker_code
        worker_inputs.append(
            WorkerInput(
                worker_code=worker_code,
                name=worker.name,
                role=worker.role,
                is_active=worker.is_active,
                station_skills=station_skills_by_worker_id.get(worker_id, []),
                scheduling_profile=_normalize_worker_scheduling_profile(
                    worker.scheduling_profile_json,
                    year=bundle.year,
                    month=bundle.month,
                    available_shift_codes=available_shift_codes,
                ),
            )
        )

    station_inputs = [
        StationInput(
            station_code=_resolve_station_code(station),
            name=station.name,
            is_active=station.is_active,
        )
        for station in bundle.stations
    ]

    shift_inputs = [
        ShiftInput(
            shift_code=shift.code,
            name=shift.name,
            paid_hours=shift.paid_hours,
            is_off_shift=shift.is_off_shift,
            start_time=shift.start_time,
            end_time=shift.end_time,
        )
        for shift in bundle.shifts
        if shift.is_active
    ]

    leave_request_inputs: list[LeaveRequestInput] = []
    for leave_request in bundle.leave_requests:
        worker_code = worker_codes_by_id.get(leave_request.worker_id)
        if worker_code is None:
            raise LookupError(
                f"Leave request references unknown worker_id "
                f"{leave_request.worker_id!r}."
            )
        leave_request_inputs.append(
            LeaveRequestInput(
                worker_code=worker_code,
                date=leave_request.leave_date,
                leave_type=leave_request.reason or "leave",
            )
        )

    return MonthPlanningInput(
        tenant_code=bundle.tenant.slug,
        year=bundle.year,
        month=bundle.month,
        workers=worker_inputs,
        stations=station_inputs,
        shifts=shift_inputs,
        leave_requests=leave_request_inputs,
        constraint_config=bundle.constraint_config.config_json,
        adjustment_patch=None,
    )


def _validate_request(request: PreviewMonthScheduleRequest) -> None:
    """Guard the service boundary against invalid calendar inputs."""

    if request.year < 1:
        raise ValueError("Preview year must be greater than zero.")
    if request.month < 1 or request.month > 12:
        raise ValueError("Preview month must be between 1 and 12.")


def _normalize_worker_scheduling_profile(
    raw_profile_json: object,
    *,
    year: int,
    month: int,
    available_shift_codes: set[str],
) -> WorkerSchedulingProfileInput:
    if not isinstance(raw_profile_json, dict):
        return WorkerSchedulingProfileInput()

    raw_wish_off = raw_profile_json.get("wish_off")
    wish_off = raw_wish_off if isinstance(raw_wish_off, dict) else {}
    return WorkerSchedulingProfileInput(
        shift_prefs=_normalize_shift_prefs(
            raw_profile_json.get("shift_prefs"),
            available_shift_codes=available_shift_codes,
        ),
        fixed_day_off_weekdays=_normalize_fixed_days_off(
            raw_profile_json.get("fixed_days_off")
        ),
        ad_hoc_unavailable=_normalize_profile_dates(
            raw_profile_json.get("ad_hoc_unavailable"),
            year=year,
            month=month,
        ),
        wish_off=WorkerWishOffInput(
            hard=_normalize_profile_dates(
                wish_off.get("hard"),
                year=year,
                month=month,
            ),
            soft=_normalize_profile_dates(
                wish_off.get("soft"),
                year=year,
                month=month,
            ),
        ),
        core=bool(raw_profile_json.get("core", False)),
    )


def _normalize_shift_prefs(
    raw_shift_prefs: object,
    *,
    available_shift_codes: set[str],
) -> list[str]:
    if not isinstance(raw_shift_prefs, list):
        return []

    shift_codes_by_key = {
        shift_code.strip().casefold(): shift_code
        for shift_code in available_shift_codes
        if shift_code.strip()
    }
    normalized_shift_prefs: list[str] = []
    seen_shift_codes: set[str] = set()
    for raw_shift_code in raw_shift_prefs:
        if not isinstance(raw_shift_code, str):
            continue
        shift_code = shift_codes_by_key.get(raw_shift_code.strip().casefold())
        if shift_code is None or shift_code in seen_shift_codes:
            continue
        seen_shift_codes.add(shift_code)
        normalized_shift_prefs.append(shift_code)
    return normalized_shift_prefs


def _normalize_fixed_days_off(raw_fixed_days_off: object) -> list[int]:
    if not isinstance(raw_fixed_days_off, list):
        return []

    normalized_weekdays: list[int] = []
    seen_weekdays: set[int] = set()
    for raw_weekday in raw_fixed_days_off:
        weekday_index = _coerce_weekday_index(raw_weekday)
        if weekday_index is None or weekday_index in seen_weekdays:
            continue
        seen_weekdays.add(weekday_index)
        normalized_weekdays.append(weekday_index)
    return normalized_weekdays


def _coerce_weekday_index(raw_weekday: object) -> int | None:
    if isinstance(raw_weekday, int) and 0 <= raw_weekday <= 6:
        return raw_weekday
    if not isinstance(raw_weekday, str):
        return None
    weekday_key = raw_weekday.strip().casefold()
    if not weekday_key:
        return None
    return _WEEKDAY_LOOKUP.get(weekday_key)


def _normalize_profile_dates(
    raw_dates: object,
    *,
    year: int,
    month: int,
) -> list[date]:
    if not isinstance(raw_dates, list):
        return []

    normalized_dates: list[date] = []
    seen_dates: set[date] = set()
    for raw_value in raw_dates:
        parsed_date = _parse_profile_date(raw_value)
        if parsed_date is None:
            continue
        if parsed_date.year != year or parsed_date.month != month:
            continue
        if parsed_date in seen_dates:
            continue
        seen_dates.add(parsed_date)
        normalized_dates.append(parsed_date)
    return normalized_dates


def _parse_profile_date(raw_value: object) -> date | None:
    if isinstance(raw_value, date):
        return raw_value
    if not isinstance(raw_value, str):
        return None
    normalized = raw_value.strip().replace("/", "-")
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _resolve_worker_code(worker: Worker) -> str:
    """Choose the engine identifier for a worker at the service boundary."""

    return _coalesce_engine_code(worker.code, worker.id, label="worker")


def _resolve_station_code(station: Station) -> str:
    """Choose the engine identifier for a station at the service boundary."""

    return _coalesce_engine_code(station.code, station.id, label="station")


def _coalesce_engine_code(
    code: str | None,
    record_id: RecordId | None,
    *,
    label: str,
) -> str:
    """Prefer business codes, falling back to persisted IDs for preview wiring."""

    if code:
        return code
    if record_id:
        return record_id
    raise ValueError(f"{label.capitalize()} requires either a code or persisted id.")


def _require_record_id(record_id: RecordId | None, *, label: str) -> RecordId:
    """Ensure repository-loaded records can be used for downstream lookups."""

    if record_id is None:
        raise ValueError(f"{label} must be populated on repository results.")
    return record_id


__all__ = [
    "MonthlySchedulePreviewEngine",
    "PreviewMonthScheduleRequest",
    "PreviewMonthScheduleResponse",
    "PreviewMonthScheduleService",
    "preview_month_schedule",
]
