from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.ai.interfaces import ModelUnavailableError
from app.ai.noop_client import NoopStructuredOutputModelClient
from app.engine.contracts import (
    AssignmentOutput,
    LeaveRequestInput,
    MonthPlanningInput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
    ShiftInput,
    StationInput,
    WarningOutput,
    WorkerInput,
    WorkerSchedulingProfileInput,
)
from app.infra.models import MonthlyAssignment, MonthlyWorkspace, ShiftDefinition, Station, Worker
from app.infra.repositories import CurrentWorkspaceState
from app.services.explain import (
    build_day_explain_context,
)
from app.services.explain_langgraph import LangGraphDayExplainWorkflow
from app.services.explain import DayExplainWorkflowRequest


def test_build_day_explain_context_collects_day_facts_and_candidate_diff() -> None:
    ctx = _sample_context()

    context = build_day_explain_context(
        target_date=dt.date(2026, 4, 1),
        request_category="refine_change_summary",
        request_worker_code="W2",
        planning_input=ctx.planning_input,
        current_state=ctx.current_state,
        candidate_result=ctx.candidate_result,
        workers=ctx.workers,
        stations=ctx.stations,
        shifts=ctx.shifts,
    )

    assert context["source_mode"] == "candidate_preview"
    assert context["assignment_count"] == 1
    assert context["warning_count"] == 1
    assert context["fallback_assignments"][0]["worker_code"] == "W1"
    assert context["comparison"]["has_comparison"] is True
    assert context["comparison"]["added_assignments"][0]["worker_code"] == "W1"
    assert context["comparison"]["removed_assignments"][0]["worker_code"] == "W2"
    assert context["requested_worker"]["worker_code"] == "W2"
    assert context["requested_worker"]["assigned"] is False
    assert context["requested_worker"]["availability_facts"] == [
        {"reason_code": "leave"}
    ]
    assert context["constraints"]["min_staff_target"] == 2


def test_langgraph_day_explain_workflow_rejects_non_scheduling_request_before_model_use() -> None:
    ctx = _sample_context()
    model_client = _RecordingModelClient(
        payload={
            "headline": "unused",
            "sections": [{"key": "assignments", "title": "Assignments", "items": ["unused"]}],
        }
    )
    workflow = LangGraphDayExplainWorkflow(model_client=model_client)

    response = workflow(
        _workflow_request(
            ctx,
            request_text="Write a haiku about spring rain.",
            response_language_hint="en",
        )
    )

    assert response.outcome.status == "unsupported"
    assert response.outcome.message_key == "explain_unsupported_request"
    assert response.explanation is None
    assert response.parsed_request_json["reason_code"] == "unsupported_request"
    assert model_client.calls == []


def test_langgraph_day_explain_workflow_rejects_out_of_context_date_before_model_use() -> None:
    ctx = _sample_context()
    model_client = _RecordingModelClient(
        payload={
            "headline": "unused",
            "sections": [{"key": "assignments", "title": "Assignments", "items": ["unused"]}],
        }
    )
    workflow = LangGraphDayExplainWorkflow(model_client=model_client)

    response = workflow(
        _workflow_request(
            ctx,
            request_text="Why was 2026-04-02 scheduled this way?",
            response_language_hint="en",
        )
    )

    assert response.outcome.status == "unsupported"
    assert response.outcome.message_key == "explain_out_of_context_date"
    assert response.parsed_request_json["reason_code"] == "out_of_context_date"
    assert response.explanation is None
    assert model_client.calls == []


