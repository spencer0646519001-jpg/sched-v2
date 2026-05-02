"""Tiny offline eval harness for the refine intent layer.

This module intentionally evaluates the deterministic local refine parser path.
It does not create a real model client and it does not call the OpenAI API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from app.ai.noop_client import NoopStructuredOutputModelClient
from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningInput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
    ShiftInput,
    StationInput,
    WorkerInput,
    WorkerSchedulingProfileInput,
)
from app.services.refine import RefineWorkflowRequest
from app.services.refine_langgraph import LangGraphRefineWorkflow

CASES_PATH = Path(__file__).with_name("refine_intent_cases.json")


@dataclass(frozen=True, slots=True)
class RefineIntentEvalCase:
    case_id: str
    language: str
    category: str
    request_text: str
    expected_domains: tuple[str, ...]
    expected_capability_statuses: tuple[str, ...]
    expected_intent_types: tuple[str, ...] | None = None
    expected_preview_executed: bool | None = None
    expected_missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RefineIntentEvalResult:
    case_id: str
    language: str
    actual_language: str
    category: str
    expected_domain: str
    actual_domain: str
    expected_status: str
    actual_status: str
    expected_intent_type: str
    actual_intent_type: str
    expected_preview_executed: bool | None
    actual_preview_executed: bool
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RefineIntentEvalReport:
    results: tuple[RefineIntentEvalResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    def accuracy_by_category(self) -> dict[str, tuple[int, int]]:
        return _accuracy_by_field(self.results, "category")

    def accuracy_by_language(self) -> dict[str, tuple[int, int]]:
        return _accuracy_by_field(self.results, "language")


class _EvalPreviewEngine:
    """Deterministic preview stand-in used only for executable eval cases."""

    def __init__(self) -> None:
        self.calls: list[MonthPlanningInput] = []

    def __call__(self, planning_input: MonthPlanningInput) -> MonthPlanningResult:
        self.calls.append(planning_input)
        patch = (planning_input.adjustment_patch or [None])[0]
        assignments: list[AssignmentOutput] = []
        if patch is not None and patch.operation != "remove":
            assignments.append(
                AssignmentOutput(
                    date=patch.date,
                    worker_code=patch.worker_code,
                    shift_code=patch.shift_code or "D",
                    station_code=patch.station_code,
                    source="refine_eval",
                    note=patch.note,
                )
            )
        return MonthPlanningResult(
            assignments=assignments,
            warnings=[],
            summary=MonthPlanningSummary(
                total_assignments=len(assignments),
                total_warnings=0,
                assignments_by_worker={
                    assignment.worker_code: 1 for assignment in assignments
                },
                paid_hours_by_worker={
                    assignment.worker_code: Decimal("8.00")
                    for assignment in assignments
                },
                warnings_by_type={},
            ),
            metadata=MonthPlanningMetadata(
                generated_at=dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc),
                source_type="refine_eval",
                refinement_applied=bool(planning_input.adjustment_patch),
                notes=["offline_refine_intent_eval"],
            ),
        )


def load_cases(path: Path = CASES_PATH) -> tuple[RefineIntentEvalCase, ...]:
    """Load and lightly validate the reviewer-facing eval corpus."""

    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("Refine intent eval corpus must be a JSON list.")
    return tuple(_parse_case(raw_case) for raw_case in raw_cases)


def run_refine_intent_eval(
    cases: Sequence[RefineIntentEvalCase] | None = None,
) -> RefineIntentEvalReport:
    """Run the offline deterministic refine intent eval."""

    eval_cases = tuple(cases) if cases is not None else load_cases()
    engine = _EvalPreviewEngine()
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=NoopStructuredOutputModelClient(),
    )
    results = tuple(_evaluate_case(workflow, case) for case in eval_cases)
    return RefineIntentEvalReport(results=results)


def format_report(report: RefineIntentEvalReport) -> str:
    """Render a compact table plus simple summary metrics."""

    return "\n\n".join(
        [
            _format_results_table(report.results),
            _format_summary(report),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline refine intent classification eval.",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=CASES_PATH,
        help="Path to the refine intent eval corpus JSON.",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Print failures but exit 0.",
    )
    args = parser.parse_args(argv)

    report = run_refine_intent_eval(load_cases(args.cases))
    print(format_report(report))
    if report.failed and not args.no_fail:
        return 1
    return 0


def _parse_case(raw_case: object) -> RefineIntentEvalCase:
    if not isinstance(raw_case, dict):
        raise ValueError("Each refine intent eval case must be an object.")
    expected = raw_case.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("Each refine intent eval case requires expected values.")

    expected_intent_types = expected.get("intent_types")
    return RefineIntentEvalCase(
        case_id=_required_text(raw_case, "case_id"),
        language=_required_text(raw_case, "language"),
        category=_required_text(raw_case, "category"),
        request_text=_required_text(raw_case, "request_text"),
        expected_domains=_expected_values(expected, "domains"),
        expected_capability_statuses=_expected_values(
            expected,
            "capability_statuses",
        ),
        expected_intent_types=(
            _expected_values(expected, "intent_types")
            if expected_intent_types is not None
            else None
        ),
        expected_preview_executed=_optional_bool(expected, "preview_executed"),
        expected_missing_fields=(
            _expected_values(expected, "missing_fields")
            if expected.get("missing_fields") is not None
            else ()
        ),
    )


def _evaluate_case(
    workflow: LangGraphRefineWorkflow,
    case: RefineIntentEvalCase,
) -> RefineIntentEvalResult:
    response = workflow(_build_eval_request(case.request_text))
    parsed = response.parsed_intent_json
    actual_domain = _text_or_blank(parsed.get("domain"))
    actual_status = _text_or_blank(parsed.get("capability_status"))
    actual_intent_type = _text_or_blank(parsed.get("intent_type"))
    parsed_preview = bool(parsed.get("preview_executed"))
    candidate_preview = response.candidate_result is not None
    actual_preview_executed = parsed_preview and candidate_preview
    actual_missing_fields = _string_set(parsed.get("missing_fields"))

    failures: list[str] = []
    if actual_domain not in case.expected_domains:
        failures.append("domain")
    if actual_status not in case.expected_capability_statuses:
        failures.append("capability_status")
    if (
        case.expected_intent_types is not None
        and actual_intent_type not in case.expected_intent_types
    ):
        failures.append("intent_type")
    if (
        case.expected_preview_executed is not None
        and actual_preview_executed != case.expected_preview_executed
    ):
        failures.append("preview_executed")
    if not set(case.expected_missing_fields).issubset(actual_missing_fields):
        failures.append("missing_fields")

    return RefineIntentEvalResult(
        case_id=case.case_id,
        language=case.language,
        actual_language=_text_or_blank(parsed.get("request_language")),
        category=case.category,
        expected_domain=_join_expected(case.expected_domains),
        actual_domain=actual_domain,
        expected_status=_join_expected(case.expected_capability_statuses),
        actual_status=actual_status,
        expected_intent_type=_join_expected(case.expected_intent_types or ()),
        actual_intent_type=actual_intent_type,
        expected_preview_executed=case.expected_preview_executed,
        actual_preview_executed=actual_preview_executed,
        passed=not failures,
        failures=tuple(failures),
    )


def _build_eval_request(request_text: str) -> RefineWorkflowRequest:
    return RefineWorkflowRequest(
        tenant_slug="eval-kitchen",
        year=2026,
        month=5,
        workspace_id="eval-workspace",
        request_text=request_text,
        planning_input=_build_eval_planning_input(),
        current_assignments=[
            AssignmentOutput(
                date=dt.date(2026, 5, 2),
                worker_code="SPENCER",
                shift_code="D",
                station_code="PETIT_FOUR",
                source="current_workspace",
                note=None,
            )
        ],
    )


def _build_eval_planning_input() -> MonthPlanningInput:
    return MonthPlanningInput(
        tenant_code="eval-kitchen",
        year=2026,
        month=5,
        workers=[
            WorkerInput(
                worker_code="SPENCER",
                name="Spencer",
                role="employee",
                is_active=True,
                station_skills=["GATEAU", "PETIT_FOUR"],
                scheduling_profile=WorkerSchedulingProfileInput(),
            ),
            WorkerInput(
                worker_code="MASUDA",
                name="Masuda",
                role="employee",
                is_active=True,
                station_skills=["GATEAU", "PETIT_FOUR"],
                scheduling_profile=WorkerSchedulingProfileInput(),
            ),
        ],
        stations=[
            StationInput(
                station_code="GATEAU",
                name="gateau",
                is_active=True,
                metadata_json={"aliases": ["gateau"]},
            ),
            StationInput(
                station_code="PETIT_FOUR",
                name="petit_four",
                is_active=True,
                metadata_json={"aliases": ["petit_four"]},
            ),
        ],
        shifts=[
            ShiftInput(
                shift_code="C",
                name="C",
                paid_hours=Decimal("8.00"),
                is_off_shift=False,
                metadata_json={
                    "aliases": ["C", "morning", "早班", "朝番"],
                },
            ),
            ShiftInput(
                shift_code="D",
                name="D",
                paid_hours=Decimal("8.00"),
                is_off_shift=False,
            ),
        ],
        leave_requests=[],
        constraint_config={
            "stations": {"GATEAU": 1, "PETIT_FOUR": 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 2,
        },
        adjustment_patch=None,
    )


def _format_results_table(results: Sequence[RefineIntentEvalResult]) -> str:
    headers = [
        "case_id",
        "language",
        "category",
        "expected_domain",
        "actual_domain",
        "expected_status",
        "actual_status",
        "intent_type",
        "preview",
        "pass",
    ]
    rows = [
        [
            result.case_id,
            result.language,
            result.category,
            result.expected_domain,
            result.actual_domain,
            result.expected_status,
            result.actual_status,
            result.actual_intent_type or "-",
            "yes" if result.actual_preview_executed else "no",
            "PASS" if result.passed else f"FAIL ({', '.join(result.failures)})",
        ]
        for result in results
    ]
    widths = [
        max(len(str(row[index])) for row in [headers, *rows])
        for index in range(len(headers))
    ]
    lines = [
        _format_table_row(headers, widths),
        _format_table_row(["-" * width for width in widths], widths),
    ]
    lines.extend(_format_table_row(row, widths) for row in rows)
    return "\n".join(lines)


def _format_summary(report: RefineIntentEvalReport) -> str:
    lines = [
        "summary",
        f"total: {report.total}",
        f"passed: {report.passed}",
        f"failed: {report.failed}",
        "accuracy_by_category:",
    ]
    lines.extend(_format_accuracy_lines(report.accuracy_by_category()))
    lines.append("accuracy_by_language:")
    lines.extend(_format_accuracy_lines(report.accuracy_by_language()))
    return "\n".join(lines)


def _format_accuracy_lines(values: dict[str, tuple[int, int]]) -> list[str]:
    lines: list[str] = []
    for label in sorted(values):
        passed, total = values[label]
        percent = (passed / total * 100) if total else 0
        lines.append(f"  {label}: {passed}/{total} ({percent:.1f}%)")
    return lines


def _accuracy_by_field(
    results: Sequence[RefineIntentEvalResult],
    field_name: str,
) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = {}
    for result in results:
        label = str(getattr(result, field_name))
        passed, total = counts.setdefault(label, [0, 0])
        counts[label] = [passed + int(result.passed), total + 1]
    return {
        label: (values[0], values[1])
        for label, values in counts.items()
    }


def _format_table_row(values: Sequence[str], widths: Sequence[int]) -> str:
    return " | ".join(
        str(value).ljust(width)
        for value, width in zip(values, widths, strict=True)
    )


def _required_text(raw_case: dict[str, Any], key: str) -> str:
    value = raw_case.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Refine intent eval case requires {key}.")
    return value


def _expected_values(expected: dict[str, Any], key: str) -> tuple[str, ...]:
    value = expected.get(key)
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, list):
        values = tuple(item for item in value if isinstance(item, str) and item)
    else:
        values = ()
    if not values:
        raise ValueError(f"Refine intent eval case requires expected {key}.")
    return values


def _optional_bool(expected: dict[str, Any], key: str) -> bool | None:
    value = expected.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Expected {key} must be a boolean when provided.")
    return value


def _text_or_blank(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _join_expected(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"


if __name__ == "__main__":
    raise SystemExit(main())
