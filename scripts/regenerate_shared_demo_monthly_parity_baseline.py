"""Regenerate the frozen shared-demo V1 monthly baseline artifact.

This helper is intentionally narrow and one-off:
- reads one checked-in V2 month fixture from tests/fixtures
- imports sched-mvp only when the script is invoked
- verifies the expected sched-mvp commit
- rebuilds the month with the V1 weekly engine path
- writes one normalized artifact back under tests/fixtures

It is not part of normal V2 runtime execution.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import importlib
import json
import sys
from collections import Counter
from pathlib import Path


EXPECTED_SCHED_MVP_COMMIT = "37b2797a900692df573e1cf70e5ac07023bb5f69"
DEFAULT_FIXTURE_RELATIVE_PATH = Path(
    "tests/fixtures/monthly_parity/shared_demo_april_2026/planning_input.json"
)
DEFAULT_OUTPUT_RELATIVE_PATH = Path(
    "tests/fixtures/monthly_parity/shared_demo_april_2026/v1_baseline.json"
)


def main() -> None:
    args = _build_argument_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    fixture_path = (
        Path(args.fixture).resolve()
        if args.fixture
        else (repo_root / DEFAULT_FIXTURE_RELATIVE_PATH).resolve()
    )
    output_path = (
        Path(args.output).resolve()
        if args.output
        else (repo_root / DEFAULT_OUTPUT_RELATIVE_PATH).resolve()
    )
    sched_mvp_root = Path(args.sched_mvp_root).resolve()

    fixture = _load_json(fixture_path)
    fixture_sha256 = _compute_fixture_sha256(fixture)
    actual_commit = _read_git_commit(sched_mvp_root)
    if actual_commit != EXPECTED_SCHED_MVP_COMMIT:
        raise SystemExit(
            "sched-mvp commit mismatch: "
            f"expected {EXPECTED_SCHED_MVP_COMMIT}, got {actual_commit}."
        )

    EngineInputs, generate_week = _load_sched_mvp_engine(sched_mvp_root, repo_root)

    engine_inputs = _build_v1_engine_inputs(fixture, EngineInputs)
    leave_by_date = _build_leave_by_date(fixture)
    month_plan = _generate_v1_month_plan(
        fixture["year"],
        fixture["month"],
        leave_by_date=leave_by_date,
        engine_inputs=engine_inputs,
        generate_week=generate_week,
    )
    normalized_assignments = _normalize_assignments(fixture, month_plan)
    normalized_warnings = _normalize_warnings(
        fixture,
        month_plan,
        normalized_assignments,
    )

    artifact = {
        "artifact_version": "v1",
        "fixture_id": fixture["fixture_id"],
        "fixture_sha256": fixture_sha256,
        "generated_at": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "generated_from": {
            "repo": "sched-mvp",
            "commit": actual_commit,
            "entrypoint": "app.generate_week.generate_week",
            "month_rollup": "weekly_chunk_rollup",
        },
        "normalization_notes": [
            "worker identities are mapped from fixture names to fixture worker_code values",
            "station codes are normalized to the frozen fixture station_code values",
            "headcount-only chef presence is not synthesized into assignment rows",
            "weekly_rest warnings are reconstructed from month assignment coverage",
            "shared demo baseline uses an empty holiday calendar for cross-repo parity",
        ],
        "assignments": normalized_assignments,
        "warnings": normalized_warnings,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sched-mvp-root",
        default=str(Path(__file__).resolve().parents[2] / "sched-mvp"),
        help="Path to the sibling sched-mvp checkout.",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Optional override for the frozen planning_input.json path.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional override for the normalized v1 baseline artifact path.",
    )
    return parser


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _compute_fixture_sha256(fixture: dict[str, object]) -> str:
    canonical = json.dumps(
        fixture,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _read_git_commit(repo_root: Path) -> str:
    git_dir = repo_root / ".git"
    head_text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if not head_text.startswith("ref:"):
        return head_text

    ref_name = head_text.split(":", 1)[1].strip()
    ref_path = git_dir / Path(ref_name)
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8").strip()

    packed_refs_path = git_dir / "packed-refs"
    if not packed_refs_path.exists():
        raise FileNotFoundError(
            f"Unable to resolve git ref {ref_name!r} inside {git_dir}."
        )

    for line in packed_refs_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        commit, packed_ref_name = line.split(" ", 1)
        if packed_ref_name.strip() == ref_name:
            return commit.strip()

    raise FileNotFoundError(
        f"Unable to resolve git ref {ref_name!r} inside {git_dir}."
    )


def _load_sched_mvp_engine(
    sched_mvp_root: Path,
    current_repo_root: Path,
):
    script_dir = Path(__file__).resolve().parent
    sys.path = [
        path
        for path in sys.path
        if path not in {"", str(current_repo_root), str(script_dir)}
    ]
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
    sys.path.insert(0, str(sched_mvp_root))

    try:
        generate_day_module = importlib.import_module("app.generate_day")
        generate_week_module = importlib.import_module("app.generate_week")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Unable to import sched-mvp runtime dependencies. "
            "Run this helper with the sched-mvp virtualenv, for example: "
            r"..\sched-mvp\.venv\Scripts\python "
            r"scripts\regenerate_shared_demo_monthly_parity_baseline.py "
            r"--sched-mvp-root ..\sched-mvp"
        ) from exc
    return generate_day_module.EngineInputs, generate_week_module.generate_week


def _build_v1_engine_inputs(
    fixture: dict[str, object],
    EngineInputs,
):
    active_workers = [
        worker
        for worker in fixture["workers"]
        if bool(worker.get("is_active", False))
    ]
    active_station_codes = [
        station["station_code"]
        for station in fixture["stations"]
        if bool(station.get("is_active", False))
    ]

    people = [
        {
            "name": worker["name"],
            "role": worker["role"],
            "station_skills": list(worker.get("station_skills") or []),
            "headcount_only": worker["role"].strip().casefold() == "chef",
            "fixed_days_off": [],
            "ad_hoc_unavailable": [],
            "wish_off": {"hard": [], "soft": []},
            "special_leave_days": [],
            "shift_prefs": [],
        }
        for worker in active_workers
    ]
    shifts_list = [
        {
            "code": shift["shift_code"],
            "name": shift["name"],
            "paid_hours": float(shift["paid_hours"]),
            "start": shift.get("start_time"),
            "end": shift.get("end_time"),
            "is_off_shift": bool(shift.get("is_off_shift", False)),
        }
        for shift in fixture["shifts"]
    ]
    rules = dict(fixture["constraint_config"])
    rules.setdefault("allow_fallback_when_short", True)
    rules.setdefault("fallback_penalty", 1.0)
    rules.setdefault("enforce_hard_off", True)
    rules.setdefault("soft_off_penalty", 2.5)

    return EngineInputs(
        shifts_list=shifts_list,
        rules=rules,
        calendar={"holidays": []},
        people=people,
        station_order=active_station_codes,
    )


def _build_leave_by_date(
    fixture: dict[str, object],
) -> dict[str, list[str]]:
    worker_name_by_code = {
        worker["worker_code"]: worker["name"] for worker in fixture["workers"]
    }
    leave_by_date: dict[str, list[str]] = {}
    for leave_request in fixture["leave_requests"]:
        worker_name = worker_name_by_code[leave_request["worker_code"]]
        leave_by_date.setdefault(leave_request["date"], []).append(worker_name)
    return {
        date_str: list(dict.fromkeys(names))
        for date_str, names in leave_by_date.items()
    }


def _generate_v1_month_plan(
    year: int,
    month: int,
    *,
    leave_by_date: dict[str, list[str]],
    engine_inputs,
    generate_week,
) -> dict[str, dict[str, object]]:
    month_start = dt.date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    current_date = month_start
    previous_state = None
    month_plan: dict[str, dict[str, object]] = {}

    while current_date.month == month and current_date.day <= last_day:
        days_left = last_day - current_date.day + 1
        chunk_days = min(7, days_left)
        week_state = generate_week(
            current_date.isoformat(),
            num_days=chunk_days,
            prev_state=previous_state,
            leave_by_date=leave_by_date,
            inputs=engine_inputs,
        )
        month_plan.update(week_state["week_plan"])
        previous_state = week_state
        current_date += dt.timedelta(days=chunk_days)

    return month_plan


def _normalize_assignments(
    fixture: dict[str, object],
    month_plan: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    worker_code_by_name = {
        worker["name"]: worker["worker_code"] for worker in fixture["workers"]
    }
    station_code_lookup = {
        str(station["station_code"]).strip().casefold(): station["station_code"]
        for station in fixture["stations"]
    }

    assignments: list[dict[str, object]] = []
    for date_str, day_plan in sorted(month_plan.items()):
        assignment_date = dt.date.fromisoformat(date_str)
        raw_assignments = day_plan.get("assignments", {}) or {}
        for raw_station_code, records in sorted(raw_assignments.items()):
            station_code = station_code_lookup[
                str(raw_station_code).strip().casefold()
            ]
            for record in records or []:
                assignments.append(
                    {
                        "date": assignment_date.isoformat(),
                        "worker_code": worker_code_by_name[record["name"]],
                        "shift_code": str(record["shift"]),
                        "station_code": station_code,
                    }
                )

    assignments.sort(
        key=lambda assignment: (
            assignment["date"],
            assignment["worker_code"],
            assignment["station_code"] or "",
            assignment["shift_code"],
        )
    )
    return assignments


def _normalize_warnings(
    fixture: dict[str, object],
    month_plan: dict[str, dict[str, object]],
    normalized_assignments: list[dict[str, object]],
) -> list[dict[str, object]]:
    worker_code_by_name = {
        worker["name"]: worker["worker_code"] for worker in fixture["workers"]
    }
    warnings: list[dict[str, object]] = []

    for date_str, day_plan in sorted(month_plan.items()):
        assignment_date = dt.date.fromisoformat(date_str)
        for raw_warning in day_plan.get("warnings", []) or []:
            warnings.extend(
                _normalize_day_warning(
                    str(raw_warning),
                    assignment_date=assignment_date,
                    worker_code_by_name=worker_code_by_name,
                )
            )

    worker_day_counts = Counter(
        (assignment["date"], assignment["worker_code"])
        for assignment in normalized_assignments
    )
    for (date_str, worker_code), count in sorted(worker_day_counts.items()):
        if count > 1:
            warnings.append(
                {
                    "type": "multi_assign",
                    "date": date_str,
                    "worker_code": worker_code,
                }
            )

    warnings.extend(
        _build_weekly_rest_warnings(
            fixture,
            normalized_assignments=normalized_assignments,
        )
    )

    warnings.sort(
        key=lambda warning: (
            warning["date"] or "9999-12-31",
            warning["type"],
            warning["worker_code"] or "",
        )
    )
    return warnings


def _normalize_day_warning(
    raw_warning: str,
    *,
    assignment_date: dt.date,
    worker_code_by_name: dict[str, str],
) -> list[dict[str, object]]:
    if raw_warning.startswith("AUTO_REST:"):
        raw_names = raw_warning.split(":", 1)[1]
        return [
            {
                "type": "auto_rest",
                "date": assignment_date.isoformat(),
                "worker_code": worker_code_by_name[name.strip()],
            }
            for name in raw_names.split(",")
            if name.strip()
        ]

    if raw_warning.startswith("CHEF_OVERWORK:"):
        raw_name = raw_warning.split(":", 1)[1].strip()
        return [
            {
                "type": "chef_overwork",
                "date": assignment_date.isoformat(),
                "worker_code": worker_code_by_name[raw_name],
            }
        ]

    return [
        {
            "type": raw_warning.strip().casefold(),
            "date": assignment_date.isoformat(),
            "worker_code": None,
        }
    ]


def _build_weekly_rest_warnings(
    fixture: dict[str, object],
    *,
    normalized_assignments: list[dict[str, object]],
) -> list[dict[str, object]]:
    month_dates = _iter_month_dates(fixture["year"], fixture["month"])
    week_to_dates: dict[tuple[int, int], list[dt.date]] = {}
    for month_date in month_dates:
        iso_year, iso_week, _ = month_date.isocalendar()
        week_to_dates.setdefault((iso_year, iso_week), []).append(month_date)

    worked_dates_by_worker: dict[str, set[dt.date]] = {
        worker["worker_code"]: set()
        for worker in fixture["workers"]
        if bool(worker.get("is_active", False))
    }
    for assignment in normalized_assignments:
        worked_dates_by_worker[assignment["worker_code"]].add(
            dt.date.fromisoformat(assignment["date"])
        )

    warnings: list[dict[str, object]] = []
    for _, week_dates in sorted(week_to_dates.items()):
        if len(week_dates) != 7:
            continue
        for worker_code, worked_dates in worked_dates_by_worker.items():
            days_off = 7 - sum(1 for week_date in week_dates if week_date in worked_dates)
            if days_off < 2:
                warnings.append(
                    {
                        "type": "weekly_rest",
                        "date": None,
                        "worker_code": worker_code,
                    }
                )
    return warnings


def _iter_month_dates(year: int, month: int) -> list[dt.date]:
    days_in_month = calendar.monthrange(year, month)[1]
    return [
        dt.date(year, month, day_number)
        for day_number in range(1, days_in_month + 1)
    ]


if __name__ == "__main__":
    main()