def test_langgraph_day_explain_workflow_uses_model_for_supported_request() -> None:
    ctx = _sample_context()
    model_client = _RecordingModelClient(
        payload={
            "headline": "Warnings for 2026-04-01",
            "sections": [
                {
                    "key": "warnings",
                    "title": "Warnings",
                    "items": ["Station understaffed: station=GRILL, missing=1"],
                }
            ],
        }
    )
    workflow = LangGraphDayExplainWorkflow(model_client=model_client)

    response = workflow(
        _workflow_request(
            ctx,
            request_text="What warnings exist for 4/1?",
            response_language_hint="en",
        )
    )

    assert response.outcome.status == "ready"
    assert response.parsed_request_json["request_category"] == "warnings_summary"
    assert response.explanation is not None
    assert response.explanation.model_used is True
    assert response.explanation.fallback_used is False
    assert response.explanation.headline == "Warnings for 2026-04-01"
    assert len(model_client.calls) == 1


def test_langgraph_day_explain_workflow_falls_back_when_model_is_unavailable() -> None:
    ctx = _sample_context()
    workflow = LangGraphDayExplainWorkflow(
        model_client=NoopStructuredOutputModelClient()
    )

    response = workflow(
        _workflow_request(
            ctx,
            request_text="",
            response_language_hint="zh",
        )
    )

    assert response.outcome.status == "ready"
    assert response.response_language == "zh"
    assert response.explanation is not None
    assert response.explanation.model_used is False
    assert response.explanation.fallback_used is True
    assert response.explanation.sections
    assert response.parsed_request_json["fallback_used"] is True


def test_langgraph_day_explain_workflow_explains_worker_not_assigned_from_context() -> None:
    ctx = _sample_context()
    workflow = LangGraphDayExplainWorkflow(
        model_client=NoopStructuredOutputModelClient()
    )

    response = workflow(
        _workflow_request(
            ctx,
            request_text="Why is Casey not assigned on 4/1?",
            response_language_hint="en",
        )
    )

    assert response.outcome.status == "ready"
    assert response.parsed_request_json["request_category"] == "worker_assignment_check"
    assert response.explanation is not None
    all_items = [
        item
        for section in response.explanation.sections
        for item in section.items
    ]
    assert any("Casey (W2) is not assigned" in item for item in all_items)
    assert any("approved leave" in item for item in all_items)


def test_langgraph_day_explain_workflow_requires_candidate_for_refine_change_request() -> None:
    ctx = _sample_context()
    model_client = _RecordingModelClient(
        payload={
            "headline": "unused",
            "sections": [{"key": "assignments", "title": "Assignments", "items": ["unused"]}],
        }
    )
    workflow = LangGraphDayExplainWorkflow(model_client=model_client)

    response = workflow(
        _workflow_request(
            ctx,
            request_text="What changed in this refine preview?",
            response_language_hint="en",
            candidate_result=None,
        )
    )

    assert response.outcome.status == "unsupported"
    assert response.outcome.message_key == "explain_candidate_required"
    assert response.parsed_request_json["reason_code"] == "candidate_required"
    assert response.explanation is None
    assert model_client.calls == []


