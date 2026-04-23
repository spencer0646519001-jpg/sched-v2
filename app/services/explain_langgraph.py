"""Bounded LangGraph workflow for day-level schedule explanation."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.ai.interfaces import ModelUnavailableError, StructuredOutputModelClient
from app.services.explain import (
    EXPLAIN_STATUS_AMBIGUOUS,
    EXPLAIN_STATUS_READY,
    EXPLAIN_STATUS_UNSUPPORTED,
    DayExplainNarrative,
    DayExplainWorkflowRequest,
    DayExplainWorkflowResult,
    ExplainOutcome,
    build_day_explain_context,
    coerce_day_explanation_payload,
    render_day_explanation_fallback,
    render_explain_outcome,
    serialize_day_explanation_payload,
)

_CHINESE_HINTS = (
    "为什么",
    "说明",
    "解释",
    "警告",
    "排班",
    "安排",
    "回退",
    "变更",
    "调整",
)
_JAPANESE_HINTS = (
    "なぜ",
    "説明",
    "警告",
    "シフト",
    "割り当て",
    "フォールバック",
    "変更",
    "プレビュー",
)

_FOUR_DIGIT_DATE_PATTERN = re.compile(
    r"(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})"
)
_MONTH_DAY_KANJI_PATTERN = re.compile(
    r"(?P<month>\d{1,2})月(?P<day>\d{1,2})(?:日|号)"
)
_MONTH_DAY_SLASH_PATTERN = re.compile(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})")

_WARNING_KEYWORDS = {
    "warning",
    "warnings",
    "warn",
    "警告",
    "注意",
}
_FALLBACK_KEYWORDS = {
    "fallback",
    "回退",
    "兜底",
    "フォールバック",
}
_CHANGE_KEYWORDS = {
    "change",
    "changed",
    "difference",
    "diff",
    "preview",
    "refine",
    "变化",
    "变更",
    "差异",
    "调整预览",
    "変更",
    "差分",
    "プレビュー",
}
_WHY_KEYWORDS = {
    "why",
    "explain",
    "scheduled",
    "assign",
    "assigned",
    "not assigned",
    "为什么",
    "为何",
    "没排",
    "没有安排",
    "说明",
    "解释",
    "なぜ",
    "説明",
    "入っていない",
    "割り当て",
}

_MODEL_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string", "minLength": 1},
        "sections": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "key": {
                        "type": "string",
                        "enum": [
                            "assignments",
                            "warnings",
                            "fallback",
                            "constraints",
                            "changes",
                        ],
                    },
                    "title": {"type": "string", "minLength": 1},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["key", "title", "items"],
            },
        },
    },
    "required": ["headline", "sections"],
}


class ExplainGraphState(TypedDict, total=False):
    """Small shared state passed through the explain graph."""

    workflow_request: DayExplainWorkflowRequest
    request_language: str
    response_language: str
    intent_status: str
    request_category: str
    request_worker_code: str | None
    reason_code: str | None
    context_facts: dict[str, Any]
    explanation: DayExplainNarrative
    outcome: ExplainOutcome
    model_used: bool
    fallback_used: bool
    parsed_request_json: dict[str, Any]


class LangGraphDayExplainWorkflow:
    """Small compiled LangGraph workflow for bounded day explanation."""

    def __init__(self, *, model_client: StructuredOutputModelClient) -> None:
        self._model_client = model_client
        builder = StateGraph(ExplainGraphState)
        builder.add_node("detect_language", self._detect_language)
        builder.add_node("normalize_request", self._normalize_request)
        builder.add_node("build_context", self._build_context)
        builder.add_node("generate_explanation", self._generate_explanation)
        builder.add_edge(START, "detect_language")
        builder.add_edge("detect_language", "normalize_request")
        builder.add_edge("normalize_request", "build_context")
        builder.add_edge("build_context", "generate_explanation")
        builder.add_edge("generate_explanation", END)
        self.compiled_graph = builder.compile()

    def __call__(
        self,
        request: DayExplainWorkflowRequest,
    ) -> DayExplainWorkflowResult:
        final_state = self.compiled_graph.invoke({"workflow_request": request})
        request_language = final_state.get("request_language", "unknown")
        response_language = final_state.get("response_language", "en")
        outcome = final_state.get("outcome") or _build_outcome(
            response_language,
            status=EXPLAIN_STATUS_UNSUPPORTED,
            message_key="explain_unsupported_request",
        )
        context_facts = dict(final_state.get("context_facts") or {})
        explanation = final_state.get("explanation")
        parsed_request_json = dict(
            final_state.get("parsed_request_json")
            or _build_parsed_request_json(
                request_language=request_language,
                response_language=response_language,
                intent_status=final_state.get(
                    "intent_status",
                    EXPLAIN_STATUS_UNSUPPORTED,
                ),
                request_category=final_state.get("request_category"),
                request_worker_code=final_state.get("request_worker_code"),
                reason_code=final_state.get("reason_code"),
                source_mode=(
                    str(context_facts.get("source_mode"))
                    if context_facts.get("source_mode") is not None
                    else None
                ),
                model_used=bool(final_state.get("model_used")),
                fallback_used=bool(final_state.get("fallback_used")),
                outcome=outcome,
                context_facts=context_facts,
                explanation=explanation,
            )
        )
        return DayExplainWorkflowResult(
            request_language=request_language,
            response_language=response_language,
            outcome=outcome,
            parsed_request_json=parsed_request_json,
            context_facts=context_facts,
            explanation=explanation,
        )

    def _detect_language(self, state: ExplainGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        request_language = _detect_request_language(request.request_text)
        response_language = _resolve_response_language(
            request_language=request_language,
            response_language_hint=request.response_language_hint,
        )
        return {
            "request_language": request_language,
            "response_language": response_language,
        }

    def _normalize_request(self, state: ExplainGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        request_language = str(state.get("request_language") or "unknown")
        response_language = str(state.get("response_language") or "en")
        normalized_text = (request.request_text or "").strip()

        if normalized_text:
            mentioned_dates = _extract_request_dates(
                normalized_text,
                year=request.year,
                month=request.month,
            )
            if any(mentioned_date != request.target_date for mentioned_date in mentioned_dates):
                outcome = _build_outcome(
                    response_language,
                    status=EXPLAIN_STATUS_UNSUPPORTED,
                    message_key="explain_out_of_context_date",
                )
                return {
                    "intent_status": EXPLAIN_STATUS_UNSUPPORTED,
                    "reason_code": "out_of_context_date",
                    "outcome": outcome,
                    "parsed_request_json": _build_parsed_request_json(
                        request_language=request_language,
                        response_language=response_language,
                        intent_status=EXPLAIN_STATUS_UNSUPPORTED,
                        reason_code="out_of_context_date",
                        outcome=outcome,
                    ),
                }

        request_category = _classify_request(
            normalized_text,
            has_candidate_preview=request.candidate_result is not None,
        )
        if request_category is None:
            outcome = _build_outcome(
                response_language,
                status=EXPLAIN_STATUS_UNSUPPORTED,
                message_key="explain_unsupported_request",
            )
            return {
                "intent_status": EXPLAIN_STATUS_UNSUPPORTED,
                "reason_code": "unsupported_request",
                "outcome": outcome,
                "parsed_request_json": _build_parsed_request_json(
                    request_language=request_language,
                    response_language=response_language,
                    intent_status=EXPLAIN_STATUS_UNSUPPORTED,
                    reason_code="unsupported_request",
                    outcome=outcome,
                ),
            }

        if (
            request_category == "refine_change_summary"
            and request.candidate_result is None
        ):
            outcome = _build_outcome(
                response_language,
                status=EXPLAIN_STATUS_UNSUPPORTED,
                message_key="explain_candidate_required",
            )
            return {
                "intent_status": EXPLAIN_STATUS_UNSUPPORTED,
                "request_category": request_category,
                "reason_code": "candidate_required",
                "outcome": outcome,
                "parsed_request_json": _build_parsed_request_json(
                    request_language=request_language,
                    response_language=response_language,
                    intent_status=EXPLAIN_STATUS_UNSUPPORTED,
                    request_category=request_category,
                    reason_code="candidate_required",
                    outcome=outcome,
                ),
            }

        request_worker_code: str | None = None
        if request_category == "worker_assignment_check":
            resolution = _resolve_worker_code(
                normalized_text,
                workers=request.planning_input.workers,
            )
            if resolution.status != "resolved" or resolution.worker_code is None:
                outcome = _build_outcome(
                    response_language,
                    status=EXPLAIN_STATUS_AMBIGUOUS,
                    message_key="explain_unknown_worker",
                )
                return {
                    "intent_status": EXPLAIN_STATUS_AMBIGUOUS,
                    "request_category": request_category,
                    "reason_code": "unknown_worker",
                    "outcome": outcome,
                    "parsed_request_json": _build_parsed_request_json(
                        request_language=request_language,
                        response_language=response_language,
                        intent_status=EXPLAIN_STATUS_AMBIGUOUS,
                        request_category=request_category,
                        reason_code="unknown_worker",
                        outcome=outcome,
                    ),
                }
            request_worker_code = resolution.worker_code

        return {
            "intent_status": "supported",
            "request_category": request_category,
            "request_worker_code": request_worker_code,
        }

    def _build_context(self, state: ExplainGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        request_language = str(state.get("request_language") or "unknown")
        response_language = str(state.get("response_language") or "en")
        intent_status = str(
            state.get("intent_status") or EXPLAIN_STATUS_UNSUPPORTED
        )
        request_category = state.get("request_category")
        request_worker_code = state.get("request_worker_code")
        outcome = state.get("outcome")

        if intent_status != "supported" or not isinstance(request_category, str):
            resolved_outcome = outcome or _build_outcome(
                response_language,
                status=EXPLAIN_STATUS_UNSUPPORTED,
                message_key="explain_unsupported_request",
            )
            return {
                "outcome": resolved_outcome,
                "parsed_request_json": _build_parsed_request_json(
                    request_language=request_language,
                    response_language=response_language,
                    intent_status=intent_status,
                    request_category=request_category,
                    request_worker_code=request_worker_code,
                    reason_code=state.get("reason_code"),
                    outcome=resolved_outcome,
                ),
            }

        context_facts = build_day_explain_context(
            target_date=request.target_date,
            request_category=request_category,
            request_worker_code=request_worker_code,
            planning_input=request.planning_input,
            current_state=request.current_state,
            candidate_result=request.candidate_result,
            workers=request.workers,
            stations=request.stations,
            shifts=request.shifts,
        )
        return {
            "context_facts": context_facts,
        }

    def _generate_explanation(self, state: ExplainGraphState) -> dict[str, object]:
        request = state["workflow_request"]
        request_language = str(state.get("request_language") or "unknown")
        response_language = str(state.get("response_language") or "en")
        intent_status = str(
            state.get("intent_status") or EXPLAIN_STATUS_UNSUPPORTED
        )
        request_category = state.get("request_category")
        request_worker_code = state.get("request_worker_code")
        reason_code = state.get("reason_code")
        context_facts = dict(state.get("context_facts") or {})

        if intent_status != "supported" or not isinstance(request_category, str):
            outcome = state.get("outcome") or _build_outcome(
                response_language,
                status=intent_status,
                message_key=(
                    "explain_unknown_worker"
                    if intent_status == EXPLAIN_STATUS_AMBIGUOUS
                    else "explain_unsupported_request"
                ),
            )
            return {
                "outcome": outcome,
                "parsed_request_json": _build_parsed_request_json(
                    request_language=request_language,
                    response_language=response_language,
                    intent_status=intent_status,
                    request_category=request_category,
                    request_worker_code=request_worker_code,
                    reason_code=reason_code,
                    source_mode=(
                        str(context_facts.get("source_mode"))
                        if context_facts.get("source_mode") is not None
                        else None
                    ),
                    outcome=outcome,
                    context_facts=context_facts,
                ),
            }

        explanation: DayExplainNarrative
        model_used = False
        fallback_used = False
        try:
            model_payload = self._model_client.generate_json(
                system_prompt=_build_system_prompt(response_language),
                user_prompt=_build_user_prompt(
                    response_language=response_language,
                    request=request,
                    request_category=request_category,
                    request_worker_code=request_worker_code,
                    context_facts=context_facts,
                ),
                json_schema=_MODEL_JSON_SCHEMA,
            )
            explanation = coerce_day_explanation_payload(model_payload)
            model_used = True
        except (ModelUnavailableError, ValueError):
            explanation = render_day_explanation_fallback(
                language=response_language,
                request_category=request_category,
                context_facts=context_facts,
            )
            fallback_used = True

        outcome = _build_outcome(
            response_language,
            status=EXPLAIN_STATUS_READY,
            message_key="explain_ready",
        )
        return {
            "explanation": explanation,
            "model_used": model_used,
            "fallback_used": fallback_used,
            "outcome": outcome,
            "parsed_request_json": _build_parsed_request_json(
                request_language=request_language,
                response_language=response_language,
                intent_status="supported",
                request_category=request_category,
                request_worker_code=request_worker_code,
                source_mode=str(context_facts.get("source_mode") or ""),
                model_used=model_used,
                fallback_used=fallback_used,
                outcome=outcome,
                context_facts=context_facts,
                explanation=explanation,
            ),
        }


@dataclass(frozen=True, slots=True)
class _WorkerResolution:
    status: str
    worker_code: str | None = None


def _build_outcome(
    language: str,
    *,
    status: str,
    message_key: str,
) -> ExplainOutcome:
    return ExplainOutcome(
        language=language,
        status=status,
        message_key=message_key,
    )


def _build_parsed_request_json(
    *,
    request_language: str,
    response_language: str,
    intent_status: str,
    request_category: str | None = None,
    request_worker_code: str | None = None,
    reason_code: str | None = None,
    source_mode: str | None = None,
    model_used: bool = False,
    fallback_used: bool = False,
    outcome: ExplainOutcome,
    context_facts: dict[str, Any] | None = None,
    explanation: DayExplainNarrative | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_language": request_language,
        "response_language": response_language,
        "intent_status": intent_status,
        "model_used": model_used,
        "fallback_used": fallback_used,
        "outcome": {
            "language": outcome.language,
            "status": outcome.status,
            "message_key": outcome.message_key,
            "message_values": dict(outcome.message_values),
            "message_text": render_explain_outcome(outcome),
        },
    }
    if request_category is not None:
        payload["request_category"] = request_category
    if request_worker_code is not None:
        payload["request_worker_code"] = request_worker_code
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if source_mode:
        payload["source_mode"] = source_mode
    if context_facts is not None:
        payload["context_summary"] = {
            "assignment_count": context_facts.get("assignment_count"),
            "warning_count": context_facts.get("warning_count"),
            "source_mode": context_facts.get("source_mode"),
        }
    if explanation is not None:
        payload["explanation"] = serialize_day_explanation_payload(explanation)
    return payload


def _detect_request_language(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return "unknown"
    if any(hint in normalized for hint in _CHINESE_HINTS):
        return "zh"
    if any(hint in normalized for hint in _JAPANESE_HINTS):
        return "ja"
    if re.search(r"[a-z]", normalized, flags=re.IGNORECASE):
        return "en"
    return "unknown"


def _resolve_response_language(
    *,
    request_language: str,
    response_language_hint: str | None,
) -> str:
    if request_language in {"zh", "ja", "en"}:
        return request_language
    normalized_hint = (response_language_hint or "").strip().lower()
    if normalized_hint in {"zh", "ja", "en"}:
        return normalized_hint
    if normalized_hint.startswith("ja"):
        return "ja"
    if normalized_hint.startswith("zh"):
        return "zh"
    return "en"


def _classify_request(
    request_text: str,
    *,
    has_candidate_preview: bool,
) -> str | None:
    normalized_text = request_text.strip()
    if not normalized_text:
        return "day_overview"

    lowered = normalized_text.casefold()
    if any(keyword in lowered for keyword in _FALLBACK_KEYWORDS):
        return "fallback_summary"
    if any(keyword in lowered for keyword in _WARNING_KEYWORDS):
        return "warnings_summary"
    if any(keyword in lowered for keyword in _CHANGE_KEYWORDS):
        return "refine_change_summary"
    if (
        "not assigned" in lowered
        or "未被排班" in normalized_text
        or "没有安排" in normalized_text
        or "入っていない" in normalized_text
        or "why is" in lowered
    ):
        return "worker_assignment_check"
    if any(keyword in lowered for keyword in _WHY_KEYWORDS):
        return "day_overview"
    return None


def _resolve_worker_code(
    request_text: str,
    *,
    workers: list[Any],
) -> _WorkerResolution:
    lowered = request_text.casefold()
    matches: list[str] = []
    for worker in workers:
        worker_code = getattr(worker, "worker_code", "")
        worker_name = getattr(worker, "name", "")
        possible_tokens = [
            worker_code.casefold(),
            worker_name.casefold(),
        ]
        if any(token and token in lowered for token in possible_tokens):
            matches.append(worker_code)
    unique_matches = sorted(set(matches))
    if len(unique_matches) == 1:
        return _WorkerResolution(status="resolved", worker_code=unique_matches[0])
    return _WorkerResolution(status="ambiguous")


def _extract_request_dates(
    request_text: str,
    *,
    year: int,
    month: int,
) -> list[dt.date]:
    parsed_dates: set[dt.date] = set()
    for match in _FOUR_DIGIT_DATE_PATTERN.finditer(request_text):
        try:
            parsed_dates.add(
                dt.date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    for match in _MONTH_DAY_KANJI_PATTERN.finditer(request_text):
        try:
            parsed_dates.add(
                dt.date(
                    year,
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    for match in _MONTH_DAY_SLASH_PATTERN.finditer(request_text):
        try:
            parsed_dates.add(
                dt.date(
                    year,
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    return sorted(
        parsed_dates,
        key=lambda parsed_date: (
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
        ),
    )


def _build_system_prompt(response_language: str) -> str:
    return (
        "You format bounded day-level schedule explanations for a restaurant scheduling system. "
        "Use only the provided JSON facts. "
        "Do not answer general questions. "
        "Do not invent missing reasons. "
        "Do not provide chain-of-thought. "
        "Return concise reviewer-facing output in "
        f"{response_language} only."
    )


def _build_user_prompt(
    *,
    response_language: str,
    request: DayExplainWorkflowRequest,
    request_category: str,
    request_worker_code: str | None,
    context_facts: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "task": "format_day_schedule_explanation",
            "response_language": response_language,
            "selected_day": request.target_date.isoformat(),
            "request_category": request_category,
            "request_worker_code": request_worker_code,
            "request_text": request.request_text,
            "requirements": {
                "max_sections": 5,
                "max_items_per_section": 3,
                "must_use_context_only": True,
                "must_stay_schedule_only": True,
                "no_chain_of_thought": True,
            },
            "context_facts": context_facts,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


__all__ = ["LangGraphDayExplainWorkflow"]
