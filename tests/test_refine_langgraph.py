from __future__ import annotations

import datetime as dt
from decimal import Decimal

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
from app.services.refine import (
    RefineOutcome,
    RefineWorkflowRequest,
    render_refine_outcome,
)
from app.services.refine_langgraph import LangGraphRefineWorkflow


def test_langgraph_refine_workflow_supports_bounded_zh_set_preview() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        RefineWorkflowRequest(
            tenant_slug="tenant-a",
            year=2026,
            month=4,
            workspace_id="workspace-1",
            request_text=(
                "\u8bf7\u628a W1 \u5b89\u6392\u5230 2026-04-01 "
                "\u7684 EVE \u5728 GRILL"
            ),
            planning_input=_build_planning_input(),
        )
    )

    assert workflow.compiled_graph is not None
    assert response.request_language == "zh"
    assert response.outcome.status == "preview_ready"
    assert response.outcome.message_key == "refine_preview_ready_set"
    assert response.parsed_intent_json["request_language"] == "zh"
    assert response.parsed_intent_json["intent_type"] == "set_assignment"
    assert response.parsed_intent_json["preview_executed"] is True
    assert response.parsed_intent_json["canonical_intent"] == {
        "date": "2026-04-01",
        "worker_code": "W1",
        "shift_code": "EVE",
        "station_code": "GRILL",
    }
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].operation == "set"
    assert response.adjustment_patch[0].shift_code == "EVE"
    assert response.adjustment_patch[0].station_code == "GRILL"
    assert response.candidate_result is not None
    assert len(engine.requests) == 1
    assert engine.requests[0].adjustment_patch is not None
    assert engine.requests[0].adjustment_patch[0].shift_code == "EVE"


def test_langgraph_refine_workflow_supports_bounded_ja_remove_preview() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        RefineWorkflowRequest(
            tenant_slug="tenant-a",
            year=2026,
            month=4,
            workspace_id="workspace-1",
            request_text="2026-04-01 \u306e W1 \u3092\u5916\u3057\u3066",
            planning_input=_build_planning_input(),
        )
    )

    assert response.request_language == "ja"
    assert response.outcome.status == "preview_ready"
    assert response.outcome.message_key == "refine_preview_ready_remove"
    assert response.parsed_intent_json["intent_type"] == "remove_assignment"
    assert response.parsed_intent_json["preview_executed"] is True
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].operation == "remove"
    assert response.adjustment_patch[0].worker_code == "W1"
    assert response.candidate_result is not None
    assert len(engine.requests) == 1
    assert engine.requests[0].adjustment_patch[0].operation == "remove"


def test_langgraph_refine_workflow_returns_safe_ambiguous_outcome_without_preview() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        RefineWorkflowRequest(
            tenant_slug="tenant-a",
            year=2026,
            month=4,
            workspace_id="workspace-1",
            request_text="W1 \u3092 2026-04-01 \u306b\u5165\u308c\u3066",
            planning_input=_build_planning_input(),
        )
    )

    assert response.request_language == "ja"
    assert response.outcome.status == "ambiguous"
    assert response.outcome.message_key == "refine_ambiguous_reference"
    assert response.parsed_intent_json["preview_executed"] is False
    assert response.parsed_intent_json["outcome"]["message_values"] == {
        "reason_code": "shift_required"
    }
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_render_refine_outcome_uses_bounded_same_language_templates() -> None:
    zh_text = render_refine_outcome(
        RefineOutcome(
            language="zh",
            status="preview_ready",
            message_key="refine_preview_ready_set",
        )
    )
    ja_text = render_refine_outcome(
        RefineOutcome(
            language="ja",
            status="preview_ready",
            message_key="refine_preview_ready_remove",
        )
    )

    assert zh_text == "\u5df2\u751f\u6210\u8c03\u6574\u9884\u89c8\u3002"
    assert ja_text == (
        "\u524a\u9664\u30d7\u30ec\u30d3\u30e5\u30fc\u3092"
        "\u751f\u6210\u3057\u307e\u3057\u305f\u3002"
    )


class _RecordingEngine:
    def __init__(self) -> None:
        self.requests: list[MonthPlanningInput] = []

    def __call__(self, planning_input: MonthPlanningInput) -> MonthPlanningResult:
        self.requests.append(planning_input)
        return _build_result()


def _build_planning_input() -> MonthPlanningInput:
    return MonthPlanningInput(
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
            )
        ],
        stations=[
            StationInput(
                station_code="GRILL",
                name="Grill",
                is_active=True,
            )
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
        leave_requests=[],
        constraint_config={
            "stations": {"GRILL": 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
        },
        adjustment_patch=None,
    )


def _build_result() -> MonthPlanningResult:
    return MonthPlanningResult(
        assignments=[
            AssignmentOutput(
                date=dt.date(2026, 4, 1),
                worker_code="W1",
                shift_code="DAY",
                station_code="GRILL",
                source="monthly_planner",
                note=None,
            )
        ],
        warnings=[],
        summary=MonthPlanningSummary(
            total_assignments=1,
            total_warnings=0,
            assignments_by_worker={"W1": 1},
            paid_hours_by_worker={"W1": Decimal("8")},
            warnings_by_type={},
        ),
        metadata=MonthPlanningMetadata(
            generated_at=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc),
            source_type="monthly_planner",
            refinement_applied=True,
            notes=["graph-test"],
        ),
    )
