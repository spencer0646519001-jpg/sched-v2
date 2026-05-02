"""Minimal LangGraph-backed bilingual refine workflow.

This slice intentionally stays small:
- single-turn only
- no memory
- no tools
- no autonomous apply/save
- bounded zh/ja normalization only
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.ai.interfaces import ModelUnavailableError, StructuredOutputModelClient
from app.ai.noop_client import NoopStructuredOutputModelClient
from app.engine.contracts import (
    AssignmentOutput,
    AssignmentPatchInput,
    MonthPlanningResult,
    ShiftInput,
    StationInput,
    WorkerInput,
)
from app.engine.evaluation import attach_month_planning_evaluation
from app.services.refine import (
    MonthlyScheduleRefineEngine,
    RefineOutcome,
    RefineWorkflowRequest,
    RefineWorkflowResult,
    _build_refined_planning_input,
)

_ZH_SET_KEYWORDS = (
    "\u5b89\u6392",
    "\u6392\u5230",
    "\u8bbe\u4e3a",
    "\u6539\u4e3a",
    "\u6539\u6210",
    "\u6539\u5230",
    "\u6539\u53bb",
    "\u73ed\u5225\u6539",
    "\u73ed\u522b\u6539",
)
_ZH_REMOVE_KEYWORDS = (
    "\u5220\u9664",
    "\u79fb\u9664",
    "\u53d6\u6d88",
    "\u4f11\u5047",
    "\u4e0d\u8981\u6392\u73ed",
    "\u4e0d\u8981\u6392",
    "\u4e0d\u6392\u73ed",
)
_JA_SET_KEYWORDS = (
    "\u5165\u308c\u3066",
    "\u5165\u308c\u308b",
    "\u306b\u3057\u3066",
    "\u8a2d\u5b9a",
)
_JA_REMOVE_KEYWORDS = (
    "\u5916\u3057\u3066",
    "\u5916\u3059",
    "\u524a\u9664",
    "\u4f11\u307f",
    "\u4f11\u6687",
)
_EN_SET_KEYWORDS = (
    "assign",
    "change",
    "move",
    "put",
    "schedule",
    "shift",
    "switch",
)
_EN_REMOVE_KEYWORDS = (
    "delete",
    "no shift",
    "off",
    "remove",
    "unschedule",
)
_DIRECT_MUTATION_KEYS = frozenset(
    {
        "apply",
        "commit",
        "direct_apply",
        "direct_mutation",
        "mutate",
        "persist",
        "save",
        "update_db",
        "write_db",
    }
)
CAPABILITY_EXECUTABLE = "executable"
CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE = "understood_but_not_executable"
CAPABILITY_NON_SCHEDULING = "non_scheduling"
CAPABILITY_AMBIGUOUS = "ambiguous_or_missing_information"
SCHEDULING_DOMAIN = "scheduling"
NON_SCHEDULING_DOMAIN = "non_scheduling"
UNKNOWN_DOMAIN = "unknown"

_ABSTRACT_INTENT_TYPES = {
    "reduce_or_avoid_shift_type",
    "workload_or_fairness",
    "station_coverage",
    "swap_workers",
}
_SUPPORTED_INTENT_TYPES = {
    "set_assignment",
    "change_shift",
    "change_station",
    "remove_assignment",
}
_SUPPORTED_MODEL_INTENT_TYPES = _SUPPORTED_INTENT_TYPES | _ABSTRACT_INTENT_TYPES
_SUPPORTED_MODEL_CAPABILITY_STATUSES = {
    CAPABILITY_EXECUTABLE,
    CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
    CAPABILITY_NON_SCHEDULING,
    CAPABILITY_AMBIGUOUS,
}
_SUPPORTED_MODEL_DOMAINS = {
    SCHEDULING_DOMAIN,
    NON_SCHEDULING_DOMAIN,
    UNKNOWN_DOMAIN,
}
_CONCRETE_EDIT_SUGGESTIONS = {
    "zh": "5/2 Spencer 改成 C",
    "ja": "5/2 Spencer を C にして",
    "en": "Change Spencer to shift C on 5/2",
    "unknown": "Change Spencer to shift C on 5/2",
}
_INTENT_LABELS = {
    "reduce_or_avoid_shift_type": "reduce or avoid a shift type",
    "workload_or_fairness": "workload or fairness balancing",
    "station_coverage": "station coverage adjustment",
    "swap_workers": "worker swap",
    "set_assignment": "single-day assignment edit",
    "change_shift": "single-day shift change",
    "change_station": "single-day station change",
    "remove_assignment": "single-day remove/off edit",
}
_MISSING_FIELD_LABELS = {
    "date": "date",
    "worker": "worker",
    "target_shift_or_station": "target shift or station",
    "shift": "target shift",
    "station": "target station",
    "secondary_worker": "second worker",
}
_DATE_RANGE_HINTS = (
    ("next_week", ("next week", "\u4e0b\u9031", "\u4e0b\u5468", "\u6765\u9031")),
    ("this_week", ("this week", "\u9019\u9031", "\u8fd9\u5468", "\u4eca\u9031")),
    ("tomorrow", ("tomorrow", "\u660e\u5929", "\u660e\u65e5")),
    ("recently", ("recently", "\u6700\u8fd1")),
)
_REDUCE_SHIFT_HINTS = (
    "reduce",
    "fewer",
    "less",
    "avoid",
    "\u5c11\u4e00\u9ede",
    "\u5c11\u4e00\u70b9",
    "\u4e0d\u8981\u518d\u6392\u592a\u591a",
    "\u6e1b\u3089",
)
_MORNING_SHIFT_HINTS = (
    "morning",
    "\u65e9\u73ed",
    "\u671d\u756a",
)
_WORKLOAD_FAIRNESS_HINTS = (
    "balance the workload",
    "workload",
    "fair",
    "fairer",
    "tired",
    "\u73ed\u6578\u5e73\u5747",
    "\u73ed\u6570\u5e73\u5747",
    "\u5e73\u5747\u4e00\u9ede",
    "\u5e73\u5747\u4e00\u70b9",
    "\u592a\u7d2f",
    "\u516c\u5e73",
)
_STATION_COVERAGE_HINTS = (
    "coverage",
    "add more coverage",
    "\u4eba\u624b\u4e0d\u5920",
    "\u88dc\u4eba",
    "\u8865\u4eba",
    "\u539a\u3081",
)
_SWAP_HINTS = (
    "swap",
    "\u5c0d\u8abf",
    "\u5bf9\u8c03",
    "\u4ea4\u63db",
    "\u5165\u308c\u66ff\u3048",
)
_VAGUE_SCHEDULING_HINTS = (
    "\u6539\u4e00\u4e0b",
    "\u5909\u66f4\u3057\u3066",
    "\u90a3\u500b\u4eba",
    "\u90a3\u4e2a\u4eba",
    "\u628a\u4ed6",
    "\u63db\u6389",
    "\u6362\u6389",
    "\u63db",
    "\u6362",
)

_CHINESE_LANGUAGE_HINTS = (
    "\u8bf7",
    "\u628a",
    "\u8b93",
    "\u8ba9",
    *_ZH_SET_KEYWORDS,
    *_ZH_REMOVE_KEYWORDS,
    "\u5c11\u4e00\u9ede",
    "\u5c11\u4e00\u70b9",
    "\u4e0d\u8981\u518d\u6392\u592a\u591a",
    "\u73ed\u6578\u5e73\u5747",
    "\u73ed\u6570\u5e73\u5747",
    "\u5e73\u5747\u4e00\u9ede",
    "\u5e73\u5747\u4e00\u70b9",
    "\u592a\u7d2f",
    "\u4eba\u624b\u4e0d\u5920",
    "\u88dc\u4eba",
    "\u8865\u4eba",
    "\u5c0d\u8abf",
    "\u5bf9\u8c03",
    "\u63db\u6389",
    "\u6362\u6389",
)
_JAPANESE_LANGUAGE_HINTS = (
    "\u3092",
    "\u306b",
    "\u306e",
    "\u3067",
    *_JA_SET_KEYWORDS,
    *_JA_REMOVE_KEYWORDS,
    "\u6e1b\u3089",
    "\u671d\u756a",
    "\u6765\u9031",
    "\u539a\u3081",
    "\u5165\u308c\u66ff\u3048",
)
_ENGLISH_LANGUAGE_HINTS = (
    *_EN_SET_KEYWORDS,
    *_EN_REMOVE_KEYWORDS,
    *_REDUCE_SHIFT_HINTS,
    *_WORKLOAD_FAIRNESS_HINTS,
    *_STATION_COVERAGE_HINTS,
    *_SWAP_HINTS,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9_-]+")
_FOUR_DIGIT_DATE_PATTERN = re.compile(
    r"(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})"
)
_MONTH_DAY_KANJI_PATTERN = re.compile(
    r"(?P<month>\d{1,2})\u6708(?P<day>\d{1,2})(?:\u65e5|\u53f7)"
)
_MONTH_DAY_SLASH_PATTERN = re.compile(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})")
_MODEL_INTENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "request_language": {
            "type": "string",
            "enum": ["en", "zh", "ja", "unknown"],
        },
        "domain": {
            "type": "string",
            "enum": ["scheduling", "non_scheduling", "unknown"],
        },
        "capability_status": {
            "type": "string",
            "enum": [
                "executable",
                "understood_but_not_executable",
                "non_scheduling",
                "ambiguous_or_missing_information",
            ],
        },
        "intent_status": {
            "type": "string",
            "enum": ["supported", "ambiguous", "unsupported"],
        },
        "intent_type": {
            "type": ["string", "null"],
            "enum": [
                "set_assignment",
                "change_shift",
                "change_station",
                "remove_assignment",
                "reduce_or_avoid_shift_type",
                "workload_or_fairness",
                "station_coverage",
                "swap_workers",
                None,
            ],
        },
        "date": {
            "type": ["string", "null"],
            "description": "ISO date inside the selected month, or null.",
        },
        "worker_code": {"type": ["string", "null"]},
        "secondary_worker_code": {"type": ["string", "null"]},
        "shift_code": {"type": ["string", "null"]},
        "shift_type": {"type": ["string", "null"]},
        "station_code": {"type": ["string", "null"]},
        "date_range": {
            "type": ["string", "null"],
            "description": "Bounded label such as next_week, this_week, tomorrow, or recently.",
        },
        "preference_strength": {
            "type": ["string", "null"],
            "enum": ["reduce", "avoid", "increase", "balance", "unspecified", None],
        },
        "missing_fields": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason_code": {
            "type": ["string", "null"],
            "description": "Reason when the request is ambiguous or unsupported.",
        },
    },
    "required": [
        "request_language",
        "domain",
        "capability_status",
        "intent_status",
        "intent_type",
        "date",
        "worker_code",
        "secondary_worker_code",
        "shift_code",
        "shift_type",
        "station_code",
        "date_range",
        "preference_strength",
        "missing_fields",
        "reason_code",
    ],
}
_MODEL_INTENT_ALLOWED_KEYS = set(_MODEL_INTENT_JSON_SCHEMA["properties"])
_SUPPORTED_MODEL_LANGUAGES = {"en", "zh", "ja", "unknown"}


class RefineGraphState(TypedDict, total=False):
    """Small shared state passed through the single-turn refine graph."""

    workflow_request: RefineWorkflowRequest
    request_language: str
    domain: str
    capability_status: str
    intent_status: str
    intent_type: str
    canonical_intent: dict[str, Any]
    missing_fields: list[str]
    adjustment_patch: list[AssignmentPatchInput] | None
    outcome: RefineOutcome
    parsed_intent_json: dict[str, Any]
    candidate_result: MonthPlanningResult | None
    preview_executed: bool
    model_used: bool
    fallback_used: bool


class _UnsafeModelIntentError(ValueError):
    """Raised when model output asks for direct mutation outside refine."""


@dataclass(frozen=True, slots=True)
class _AliasEntry:
    canonical_code: str
    token_key: str | None
    compact_key: str


@dataclass(frozen=True, slots=True)
class _EntityMatch:
    canonical_code: str
    start: int
    end: int


class LangGraphRefineWorkflow:
    """Tiny compiled LangGraph workflow for bounded bilingual refine preview."""

    def __init__(
        self,
        *,
        engine_runner: MonthlyScheduleRefineEngine,
        model_client: StructuredOutputModelClient | None = None,
    ) -> None:
        self._engine_runner = engine_runner
        self._model_client = model_client or NoopStructuredOutputModelClient()
        builder = StateGraph(RefineGraphState)
        builder.add_node("detect_language", self._detect_language)
        builder.add_node("normalize_intent", self._normalize_intent)
        builder.add_node("run_preview_if_supported", self._run_preview_if_supported)
        builder.add_edge(START, "detect_language")
        builder.add_edge("detect_language", "normalize_intent")
        builder.add_edge("normalize_intent", "run_preview_if_supported")
        builder.add_edge("run_preview_if_supported", END)
        self.compiled_graph = builder.compile()

    def __call__(self, request: RefineWorkflowRequest) -> RefineWorkflowResult:
        final_state = self.compiled_graph.invoke({"workflow_request": request})
        request_language = final_state.get("request_language", "unknown")
        outcome = final_state.get("outcome") or _build_outcome(
            request_language,
            status="unsupported",
            message_key="refine_unsupported_intent",
        )
        parsed_intent_json = dict(
            final_state.get("parsed_intent_json")
            or _build_parsed_intent_json(
                request_language=request_language,
                domain=final_state.get("domain", UNKNOWN_DOMAIN),
                capability_status=final_state.get(
                    "capability_status",
                    _capability_status_from_intent_status(
                        final_state.get("intent_status", "unsupported")
                    ),
                ),
                intent_status=final_state.get("intent_status", "unsupported"),
                intent_type=final_state.get("intent_type"),
                canonical_intent=final_state.get("canonical_intent"),
                missing_fields=final_state.get("missing_fields"),
                outcome=outcome,
                adjustment_patch=final_state.get("adjustment_patch"),
                preview_executed=bool(final_state.get("preview_executed")),
                model_used=bool(final_state.get("model_used")),
                fallback_used=bool(final_state.get("fallback_used")),
            )
        )
        return RefineWorkflowResult(
            request_language=request_language,
            outcome=outcome,
            parsed_intent_json=parsed_intent_json,
            adjustment_patch=final_state.get("adjustment_patch"),
            candidate_result=final_state.get("candidate_result"),
        )

    def _detect_language(self, state: RefineGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        return {"request_language": _detect_request_language(request.request_text)}

    def _normalize_intent(self, state: RefineGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        request_language = state.get("request_language", "unknown")
        model_state, fallback_used = self._normalize_intent_with_model(
            request=request,
            fallback_language=request_language,
        )
        if model_state is not None:
            return model_state

        pr7_state = _classify_local_pr7_state(
            request,
            request_language=request_language,
            fallback_used=fallback_used,
        )
        if pr7_state is not None:
            return pr7_state

        if not _looks_like_scheduling_request(request.request_text):
            return _non_scheduling_state(
                request_language,
                reason_code="non_scheduling_request",
                fallback_used=fallback_used,
            )

        parsed_date, date_reason_code = _parse_request_date(
            request.request_text,
            year=request.year,
            month=request.month,
        )
        if parsed_date is None:
            return _ambiguous_state(
                request_language,
                reason_code=date_reason_code or "date_required",
                fallback_used=fallback_used,
            )

        worker_code = _resolve_worker_code(
            request.request_text,
            workers=request.planning_input.workers,
        )
        if worker_code is None:
            return _ambiguous_state(
                request_language,
                reason_code="worker_required",
                fallback_used=fallback_used,
            )

        intent_type = _detect_intent_type(
            request.request_text,
            shift_code=_resolve_shift_code(
                request.request_text,
                shifts=request.planning_input.shifts,
            ),
            station_code=_resolve_station_code(
                request.request_text,
                stations=request.planning_input.stations,
            ),
        )
        if intent_type is None:
            outcome = _build_outcome(
                request_language,
                status="unsupported",
                message_key="refine_unsupported_intent",
            )
            return {
                "intent_status": "unsupported",
                "domain": SCHEDULING_DOMAIN,
                "capability_status": CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
                "outcome": outcome,
                "preview_executed": False,
                "parsed_intent_json": _build_parsed_intent_json(
                    request_language=request_language,
                    domain=SCHEDULING_DOMAIN,
                    capability_status=CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
                    intent_status="unsupported",
                    outcome=outcome,
                    preview_executed=False,
                    fallback_used=fallback_used,
                ),
                "fallback_used": fallback_used,
            }

        if intent_type == "remove_assignment":
            existing_assignment, existing_reason_code = _resolve_existing_assignment(
                request,
                assignment_date=parsed_date,
                worker_code=worker_code,
            )
            if existing_assignment is None:
                return _ambiguous_state(
                    request_language,
                    reason_code=existing_reason_code or "existing_assignment_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )
            canonical_intent = {
                "date": parsed_date.isoformat(),
                "worker_code": worker_code,
            }
            return {
                "intent_status": "supported",
                "domain": SCHEDULING_DOMAIN,
                "capability_status": CAPABILITY_EXECUTABLE,
                "intent_type": intent_type,
                "canonical_intent": canonical_intent,
                "adjustment_patch": [
                    AssignmentPatchInput(
                        operation="remove",
                        date=parsed_date,
                        worker_code=worker_code,
                        note="langgraph_refine_preview",
                    )
                ],
                "fallback_used": fallback_used,
            }

        shift_code = _resolve_shift_code(
            request.request_text,
            shifts=request.planning_input.shifts,
        )

        station_code = _resolve_station_code(
            request.request_text,
            stations=request.planning_input.stations,
        )

        if intent_type == "change_shift":
            if shift_code is None:
                return _ambiguous_state(
                    request_language,
                    reason_code="shift_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )
            existing_assignment, existing_reason_code = _resolve_existing_assignment(
                request,
                assignment_date=parsed_date,
                worker_code=worker_code,
            )
            if existing_assignment is None:
                return _ambiguous_state(
                    request_language,
                    reason_code=existing_reason_code or "existing_assignment_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )
            if existing_assignment.station_code is None:
                return _ambiguous_state(
                    request_language,
                    reason_code="existing_station_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )
            station_code = existing_assignment.station_code
        elif intent_type == "change_station":
            if station_code is None:
                return _ambiguous_state(
                    request_language,
                    reason_code="station_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )
            existing_assignment, existing_reason_code = _resolve_existing_assignment(
                request,
                assignment_date=parsed_date,
                worker_code=worker_code,
            )
            if existing_assignment is None:
                return _ambiguous_state(
                    request_language,
                    reason_code=existing_reason_code or "existing_assignment_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )
            shift_code = existing_assignment.shift_code
        else:
            if shift_code is None:
                return _ambiguous_state(
                    request_language,
                    reason_code="shift_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )
            if station_code is None:
                return _ambiguous_state(
                    request_language,
                    reason_code="station_required",
                    intent_type=intent_type,
                    fallback_used=fallback_used,
                )

        canonical_intent = {
            "date": parsed_date.isoformat(),
            "worker_code": worker_code,
            "shift_code": shift_code,
            "station_code": station_code,
        }
        return {
            "intent_status": "supported",
            "domain": SCHEDULING_DOMAIN,
            "capability_status": CAPABILITY_EXECUTABLE,
            "intent_type": intent_type,
            "canonical_intent": canonical_intent,
            "adjustment_patch": [
                AssignmentPatchInput(
                    operation="set",
                    date=parsed_date,
                    worker_code=worker_code,
                    shift_code=shift_code,
                    station_code=station_code,
                    note="langgraph_refine_preview",
                )
            ],
            "fallback_used": fallback_used,
        }

    def _normalize_intent_with_model(
        self,
        *,
        request: RefineWorkflowRequest,
        fallback_language: str,
    ) -> tuple[dict[str, object] | None, bool]:
        try:
            model_payload = self._model_client.generate_json(
                system_prompt=_build_model_system_prompt(),
                user_prompt=_build_model_user_prompt(request),
                json_schema=_MODEL_INTENT_JSON_SCHEMA,
            )
            model_state = _coerce_model_intent_state(
                model_payload,
                request=request,
                fallback_language=fallback_language,
            )
            if model_state.get("intent_status") == "supported":
                return model_state, False
            if (
                "capability_status" in model_payload
                and model_state.get("capability_status")
                in {
                    CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
                    CAPABILITY_NON_SCHEDULING,
                    CAPABILITY_AMBIGUOUS,
                }
            ):
                return model_state, False
            return None, True
        except _UnsafeModelIntentError:
            request_language = (
                fallback_language
                if fallback_language in _SUPPORTED_MODEL_LANGUAGES
                else "unknown"
            )
            outcome = _build_outcome(
                request_language,
                status="unsupported",
                message_key="refine_unsupported_intent",
                message_values={"reason_code": "direct_mutation_not_allowed"},
            )
            return {
                "request_language": request_language,
                "intent_status": "unsupported",
                "domain": SCHEDULING_DOMAIN,
                "capability_status": CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
                "outcome": outcome,
                "preview_executed": False,
                "model_used": True,
                "fallback_used": False,
                "parsed_intent_json": _build_parsed_intent_json(
                    request_language=request_language,
                    domain=SCHEDULING_DOMAIN,
                    capability_status=CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
                    intent_status="unsupported",
                    reason_code="direct_mutation_not_allowed",
                    outcome=outcome,
                    preview_executed=False,
                    model_used=True,
                    fallback_used=False,
                ),
            }, False
        except (ModelUnavailableError, ValueError):
            return None, True

    def _run_preview_if_supported(self, state: RefineGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        request_language = state.get("request_language", "unknown")
        domain = state.get("domain", SCHEDULING_DOMAIN)
        capability_status = state.get(
            "capability_status",
            _capability_status_from_intent_status(
                state.get("intent_status", "unsupported")
            ),
        )
        intent_status = state.get("intent_status", "unsupported")
        intent_type = state.get("intent_type")
        canonical_intent = dict(state.get("canonical_intent") or {})
        adjustment_patch = state.get("adjustment_patch")

        if (
            intent_status != "supported"
            or capability_status != CAPABILITY_EXECUTABLE
            or not adjustment_patch
            or intent_type is None
        ):
            outcome = state.get("outcome") or _build_outcome(
                request_language,
                status="unsupported",
                message_key="refine_unsupported_intent",
            )
            model_used = bool(state.get("model_used"))
            fallback_used = bool(state.get("fallback_used"))
            parsed_intent_json = state.get("parsed_intent_json")
            if isinstance(parsed_intent_json, dict):
                return {
                    "outcome": outcome,
                    "preview_executed": False,
                    "model_used": model_used,
                    "fallback_used": fallback_used,
                    "parsed_intent_json": dict(parsed_intent_json),
                }
            return {
                "outcome": outcome,
                "preview_executed": False,
                "model_used": model_used,
                "fallback_used": fallback_used,
                "parsed_intent_json": _build_parsed_intent_json(
                    request_language=request_language,
                    domain=domain,
                    capability_status=capability_status,
                    intent_status=intent_status,
                    intent_type=intent_type,
                    canonical_intent=canonical_intent or None,
                    missing_fields=state.get("missing_fields"),
                    outcome=outcome,
                    adjustment_patch=adjustment_patch,
                    preview_executed=False,
                    model_used=model_used,
                    fallback_used=fallback_used,
                ),
            }

        refined_planning_input = _build_refined_planning_input(
            request.planning_input,
            adjustment_patch,
        )
        candidate_result = attach_month_planning_evaluation(
            self._engine_runner(refined_planning_input)
        )
        outcome = _build_outcome(
            request_language,
            status="preview_ready",
            message_key=(
                "refine_preview_ready_remove"
                if intent_type == "remove_assignment"
                else "refine_preview_ready_set"
            ),
            message_values=canonical_intent,
        )
        model_used = bool(state.get("model_used"))
        fallback_used = bool(state.get("fallback_used"))
        return {
            "candidate_result": candidate_result,
            "outcome": outcome,
            "preview_executed": True,
            "model_used": model_used,
            "fallback_used": fallback_used,
            "parsed_intent_json": _build_parsed_intent_json(
                request_language=request_language,
                domain=SCHEDULING_DOMAIN,
                capability_status=CAPABILITY_EXECUTABLE,
                intent_status="supported",
                intent_type=intent_type,
                canonical_intent=canonical_intent,
                outcome=outcome,
                adjustment_patch=adjustment_patch,
                preview_executed=True,
                model_used=model_used,
                fallback_used=fallback_used,
            ),
        }


def _build_outcome(
    language: str,
    *,
    status: str,
    message_key: str,
    message_values: dict[str, object] | None = None,
) -> RefineOutcome:
    return RefineOutcome(
        language=language,
        status=status,
        message_key=message_key,
        message_values=dict(message_values or {}),
    )


def _build_parsed_intent_json(
    *,
    request_language: str,
    domain: str,
    capability_status: str,
    intent_status: str,
    intent_type: str | None = None,
    canonical_intent: dict[str, object] | None = None,
    missing_fields: list[str] | None = None,
    outcome: RefineOutcome,
    adjustment_patch: list[AssignmentPatchInput] | None = None,
    preview_executed: bool,
    reason_code: str | None = None,
    model_used: bool = False,
    fallback_used: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_language": request_language,
        "domain": domain,
        "capability_status": capability_status,
        "intent_status": intent_status,
        "preview_executed": preview_executed,
        "model_used": model_used,
        "fallback_used": fallback_used,
        "outcome": {
            "language": outcome.language,
            "status": outcome.status,
            "message_key": outcome.message_key,
            "message_values": dict(outcome.message_values),
        },
    }
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if missing_fields:
        payload["missing_fields"] = list(missing_fields)
    if intent_type is not None:
        payload["intent_type"] = intent_type
    if canonical_intent is not None:
        payload["canonical_intent"] = dict(canonical_intent)
    if adjustment_patch:
        payload["adjustment_patch"] = [
            {
                "operation": patch.operation,
                "date": patch.date.isoformat(),
                "worker_code": patch.worker_code,
                "shift_code": patch.shift_code,
                "station_code": patch.station_code,
                "note": patch.note,
            }
            for patch in adjustment_patch
        ]
    return payload


def _ambiguous_state(
    language: str,
    *,
    reason_code: str,
    intent_type: str | None = None,
    canonical_intent: dict[str, object] | None = None,
    missing_fields: list[str] | None = None,
    model_used: bool = False,
    fallback_used: bool = False,
) -> dict[str, object]:
    resolved_missing_fields = missing_fields or _missing_fields_for_reason(reason_code)
    outcome = _build_outcome(
        language,
        status="ambiguous",
        message_key="refine_ambiguous_missing_information",
        message_values={
            "reason_code": reason_code,
            "missing_fields": _render_missing_fields(resolved_missing_fields),
        },
    )
    return {
        "intent_status": "ambiguous",
        "domain": SCHEDULING_DOMAIN,
        "capability_status": CAPABILITY_AMBIGUOUS,
        "intent_type": intent_type,
        "canonical_intent": dict(canonical_intent or {}),
        "missing_fields": list(resolved_missing_fields),
        "outcome": outcome,
        "preview_executed": False,
        "model_used": model_used,
        "fallback_used": fallback_used,
        "parsed_intent_json": _build_parsed_intent_json(
            request_language=language,
            domain=SCHEDULING_DOMAIN,
            capability_status=CAPABILITY_AMBIGUOUS,
            intent_status="ambiguous",
            intent_type=intent_type,
            canonical_intent=canonical_intent,
            missing_fields=resolved_missing_fields,
            reason_code=reason_code,
            outcome=outcome,
            preview_executed=False,
            model_used=model_used,
            fallback_used=fallback_used,
        ),
    }


def _non_scheduling_state(
    language: str,
    *,
    reason_code: str,
    model_used: bool = False,
    fallback_used: bool = False,
) -> dict[str, object]:
    outcome = _build_outcome(
        language,
        status=CAPABILITY_NON_SCHEDULING,
        message_key="refine_non_scheduling_request",
        message_values={"reason_code": reason_code},
    )
    return {
        "intent_status": "unsupported",
        "domain": NON_SCHEDULING_DOMAIN,
        "capability_status": CAPABILITY_NON_SCHEDULING,
        "outcome": outcome,
        "preview_executed": False,
        "model_used": model_used,
        "fallback_used": fallback_used,
        "parsed_intent_json": _build_parsed_intent_json(
            request_language=language,
            domain=NON_SCHEDULING_DOMAIN,
            capability_status=CAPABILITY_NON_SCHEDULING,
            intent_status="unsupported",
            reason_code=reason_code,
            outcome=outcome,
            preview_executed=False,
            model_used=model_used,
            fallback_used=fallback_used,
        ),
    }


def _understood_but_not_executable_state(
    language: str,
    *,
    intent_type: str,
    canonical_intent: dict[str, object] | None = None,
    reason_code: str,
    model_used: bool = False,
    fallback_used: bool = False,
) -> dict[str, object]:
    outcome = _build_outcome(
        language,
        status=CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
        message_key="refine_understood_but_not_executable",
        message_values={
            "intent_label": _intent_label(intent_type),
            "intent_type": intent_type,
            "reason_code": reason_code,
            "suggestion": _concrete_edit_suggestion(language),
        },
    )
    return {
        "intent_status": "unsupported",
        "domain": SCHEDULING_DOMAIN,
        "capability_status": CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
        "intent_type": intent_type,
        "canonical_intent": dict(canonical_intent or {}),
        "outcome": outcome,
        "preview_executed": False,
        "model_used": model_used,
        "fallback_used": fallback_used,
        "parsed_intent_json": _build_parsed_intent_json(
            request_language=language,
            domain=SCHEDULING_DOMAIN,
            capability_status=CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
            intent_status="unsupported",
            intent_type=intent_type,
            canonical_intent=canonical_intent,
            reason_code=reason_code,
            outcome=outcome,
            preview_executed=False,
            model_used=model_used,
            fallback_used=fallback_used,
        ),
    }


def _capability_status_from_intent_status(intent_status: str) -> str:
    if intent_status == "supported":
        return CAPABILITY_EXECUTABLE
    if intent_status == "ambiguous":
        return CAPABILITY_AMBIGUOUS
    return CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE


def _missing_fields_for_reason(reason_code: str) -> list[str]:
    return {
        "date_required": ["date"],
        "worker_required": ["worker"],
        "secondary_worker_required": ["secondary_worker"],
        "shift_required": ["shift"],
        "station_required": ["station"],
        "target_assignment_required": ["target_shift_or_station"],
    }.get(reason_code, ["date", "worker", "target_shift_or_station"])


def _render_missing_fields(missing_fields: list[str]) -> str:
    labels = [
        _MISSING_FIELD_LABELS.get(field_name, field_name)
        for field_name in missing_fields
    ]
    return ", ".join(labels)


def _intent_label(intent_type: str) -> str:
    return _INTENT_LABELS.get(intent_type, intent_type)


def _concrete_edit_suggestion(language: str) -> str:
    return _CONCRETE_EDIT_SUGGESTIONS.get(
        language,
        _CONCRETE_EDIT_SUGGESTIONS["unknown"],
    )


def _build_model_system_prompt() -> str:
    return (
        "Interpret one restaurant monthly-schedule refine request into bounded JSON. "
        "Use only the provided worker, shift, station, and month context. "
        "Set domain to scheduling only for schedule-change requests. Set "
        "capability_status to executable only for one set_assignment, "
        "change_shift, change_station, or remove_assignment intent. For "
        "change_shift, return the target shift and leave station_code null. For "
        "change_station, return the target station and leave shift_code null. If "
        "the request explicitly contains both a station and a shift, return "
        "set_assignment, not change_shift or change_station. Classify reduce or "
        "avoid shift type, workload fairness, station coverage, and worker swap "
        "requests as scheduling with understood_but_not_executable. If required "
        "details are missing, return ambiguous_or_missing_information and list "
        "missing_fields. If the request is not scheduling-related, return "
        "non_scheduling. Never apply, save, or mutate a schedule."
    )


def _build_model_user_prompt(request: RefineWorkflowRequest) -> str:
    planning_input = request.planning_input
    return json.dumps(
        {
            "task": "interpret_month_refine_request",
            "tenant_slug": request.tenant_slug,
            "selected_month": f"{request.year:04d}-{request.month:02d}",
            "request_text": request.request_text,
            "allowed_intent_types": [
                "set_assignment",
                "change_shift",
                "change_station",
                "remove_assignment",
                "reduce_or_avoid_shift_type",
                "workload_or_fairness",
                "station_coverage",
                "swap_workers",
            ],
            "allowed_capability_statuses": [
                CAPABILITY_EXECUTABLE,
                CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
                CAPABILITY_NON_SCHEDULING,
                CAPABILITY_AMBIGUOUS,
            ],
            "requirements": {
                "date_must_be_inside_selected_month": True,
                "use_only_listed_codes": True,
                "return_exactly_one_intent": True,
                "do_not_apply_or_save": True,
                "set_assignment_requires": [
                    "date",
                    "worker_code",
                    "shift_code",
                    "station_code",
                ],
                "change_shift_requires": [
                    "date",
                    "worker_code",
                    "shift_code",
                    "existing_current_assignment",
                ],
                "change_station_requires": [
                    "date",
                    "worker_code",
                    "station_code",
                    "existing_current_assignment",
                ],
                "remove_assignment_requires": ["date", "worker_code"],
                "unsupported_scheduling_intents_do_not_execute": True,
                "non_scheduling_requests_are_rejected": True,
            },
            "current_assignments": [
                {
                    "date": assignment.date.isoformat(),
                    "worker_code": assignment.worker_code,
                    "shift_code": assignment.shift_code,
                    "station_code": assignment.station_code,
                }
                for assignment in (request.current_assignments or [])
            ],
            "workers": [
                {
                    "worker_code": worker.worker_code,
                    "name": worker.name,
                    "role": worker.role,
                    "aliases": _collect_prompt_aliases(worker.metadata_json),
                }
                for worker in planning_input.workers
            ],
            "shifts": [
                {
                    "shift_code": shift.shift_code,
                    "name": shift.name,
                    "is_off_shift": shift.is_off_shift,
                    "aliases": _collect_prompt_aliases(shift.metadata_json),
                }
                for shift in planning_input.shifts
            ],
            "stations": [
                {
                    "station_code": station.station_code,
                    "name": station.name,
                    "is_active": station.is_active,
                    "aliases": _collect_prompt_aliases(station.metadata_json),
                }
                for station in planning_input.stations
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _collect_prompt_aliases(metadata_json: dict[str, object] | None) -> list[str]:
    if not isinstance(metadata_json, dict):
        return []

    aliases: list[str] = []
    raw_aliases = metadata_json.get("aliases")
    if isinstance(raw_aliases, list):
        aliases.extend(
            alias.strip()
            for alias in raw_aliases
            if isinstance(alias, str) and alias.strip()
        )

    localized_aliases = metadata_json.get("localized_aliases")
    if isinstance(localized_aliases, dict):
        for raw_values in localized_aliases.values():
            if not isinstance(raw_values, list):
                continue
            aliases.extend(
                alias.strip()
                for alias in raw_values
                if isinstance(alias, str) and alias.strip()
            )
    return sorted(set(aliases))


def _classify_local_pr7_state(
    request: RefineWorkflowRequest,
    *,
    request_language: str,
    fallback_used: bool,
) -> dict[str, object] | None:
    request_text = request.request_text
    normalized_text = request_text.casefold()
    worker_codes = _resolve_worker_codes(
        request_text,
        workers=request.planning_input.workers,
    )

    if _contains_any_hint(normalized_text, request_text, _SWAP_HINTS):
        canonical_intent = _build_local_abstract_canonical_intent(
            request,
            worker_codes=worker_codes,
        )
        if len(worker_codes) < 2:
            return _ambiguous_state(
                request_language,
                reason_code="secondary_worker_required",
                intent_type="swap_workers",
                canonical_intent=canonical_intent,
                missing_fields=["secondary_worker"],
                fallback_used=fallback_used,
            )
        canonical_intent["worker_code"] = worker_codes[0]
        canonical_intent["secondary_worker_code"] = worker_codes[1]
        return _understood_but_not_executable_state(
            request_language,
            intent_type="swap_workers",
            canonical_intent=canonical_intent,
            reason_code="swap_not_executable",
            fallback_used=fallback_used,
        )

    if _looks_like_reduce_or_avoid_shift_request(request_text):
        canonical_intent = _build_local_abstract_canonical_intent(
            request,
            worker_codes=worker_codes,
        )
        shift_type = _detect_shift_type(request_text)
        if shift_type is not None:
            canonical_intent["shift_type"] = shift_type
        canonical_intent["preference_strength"] = _detect_preference_strength(
            request_text
        )
        return _understood_but_not_executable_state(
            request_language,
            intent_type="reduce_or_avoid_shift_type",
            canonical_intent=canonical_intent,
            reason_code="single_day_edits_only",
            fallback_used=fallback_used,
        )

    if _contains_any_hint(normalized_text, request_text, _WORKLOAD_FAIRNESS_HINTS):
        canonical_intent = _build_local_abstract_canonical_intent(
            request,
            worker_codes=worker_codes,
        )
        return _understood_but_not_executable_state(
            request_language,
            intent_type="workload_or_fairness",
            canonical_intent=canonical_intent,
            reason_code="planner_level_optimization_required",
            fallback_used=fallback_used,
        )

    if _contains_any_hint(normalized_text, request_text, _STATION_COVERAGE_HINTS):
        canonical_intent = _build_local_abstract_canonical_intent(
            request,
            worker_codes=worker_codes,
        )
        return _understood_but_not_executable_state(
            request_language,
            intent_type="station_coverage",
            canonical_intent=canonical_intent,
            reason_code="coverage_planning_not_executable",
            fallback_used=fallback_used,
        )

    if _looks_like_vague_scheduling_request(request_text):
        canonical_intent = _build_local_abstract_canonical_intent(
            request,
            worker_codes=worker_codes,
        )
        missing_fields = _missing_fields_for_vague_request(
            request,
            worker_codes=worker_codes,
        )
        return _ambiguous_state(
            request_language,
            reason_code="target_assignment_required",
            canonical_intent=canonical_intent,
            missing_fields=missing_fields,
            fallback_used=fallback_used,
        )

    return None


def _build_local_abstract_canonical_intent(
    request: RefineWorkflowRequest,
    *,
    worker_codes: list[str],
) -> dict[str, object]:
    canonical_intent: dict[str, object] = {}
    parsed_date, _ = _parse_request_date(
        request.request_text,
        year=request.year,
        month=request.month,
    )
    if parsed_date is not None:
        canonical_intent["date"] = parsed_date.isoformat()
    date_range = _detect_date_range_label(request.request_text)
    if date_range is not None:
        canonical_intent["date_range"] = date_range
    if worker_codes:
        canonical_intent["worker_code"] = worker_codes[0]
    shift_code = _resolve_shift_code(
        request.request_text,
        shifts=request.planning_input.shifts,
    )
    if shift_code is not None:
        canonical_intent["shift_code"] = shift_code
    station_code = _resolve_station_code(
        request.request_text,
        stations=request.planning_input.stations,
    )
    if station_code is not None:
        canonical_intent["station_code"] = station_code
    return canonical_intent


def _build_model_non_executable_canonical_intent(
    payload: dict[str, Any],
    *,
    request: RefineWorkflowRequest,
) -> dict[str, object]:
    canonical_intent: dict[str, object] = {}
    date_value = _coerce_optional_model_text(payload.get("date"), label="date")
    if date_value is not None:
        parsed_date = _coerce_model_date(
            date_value,
            year=request.year,
            month=request.month,
        )
        canonical_intent["date"] = parsed_date.isoformat()
    for payload_key, canonical_key, allowed_codes in (
        (
            "worker_code",
            "worker_code",
            [
                worker.worker_code
                for worker in request.planning_input.workers
                if worker.is_active
            ],
        ),
        (
            "secondary_worker_code",
            "secondary_worker_code",
            [
                worker.worker_code
                for worker in request.planning_input.workers
                if worker.is_active
            ],
        ),
        (
            "shift_code",
            "shift_code",
            [
                shift.shift_code
                for shift in request.planning_input.shifts
                if not shift.is_off_shift
            ],
        ),
        (
            "station_code",
            "station_code",
            [
                station.station_code
                for station in request.planning_input.stations
                if station.is_active
            ],
        ),
    ):
        resolved_code = _resolve_optional_model_code(
            payload.get(payload_key),
            allowed_codes=allowed_codes,
            label=payload_key,
        )
        if resolved_code is not None:
            canonical_intent[canonical_key] = resolved_code
    for payload_key in ("date_range", "shift_type", "preference_strength"):
        text_value = _coerce_optional_model_text(
            payload.get(payload_key),
            label=payload_key,
        )
        if text_value is not None:
            canonical_intent[payload_key] = text_value
    return canonical_intent


def _coerce_model_intent_state(
    payload: dict[str, Any],
    *,
    request: RefineWorkflowRequest,
    fallback_language: str,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Structured refine payload must be a JSON object.")

    unexpected_keys = set(payload) - _MODEL_INTENT_ALLOWED_KEYS
    if unexpected_keys:
        if _contains_direct_mutation_key(unexpected_keys):
            raise _UnsafeModelIntentError(
                "Structured refine payload requested direct mutation."
            )
        raise ValueError("Structured refine payload contained unsupported keys.")
    for command_field in (
        "intent_type",
        "reason_code",
        "domain",
        "capability_status",
    ):
        command_value = payload.get(command_field)
        if (
            isinstance(command_value, str)
            and _contains_direct_mutation_key({command_value})
        ):
            raise _UnsafeModelIntentError(
                "Structured refine payload requested direct mutation."
            )

    request_language = _coerce_model_language(
        payload.get("request_language"),
        fallback_language=fallback_language,
    )
    domain = _coerce_model_domain(payload.get("domain"))
    intent_status = _coerce_required_model_text(
        payload.get("intent_status"),
        label="intent_status",
    )
    if intent_status not in {"supported", "ambiguous", "unsupported"}:
        raise ValueError("Structured refine payload contained an invalid status.")

    raw_intent_type = payload.get("intent_type")
    intent_type = _coerce_optional_model_text(raw_intent_type, label="intent_type")
    if intent_type is not None and intent_type not in _SUPPORTED_MODEL_INTENT_TYPES:
        raise ValueError("Structured refine payload contained an invalid intent type.")
    capability_status = _coerce_model_capability_status(
        payload.get("capability_status"),
        intent_status=intent_status,
        intent_type=intent_type,
        domain=domain,
    )

    reason_code = (
        _coerce_optional_model_text(payload.get("reason_code"), label="reason_code")
        or "ambiguous_reference"
    )
    missing_fields = _coerce_model_missing_fields(payload.get("missing_fields"))

    if domain == NON_SCHEDULING_DOMAIN or capability_status == CAPABILITY_NON_SCHEDULING:
        return _non_scheduling_state(
            request_language,
            reason_code=reason_code,
            model_used=True,
            fallback_used=False,
        )

    if capability_status == CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE:
        canonical_intent = _build_model_non_executable_canonical_intent(
            payload,
            request=request,
        )
        return _understood_but_not_executable_state(
            request_language,
            intent_type=intent_type or "scheduling_request",
            canonical_intent=canonical_intent,
            reason_code=reason_code,
            model_used=True,
            fallback_used=False,
        )

    if (
        intent_status == "ambiguous"
        or capability_status == CAPABILITY_AMBIGUOUS
    ):
        canonical_intent = _build_model_non_executable_canonical_intent(
            payload,
            request=request,
        )
        return _ambiguous_state(
            request_language,
            reason_code=reason_code,
            intent_type=intent_type,
            canonical_intent=canonical_intent,
            missing_fields=missing_fields,
            model_used=True,
            fallback_used=False,
        )

    if intent_status == "unsupported":
        outcome = _build_outcome(
            request_language,
            status="unsupported",
            message_key=(
                "refine_unsupported_language"
                if reason_code == "unsupported_language"
                else "refine_unsupported_intent"
            ),
            message_values={"reason_code": reason_code},
        )
        return {
            "request_language": request_language,
            "intent_status": "unsupported",
            "domain": domain,
            "capability_status": CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
            "intent_type": intent_type,
            "outcome": outcome,
            "preview_executed": False,
            "model_used": True,
            "fallback_used": False,
            "parsed_intent_json": _build_parsed_intent_json(
                request_language=request_language,
                domain=domain,
                capability_status=CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE,
                intent_status="unsupported",
                intent_type=intent_type,
                reason_code=reason_code,
                outcome=outcome,
                preview_executed=False,
                model_used=True,
                fallback_used=False,
            ),
        }

    if intent_type in _ABSTRACT_INTENT_TYPES:
        canonical_intent = _build_model_non_executable_canonical_intent(
            payload,
            request=request,
        )
        return _understood_but_not_executable_state(
            request_language,
            intent_type=intent_type,
            canonical_intent=canonical_intent,
            reason_code="unsupported_intent_not_executable",
            model_used=True,
            fallback_used=False,
        )

    if intent_type is None:
        raise ValueError("Supported refine payload requires an intent type.")

    parsed_date = _coerce_model_date(
        payload.get("date"),
        year=request.year,
        month=request.month,
    )
    worker_code = _resolve_model_code(
        payload.get("worker_code"),
        allowed_codes=[
            worker.worker_code
            for worker in request.planning_input.workers
            if worker.is_active
        ],
        label="worker_code",
    )
    explicit_shift_code = _resolve_shift_code(
        request.request_text,
        shifts=request.planning_input.shifts,
    )
    explicit_station_code = _resolve_station_code(
        request.request_text,
        stations=request.planning_input.stations,
    )
    if (
        intent_type != "remove_assignment"
        and explicit_shift_code is not None
        and explicit_station_code is not None
    ):
        intent_type = "set_assignment"

    if intent_type == "remove_assignment":
        existing_assignment, existing_reason_code = _resolve_existing_assignment(
            request,
            assignment_date=parsed_date,
            worker_code=worker_code,
        )
        if existing_assignment is None:
            return _ambiguous_state(
                request_language,
                reason_code=existing_reason_code or "existing_assignment_required",
                intent_type=intent_type,
                model_used=True,
                fallback_used=False,
            )
        canonical_intent = {
            "date": parsed_date.isoformat(),
            "worker_code": worker_code,
        }
        adjustment_patch = [
            AssignmentPatchInput(
                operation="remove",
                date=parsed_date,
                worker_code=worker_code,
                note="langgraph_refine_preview",
            )
        ]
    elif intent_type == "change_shift":
        shift_code = _resolve_model_code(
            payload.get("shift_code"),
            allowed_codes=[
                shift.shift_code
                for shift in request.planning_input.shifts
                if not shift.is_off_shift
            ],
            label="shift_code",
        )
        existing_assignment, existing_reason_code = _resolve_existing_assignment(
            request,
            assignment_date=parsed_date,
            worker_code=worker_code,
        )
        if existing_assignment is None:
            return _ambiguous_state(
                request_language,
                reason_code=existing_reason_code or "existing_assignment_required",
                intent_type=intent_type,
                model_used=True,
                fallback_used=False,
            )
        if existing_assignment.station_code is None:
            return _ambiguous_state(
                request_language,
                reason_code="existing_station_required",
                intent_type=intent_type,
                model_used=True,
                fallback_used=False,
            )
        station_code = existing_assignment.station_code
        canonical_intent = {
            "date": parsed_date.isoformat(),
            "worker_code": worker_code,
            "shift_code": shift_code,
            "station_code": station_code,
        }
        adjustment_patch = [
            AssignmentPatchInput(
                operation="set",
                date=parsed_date,
                worker_code=worker_code,
                shift_code=shift_code,
                station_code=station_code,
                note="langgraph_refine_preview",
            )
        ]
    elif intent_type == "change_station":
        station_code = _resolve_model_code(
            payload.get("station_code"),
            allowed_codes=[
                station.station_code
                for station in request.planning_input.stations
                if station.is_active
            ],
            label="station_code",
        )
        existing_assignment, existing_reason_code = _resolve_existing_assignment(
            request,
            assignment_date=parsed_date,
            worker_code=worker_code,
        )
        if existing_assignment is None:
            return _ambiguous_state(
                request_language,
                reason_code=existing_reason_code or "existing_assignment_required",
                intent_type=intent_type,
                model_used=True,
                fallback_used=False,
            )
        shift_code = existing_assignment.shift_code
        canonical_intent = {
            "date": parsed_date.isoformat(),
            "worker_code": worker_code,
            "shift_code": shift_code,
            "station_code": station_code,
        }
        adjustment_patch = [
            AssignmentPatchInput(
                operation="set",
                date=parsed_date,
                worker_code=worker_code,
                shift_code=shift_code,
                station_code=station_code,
                note="langgraph_refine_preview",
            )
        ]
    else:
        shift_code = _resolve_model_code(
            explicit_shift_code or payload.get("shift_code"),
            allowed_codes=[
                shift.shift_code
                for shift in request.planning_input.shifts
                if not shift.is_off_shift
            ],
            label="shift_code",
        )
        station_code = _resolve_model_code(
            explicit_station_code or payload.get("station_code"),
            allowed_codes=[
                station.station_code
                for station in request.planning_input.stations
                if station.is_active
            ],
            label="station_code",
        )
        canonical_intent = {
            "date": parsed_date.isoformat(),
            "worker_code": worker_code,
            "shift_code": shift_code,
            "station_code": station_code,
        }
        adjustment_patch = [
            AssignmentPatchInput(
                operation="set",
                date=parsed_date,
                worker_code=worker_code,
                shift_code=shift_code,
                station_code=station_code,
                note="langgraph_refine_preview",
            )
        ]

    return {
        "request_language": request_language,
        "intent_status": "supported",
        "domain": SCHEDULING_DOMAIN,
        "capability_status": CAPABILITY_EXECUTABLE,
        "intent_type": intent_type,
        "canonical_intent": canonical_intent,
        "adjustment_patch": adjustment_patch,
        "model_used": True,
        "fallback_used": False,
    }


def _coerce_model_language(value: object, *, fallback_language: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _SUPPORTED_MODEL_LANGUAGES:
            return normalized
    if fallback_language in _SUPPORTED_MODEL_LANGUAGES:
        return fallback_language
    return "unknown"


def _coerce_model_domain(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _SUPPORTED_MODEL_DOMAINS:
            return normalized
        if normalized:
            raise ValueError("Structured refine payload contained an invalid domain.")
    elif value is not None:
        raise ValueError("Structured refine payload domain must be a string.")
    return SCHEDULING_DOMAIN


def _coerce_model_capability_status(
    value: object,
    *,
    intent_status: str,
    intent_type: str | None,
    domain: str,
) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _SUPPORTED_MODEL_CAPABILITY_STATUSES:
            return normalized
        if normalized:
            raise ValueError(
                "Structured refine payload contained an invalid capability status."
            )
    elif value is not None:
        raise ValueError(
            "Structured refine payload capability_status must be a string."
        )
    if domain == NON_SCHEDULING_DOMAIN:
        return CAPABILITY_NON_SCHEDULING
    if intent_status == "supported":
        return CAPABILITY_EXECUTABLE
    if intent_status == "ambiguous":
        return CAPABILITY_AMBIGUOUS
    if intent_type in _ABSTRACT_INTENT_TYPES:
        return CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE
    return CAPABILITY_UNDERSTOOD_BUT_NOT_EXECUTABLE


def _coerce_model_missing_fields(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Structured refine payload missing_fields must be a list.")
    missing_fields: list[str] = []
    for raw_item in value:
        if not isinstance(raw_item, str):
            raise ValueError(
                "Structured refine payload missing_fields entries must be strings."
            )
        item = raw_item.strip()
        if item:
            missing_fields.append(item)
    return missing_fields


def _coerce_required_model_text(value: object, *, label: str) -> str:
    text = _coerce_optional_model_text(value, label=label)
    if text is None:
        raise ValueError(f"Structured refine payload requires {label}.")
    return text


def _coerce_optional_model_text(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Structured refine payload {label} must be a string.")
    normalized = value.strip()
    return normalized or None


def _coerce_model_date(value: object, *, year: int, month: int) -> date:
    date_text = _coerce_required_model_text(value, label="date")
    try:
        parsed_date = date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError("Structured refine payload date must be ISO formatted.") from exc
    if parsed_date.year != year or parsed_date.month != month:
        raise ValueError("Structured refine payload date must stay in scope.")
    return parsed_date


def _resolve_model_code(
    value: object,
    *,
    allowed_codes: list[str],
    label: str,
) -> str:
    code_text = _coerce_required_model_text(value, label=label)
    allowed_by_key = {code.casefold(): code for code in allowed_codes if code}
    resolved_code = allowed_by_key.get(code_text.casefold())
    if resolved_code is None:
        raise ValueError(f"Structured refine payload has unknown {label}.")
    return resolved_code


def _resolve_optional_model_code(
    value: object,
    *,
    allowed_codes: list[str],
    label: str,
) -> str | None:
    if value is None:
        return None
    return _resolve_model_code(value, allowed_codes=allowed_codes, label=label)


def _detect_request_language(request_text: str) -> str:
    if _contains_hiragana_or_katakana(request_text):
        return "ja"
    if any(token in request_text for token in _JAPANESE_LANGUAGE_HINTS):
        return "ja"
    if any(token in request_text for token in _CHINESE_LANGUAGE_HINTS):
        return "zh"
    if _contains_english_keyword(request_text, _ENGLISH_LANGUAGE_HINTS):
        return "en"
    return "unknown"


def _contains_hiragana_or_katakana(value: str) -> bool:
    return any(
        ("\u3040" <= character <= "\u309f")
        or ("\u30a0" <= character <= "\u30ff")
        for character in value
    )


def _contains_english_keyword(request_text: str, keywords: tuple[str, ...]) -> bool:
    normalized_text = request_text.casefold()
    tokens = set(_TOKEN_PATTERN.findall(normalized_text))
    for keyword in keywords:
        normalized_keyword = keyword.casefold()
        if " " in normalized_keyword:
            if normalized_keyword in normalized_text:
                return True
            continue
        if normalized_keyword in tokens:
            return True
    return False


def _looks_like_scheduling_request(request_text: str) -> bool:
    normalized_text = request_text.casefold()
    return (
        any(keyword in request_text for keyword in _ZH_SET_KEYWORDS)
        or any(keyword in request_text for keyword in _ZH_REMOVE_KEYWORDS)
        or any(keyword in request_text for keyword in _JA_SET_KEYWORDS)
        or any(keyword in request_text for keyword in _JA_REMOVE_KEYWORDS)
        or _contains_english_keyword(request_text, _EN_SET_KEYWORDS)
        or _contains_english_keyword(request_text, _EN_REMOVE_KEYWORDS)
        or _contains_any_hint(normalized_text, request_text, _REDUCE_SHIFT_HINTS)
        or _contains_any_hint(normalized_text, request_text, _WORKLOAD_FAIRNESS_HINTS)
        or _contains_any_hint(normalized_text, request_text, _STATION_COVERAGE_HINTS)
        or _contains_any_hint(normalized_text, request_text, _SWAP_HINTS)
        or _contains_any_hint(normalized_text, request_text, _VAGUE_SCHEDULING_HINTS)
    )


def _contains_any_hint(
    normalized_text: str,
    request_text: str,
    hints: tuple[str, ...],
) -> bool:
    return any(
        hint.casefold() in normalized_text
        if hint.isascii()
        else hint in request_text
        for hint in hints
    )


def _looks_like_reduce_or_avoid_shift_request(request_text: str) -> bool:
    normalized_text = request_text.casefold()
    return (
        _contains_any_hint(normalized_text, request_text, _REDUCE_SHIFT_HINTS)
        and (
            _contains_any_hint(normalized_text, request_text, _MORNING_SHIFT_HINTS)
            or _contains_english_keyword(request_text, ("shift", "shifts"))
            or "\u73ed" in request_text
        )
    )


def _looks_like_vague_scheduling_request(request_text: str) -> bool:
    normalized_text = request_text.casefold()
    return _contains_any_hint(
        normalized_text,
        request_text,
        _VAGUE_SCHEDULING_HINTS,
    )


def _detect_date_range_label(request_text: str) -> str | None:
    normalized_text = request_text.casefold()
    for label, hints in _DATE_RANGE_HINTS:
        if _contains_any_hint(normalized_text, request_text, hints):
            return label
    return None


def _detect_shift_type(request_text: str) -> str | None:
    normalized_text = request_text.casefold()
    if _contains_any_hint(normalized_text, request_text, _MORNING_SHIFT_HINTS):
        return "morning"
    return None


def _detect_preference_strength(request_text: str) -> str:
    normalized_text = request_text.casefold()
    if (
        "avoid" in normalized_text
        or "\u4e0d\u8981" in request_text
        or "\u907f\u3051" in request_text
    ):
        return "avoid"
    if _contains_any_hint(normalized_text, request_text, _REDUCE_SHIFT_HINTS):
        return "reduce"
    return "unspecified"


def _missing_fields_for_vague_request(
    request: RefineWorkflowRequest,
    *,
    worker_codes: list[str],
) -> list[str]:
    missing_fields: list[str] = []
    parsed_date, _ = _parse_request_date(
        request.request_text,
        year=request.year,
        month=request.month,
    )
    if parsed_date is None:
        missing_fields.append("date")
    if not worker_codes:
        missing_fields.append("worker")
    shift_code = _resolve_shift_code(
        request.request_text,
        shifts=request.planning_input.shifts,
    )
    station_code = _resolve_station_code(
        request.request_text,
        stations=request.planning_input.stations,
    )
    if shift_code is None and station_code is None:
        missing_fields.append("target_shift_or_station")
    return missing_fields or ["target_shift_or_station"]


def _detect_intent_type(
    request_text: str,
    *,
    shift_code: str | None,
    station_code: str | None,
) -> str | None:
    has_set = (
        any(keyword in request_text for keyword in _ZH_SET_KEYWORDS)
        or any(keyword in request_text for keyword in _JA_SET_KEYWORDS)
        or _contains_english_keyword(request_text, _EN_SET_KEYWORDS)
    )
    has_remove = (
        any(keyword in request_text for keyword in _ZH_REMOVE_KEYWORDS)
        or any(keyword in request_text for keyword in _JA_REMOVE_KEYWORDS)
        or _contains_english_keyword(request_text, _EN_REMOVE_KEYWORDS)
    )
    if has_set and has_remove:
        return None
    if has_remove:
        return "remove_assignment"
    if not has_set:
        return None
    if shift_code is not None and station_code is not None:
        return "set_assignment"
    if _has_station_change_marker(request_text):
        return "change_station"
    if _has_shift_change_marker(request_text):
        return "change_shift"
    if shift_code is not None:
        return "change_shift"
    if station_code is not None:
        return "change_station"
    return "set_assignment"


def _has_shift_change_marker(request_text: str) -> bool:
    return (
        "\u73ed\u5225\u6539" in request_text
        or "\u73ed\u522b\u6539" in request_text
        or _contains_english_keyword(request_text, ("shift", "switch"))
    )


def _has_station_change_marker(request_text: str) -> bool:
    normalized_text = request_text.casefold()
    return (
        "\u6539\u53bb" in request_text
        or "\u6539\u5230" in request_text
        or "\u6392\u5230" in request_text
        or "move to" in normalized_text
    )


def _parse_request_date(
    request_text: str,
    *,
    year: int,
    month: int,
) -> tuple[date | None, str | None]:
    saw_date = False
    for match in _FOUR_DIGIT_DATE_PATTERN.finditer(request_text):
        saw_date = True
        parsed = _coerce_date(
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
        if parsed is None:
            return None, "invalid_date"
        if parsed.year != year or parsed.month != month:
            return None, "date_outside_scope"
        return parsed, None
    for match in _MONTH_DAY_KANJI_PATTERN.finditer(request_text):
        saw_date = True
        parsed = _coerce_date(
            year=year,
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
        if parsed is None:
            return None, "invalid_date"
        if parsed.month != month:
            return None, "date_outside_scope"
        return parsed, None
    for match in _MONTH_DAY_SLASH_PATTERN.finditer(request_text):
        saw_date = True
        parsed = _coerce_date(
            year=year,
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
        if parsed is None:
            return None, "invalid_date"
        if parsed.month != month:
            return None, "date_outside_scope"
        return parsed, None
    if saw_date:
        return None, "invalid_date"
    return None, "date_required"


def _coerce_date(*, year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_worker_code(
    request_text: str,
    *,
    workers: list[WorkerInput],
) -> str | None:
    matches = _find_entity_matches(
        request_text,
        _build_alias_entries(
            [worker for worker in workers if worker.is_active],
            code_getter=lambda worker: worker.worker_code,
            name_getter=lambda worker: worker.name,
            metadata_getter=lambda worker: worker.metadata_json,
        ),
    )
    return _resolve_single_match(matches)


def _resolve_worker_codes(
    request_text: str,
    *,
    workers: list[WorkerInput],
) -> list[str]:
    matches = _find_entity_match_spans(
        request_text,
        _build_alias_entries(
            [worker for worker in workers if worker.is_active],
            code_getter=lambda worker: worker.worker_code,
            name_getter=lambda worker: worker.name,
            metadata_getter=lambda worker: worker.metadata_json,
        ),
    )
    ordered_codes: list[str] = []
    seen: set[str] = set()
    for match in sorted(matches, key=lambda item: (item.start, item.end)):
        if match.canonical_code in seen:
            continue
        seen.add(match.canonical_code)
        ordered_codes.append(match.canonical_code)
    return ordered_codes


def _resolve_station_code(
    request_text: str,
    *,
    stations: list[StationInput],
) -> str | None:
    active_stations = [station for station in stations if station.is_active]
    matches = _find_entity_matches(
        request_text,
        _build_alias_entries(
            active_stations,
            code_getter=lambda station: station.station_code,
            name_getter=lambda station: station.name,
            metadata_getter=lambda station: station.metadata_json,
        ),
    )
    return _resolve_single_match(matches)


def _resolve_shift_code(
    request_text: str,
    *,
    shifts: list[ShiftInput],
) -> str | None:
    working_shifts = [shift for shift in shifts if not shift.is_off_shift]
    entries = _build_alias_entries(
        working_shifts,
        code_getter=lambda shift: shift.shift_code,
        name_getter=lambda shift: shift.name,
        metadata_getter=lambda shift: shift.metadata_json,
    )
    matches = _find_entity_matches(
        request_text,
        entries,
    )
    if len(matches) == 1:
        return _resolve_single_match(matches)
    if len(matches) > 1:
        return _resolve_target_shift_code(request_text, entries)
    return None


def _resolve_target_shift_code(
    request_text: str,
    entries: list[_AliasEntry],
) -> str | None:
    matches = _find_entity_match_spans(request_text, entries)
    if not matches:
        return None

    marker_positions = _find_target_shift_marker_positions(request_text)
    for marker_end in sorted(marker_positions, reverse=True):
        trailing_matches = [
            match for match in matches if match.start >= marker_end
        ]
        resolved = _resolve_single_match(
            {match.canonical_code for match in trailing_matches}
        )
        if resolved is not None:
            return resolved
    return None


def _find_target_shift_marker_positions(request_text: str) -> list[int]:
    normalized_text = request_text.casefold()
    markers = (
        "\u6539\u6210",
        "\u6539\u4e3a",
        "\u73ed\u5225\u6539",
        "\u73ed\u522b\u6539",
        "shift",
        " to ",
    )
    positions: list[int] = []
    for marker in markers:
        search_text = normalized_text if marker.isascii() else request_text
        start_index = search_text.find(marker)
        while start_index != -1:
            positions.append(start_index + len(marker))
            start_index = search_text.find(marker, start_index + len(marker))
    return positions


def _resolve_existing_assignment(
    request: RefineWorkflowRequest,
    *,
    assignment_date: date,
    worker_code: str,
) -> tuple[AssignmentOutput | None, str | None]:
    matches = [
        assignment
        for assignment in (request.current_assignments or [])
        if assignment.date == assignment_date and assignment.worker_code == worker_code
    ]
    if not matches:
        return None, "existing_assignment_required"
    if len(matches) > 1:
        return None, "existing_assignment_ambiguous"
    return matches[0], None


def _contains_direct_mutation_key(keys: set[str]) -> bool:
    normalized_keys = {key.strip().casefold() for key in keys}
    return any(
        mutation_key in normalized_key
        for normalized_key in normalized_keys
        for mutation_key in _DIRECT_MUTATION_KEYS
    )


def _resolve_single_match(matches: set[str]) -> str | None:
    if len(matches) != 1:
        return None
    return next(iter(matches))


def _build_alias_entries(
    items: list[object],
    *,
    code_getter,
    name_getter,
    metadata_getter,
) -> list[_AliasEntry]:
    entries: list[_AliasEntry] = []
    seen: set[tuple[str, str | None, str]] = set()

    for item in items:
        canonical_code = str(code_getter(item)).strip()
        if not canonical_code:
            continue
        for alias in _collect_aliases(
            code=canonical_code,
            name=name_getter(item),
            metadata_json=metadata_getter(item),
        ):
            normalized_alias = alias.strip().casefold()
            if not normalized_alias:
                continue
            compact_alias = re.sub(r"\s+", "", normalized_alias)
            token_key = (
                normalized_alias
                if _TOKEN_PATTERN.fullmatch(normalized_alias) is not None
                else None
            )
            signature = (canonical_code, token_key, compact_alias)
            if signature in seen:
                continue
            seen.add(signature)
            entries.append(
                _AliasEntry(
                    canonical_code=canonical_code,
                    token_key=token_key,
                    compact_key=compact_alias,
                )
            )
    return entries


def _collect_aliases(
    *,
    code: str,
    name: str,
    metadata_json: dict[str, object] | None,
) -> set[str]:
    aliases = {code, name}
    if not isinstance(metadata_json, dict):
        return aliases

    raw_aliases = metadata_json.get("aliases")
    if isinstance(raw_aliases, list):
        aliases.update(
            str(alias)
            for alias in raw_aliases
            if isinstance(alias, str) and alias.strip()
        )

    localized_aliases = metadata_json.get("localized_aliases")
    if isinstance(localized_aliases, dict):
        for raw_values in localized_aliases.values():
            if not isinstance(raw_values, list):
                continue
            aliases.update(
                str(alias)
                for alias in raw_values
                if isinstance(alias, str) and alias.strip()
            )
    return aliases


def _find_entity_matches(
    request_text: str,
    entries: list[_AliasEntry],
) -> set[str]:
    return {
        match.canonical_code
        for match in _find_entity_match_spans(request_text, entries)
    }


def _find_entity_match_spans(
    request_text: str,
    entries: list[_AliasEntry],
) -> list[_EntityMatch]:
    normalized_text = request_text.casefold()
    seen: set[tuple[str, int, int]] = set()
    spans: list[_EntityMatch] = []
    for entry in entries:
        if entry.token_key is not None:
            for token_match in _TOKEN_PATTERN.finditer(normalized_text):
                if token_match.group(0) != entry.token_key:
                    continue
                signature = (
                    entry.canonical_code,
                    token_match.start(),
                    token_match.end(),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                spans.append(
                    _EntityMatch(
                        canonical_code=entry.canonical_code,
                        start=token_match.start(),
                        end=token_match.end(),
                    )
                )
            continue

        start_index = normalized_text.find(entry.compact_key)
        while start_index != -1:
            end_index = start_index + len(entry.compact_key)
            signature = (entry.canonical_code, start_index, end_index)
            if signature not in seen:
                seen.add(signature)
                spans.append(
                    _EntityMatch(
                        canonical_code=entry.canonical_code,
                        start=start_index,
                        end=end_index,
                    )
                )
            start_index = normalized_text.find(entry.compact_key, end_index)
    return spans


__all__ = ["LangGraphRefineWorkflow", "RefineGraphState"]
