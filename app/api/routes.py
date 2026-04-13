"""Thin route-layer skeleton for the V2 monthly scheduling API.

This module stays intentionally framework-neutral. Route handlers accept API
schema objects, translate them into service-layer dataclasses, delegate to
injected services, and translate responses back into API schemas. The primary
runtime for V2 is Django, and the Django adapter should register these route
definitions without moving business logic into the transport layer.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from app.api.schemas import (
    ApiJsonObject,
    ApiSchema,
    ApplyMonthScheduleRequestSchema,
    ApplyMonthScheduleResponseSchema,
    ExportMonthScheduleRequestSchema,
    ExportMonthScheduleResponseSchema,
    ExportMonthScheduleRowSchema,
    MonthPlanningAssignmentSchema,
    MonthPlanningEvaluationSchema,
    MonthPlanningMetadataSchema,
    MonthPlanningResultSchema,
    MonthPlanningSummarySchema,
    MonthPlanningWarningSchema,
    PreviewMonthScheduleRequestSchema,
    PreviewMonthScheduleResponseSchema,
    RefineMonthScheduleRequestSchema,
    RefineMonthScheduleResponseSchema,
    SaveMonthScheduleRequestSchema,
    SaveMonthScheduleResponseSchema,
)
from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningEvaluation,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
    WarningOutput,
)
from app.services.apply import (
    ApplyMonthScheduleRequest as ApplyServiceRequest,
    ApplyMonthScheduleResponse as ApplyServiceResponse,
    ApplyMonthScheduleService,
)
from app.services.export import (
    ExportMonthScheduleRequest as ExportServiceRequest,
    ExportMonthScheduleResponse as ExportServiceResponse,
    ExportMonthScheduleRow as ExportServiceRow,
    ExportMonthScheduleService,
)
from app.services.preview import (
    PreviewMonthScheduleRequest as PreviewServiceRequest,
    PreviewMonthScheduleResponse as PreviewServiceResponse,
    PreviewMonthScheduleService,
)
from app.services.refine import (
    RefineMonthScheduleRequest as RefineServiceRequest,
    RefineMonthScheduleResponse as RefineServiceResponse,
    RefineMonthScheduleService,
)
from app.services.save import (
    SaveMonthScheduleRequest as SaveServiceRequest,
    SaveMonthScheduleResponse as SaveServiceResponse,
    SaveMonthScheduleService,
)

_MONTHLY_SCHEDULE_BASE_PATH = "/v2/monthly-schedules"


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    """Minimal route metadata for the Django-first HTTP adapter layer.

    Method and path values are placeholders that make the transport boundary
    explicit while keeping request/response translation reusable outside Django
    when needed for tests or internal callers.
    """

    name: str
    method: str
    path: str
    request_schema: type[ApiSchema]
    response_schema: type[ApiSchema]
    handler: Callable[..., object]


@dataclass(slots=True)
class MonthlyScheduleRoutes:
    """Framework-neutral route bundle consumed by the Django-first runtime."""

    preview_service: PreviewMonthScheduleService
    apply_service: ApplyMonthScheduleService
    save_service: SaveMonthScheduleService
    refine_service: RefineMonthScheduleService | None = None
    export_service: ExportMonthScheduleService | None = None

    def route_definitions(self) -> tuple[RouteDefinition, ...]:
        """Return the minimal route table the Django adapter can register."""

        route_definitions: list[RouteDefinition] = [
            RouteDefinition(
                name="preview_month_schedule",
                method="POST",
                path=f"{_MONTHLY_SCHEDULE_BASE_PATH}/preview",
                request_schema=PreviewMonthScheduleRequestSchema,
                response_schema=PreviewMonthScheduleResponseSchema,
                handler=self.preview_month_schedule,
            ),
            RouteDefinition(
                name="apply_month_schedule",
                method="POST",
                path=f"{_MONTHLY_SCHEDULE_BASE_PATH}/apply",
                request_schema=ApplyMonthScheduleRequestSchema,
                response_schema=ApplyMonthScheduleResponseSchema,
                handler=self.apply_month_schedule,
            ),
            RouteDefinition(
                name="save_month_schedule",
                method="POST",
                path=f"{_MONTHLY_SCHEDULE_BASE_PATH}/save",
                request_schema=SaveMonthScheduleRequestSchema,
                response_schema=SaveMonthScheduleResponseSchema,
                handler=self.save_month_schedule,
            ),
        ]
        if self.refine_service is not None:
            route_definitions.append(
                RouteDefinition(
                    name="refine_month_schedule",
                    method="POST",
                    path=f"{_MONTHLY_SCHEDULE_BASE_PATH}/refine",
                    request_schema=RefineMonthScheduleRequestSchema,
                    response_schema=RefineMonthScheduleResponseSchema,
                    handler=self.refine_month_schedule,
                )
            )
        if self.export_service is not None:
            route_definitions.append(
                RouteDefinition(
                    name="export_month_schedule",
                    method="POST",
                    path=f"{_MONTHLY_SCHEDULE_BASE_PATH}/export",
                    request_schema=ExportMonthScheduleRequestSchema,
                    response_schema=ExportMonthScheduleResponseSchema,
                    handler=self.export_month_schedule,
                )
            )
        return tuple(route_definitions)

    def preview_month_schedule(
        self,
        request: PreviewMonthScheduleRequestSchema,
    ) -> PreviewMonthScheduleResponseSchema:
        """Translate preview transport input into one service call."""

        service_response = self.preview_service.preview_month_schedule(
            _map_preview_request_to_service(request)
        )
        return _map_preview_response_to_api(service_response)

    def apply_month_schedule(
        self,
        request: ApplyMonthScheduleRequestSchema,
    ) -> ApplyMonthScheduleResponseSchema:
        """Translate apply transport input into one service call."""

        service_response = self.apply_service.apply_month_schedule(
            _map_apply_request_to_service(request)
        )
        return _map_apply_response_to_api(service_response)

    def save_month_schedule(
        self,
        request: SaveMonthScheduleRequestSchema,
    ) -> SaveMonthScheduleResponseSchema:
        """Translate save transport input into one service call."""

        service_response = self.save_service.save_month_schedule(
            _map_save_request_to_service(request)
        )
        return _map_save_response_to_api(service_response)

    def refine_month_schedule(
        self,
        request: RefineMonthScheduleRequestSchema,
    ) -> RefineMonthScheduleResponseSchema:
        """Translate refine transport input into one service call."""

        if self.refine_service is None:
            raise RuntimeError("Refine month schedule route is not wired.")
        service_response = self.refine_service.refine_month_schedule(
            _map_refine_request_to_service(request)
        )
        return _map_refine_response_to_api(service_response)

    def export_month_schedule(
        self,
        request: ExportMonthScheduleRequestSchema,
    ) -> ExportMonthScheduleResponseSchema:
        """Translate export transport input into one service call."""

        if self.export_service is None:
            raise RuntimeError("Export month schedule route is not wired.")
        service_response = self.export_service.export_month_schedule(
            _map_export_request_to_service(request)
        )
        return _map_export_response_to_api(service_response)


def build_month_schedule_routes(
    *,
    preview_service: PreviewMonthScheduleService,
    apply_service: ApplyMonthScheduleService,
    save_service: SaveMonthScheduleService,
    refine_service: RefineMonthScheduleService | None = None,
    export_service: ExportMonthScheduleService | None = None,
) -> MonthlyScheduleRoutes:
    """Create the route bundle without introducing Django startup wiring.

    The Django-first runtime can wire a partial vertical slice by omitting
    services whose endpoints remain deferred for a later PR.
    """

    return MonthlyScheduleRoutes(
        preview_service=preview_service,
        apply_service=apply_service,
        save_service=save_service,
        refine_service=refine_service,
        export_service=export_service,
    )


def _map_preview_request_to_service(
    request: PreviewMonthScheduleRequestSchema,
) -> PreviewServiceRequest:
    """Convert preview API input into the preview service request shape."""

    return PreviewServiceRequest(
        tenant_slug=request.tenant_slug,
        year=request.year,
        month=request.month,
    )


def _map_apply_request_to_service(
    request: ApplyMonthScheduleRequestSchema,
) -> ApplyServiceRequest:
    """Convert apply API input into the apply service request shape."""

    return ApplyServiceRequest(
        tenant_slug=request.tenant_slug,
        year=request.year,
        month=request.month,
        result=_map_month_planning_result_to_contract(request.result),
    )


def _map_save_request_to_service(
    request: SaveMonthScheduleRequestSchema,
) -> SaveServiceRequest:
    """Convert save API input into the save service request shape."""

    return SaveServiceRequest(
        tenant_slug=request.tenant_slug,
        year=request.year,
        month=request.month,
        label=request.label,
        note=request.note,
    )


def _map_refine_request_to_service(
    request: RefineMonthScheduleRequestSchema,
) -> RefineServiceRequest:
    """Convert refine API input into the refine service request shape."""

    return RefineServiceRequest(
        tenant_slug=request.tenant_slug,
        year=request.year,
        month=request.month,
        request_text=request.request_text,
    )


def _map_export_request_to_service(
    request: ExportMonthScheduleRequestSchema,
) -> ExportServiceRequest:
    """Convert export API input into the export service request shape."""

    return ExportServiceRequest(
        tenant_slug=request.tenant_slug,
        year=request.year,
        month=request.month,
    )


def _map_preview_response_to_api(
    response: PreviewServiceResponse,
) -> PreviewMonthScheduleResponseSchema:
    """Convert the preview service result into an API response schema."""

    return PreviewMonthScheduleResponseSchema(
        request=PreviewMonthScheduleRequestSchema(
            tenant_slug=response.request.tenant_slug,
            year=response.request.year,
            month=response.request.month,
        ),
        result=_map_month_planning_result_to_schema(response.result),
    )


def _map_apply_response_to_api(
    response: ApplyServiceResponse,
) -> ApplyMonthScheduleResponseSchema:
    """Convert the apply service result into an API response schema."""

    return ApplyMonthScheduleResponseSchema(
        tenant_slug=response.tenant_slug,
        year=response.year,
        month=response.month,
        workspace_id=response.workspace_id,
        workspace_status=response.workspace_status,
        assignment_count=response.assignment_count,
        warning_count=response.warning_count,
        workspace_created=response.workspace_created,
    )


def _map_save_response_to_api(
    response: SaveServiceResponse,
) -> SaveMonthScheduleResponseSchema:
    """Convert the save service result into an API response schema."""

    return SaveMonthScheduleResponseSchema(
        tenant_slug=response.tenant_slug,
        year=response.year,
        month=response.month,
        version_id=response.version_id,
        version_number=response.version_number,
        workspace_id=response.workspace_id,
        assignment_count=response.assignment_count,
    )


def _map_refine_response_to_api(
    response: RefineServiceResponse,
) -> RefineMonthScheduleResponseSchema:
    """Convert the refine service result into an API response schema."""

    return RefineMonthScheduleResponseSchema(
        tenant_slug=response.tenant_slug,
        year=response.year,
        month=response.month,
        workspace_id=response.workspace_id,
        refine_request_id=response.refine_request_id,
        status=response.status,
        parsed_intent_json=_copy_json_object(response.parsed_intent_json),
        candidate_result=_map_month_planning_result_to_schema(
            response.candidate_result
        ),
    )


def _map_export_response_to_api(
    response: ExportServiceResponse,
) -> ExportMonthScheduleResponseSchema:
    """Convert the export service result into an API response schema."""

    return ExportMonthScheduleResponseSchema(
        tenant_slug=response.tenant_slug,
        year=response.year,
        month=response.month,
        workspace_id=response.workspace_id,
        workspace_status=response.workspace_status,
        row_count=response.row_count,
        rows=[_map_export_row_to_schema(row) for row in response.rows],
        csv_text=response.csv_text,
    )


def _map_month_planning_result_to_contract(
    result: MonthPlanningResultSchema,
) -> MonthPlanningResult:
    """Translate API result payloads back into the engine/service contract."""

    return MonthPlanningResult(
        assignments=[
            AssignmentOutput(
                date=assignment.date,
                worker_code=assignment.worker_code,
                shift_code=assignment.shift_code,
                source=assignment.source,
                station_code=assignment.station_code,
                note=assignment.note,
            )
            for assignment in result.assignments
        ],
        warnings=[
            WarningOutput(
                type=warning.type,
                message_key=warning.message_key,
                worker_code=warning.worker_code,
                date=warning.date,
                details=_copy_json_object(warning.details),
            )
            for warning in result.warnings
        ],
        summary=MonthPlanningSummary(
            total_assignments=result.summary.total_assignments,
            total_warnings=result.summary.total_warnings,
            assignments_by_worker=dict(result.summary.assignments_by_worker),
            paid_hours_by_worker=dict(result.summary.paid_hours_by_worker),
            warnings_by_type=dict(result.summary.warnings_by_type),
        ),
        metadata=MonthPlanningMetadata(
            generated_at=result.metadata.generated_at,
            source_type=result.metadata.source_type,
            refinement_applied=result.metadata.refinement_applied,
            notes=list(result.metadata.notes) if result.metadata.notes else None,
        ),
        evaluation=(
            MonthPlanningEvaluation(
                duplicate_assignment_conflicts=(
                    result.evaluation.duplicate_assignment_conflicts
                ),
                workspace_state_integrity_violations=(
                    result.evaluation.workspace_state_integrity_violations
                ),
                understaffed_station_days=result.evaluation.understaffed_station_days,
                workers_below_min_days_off=(
                    result.evaluation.workers_below_min_days_off
                ),
                total_warnings=result.evaluation.total_warnings,
                warnings_by_type=dict(result.evaluation.warnings_by_type),
                assignments_by_worker=dict(result.evaluation.assignments_by_worker),
                paid_hours_by_worker=dict(result.evaluation.paid_hours_by_worker),
                max_minus_min_assignment_gap=(
                    result.evaluation.max_minus_min_assignment_gap
                ),
                max_minus_min_paid_hours_gap=(
                    result.evaluation.max_minus_min_paid_hours_gap
                ),
                covered_station_days=result.evaluation.covered_station_days,
                hard_constraints_passed=result.evaluation.hard_constraints_passed,
                soft_warnings_present=result.evaluation.soft_warnings_present,
                schedule_quality_label=result.evaluation.schedule_quality_label,
            )
            if result.evaluation is not None
            else None
        ),
    )


def _map_month_planning_result_to_schema(
    result: MonthPlanningResult,
) -> MonthPlanningResultSchema:
    """Translate the engine/service result contract into API response shape."""

    return MonthPlanningResultSchema(
        assignments=[
            MonthPlanningAssignmentSchema(
                date=assignment.date,
                worker_code=assignment.worker_code,
                shift_code=assignment.shift_code,
                source=assignment.source,
                station_code=assignment.station_code,
                note=assignment.note,
            )
            for assignment in result.assignments
        ],
        warnings=[
            MonthPlanningWarningSchema(
                type=warning.type,
                message_key=warning.message_key,
                worker_code=warning.worker_code,
                date=warning.date,
                details=_copy_json_object(warning.details),
            )
            for warning in result.warnings
        ],
        summary=MonthPlanningSummarySchema(
            total_assignments=result.summary.total_assignments,
            total_warnings=result.summary.total_warnings,
            assignments_by_worker=dict(result.summary.assignments_by_worker),
            paid_hours_by_worker=dict(result.summary.paid_hours_by_worker),
            warnings_by_type=dict(result.summary.warnings_by_type),
        ),
        metadata=MonthPlanningMetadataSchema(
            generated_at=result.metadata.generated_at,
            source_type=result.metadata.source_type,
            refinement_applied=result.metadata.refinement_applied,
            notes=list(result.metadata.notes) if result.metadata.notes else None,
        ),
        evaluation=(
            MonthPlanningEvaluationSchema(
                duplicate_assignment_conflicts=(
                    result.evaluation.duplicate_assignment_conflicts
                ),
                workspace_state_integrity_violations=(
                    result.evaluation.workspace_state_integrity_violations
                ),
                understaffed_station_days=result.evaluation.understaffed_station_days,
                workers_below_min_days_off=(
                    result.evaluation.workers_below_min_days_off
                ),
                total_warnings=result.evaluation.total_warnings,
                warnings_by_type=dict(result.evaluation.warnings_by_type),
                assignments_by_worker=dict(result.evaluation.assignments_by_worker),
                paid_hours_by_worker=dict(result.evaluation.paid_hours_by_worker),
                max_minus_min_assignment_gap=(
                    result.evaluation.max_minus_min_assignment_gap
                ),
                max_minus_min_paid_hours_gap=(
                    result.evaluation.max_minus_min_paid_hours_gap
                ),
                covered_station_days=result.evaluation.covered_station_days,
                hard_constraints_passed=result.evaluation.hard_constraints_passed,
                soft_warnings_present=result.evaluation.soft_warnings_present,
                schedule_quality_label=result.evaluation.schedule_quality_label,
            )
            if result.evaluation is not None
            else None
        ),
    )


def _map_export_row_to_schema(row: ExportServiceRow) -> ExportMonthScheduleRowSchema:
    """Translate one export row into the API-facing schema."""

    return ExportMonthScheduleRowSchema(
        assignment_date=_coerce_date(row.assignment_date),
        worker_code=row.worker_code,
        worker_name=row.worker_name,
        worker_role=row.worker_role,
        shift_code=row.shift_code,
        shift_name=row.shift_name,
        station_code=row.station_code,
        station_name=row.station_name,
    )


def _coerce_date(value: dt.date | str) -> dt.date:
    """Normalize service-export dates into the API schema date type."""

    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)


def _copy_json_object(value: ApiJsonObject | None) -> ApiJsonObject | None:
    """Copy JSON-like objects at the transport boundary to avoid aliasing."""

    if value is None:
        return None
    return dict(value)


__all__ = [
    "MonthlyScheduleRoutes",
    "RouteDefinition",
    "build_month_schedule_routes",
]
