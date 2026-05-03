"""Refine orchestration for bounded monthly schedule adjustments.

The refine service accepts a natural-language adjustment request, stores it as a
`RefineRequest`, delegates interpretation plus preview generation to a small
workflow boundary, and persists the resulting candidate preview when one is
available. It does not mutate the current workspace and it does not create
saved versions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Protocol, TypedDict

from app.engine.contracts import (
    AssignmentOutput,
    AssignmentPatchInput,
    MonthPlanningEvaluation,
    MonthPlanningInput,
    MonthPlanningResult,
)
from app.infra.models import (
    JsonObject,
    MonthlyAssignment,
    RecordId,
    RefineRequest,
)
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
from app.services.monthly_context import (
    build_month_planning_input,
    load_monthly_planning_bundle,
)

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
        "refine_understood_but_not_executable": (
            "\u6211\u7406\u89e3\u8fd9\u662f\u6392\u73ed\u8bf7\u6c42"
            "\uff08{intent_label}\uff09\uff0c\u4f46\u76ee\u524d\u8fd9\u4e2a"
            "\u8c03\u6574\u6d41\u7a0b\u53ea\u652f\u6301\u5355\u65e5\u7f16\u8f91\u3002"
            "\u8bf7\u5c1d\u8bd5\u8f93\u5165\u5177\u4f53\u8c03\u6574\uff0c\u4f8b\u5982\uff1a"
            "{suggestion}"
        ),
        "refine_non_scheduling_request": (
            "\u8fd9\u4e2a\u52a9\u624b\u53ea\u5904\u7406\u6392\u73ed\u8c03\u6574\u3002"
            "\u8bf7\u8f93\u5165\u4e0e\u6392\u73ed\u76f8\u5173\u7684\u8bf7\u6c42\u3002"
        ),
        "refine_ambiguous_missing_information": (
            "\u6211\u9700\u8981\u66f4\u591a\u8d44\u8baf\u624d\u80fd\u5b89\u5168"
            "\u751f\u6210\u9884\u89c8\u3002\u8bf7\u8865\u5145\uff1a"
            "{missing_fields}\u3002"
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
        "refine_understood_but_not_executable": (
            "\u3053\u308c\u306f\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb\u4f9d\u983c"
            "\uff08{intent_label}\uff09\u3068\u7406\u89e3\u3057\u307e\u3057\u305f\u304c\u3001"
            "\u73fe\u5728\u306e\u8abf\u6574\u30d5\u30ed\u30fc\u306f\u5358\u65e5\u306e"
            "\u7de8\u96c6\u3060\u3051\u306b\u5bfe\u5fdc\u3057\u3066\u3044\u307e\u3059\u3002"
            "\u4f8b\u3048\u3070\u6b21\u306e\u3088\u3046\u306b\u5177\u4f53\u7684\u306b"
            "\u6307\u5b9a\u3057\u3066\u304f\u3060\u3055\u3044\uff1a{suggestion}"
        ),
        "refine_non_scheduling_request": (
            "\u3053\u306e\u30a2\u30b7\u30b9\u30bf\u30f3\u30c8\u306f"
            "\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb\u5909\u66f4\u306e\u307f\u5bfe\u5fdc"
            "\u3057\u307e\u3059\u3002\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb\u95a2\u9023\u306e"
            "\u4f9d\u983c\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        ),
        "refine_ambiguous_missing_information": (
            "\u5b89\u5168\u306b\u30d7\u30ec\u30d3\u30e5\u30fc\u3059\u308b\u306b\u306f"
            "\u8ffd\u52a0\u60c5\u5831\u304c\u5fc5\u8981\u3067\u3059\u3002"
            "\u8ffd\u52a0\u3057\u3066\u304f\u3060\u3055\u3044\uff1a{missing_fields}\u3002"
        ),
        "refine_ambiguous_reference": (
            "\u3053\u306e\u8abf\u6574\u4f9d\u983c\u3092\u5b89\u5168\u306b"
            "\u89e3\u91c8\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
        ),
    },
    "en": {
        "refine_preview_ready_set": "Refine preview generated.",
        "refine_preview_ready_remove": "Remove preview generated.",
        "refine_unsupported_language": "Unsupported request language.",
        "refine_unsupported_intent": "Unsupported refine request.",
        "refine_understood_but_not_executable": (
            "I understand this as a scheduling request ({intent_label}), but "
            "this refine flow currently supports only single-day edits. Try a "
            "concrete edit such as: {suggestion}"
        ),
        "refine_non_scheduling_request": (
            "This assistant only handles scheduling changes. Please enter a "
            "scheduling-related request."
        ),
        "refine_ambiguous_missing_information": (
            "I need more information before I can preview that scheduling "
            "change. Please include: {missing_fields}."
        ),
        "refine_ambiguous_reference": "Unable to safely resolve this refine request.",
    },
    "unknown": {
        "refine_preview_ready_set": "Refine preview generated.",
        "refine_preview_ready_remove": "Remove preview generated.",
        "refine_unsupported_language": "Unsupported request language.",
        "refine_unsupported_intent": "Unsupported refine request.",
        "refine_understood_but_not_executable": (
            "I understand this as a scheduling request ({intent_label}), but "
            "this refine flow currently supports only single-day edits. Try a "
            "concrete edit such as: {suggestion}"
        ),
        "refine_non_scheduling_request": (
            "This assistant only handles scheduling changes. Please enter a "
            "scheduling-related request."
        ),
        "refine_ambiguous_missing_information": (
            "I need more information before I can preview that scheduling "
            "change. Please include: {missing_fields}."
        ),
        "refine_ambiguous_reference": "Unable to safely resolve this refine request.",
    },
}


class MonthlyScheduleRefineEngine(Protocol):
    """Callable engine boundary used to compute a refined candidate preview."""

    def __call__(self, planning_input: MonthPlanningInput) -> MonthPlanningResult:
        ...


class RefinePreviewDiffAssignment(TypedDict):
    """Assignment details rendered in a refine preview diff row."""

    station_code: str | None
    shift_code: str
    source: str
    note: str | None


class RefinePreviewDiffRow(TypedDict):
    """One date/person comparison row for current vs candidate preview."""

    date: str
    worker_code: str
    worker_name: str
    before: RefinePreviewDiffAssignment | None
    after: RefinePreviewDiffAssignment | None


class RefinePreviewDiff(TypedDict):
    """Structured assignment diff for a candidate refine preview."""

    added: list[RefinePreviewDiffRow]
    removed: list[RefinePreviewDiffRow]
    changed: list[RefinePreviewDiffRow]


def _empty_refine_preview_diff() -> RefinePreviewDiff:
    return {"added": [], "removed": [], "changed": []}


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
    current_assignments: list[AssignmentOutput] | None = None


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
    preview_diff: RefinePreviewDiff = field(
        default_factory=_empty_refine_preview_diff
    )


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
        base_planning_input = build_month_planning_input(bundle)
        current_assignments = _translate_current_assignments_to_engine_rows(
            current_state.assignments,
            bundle=bundle,
        )

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
                current_assignments=current_assignments,
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
        preview_diff = (
            build_refine_preview_diff(
                current_assignments,
                workflow_result.candidate_result.assignments,
                worker_display_names_by_code={
                    worker.worker_code: worker.name
                    for worker in base_planning_input.workers
                },
            )
            if workflow_result.candidate_result is not None
            else _empty_refine_preview_diff()
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
            preview_diff=preview_diff,
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


def build_refine_preview_diff(
    current_assignments: list[AssignmentOutput],
    candidate_assignments: list[AssignmentOutput],
    *,
    worker_display_names_by_code: Mapping[str, str] | None = None,
) -> RefinePreviewDiff:
    """Compare current workspace assignments with a candidate preview.

    The diff identity matches the refine patch identity: one worker on one date.
    The helper is pure and expects already-normalized engine assignment rows.
    """

    worker_display_names_by_code = worker_display_names_by_code or {}
    current_by_key = _index_assignments_for_refine_diff(
        current_assignments,
        label="current_assignments",
    )
    candidate_by_key = _index_assignments_for_refine_diff(
        candidate_assignments,
        label="candidate_assignments",
    )
    diff: RefinePreviewDiff = {"added": [], "removed": [], "changed": []}

    for assignment_key in sorted(set(current_by_key) | set(candidate_by_key)):
        current_assignment = current_by_key.get(assignment_key)
        candidate_assignment = candidate_by_key.get(assignment_key)
        date_value, worker_code = assignment_key

        if current_assignment is None and candidate_assignment is not None:
            diff["added"].append(
                _build_refine_preview_diff_row(
                    date_value=date_value,
                    worker_code=worker_code,
                    worker_display_names_by_code=worker_display_names_by_code,
                    before=None,
                    after=candidate_assignment,
                )
            )
            continue

        if current_assignment is not None and candidate_assignment is None:
            diff["removed"].append(
                _build_refine_preview_diff_row(
                    date_value=date_value,
                    worker_code=worker_code,
                    worker_display_names_by_code=worker_display_names_by_code,
                    before=current_assignment,
                    after=None,
                )
            )
            continue

        if current_assignment is None or candidate_assignment is None:
            continue

        if _assignment_schedule_signature(
            current_assignment
        ) != _assignment_schedule_signature(candidate_assignment):
            diff["changed"].append(
                _build_refine_preview_diff_row(
                    date_value=date_value,
                    worker_code=worker_code,
                    worker_display_names_by_code=worker_display_names_by_code,
                    before=current_assignment,
                    after=candidate_assignment,
                )
            )

    return diff


def _render_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, Decimal)):
        return str(value)
    return str(value)


def _index_assignments_for_refine_diff(
    assignments: list[AssignmentOutput],
    *,
    label: str,
) -> dict[tuple[date, str], AssignmentOutput]:
    indexed: dict[tuple[date, str], AssignmentOutput] = {}
    for assignment in assignments:
        assignment_key = (assignment.date, assignment.worker_code)
        if assignment_key in indexed:
            raise ValueError(
                f"{label} contains multiple assignments for "
                f"{assignment.worker_code!r} on {assignment.date.isoformat()}."
            )
        indexed[assignment_key] = assignment
    return indexed


def _build_refine_preview_diff_row(
    *,
    date_value: date,
    worker_code: str,
    worker_display_names_by_code: Mapping[str, str],
    before: AssignmentOutput | None,
    after: AssignmentOutput | None,
) -> RefinePreviewDiffRow:
    return {
        "date": date_value.isoformat(),
        "worker_code": worker_code,
        "worker_name": worker_display_names_by_code.get(worker_code, worker_code),
        "before": (
            _serialize_refine_preview_diff_assignment(before)
            if before is not None
            else None
        ),
        "after": (
            _serialize_refine_preview_diff_assignment(after)
            if after is not None
            else None
        ),
    }


def _serialize_refine_preview_diff_assignment(
    assignment: AssignmentOutput,
) -> RefinePreviewDiffAssignment:
    return {
        "station_code": assignment.station_code,
        "shift_code": assignment.shift_code,
        "source": assignment.source,
        "note": assignment.note,
    }


def _assignment_schedule_signature(
    assignment: AssignmentOutput,
) -> tuple[str, str | None]:
    return (assignment.shift_code, assignment.station_code)


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


def _translate_current_assignments_to_engine_rows(
    assignments: list[MonthlyAssignment],
    *,
    bundle: MonthlyPlanningPersistenceBundle,
) -> list[AssignmentOutput]:
    """Translate read-only current workspace rows into engine identifiers."""

    worker_codes_by_id = {
        _require_record_id(worker.id, label="worker.id"): _coalesce_engine_code(
            worker.code,
            worker.id,
            label="worker",
        )
        for worker in bundle.workers
    }
    shift_codes_by_id = {
        _require_record_id(shift.id, label="shift.id"): shift.code
        for shift in bundle.shifts
    }
    station_codes_by_id = {
        _require_record_id(station.id, label="station.id"): _coalesce_engine_code(
            station.code,
            station.id,
            label="station",
        )
        for station in bundle.stations
    }

    translated_assignments: list[AssignmentOutput] = []
    for assignment in assignments:
        worker_code = worker_codes_by_id.get(assignment.worker_id)
        if worker_code is None:
            raise LookupError(
                "Current workspace assignment references unknown worker_id "
                f"{assignment.worker_id!r}."
            )
        shift_code = shift_codes_by_id.get(assignment.shift_definition_id)
        if shift_code is None:
            raise LookupError(
                "Current workspace assignment references unknown "
                f"shift_definition_id {assignment.shift_definition_id!r}."
            )
        station_code = None
        if assignment.station_id is not None:
            station_code = station_codes_by_id.get(assignment.station_id)
            if station_code is None:
                raise LookupError(
                    "Current workspace assignment references unknown station_id "
                    f"{assignment.station_id!r}."
                )
        translated_assignments.append(
            AssignmentOutput(
                date=assignment.assignment_date,
                worker_code=worker_code,
                shift_code=shift_code,
                station_code=station_code,
                source="current_workspace",
                note=assignment.note,
            )
        )
    return translated_assignments


def _coalesce_engine_code(
    code: str | None,
    record_id: RecordId | None,
    *,
    label: str,
) -> str:
    if code:
        return code
    if record_id:
        return record_id
    raise ValueError(f"{label.capitalize()} requires either a code or persisted id.")


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
    "RefinePreviewDiff",
    "RefinePreviewDiffAssignment",
    "RefinePreviewDiffRow",
    "RefineWorkflow",
    "RefineWorkflowRequest",
    "RefineWorkflowResult",
    "_build_refined_planning_input",
    "build_refine_preview_diff",
    "refine_month_schedule",
    "render_refine_outcome",
]
