"""Refine orchestration for natural-language monthly schedule adjustments.

The refine service accepts a free-form adjustment request, stores it as a
`RefineRequest`, delegates interpretation to a parser boundary, reruns the
engine with a lightweight adjustment patch, and persists the candidate preview.
It does not mutate the current workspace and it does not create saved versions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from app.engine.contracts import (
    AssignmentPatchInput,
    MonthPlanningInput,
    MonthPlanningResult,
)
from app.infra.models import JsonObject, RecordId, RefineRequest, Tenant
from app.infra.repositories import (
    ConstraintConfigRepository,
    LeaveRequestRepository,
    MonthlyPlanningPersistenceBundle,
    RefineRequestRepository,
    ShiftRepository,
    StationRepository,
    TenantRepository,
    WorkerRepository,
    WorkspaceRepository,
)
from app.services.preview import _translate_persistence_bundle_to_engine_input

REFINE_STATUS_RECEIVED = "received"
REFINE_STATUS_PARSED = "parsed"
REFINE_STATUS_COMPLETED = "completed"


class MonthlyScheduleRefineEngine(Protocol):
    """Callable engine boundary used to compute the candidate refined preview."""

    def __call__(self, planning_input: MonthPlanningInput) -> MonthPlanningResult:
        ...


@dataclass(slots=True)
class RefineParserRequest:
    """Context passed to the parser boundary for one refine instruction."""

    tenant_slug: str
    year: int
    month: int
    workspace_id: RecordId
    request_text: str
    planning_input: MonthPlanningInput


@dataclass(slots=True)
class RefineParserResult:
    """Structured parser output consumed by the refine service."""

    intent_json: JsonObject
    adjustment_patch: list[AssignmentPatchInput] | None = None


class RefineParser(Protocol):
    """Optional AI or rule-based parser boundary for natural-language refine."""

    def __call__(self, request: RefineParserRequest) -> RefineParserResult:
        ...


@dataclass(slots=True)
class RefineMonthScheduleRequest:
    """Service-layer request for one natural-language month refinement."""

    tenant_slug: str
    year: int
    month: int
    request_text: str


@dataclass(slots=True)
class RefineMonthScheduleResponse:
    """Small refine result containing the stored request and candidate preview."""

    tenant_slug: str
    year: int
    month: int
    workspace_id: RecordId
    refine_request_id: RecordId
    status: str
    parsed_intent_json: JsonObject
    candidate_result: MonthPlanningResult


@dataclass(slots=True)
class RefineMonthScheduleService:
    """Coordinates natural-language refine into a stored candidate preview.

    Refine stays separate from preview/apply/save on purpose:
    - preview computes a read-only month result from persisted inputs
    - refine adds one structured adjustment layer and stores its candidate result
    - apply is still required to mutate current workspace state
    - save is still required to create immutable version history
    """

    tenant_repository: TenantRepository
    worker_repository: WorkerRepository
    station_repository: StationRepository
    shift_repository: ShiftRepository
    leave_request_repository: LeaveRequestRepository
    constraint_config_repository: ConstraintConfigRepository
    workspace_repository: WorkspaceRepository
    refine_request_repository: RefineRequestRepository
    parser: RefineParser
    engine_runner: MonthlyScheduleRefineEngine

    def refine_month_schedule(
        self,
        request: RefineMonthScheduleRequest,
    ) -> RefineMonthScheduleResponse:
        """Create a refine request, parse intent, and store a candidate preview."""

        _validate_request(request)

        tenant = self.tenant_repository.get_by_slug(request.tenant_slug)
        if tenant is None:
            raise LookupError(f"Tenant not found: {request.tenant_slug!r}")

        tenant_id = _require_record_id(tenant.id, label="tenant.id")
        current_state = self.workspace_repository.load_current(
            tenant_id,
            request.year,
            request.month,
        )
        if current_state is None:
            raise LookupError(
                f"No current workspace found for {tenant.slug!r} "
                f"{request.year}-{request.month:02d}."
            )

        workspace_id = _require_record_id(
            current_state.workspace.id,
            label="workspace.id",
        )
        bundle = self._load_monthly_persistence_bundle(
            tenant=tenant,
            year=request.year,
            month=request.month,
        )
        base_planning_input = _translate_persistence_bundle_to_engine_input(bundle)

        persisted_refine_request = self.refine_request_repository.create(
            RefineRequest(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                request_text=request.request_text,
                status=REFINE_STATUS_RECEIVED,
            )
        )
        refine_request_id = _require_record_id(
            persisted_refine_request.id,
            label="refine_request.id",
        )

        parser_result = self.parser(
            RefineParserRequest(
                tenant_slug=tenant.slug,
                year=request.year,
                month=request.month,
                workspace_id=workspace_id,
                request_text=request.request_text,
                planning_input=base_planning_input,
            )
        )
        parsed_intent_json = _build_persisted_intent_json(parser_result)
        parsed_refine_request = self.refine_request_repository.update_parsed_preview(
            refine_request_id,
            status=REFINE_STATUS_PARSED,
            parsed_intent_json=parsed_intent_json,
        )
        if parsed_refine_request is None:
            raise LookupError(
                f"Refine request not found after create: {refine_request_id!r}"
            )

        refined_planning_input = _build_refined_planning_input(
            base_planning_input,
            parser_result,
        )
        candidate_result = self.engine_runner(refined_planning_input)
        result_preview_json = _serialize_month_planning_result(candidate_result)
        completed_refine_request = self.refine_request_repository.update_parsed_preview(
            refine_request_id,
            status=REFINE_STATUS_COMPLETED,
            parsed_intent_json=parsed_intent_json,
            result_preview_json=result_preview_json,
        )
        if completed_refine_request is None:
            raise LookupError(
                f"Refine request not found when storing preview: "
                f"{refine_request_id!r}"
            )

        return RefineMonthScheduleResponse(
            tenant_slug=tenant.slug,
            year=request.year,
            month=request.month,
            workspace_id=workspace_id,
            refine_request_id=refine_request_id,
            status=completed_refine_request.status,
            parsed_intent_json=parsed_intent_json,
            candidate_result=candidate_result,
        )

    def _load_monthly_persistence_bundle(
        self,
        *,
        tenant: Tenant,
        year: int,
        month: int,
    ) -> MonthlyPlanningPersistenceBundle:
        """Gather the persistence snapshot required for a refined rerun."""

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


def refine_month_schedule(
    request: RefineMonthScheduleRequest,
    *,
    service: RefineMonthScheduleService,
) -> RefineMonthScheduleResponse:
    """Thin functional wrapper around the refine service boundary."""

    return service.refine_month_schedule(request)


def _build_refined_planning_input(
    base_planning_input: MonthPlanningInput,
    parser_result: RefineParserResult,
) -> MonthPlanningInput:
    """Attach the parsed adjustment patch to a preview-style planning input.

    Patch policy intentionally stays simple for now: refine contributes a
    normalized overlay patch and the engine decides how to interpret it.
    """

    merged_adjustment_patch = _merge_adjustment_patch(
        base_planning_input.adjustment_patch,
        parser_result.adjustment_patch,
    )
    return replace(
        base_planning_input,
        adjustment_patch=merged_adjustment_patch,
    )


def _merge_adjustment_patch(
    base_patch: list[AssignmentPatchInput] | None,
    refine_patch: list[AssignmentPatchInput] | None,
) -> list[AssignmentPatchInput] | None:
    """Placeholder patch merge strategy for the first refine skeleton."""

    if not base_patch and not refine_patch:
        return None
    if not base_patch:
        return list(refine_patch or [])
    if not refine_patch:
        return list(base_patch)
    return [*base_patch, *refine_patch]


def _build_persisted_intent_json(parser_result: RefineParserResult) -> JsonObject:
    """Prepare JSON-safe parser output for refine-request persistence."""

    intent_json = dict(parser_result.intent_json)
    if parser_result.adjustment_patch:
        intent_json.setdefault(
            "adjustment_patch",
            [
                _serialize_assignment_patch_input(patch)
                for patch in parser_result.adjustment_patch
            ],
        )
    return intent_json


def _serialize_assignment_patch_input(
    patch: AssignmentPatchInput,
) -> JsonObject:
    """Serialize one engine-shaped assignment patch for persistence."""

    return {
        "operation": patch.operation,
        "date": patch.date.isoformat(),
        "worker_code": patch.worker_code,
        "shift_code": patch.shift_code,
        "station_code": patch.station_code,
        "note": patch.note,
    }


def _serialize_month_planning_result(result: MonthPlanningResult) -> JsonObject:
    """Serialize a candidate preview result into JSON-like refine storage."""

    return {
        "assignments": [
            {
                "date": assignment.date.isoformat(),
                "worker_code": assignment.worker_code,
                "shift_code": assignment.shift_code,
                "station_code": assignment.station_code,
                "source": assignment.source,
                "note": assignment.note,
            }
            for assignment in result.assignments
        ],
        "warnings": [
            {
                "type": warning.type,
                "message_key": warning.message_key,
                "worker_code": warning.worker_code,
                "date": warning.date.isoformat() if warning.date else None,
                "details": warning.details,
            }
            for warning in result.warnings
        ],
        "summary": {
            "total_assignments": result.summary.total_assignments,
            "total_warnings": result.summary.total_warnings,
            "assignments_by_worker": dict(result.summary.assignments_by_worker),
            "paid_hours_by_worker": {
                worker_code: str(hours)
                for worker_code, hours in result.summary.paid_hours_by_worker.items()
            },
            "warnings_by_type": dict(result.summary.warnings_by_type),
        },
        "metadata": {
            "generated_at": result.metadata.generated_at.isoformat(),
            "source_type": result.metadata.source_type,
            "refinement_applied": result.metadata.refinement_applied,
            "notes": list(result.metadata.notes) if result.metadata.notes else None,
        },
    }


def _validate_request(request: RefineMonthScheduleRequest) -> None:
    """Guard the refine service boundary against invalid inputs."""

    if request.year < 1:
        raise ValueError("Refine year must be greater than zero.")
    if request.month < 1 or request.month > 12:
        raise ValueError("Refine month must be between 1 and 12.")
    if not request.request_text.strip():
        raise ValueError("Refine request text must not be blank.")


def _require_record_id(record_id: RecordId | None, *, label: str) -> RecordId:
    """Ensure repository-loaded records are usable for downstream refine flow."""

    if record_id is None:
        raise ValueError(f"{label} must be populated on repository results.")
    return record_id


__all__ = [
    "MonthlyScheduleRefineEngine",
    "RefineMonthScheduleRequest",
    "RefineMonthScheduleResponse",
    "RefineMonthScheduleService",
    "RefineParser",
    "RefineParserRequest",
    "RefineParserResult",
    "refine_month_schedule",
]
