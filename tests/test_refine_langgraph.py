from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

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


def test_langgraph_refine_workflow_uses_model_intent_for_candidate_preview() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "en",
            "intent_status": "supported",
            "intent_type": "set_assignment",
            "date": "2026-04-01",
            "worker_code": "W1",
            "shift_code": "EVE",
            "station_code": "GRILL",
            "reason_code": None,
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

    response = workflow(
        RefineWorkflowRequest(
            tenant_slug="tenant-a",
            year=2026,
            month=4,
            workspace_id="workspace-1",
            request_text="Please put Spencer on April 1 evening grill.",
            planning_input=_build_planning_input(),
        )
    )

    assert response.request_language == "en"
    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["model_used"] is True
    assert response.parsed_intent_json["fallback_used"] is False
    assert response.parsed_intent_json["canonical_intent"] == {
        "date": "2026-04-01",
        "worker_code": "W1",
        "shift_code": "EVE",
        "station_code": "GRILL",
    }
    assert response.candidate_result is not None
    assert len(model_client.calls) == 1
    assert len(engine.requests) == 1
    assert engine.requests[0].adjustment_patch is not None
    assert engine.requests[0].adjustment_patch[0].operation == "set"


def test_langgraph_refine_workflow_noop_model_falls_back_locally() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=NoopStructuredOutputModelClient(),
    )

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

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["model_used"] is False
    assert response.parsed_intent_json["fallback_used"] is True
    assert response.candidate_result is not None
    assert len(engine.requests) == 1


def test_langgraph_refine_parses_change_shift_and_keeps_current_station() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request("5/2 \u628a Spencer \u5f9e D \u6539\u6210 C")
    )

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["intent_type"] == "change_shift"
    assert response.parsed_intent_json["canonical_intent"] == {
        "date": "2026-05-02",
        "worker_code": "SPENCER",
        "shift_code": "C",
        "station_code": "PETIT_FOUR",
    }
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].operation == "set"
    assert response.adjustment_patch[0].shift_code == "C"
    assert response.adjustment_patch[0].station_code == "PETIT_FOUR"
    assert len(engine.requests) == 1


def test_langgraph_refine_parses_chinese_shift_change_with_iso_date() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request("2026-05-02 Spencer \u73ed\u5225\u6539 C")
    )

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["intent_type"] == "change_shift"
    assert response.parsed_intent_json["canonical_intent"]["shift_code"] == "C"
    assert response.parsed_intent_json["canonical_intent"]["station_code"] == (
        "PETIT_FOUR"
    )
    assert len(engine.requests) == 1


def test_langgraph_refine_parses_change_station_and_keeps_current_shift() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request(
            "5/2 Spencer \u6539\u53bb gateau\uff0c\u73ed\u5225\u4e0d\u8b8a"
        )
    )

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["intent_type"] == "change_station"
    assert response.parsed_intent_json["canonical_intent"] == {
        "date": "2026-05-02",
        "worker_code": "SPENCER",
        "shift_code": "D",
        "station_code": "GATEAU",
    }
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].shift_code == "D"
    assert response.adjustment_patch[0].station_code == "GATEAU"
    assert len(engine.requests) == 1


def test_langgraph_refine_still_parses_explicit_set_assignment() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request(
            "2026-05-02 \u306e Spencer \u3092 gateau \u306e C \u306b\u3057\u3066"
        )
    )

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["intent_type"] == "set_assignment"
    assert response.parsed_intent_json["canonical_intent"] == {
        "date": "2026-05-02",
        "worker_code": "SPENCER",
        "shift_code": "C",
        "station_code": "GATEAU",
    }
    assert len(engine.requests) == 1


def test_langgraph_refine_normalizes_japanese_month_day_change_shift() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request("5\u67082\u65e5 Spencer \u6539\u6210 C \u73ed")
    )

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["canonical_intent"]["date"] == "2026-05-02"
    assert response.parsed_intent_json["canonical_intent"]["shift_code"] == "C"
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].station_code == "PETIT_FOUR"


def test_langgraph_refine_parses_off_request_as_safe_remove_preview() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request("5/2 Spencer \u4e0d\u8981\u6392\u73ed")
    )

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["intent_type"] == "remove_assignment"
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].operation == "remove"
    assert response.adjustment_patch[0].worker_code == "SPENCER"
    assert len(engine.requests) == 1


