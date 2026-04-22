"""Refine orchestration for bounded monthly schedule adjustments.

The refine service accepts a natural-language adjustment request, stores it as a
`RefineRequest`, delegates interpretation plus preview generation to a small
workflow boundary, and persists the resulting candidate preview when one is
available. It does not mutate the current workspace and it does not create
saved versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.engine.contracts import (
    AssignmentPatchInput,
    MonthPlanningEvaluation,
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

_REFINE_OUTCOME_TEMPLATES: dict[str, dict[str, str]] = {
    "zh": {
        "refine_preview_ready_set": (
            "\u5df2\u751f\u6210\u8c03\u6574\u9884\u89c8\u3002"
        ),
        "refine_preview_ready_remove": (
            "\u5df2\u751f\u6210\u79fb\u9664\u9884\u89c8\u3002"
        ),
        "refine_unsupported_language": (
            "\u6682\u4e0d\u652f\u6301\u8fd9\u7c7b\u8f93\u5165\u8bed\u8a00\u3002"
        ),
        "refine_unsupported_intent": (
            "\u6682\u4e0d\u652f\u6301\u8fd9\u7c7b\u8c03\u6574\u8bf7\u6c42\u3002"
        ),
        "refine_ambiguous_reference": (
            "\u65e0\u6cd5\u5b89\u5168\u89e3\u6790\u8fd9\u6761\u8c03\u6574\u8bf7\u6c42\u3002"
        ),
    },
    "ja": {
        "refine_preview_ready_set": (
            "\u8abf\u6574\u30d7\u30ec\u30d3\u30e5\u30fc\u3092"
            "\u751f\u6210\u3057\u307e\u3057\u305f\u3002"
        ),
        "refine_preview_ready_remove": (
            "\u524a\u9664\u30d7\u30ec\u30d3\u30e5\u30fc\u3092"
            "\u751f\u6210\u3057\u307e\u3057\u305f\u3002"
        ),
        "refine_unsupported_language": (
            "\u3053\u306e\u5165\u529b\u8a00\u8a9e\u306f\u307e\u3060"
            "\u5bfe\u5fdc\u3057\u3066\u3044\u307e\u305b\u3093\u3002"
        ),
        "refine_unsupported_intent": (
            "\u3053\u306e\u8abf\u6574\u4f9d\u983c\u306b\u306f\u307e\u3060"
            "\u5bfe\u5fdc\u3057\u3066\u3044\u307e\u305b\u3093\u3002"
        ),
        "refine_ambiguous_reference": (
            "\u3053\u306e\u8abf\u6574\u4f9d\u983c\u3092\u5b89\u5168\u306b"
            "\u89e3\u91c8\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
        ),
    },
    "unknown": {
        "refine_preview_ready_set": "Refine preview generated.",
        "refine_preview_ready_remove": "Remove preview generated.",
        "refine_unsupported_language": "Unsupported request language.",
        "refine_unsupported_intent": "Unsupported refine request.",
        "refine_ambiguous_reference": "Unable to safely resolve this refine request.",
    },
}


class MonthlyScheduleRefineEngine(Protocol):
    """Callable engine boundary used to compute a refined candidate preview."""

    def __call__(self, planning_input: MonthPlanningInput) -> MonthPlanningResult:
        ...


@dataclass(slots=True)
class RefineOutcome:
    """Structured bounded outcome that can later be rendered per language."""

    language: str
    status: str
    message_key: str
    message_values: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class RefineWorkflowRequest:
    """Context passed to the workflow boundary for one refine instruction."""

    tenant_slug: str
    year: int
    month: int
    workspace_id: RecordId
    request_text: str
    planning_input: MonthPlanningInput


@dataclass(slots=True)
class RefineWorkflowResult:
    """Structured workflow result consumed by the refine service."""

    request_language: str
    outcome: RefineOutcome
    parsed_intent_json: JsonObject
    adjustment_patch: list[AssignmentPatchInput] | None = None
    candidate_result: MonthPlanningResult | None = None


class RefineWorkflow(Protocol):
    """Bounded workflow boundary for request understanding plus preview."""

    def __call__(self, request: RefineWorkflowRequest) -> RefineWorkflowResult:
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
    """Small refine result containing stored metadata and an optional preview."""

    tenant_slug: str
    year: int
    month: int
    workspace_id: RecordId
    refine_request_id: RecordId
    status: str
    request_language: str
    outcome: RefineOutcome
    parsed_intent_json: JsonObject
    candidate_result: MonthPlanningResult | None


@dataclass(slots=True)
class RefineMonthScheduleService:
    """Coordinates bounded refine requests into an optional candidate preview.

    Refine stays separate from preview/apply/save on purpose:
    - preview computes a read-only month result from persisted inputs
    - refine adds one structured adjustment layer when supported
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
    workflow: RefineWorkflow

    def refine_month_schedule(
        self,
        request: RefineMonthScheduleRequest,
    ) -> RefineMonthScheduleResponse:
        """Create a refine request, run the workflow, and store preview data."""

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

        workflow_result = self.workflow(
            RefineWorkflowRequest(
                tenant_slug=tenant.slug,
                year=request.year,
                month=request.month,
                workspace_id=workspace_id,
                request_text=request.request_text,
                planning_input=base_planning_input,
            )
        )
        parsed_intent_json = _build_persisted_intent_json(workflow_result)
        parsed_refine_request = self.refine_request_repository.update_parsed_preview(
            refine_request_id,
            status=REFINE_STATUS_PARSED,
            parsed_intent_json=parsed_intent_json,
        )
        if parsed_refine_request is None:
            raise LookupError(
                f"Refine request not found after create: {refine_request_id!r}"
            )

        result_preview_json = (
            _serialize_month_planning_result(workflow_result.candidate_result)
            if workflow_result.candidate_result is not None
            else None
        )
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
            request_language=workflow_result.request_language,
            outcome=workflow_result.outcome,
            parsed_intent_json=parsed_intent_json,
            candidate_result=workflow_result.candidate_result,
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


