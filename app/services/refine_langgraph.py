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
    "\u8bbe\u4e3a",
    "\u6539\u4e3a",
)
_ZH_REMOVE_KEYWORDS = (
    "\u5220\u9664",
    "\u79fb\u9664",
    "\u53d6\u6d88",
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
)

_CHINESE_LANGUAGE_HINTS = (
    "\u8bf7",
    "\u628a",
    *_ZH_SET_KEYWORDS,
    *_ZH_REMOVE_KEYWORDS,
)
_JAPANESE_LANGUAGE_HINTS = (
    "\u3092",
    "\u306b",
    "\u306e",
    "\u3067",
    *_JA_SET_KEYWORDS,
    *_JA_REMOVE_KEYWORDS,
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
        "intent_status": {
            "type": "string",
            "enum": ["supported", "ambiguous", "unsupported"],
        },
        "intent_type": {
            "type": ["string", "null"],
            "enum": ["set_assignment", "remove_assignment", None],
        },
        "date": {
            "type": ["string", "null"],
            "description": "ISO date inside the selected month, or null.",
        },
        "worker_code": {"type": ["string", "null"]},
        "shift_code": {"type": ["string", "null"]},
        "station_code": {"type": ["string", "null"]},
        "reason_code": {
            "type": ["string", "null"],
            "description": "Reason when the request is ambiguous or unsupported.",
        },
    },
    "required": [
        "request_language",
        "intent_status",
        "intent_type",
        "date",
        "worker_code",
        "shift_code",
        "station_code",
        "reason_code",
    ],
}
_MODEL_INTENT_ALLOWED_KEYS = set(_MODEL_INTENT_JSON_SCHEMA["properties"])
_SUPPORTED_MODEL_LANGUAGES = {"en", "zh", "ja", "unknown"}
_SUPPORTED_INTENT_TYPES = {"set_assignment", "remove_assignment"}


class RefineGraphState(TypedDict, total=False):
    """Small shared state passed through the single-turn refine graph."""

    workflow_request: RefineWorkflowRequest
    request_language: str
    intent_status: str
    intent_type: str
    canonical_intent: dict[str, Any]
    adjustment_patch: list[AssignmentPatchInput] | None
    outcome: RefineOutcome
    parsed_intent_json: dict[str, Any]
    candidate_result: MonthPlanningResult | None
    preview_executed: bool
    model_used: bool
    fallback_used: bool