def test_langgraph_refine_model_change_shift_keeps_current_station() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "en",
            "intent_status": "supported",
            "intent_type": "change_shift",
            "date": "2026-05-02",
            "worker_code": "SPENCER",
            "shift_code": "C",
            "station_code": None,
            "reason_code": None,
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

    response = workflow(_build_pr6_request("05/02 Spencer shift C"))

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["model_used"] is True
    assert response.parsed_intent_json["intent_type"] == "change_shift"
    assert response.parsed_intent_json["canonical_intent"]["station_code"] == (
        "PETIT_FOUR"
    )
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].shift_code == "C"
    assert response.adjustment_patch[0].station_code == "PETIT_FOUR"
    assert len(engine.requests) == 1


def test_langgraph_refine_model_explicit_shift_and_station_wins_set_assignment() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "ja",
            "intent_status": "supported",
            "intent_type": "change_shift",
            "date": "2026-05-02",
            "worker_code": "SPENCER",
            "shift_code": "C",
            "station_code": None,
            "reason_code": None,
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

    response = workflow(
        _build_pr6_request(
            "2026-05-02 \u306e Spencer \u3092 gateau \u306e C \u306b\u3057\u3066"
        )
    )

    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["model_used"] is True
    assert response.parsed_intent_json["intent_type"] == "set_assignment"
    assert response.parsed_intent_json["canonical_intent"] == {
        "date": "2026-05-02",
        "worker_code": "SPENCER",
        "shift_code": "C",
        "station_code": "GATEAU",
    }
    assert response.adjustment_patch is not None
    assert response.adjustment_patch[0].shift_code == "C"
    assert response.adjustment_patch[0].station_code == "GATEAU"
    assert len(engine.requests) == 1


def test_langgraph_refine_model_classifies_reduce_shift_as_not_executable() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "en",
            "domain": "scheduling",
            "capability_status": "understood_but_not_executable",
            "intent_status": "unsupported",
            "intent_type": "reduce_or_avoid_shift_type",
            "date": None,
            "worker_code": "SPENCER",
            "secondary_worker_code": None,
            "shift_code": "C",
            "shift_type": "morning",
            "station_code": None,
            "date_range": "next_week",
            "preference_strength": "reduce",
            "missing_fields": [],
            "reason_code": "single_day_edits_only",
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

    response = workflow(
        _build_pr6_request("Reduce Spencer's morning shifts next week")
    )

    assert response.outcome.status == "understood_but_not_executable"
    assert response.outcome.message_key == "refine_understood_but_not_executable"
    assert response.parsed_intent_json["domain"] == "scheduling"
    assert (
        response.parsed_intent_json["capability_status"]
        == "understood_but_not_executable"
    )
    assert response.parsed_intent_json["intent_type"] == (
        "reduce_or_avoid_shift_type"
    )
    assert response.parsed_intent_json["canonical_intent"] == {
        "worker_code": "SPENCER",
        "shift_code": "C",
        "date_range": "next_week",
        "shift_type": "morning",
        "preference_strength": "reduce",
    }
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_model_cannot_execute_abstract_intent_type() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "en",
            "domain": "scheduling",
            "capability_status": "executable",
            "intent_status": "supported",
            "intent_type": "swap_workers",
            "date": "2026-05-02",
            "worker_code": "SPENCER",
            "secondary_worker_code": "MASUDA",
            "shift_code": "C",
            "shift_type": None,
            "station_code": "GATEAU",
            "date_range": None,
            "preference_strength": None,
            "missing_fields": [],
            "reason_code": None,
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

    response = workflow(_build_pr6_request("Swap Spencer and Masuda on 5/2"))

    assert response.outcome.status == "understood_but_not_executable"
    assert response.parsed_intent_json["capability_status"] == (
        "understood_but_not_executable"
    )
    assert response.parsed_intent_json["intent_type"] == "swap_workers"
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_fallback_classifies_workload_fairness_as_not_executable() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request(
            "\u8b93\u5927\u5bb6\u73ed\u6578\u5e73\u5747\u4e00\u9ede"
        )
    )

    assert response.request_language == "zh"
    assert response.outcome.status == "understood_but_not_executable"
    assert response.parsed_intent_json["capability_status"] == (
        "understood_but_not_executable"
    )
    assert response.parsed_intent_json["intent_type"] == "workload_or_fairness"
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_fallback_classifies_station_coverage_as_not_executable() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request("Add more coverage to petit_four next week")
    )

    assert response.outcome.status == "understood_but_not_executable"
    assert response.parsed_intent_json["intent_type"] == "station_coverage"
    assert response.parsed_intent_json["canonical_intent"] == {
        "date_range": "next_week",
        "station_code": "PETIT_FOUR",
    }
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_fallback_classifies_swap_as_not_executable() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request("5/2 Spencer \u8ddf Masuda \u5c0d\u8abf")
    )

    assert response.outcome.status == "understood_but_not_executable"
    assert response.parsed_intent_json["intent_type"] == "swap_workers"
    assert response.parsed_intent_json["canonical_intent"] == {
        "date": "2026-05-02",
        "worker_code": "SPENCER",
        "secondary_worker_code": "MASUDA",
    }
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_fallback_returns_ambiguous_missing_information() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(_build_pr6_request("Spencer \u6539\u4e00\u4e0b"))

    assert response.outcome.status == "ambiguous"
    assert response.outcome.message_key == "refine_ambiguous_missing_information"
    assert response.parsed_intent_json["capability_status"] == (
        "ambiguous_or_missing_information"
    )
    assert response.parsed_intent_json["missing_fields"] == [
        "date",
        "target_shift_or_station",
    ]
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_fallback_treats_pronoun_shift_request_as_ambiguous() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request("\u660e\u5929\u90a3\u500b\u4eba\u4e0d\u8981\u65e9\u73ed")
    )

    assert response.outcome.status == "ambiguous"
    assert response.parsed_intent_json["capability_status"] == (
        "ambiguous_or_missing_information"
    )
    assert response.parsed_intent_json["missing_fields"] == ["date", "worker"]
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_fallback_rejects_non_scheduling_request() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(_build_pr6_request("Write me a poem"))

    assert response.outcome.status == "non_scheduling"
    assert response.outcome.message_key == "refine_non_scheduling_request"
    assert response.parsed_intent_json["domain"] == "non_scheduling"
    assert response.parsed_intent_json["capability_status"] == "non_scheduling"
    assert response.candidate_result is None
    assert engine.requests == []