class _SampleContext:
    def __init__(self) -> None:
        self.planning_input = MonthPlanningInput(
            tenant_code="tenant-a",
            year=2026,
            month=4,
            workers=[
                WorkerInput(
                    worker_code="W1",
                    name="Spencer",
                    role="employee",
                    is_active=True,
                    station_skills=["GRILL"],
                    scheduling_profile=WorkerSchedulingProfileInput(),
                ),
                WorkerInput(
                    worker_code="W2",
                    name="Casey",
                    role="employee",
                    is_active=True,
                    station_skills=["GRILL", "PREP"],
                    scheduling_profile=WorkerSchedulingProfileInput(),
                ),
            ],
            stations=[
                StationInput(station_code="GRILL", name="Grill", is_active=True),
                StationInput(station_code="PREP", name="Prep", is_active=True),
            ],
            shifts=[
                ShiftInput(
                    shift_code="DAY",
                    name="Day",
                    paid_hours=Decimal("8"),
                    is_off_shift=False,
                ),
                ShiftInput(
                    shift_code="EVE",
                    name="Evening",
                    paid_hours=Decimal("6"),
                    is_off_shift=False,
                ),
            ],
            leave_requests=[
                LeaveRequestInput(
                    worker_code="W2",
                    date=dt.date(2026, 4, 1),
                    leave_type="pto",
                )
            ],
            constraint_config={
                "stations": {"GRILL": 1, "PREP": 1},
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
                "max_consecutive_days": 4,
                "min_rest_days_per_month": 8,
            },
            adjustment_patch=None,
        )
        self.current_state = CurrentWorkspaceState(
            workspace=MonthlyWorkspace(
                tenant_id="tenant-1",
                year=2026,
                month=4,
                id="workspace-1",
                status="draft",
            ),
            assignments=[
                MonthlyAssignment(
                    workspace_id="workspace-1",
                    worker_id="worker-2",
                    assignment_date=dt.date(2026, 4, 1),
                    shift_definition_id="shift-day",
                    station_id="station-grill",
                    note=None,
                )
            ],
        )
        self.workers = [
            Worker(
                tenant_id="tenant-1",
                id="worker-1",
                code="W1",
                name="Spencer",
                role="employee",
            ),
            Worker(
                tenant_id="tenant-1",
                id="worker-2",
                code="W2",
                name="Casey",
                role="employee",
            ),
        ]
        self.stations = [
            Station(tenant_id="tenant-1", id="station-grill", code="GRILL", name="Grill"),
            Station(tenant_id="tenant-1", id="station-prep", code="PREP", name="Prep"),
        ]
        self.shifts = [
            ShiftDefinition(
                tenant_id="tenant-1",
                id="shift-day",
                code="DAY",
                name="Day",
                paid_hours=Decimal("8"),
            ),
            ShiftDefinition(
                tenant_id="tenant-1",
                id="shift-eve",
                code="EVE",
                name="Evening",
                paid_hours=Decimal("6"),
            ),
        ]
        self.candidate_result = MonthPlanningResult(
            assignments=[
                AssignmentOutput(
                    date=dt.date(2026, 4, 1),
                    worker_code="W1",
                    shift_code="EVE",
                    source="adjustment_patch",
                    station_code="PREP",
                    note="fallback_station_skill_mismatch",
                )
            ],
            warnings=[
                WarningOutput(
                    type="understaffed_station_day",
                    message_key="understaffed_station",
                    date=dt.date(2026, 4, 1),
                    worker_code=None,
                    details={
                        "station_code": "GRILL",
                        "required_staff": 1,
                        "assigned_staff": 0,
                        "missing_staff": 1,
                    },
                )
            ],
            summary=MonthPlanningSummary(
                total_assignments=1,
                total_warnings=1,
                assignments_by_worker={"W1": 1, "W2": 0},
                paid_hours_by_worker={"W1": Decimal("6"), "W2": Decimal("0")},
                warnings_by_type={"understaffed_station_day": 1},
            ),
            metadata=MonthPlanningMetadata(
                generated_at=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc),
                source_type="refine",
                refinement_applied=True,
                notes=["day-explain-test"],
            ),
        )


class _RecordingModelClient:
    def __init__(self, *, payload: dict[str, object], fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "json_schema": json_schema,
            }
        )
        if self.fail:
            raise ModelUnavailableError("model unavailable")
        return dict(self.payload)


def _sample_context() -> _SampleContext:
    return _SampleContext()


def _workflow_request(
    ctx: _SampleContext,
    *,
    request_text: str,
    response_language_hint: str,
    candidate_result: MonthPlanningResult | None | object = ...,
) -> DayExplainWorkflowRequest:
    resolved_candidate_result = (
        ctx.candidate_result if candidate_result is ... else candidate_result
    )
    return DayExplainWorkflowRequest(
        tenant_slug="tenant-a",
        year=2026,
        month=4,
        target_date=dt.date(2026, 4, 1),
        request_text=request_text,
        response_language_hint=response_language_hint,
        planning_input=ctx.planning_input,
        current_state=ctx.current_state,
        candidate_result=resolved_candidate_result,
        workers=ctx.workers,
        stations=ctx.stations,
        shifts=ctx.shifts,
    )