def render_refine_outcome(outcome: RefineOutcome) -> str:
    """Render one bounded outcome message in the request language."""

    templates = _REFINE_OUTCOME_TEMPLATES.get(
        outcome.language,
        _REFINE_OUTCOME_TEMPLATES["unknown"],
    )
    template = templates.get(
        outcome.message_key,
        _REFINE_OUTCOME_TEMPLATES["unknown"]["refine_ambiguous_reference"],
    )
    safe_values = {
        key: _render_value(value)
        for key, value in outcome.message_values.items()
    }
    return template.format(**safe_values)


def _render_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, Decimal)):
        return str(value)
    return str(value)


def _build_refined_planning_input(
    base_planning_input: MonthPlanningInput,
    adjustment_patch: list[AssignmentPatchInput] | None,
) -> MonthPlanningInput:
    """Attach the normalized adjustment patch to a preview-style planning input."""

    merged_adjustment_patch = _merge_adjustment_patch(
        base_planning_input.adjustment_patch,
        adjustment_patch,
    )
    return replace(
        base_planning_input,
        adjustment_patch=merged_adjustment_patch,
    )


def _merge_adjustment_patch(
    base_patch: list[AssignmentPatchInput] | None,
    refine_patch: list[AssignmentPatchInput] | None,
) -> list[AssignmentPatchInput] | None:
    """Keep the first refine merge policy explicit and deterministic."""

    if not base_patch and not refine_patch:
        return None
    if not base_patch:
        return list(refine_patch or [])
    if not refine_patch:
        return list(base_patch)
    return [*base_patch, *refine_patch]


def _build_persisted_intent_json(
    workflow_result: RefineWorkflowResult,
) -> JsonObject:
    """Prepare JSON-safe workflow output for refine-request persistence."""

    intent_json = dict(workflow_result.parsed_intent_json)
    intent_json.setdefault("request_language", workflow_result.request_language)
    persisted_outcome = _serialize_refine_outcome(workflow_result.outcome)
    existing_outcome = intent_json.get("outcome")
    if isinstance(existing_outcome, dict):
        merged_outcome = dict(existing_outcome)
        for key, value in persisted_outcome.items():
            merged_outcome.setdefault(key, value)
        intent_json["outcome"] = merged_outcome
    else:
        intent_json["outcome"] = persisted_outcome
    if workflow_result.adjustment_patch:
        intent_json.setdefault(
            "adjustment_patch",
            [
                _serialize_assignment_patch_input(patch)
                for patch in workflow_result.adjustment_patch
            ],
        )
    return intent_json


def _serialize_refine_outcome(outcome: RefineOutcome) -> JsonObject:
    """Serialize one bounded refine outcome into a JSON-safe shape."""

    return {
        "language": outcome.language,
        "status": outcome.status,
        "message_key": outcome.message_key,
        "message_values": dict(outcome.message_values),
        "message_text": render_refine_outcome(outcome),
    }


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
        "evaluation": (
            _serialize_month_planning_evaluation(result.evaluation)
            if result.evaluation is not None
            else None
        ),
    }


def _serialize_month_planning_evaluation(
    evaluation: MonthPlanningEvaluation,
) -> JsonObject:
    """Serialize the v0.1 evaluation envelope for refine preview storage."""

    return {
        "duplicate_assignment_conflicts": evaluation.duplicate_assignment_conflicts,
        "workspace_state_integrity_violations": (
            evaluation.workspace_state_integrity_violations
        ),
        "understaffed_station_days": evaluation.understaffed_station_days,
        "workers_below_min_days_off": evaluation.workers_below_min_days_off,
        "total_warnings": evaluation.total_warnings,
        "warnings_by_type": dict(evaluation.warnings_by_type),
        "assignments_by_worker": dict(evaluation.assignments_by_worker),
        "paid_hours_by_worker": {
            worker_code: str(hours)
            for worker_code, hours in evaluation.paid_hours_by_worker.items()
        },
        "max_minus_min_assignment_gap": evaluation.max_minus_min_assignment_gap,
        "max_minus_min_paid_hours_gap": str(
            evaluation.max_minus_min_paid_hours_gap
        ),
        "covered_station_days": evaluation.covered_station_days,
        "hard_constraints_passed": evaluation.hard_constraints_passed,
        "soft_warnings_present": evaluation.soft_warnings_present,
        "schedule_quality_label": evaluation.schedule_quality_label,
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
    "REFINE_STATUS_COMPLETED",
    "REFINE_STATUS_PARSED",
    "REFINE_STATUS_RECEIVED",
    "RefineMonthScheduleRequest",
    "RefineMonthScheduleResponse",
    "RefineMonthScheduleService",
    "RefineOutcome",
    "RefineWorkflow",
    "RefineWorkflowRequest",
    "RefineWorkflowResult",
    "_build_refined_planning_input",
    "refine_month_schedule",
    "render_refine_outcome",
]