@pytest.mark.parametrize(
    ("request_text", "reason_code", "expected_status"),
    [
        ("2026-06-01 Spencer \u73ed\u5225\u6539 C", "date_outside_scope", "ambiguous"),
        ("5/2 Alex \u73ed\u5225\u6539 C", "worker_required", "ambiguous"),
        ("5/2 Spencer \u73ed\u5225\u6539 Z", "shift_required", "ambiguous"),
        (
            "5/2 Spencer \u6539\u53bb saucier\uff0c\u73ed\u5225\u4e0d\u8b8a",
            "station_required",
            "ambiguous",
        ),
        ("Spencer likes coffee", None, "non_scheduling"),
    ],
)
def test_langgraph_refine_rejects_unsafe_or_unknown_local_requests(
    request_text: str,
    reason_code: str | None,
    expected_status: str,
) -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(_build_pr6_request(request_text))

    assert response.candidate_result is None
    assert response.adjustment_patch is None
    assert engine.requests == []
    assert response.parsed_intent_json["preview_executed"] is False
    if reason_code is None:
        assert response.outcome.status == expected_status
    else:
        assert response.outcome.status == expected_status
        assert response.parsed_intent_json["reason_code"] == reason_code


def test_langgraph_refine_change_shift_requires_existing_assignment() -> None:
    engine = _RecordingEngine()
    workflow = LangGraphRefineWorkflow(engine_runner=engine)

    response = workflow(
        _build_pr6_request(
            "5/2 Spencer \u73ed\u5225\u6539 C",
            current_assignments=[],
        )
    )

    assert response.outcome.status == "ambiguous"
    assert response.parsed_intent_json["reason_code"] == (
        "existing_assignment_required"
    )
    assert response.adjustment_patch is None
    assert response.candidate_result is None
    assert engine.requests == []


