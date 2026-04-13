"""Read-only preview orchestration for monthly schedule generation.

The preview service assembles persistence-side month inputs, translates them
into pure engine contracts, invokes the engine boundary, and returns the
computed preview without mutating workspace state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.engine.contracts import (
    LeaveRequestInput,
    MonthPlanningInput,
    MonthPlanningResult,
    ShiftInput,
    StationInput,
    WorkerInput,
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
    """Preview payload returned by the service layer."""

    request: PreviewMonthScheduleRequest
    result: MonthPlanningResult


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
        """Load monthly inputs, invoke the engine, and return a preview."""

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
