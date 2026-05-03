from __future__ import annotations

import datetime as dt

from app.engine.contracts import AssignmentOutput
from app.services.refine import build_refine_preview_diff


def test_build_refine_preview_diff_reports_changed_assignment() -> None:
    current = [
        _assignment(
            worker_code="W1",
            shift_code="DAY",
            station_code="GRILL",
            source="current_workspace",
        )
    ]
    candidate = [
        _assignment(
            worker_code="W1",
            shift_code="EVE",
            station_code="BAR",
            source="adjustment_patch",
            note="langgraph_refine_preview",
        )
    ]
    current_before = list(current)
    candidate_before = list(candidate)

    diff = build_refine_preview_diff(
        current,
        candidate,
        worker_display_names_by_code={"W1": "Alex"},
    )

    assert diff == {
        "added": [],
        "removed": [],
        "changed": [
            {
                "date": "2026-04-01",
                "worker_code": "W1",
                "worker_name": "Alex",
                "before": {
                    "station_code": "GRILL",
                    "shift_code": "DAY",
                    "source": "current_workspace",
                    "note": None,
                },
                "after": {
                    "station_code": "BAR",
                    "shift_code": "EVE",
                    "source": "adjustment_patch",
                    "note": "langgraph_refine_preview",
                },
            }
        ],
    }
    assert current == current_before
    assert candidate == candidate_before


def test_build_refine_preview_diff_reports_added_assignment() -> None:
    diff = build_refine_preview_diff(
        [],
        [
            _assignment(
                worker_code="W2",
                shift_code="DAY",
                station_code="GRILL",
                source="monthly_planner",
            )
        ],
        worker_display_names_by_code={"W2": "Blair"},
    )

    assert diff == {
        "added": [
            {
                "date": "2026-04-01",
                "worker_code": "W2",
                "worker_name": "Blair",
                "before": None,
                "after": {
                    "station_code": "GRILL",
                    "shift_code": "DAY",
                    "source": "monthly_planner",
                    "note": None,
                },
            }
        ],
        "removed": [],
        "changed": [],
    }


def test_build_refine_preview_diff_reports_removed_assignment() -> None:
    diff = build_refine_preview_diff(
        [
            _assignment(
                worker_code="W3",
                shift_code="DAY",
                station_code="PREP",
                source="current_workspace",
            )
        ],
        [],
    )

    assert diff == {
        "added": [],
        "removed": [
            {
                "date": "2026-04-01",
                "worker_code": "W3",
                "worker_name": "W3",
                "before": {
                    "station_code": "PREP",
                    "shift_code": "DAY",
                    "source": "current_workspace",
                    "note": None,
                },
                "after": None,
            }
        ],
        "changed": [],
    }


def test_build_refine_preview_diff_reports_no_change_for_same_assignment() -> None:
    assignment = _assignment(
        worker_code="W4",
        shift_code="DAY",
        station_code="GRILL",
        source="current_workspace",
    )

    assert build_refine_preview_diff([assignment], [assignment]) == {
        "added": [],
        "removed": [],
        "changed": [],
    }


def _assignment(
    *,
    worker_code: str,
    shift_code: str,
    station_code: str | None,
    source: str,
    note: str | None = None,
) -> AssignmentOutput:
    return AssignmentOutput(
        date=dt.date(2026, 4, 1),
        worker_code=worker_code,
        shift_code=shift_code,
        station_code=station_code,
        source=source,
        note=note,
    )