def test_langgraph_refine_workflow_model_unsupported_preserves_local_fallback() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "ja",
            "intent_status": "unsupported",
            "intent_type": None,
            "date": None,
            "worker_code": None,
            "shift_code": None,
            "station_code": None,
            "reason_code": "unsupported_request",
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

    response = workflow(
        RefineWorkflowRequest(
            tenant_slug="tenant-a",
            year=2026,
            month=4,
            workspace_id="workspace-1",
            request_text="2026-04-01 \u306e W1 \u3092 EVE \u306b\u3057\u3066 GRILL",
            planning_input=_build_planning_input(),
        )
    )

    assert response.request_language == "ja"
    assert response.outcome.status == "preview_ready"
    assert response.parsed_intent_json["model_used"] is False
    assert response.parsed_intent_json["fallback_used"] is True
    assert response.candidate_result is not None
    assert len(model_client.calls) == 1
    assert len(engine.requests) == 1
    assert engine.requests[0].adjustment_patch is not None
    assert engine.requests[0].adjustment_patch[0].shift_code == "EVE"


def test_langgraph_refine_workflow_rejects_malformed_model_output_safely() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "en",
            "intent_status": "supported",
            "intent_type": "set_assignment",
            "date": "2026-05-01",
            "worker_code": "W1",
            "shift_code": "EVE",
            "station_code": "GRILL",
            "reason_code": None,
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

    response = workflow(
        RefineWorkflowRequest(
            tenant_slug="tenant-a",
            year=2026,
            month=4,
            workspace_id="workspace-1",
            request_text="Please put Spencer on May 1 evening grill.",
            planning_input=_build_planning_input(),
        )
    )

    assert response.candidate_result is None
    assert response.parsed_intent_json["model_used"] is False
    assert response.parsed_intent_json["fallback_used"] is True
    assert len(model_client.calls) == 1
    assert engine.requests == []


def test_langgraph_refine_workflow_rejects_model_direct_apply_save_fields() -> None:
    engine = _RecordingEngine()
    model_client = _RecordingModelClient(
        payload={
            "request_language": "en",
            "intent_status": "supported",
            "intent_type": "set_assignment",
            "date": "2026-04-01",
            "worker_code": "W1",
            "shift_code": "EVE",
            "station_code": "GRILL",
            "reason_code": None,
            "apply": True,
            "save": True,
        }
    )
    workflow = LangGraphRefineWorkflow(
        engine_runner=engine,
        model_client=model_client,
    )

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

    assert response.outcome.status == "unsupported"
    assert response.candidate_result is None
    assert response.parsed_intent_json["model_used"] is True
    assert response.parsed_intent_json["fallback_used"] is False
    assert response.parsed_intent_json["reason_code"] == "direct_mutation_not_allowed"
    assert engine.requests == []


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
            current_assignments=[
                AssignmentOutput(
                    date=dt.date(2026, 4, 1),
                    worker_code="W1",
                    shift_code="DAY",
                    station_code="GRILL",
                    source="current_workspace",
                    note=None,
                )
            ],
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
    assert response.outcome.message_key == "refine_ambiguous_missing_information"
    assert response.parsed_intent_json["preview_executed"] is False
    assert response.parsed_intent_json["outcome"]["message_values"] == {
        "reason_code": "shift_required",
        "missing_fields": "target shift",
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


class _RecordingModelClient:
    def __init__(self, *, payload: dict[str, object]) -> None:
        self.payload = payload
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
        return dict(self.payload)


def _build_pr6_request(
    request_text: str,
    *,
    current_assignments: list[AssignmentOutput] | None = None,
) -> RefineWorkflowRequest:
    return RefineWorkflowRequest(
        tenant_slug="tenant-a",
        year=2026,
        month=5,
        workspace_id="workspace-1",
        request_text=request_text,
        planning_input=_build_pr6_planning_input(),
        current_assignments=(
            _build_pr6_current_assignments()
            if current_assignments is None
            else current_assignments
        ),
    )


def _build_pr6_current_assignments() -> list[AssignmentOutput]:
    return [
        AssignmentOutput(
            date=dt.date(2026, 5, 2),
            worker_code="SPENCER",
            shift_code="D",
            station_code="PETIT_FOUR",
            source="current_workspace",
            note=None,
        )
    ]


def _build_pr6_planning_input() -> MonthPlanningInput:
    return MonthPlanningInput(
        tenant_code="tenant-a",
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
                paid_hours=Decimal("8"),
                is_off_shift=False,
                metadata_json={
                    "aliases": ["C", "\u65e9\u73ed", "morning", "\u671d\u756a"]
                },
            ),
            ShiftInput(
                shift_code="D",
                name="D",
                paid_hours=Decimal("8"),
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