@dataclass(frozen=True, slots=True)
class _AliasEntry:
    canonical_code: str
    token_key: str | None
    compact_key: str


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
                intent_status=final_state.get("intent_status", "unsupported"),
                intent_type=final_state.get("intent_type"),
                canonical_intent=final_state.get("canonical_intent"),
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

        if request_language not in {"zh", "ja"}:
            outcome = _build_outcome(
                request_language,
                status="unsupported",
                message_key="refine_unsupported_language",
            )
            return {
                "intent_status": "unsupported",
                "outcome": outcome,
                "preview_executed": False,
                "parsed_intent_json": _build_parsed_intent_json(
                    request_language=request_language,
                    intent_status="unsupported",
                    outcome=outcome,
                    preview_executed=False,
                    fallback_used=fallback_used,
                ),
                "fallback_used": fallback_used,
            }

        intent_type = _detect_intent_type(request.request_text, request_language)
        if intent_type is None:
            outcome = _build_outcome(
                request_language,
                status="unsupported",
                message_key="refine_unsupported_intent",
            )
            return {
                "intent_status": "unsupported",
                "outcome": outcome,
                "preview_executed": False,
                "parsed_intent_json": _build_parsed_intent_json(
                    request_language=request_language,
                    intent_status="unsupported",
                    outcome=outcome,
                    preview_executed=False,
                    fallback_used=fallback_used,
                ),
                "fallback_used": fallback_used,
            }

        parsed_date = _parse_request_date(
            request.request_text,
            year=request.year,
            month=request.month,
        )
        if parsed_date is None:
            return _ambiguous_state(
                request_language,
                reason_code="date_required",
                intent_type=intent_type,
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
                intent_type=intent_type,
                fallback_used=fallback_used,
            )

        if intent_type == "remove_assignment":
            canonical_intent = {
                "date": parsed_date.isoformat(),
                "worker_code": worker_code,
            }
            return {
                "intent_status": "supported",
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
        if shift_code is None:
            return _ambiguous_state(
                request_language,
                reason_code="shift_required",
                intent_type=intent_type,
                fallback_used=fallback_used,
            )

        station_code = _resolve_station_code(
            request.request_text,
            stations=request.planning_input.stations,
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
            return None, True
        except (ModelUnavailableError, ValueError):
            return None, True

    def _run_preview_if_supported(self, state: RefineGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        request_language = state.get("request_language", "unknown")
        intent_status = state.get("intent_status", "unsupported")
        intent_type = state.get("intent_type")
        canonical_intent = dict(state.get("canonical_intent") or {})
        adjustment_patch = state.get("adjustment_patch")

        if intent_status != "supported" or not adjustment_patch or intent_type is None:
            outcome = state.get("outcome") or _build_outcome(
                request_language,
                status="unsupported",
                message_key="refine_unsupported_intent",
            )
            model_used = bool(state.get("model_used"))
            fallback_used = bool(state.get("fallback_used"))
            return {
                "outcome": outcome,
                "preview_executed": False,
                "model_used": model_used,
                "fallback_used": fallback_used,
                "parsed_intent_json": _build_parsed_intent_json(
                    request_language=request_language,
                    intent_status=intent_status,
                    intent_type=intent_type,
                    canonical_intent=canonical_intent or None,
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
    intent_status: str,
    intent_type: str | None = None,
    canonical_intent: dict[str, object] | None = None,
    outcome: RefineOutcome,
    adjustment_patch: list[AssignmentPatchInput] | None = None,
    preview_executed: bool,
    reason_code: str | None = None,
    model_used: bool = False,
    fallback_used: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_language": request_language,
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
    model_used: bool = False,
    fallback_used: bool = False,
) -> dict[str, object]:
    outcome = _build_outcome(
        language,
        status="ambiguous",
        message_key="refine_ambiguous_reference",
        message_values={"reason_code": reason_code},
    )
    return {
        "intent_status": "ambiguous",
        "intent_type": intent_type,
        "outcome": outcome,
        "preview_executed": False,
        "model_used": model_used,
        "fallback_used": fallback_used,
        "parsed_intent_json": _build_parsed_intent_json(
            request_language=language,
            intent_status="ambiguous",
            intent_type=intent_type,
            reason_code=reason_code,
            outcome=outcome,
            preview_executed=False,
            model_used=model_used,
            fallback_used=fallback_used,
        ),
    }


def _build_model_system_prompt() -> str:
    return (
        "Interpret one restaurant monthly-schedule refine request into bounded JSON. "
        "Use only the provided worker, shift, station, and month context. "
        "Return supported only for one set_assignment or remove_assignment intent. "
        "If any required date, worker, shift, or station is missing or ambiguous, "
        "return ambiguous. If the request is not a scheduling refine request, "
        "return unsupported. Never apply, save, or mutate a schedule."
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
                "remove_assignment",
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
                "remove_assignment_requires": ["date", "worker_code"],
            },
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
        raise ValueError("Structured refine payload contained unsupported keys.")

    request_language = _coerce_model_language(
        payload.get("request_language"),
        fallback_language=fallback_language,
    )
    intent_status = _coerce_required_model_text(
        payload.get("intent_status"),
        label="intent_status",
    )
    if intent_status not in {"supported", "ambiguous", "unsupported"}:
        raise ValueError("Structured refine payload contained an invalid status.")

    raw_intent_type = payload.get("intent_type")
    intent_type = _coerce_optional_model_text(raw_intent_type, label="intent_type")
    if intent_type is not None and intent_type not in _SUPPORTED_INTENT_TYPES:
        raise ValueError("Structured refine payload contained an invalid intent type.")

    reason_code = (
        _coerce_optional_model_text(payload.get("reason_code"), label="reason_code")
        or "ambiguous_reference"
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
            "intent_type": intent_type,
            "outcome": outcome,
            "preview_executed": False,
            "model_used": True,
            "fallback_used": False,
            "parsed_intent_json": _build_parsed_intent_json(
                request_language=request_language,
                intent_status="unsupported",
                intent_type=intent_type,
                reason_code=reason_code,
                outcome=outcome,
                preview_executed=False,
                model_used=True,
                fallback_used=False,
            ),
        }

    if intent_status == "ambiguous":
        return _ambiguous_state(
            request_language,
            reason_code=reason_code,
            intent_type=intent_type,
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
        allowed_codes=[worker.worker_code for worker in request.planning_input.workers],
        label="worker_code",
    )

    if intent_type == "remove_assignment":
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
    else:
        shift_code = _resolve_model_code(
            payload.get("shift_code"),
            allowed_codes=[
                shift.shift_code
                for shift in request.planning_input.shifts
            ],
            label="shift_code",
        )
        station_code = _resolve_model_code(
            payload.get("station_code"),
            allowed_codes=[
                station.station_code
                for station in request.planning_input.stations
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


def _detect_request_language(request_text: str) -> str:
    if _contains_hiragana_or_katakana(request_text):
        return "ja"
    if any(token in request_text for token in _JAPANESE_LANGUAGE_HINTS):
        return "ja"
    if any(token in request_text for token in _CHINESE_LANGUAGE_HINTS):
        return "zh"
    return "unknown"


def _contains_hiragana_or_katakana(value: str) -> bool:
    return any(
        ("\u3040" <= character <= "\u309f")
        or ("\u30a0" <= character <= "\u30ff")
        for character in value
    )


def _detect_intent_type(request_text: str, language: str) -> str | None:
    keyword_map = {
        "zh": (_ZH_SET_KEYWORDS, _ZH_REMOVE_KEYWORDS),
        "ja": (_JA_SET_KEYWORDS, _JA_REMOVE_KEYWORDS),
    }
    set_keywords, remove_keywords = keyword_map[language]
    has_set = any(keyword in request_text for keyword in set_keywords)
    has_remove = any(keyword in request_text for keyword in remove_keywords)
    if has_set and has_remove:
        return None
    if has_set:
        return "set_assignment"
    if has_remove:
        return "remove_assignment"
    return None


def _parse_request_date(
    request_text: str,
    *,
    year: int,
    month: int,
) -> date | None:
    for match in _FOUR_DIGIT_DATE_PATTERN.finditer(request_text):
        parsed = _coerce_date(
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
        if parsed is not None and parsed.year == year and parsed.month == month:
            return parsed
    for match in _MONTH_DAY_KANJI_PATTERN.finditer(request_text):
        parsed = _coerce_date(
            year=year,
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
        if parsed is not None and parsed.month == month:
            return parsed
    for match in _MONTH_DAY_SLASH_PATTERN.finditer(request_text):
        parsed = _coerce_date(
            year=year,
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
        if parsed is not None and parsed.month == month:
            return parsed
    return None


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
            workers,
            code_getter=lambda worker: worker.worker_code,
            name_getter=lambda worker: worker.name,
            metadata_getter=lambda worker: worker.metadata_json,
        ),
    )
    return _resolve_single_match(matches)


def _resolve_station_code(
    request_text: str,
    *,
    stations: list[StationInput],
) -> str | None:
    matches = _find_entity_matches(
        request_text,
        _build_alias_entries(
            stations,
            code_getter=lambda station: station.station_code,
            name_getter=lambda station: station.name,
            metadata_getter=lambda station: station.metadata_json,
        ),
    )
    if matches:
        return _resolve_single_match(matches)

    active_station_codes = [
        station.station_code
        for station in stations
        if station.is_active
    ]
    if len(active_station_codes) == 1:
        return active_station_codes[0]
    return None


def _resolve_shift_code(
    request_text: str,
    *,
    shifts: list[ShiftInput],
) -> str | None:
    matches = _find_entity_matches(
        request_text,
        _build_alias_entries(
            shifts,
            code_getter=lambda shift: shift.shift_code,
            name_getter=lambda shift: shift.name,
            metadata_getter=lambda shift: shift.metadata_json,
        ),
    )
    if matches:
        return _resolve_single_match(matches)

    working_shift_codes = [
        shift.shift_code
        for shift in shifts
        if not shift.is_off_shift
    ]
    if len(working_shift_codes) == 1:
        return working_shift_codes[0]
    return None


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
    normalized_text = request_text.casefold()
    compact_text = re.sub(r"\s+", "", normalized_text)
    tokens = set(_TOKEN_PATTERN.findall(normalized_text))
    matches: set[str] = set()
    for entry in entries:
        if entry.token_key is not None and entry.token_key in tokens:
            matches.add(entry.canonical_code)
            continue
        if entry.token_key is None and entry.compact_key in compact_text:
            matches.add(entry.canonical_code)
    return matches


__all__ = ["LangGraphRefineWorkflow", "RefineGraphState"]
