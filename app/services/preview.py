"""Read-only preview orchestration for monthly schedule generation.

The preview service loads shared monthly context, invokes the engine boundary,
and returns the computed preview without mutating workspace state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.engine.contracts import MonthPlanningInput, MonthPlanningResult
from app.engine.evaluation import attach_month_planning_evaluation
from app.infra.repositories import (
    ConstraintConfigRepository,
    LeaveRequestRepository,
    ShiftRepository,
    StationRepository,
    TenantRepository,
    WorkerRepository,
)
from app.services.monthly_context import (
    build_month_planning_input,
    load_monthly_planning_bundle,
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

        bundle = load_monthly_planning_bundle(
            tenant=tenant,
            year=request.year,
            month=request.month,
            worker_repository=self.worker_repository,
            station_repository=self.station_repository,
            shift_repository=self.shift_repository,
            leave_request_repository=self.leave_request_repository,
            constraint_config_repository=self.constraint_config_repository,
        )
        planning_input = build_month_planning_input(bundle)
        preview_result = attach_month_planning_evaluation(
            self.engine_runner(planning_input)
        )

        return PreviewMonthScheduleResponse(request=request, result=preview_result)


def preview_month_schedule(
    request: PreviewMonthScheduleRequest,
    *,
    service: PreviewMonthScheduleService,
) -> PreviewMonthScheduleResponse:
    """Thin functional wrapper around the preview service boundary."""

    return service.preview_month_schedule(request)


def _validate_request(request: PreviewMonthScheduleRequest) -> None:
    """Guard the service boundary against invalid calendar inputs."""

    if request.year < 1:
        raise ValueError("Preview year must be greater than zero.")
    if request.month < 1 or request.month > 12:
        raise ValueError("Preview month must be between 1 and 12.")


__all__ = [
    "MonthlySchedulePreviewEngine",
    "PreviewMonthScheduleRequest",
    "PreviewMonthScheduleResponse",
    "PreviewMonthScheduleService",
    "preview_month_schedule",
]
