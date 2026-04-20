"""Mirrored v1 demo-world data for the v2 local monthly workspace.

This module mirrors the canonical first-version demo inputs from:
- ``sched-mvp/data/workers.json``
- ``sched-mvp/data/shifts.json``
- ``sched-mvp/data/rules.json``

Small v2-only transformations are kept explicit here:
- worker codes are derived because v1 does not define persisted worker codes
- station codes follow the normalized persisted v1 demo bootstrap shape
- shift names mirror the v1 shift code because v1 defines codes, not labels

Deeper alignment such as richer shift preferences and broader rule pass-through
still lands in follow-up PRs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from decimal import Decimal

DEMO_TENANT_SLUG = "demo_kitchen"
DEMO_TENANT_NAME = "demo_kitchen"
DEMO_DEFAULT_LOCALE = "en-US"
DEMO_MONTH_SCOPE = "2026-04"


@dataclass(frozen=True, slots=True)
class DemoWorkerRow:
    code: str
    name: str
    role: str
    station_skills: tuple[str, ...] = ()
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class DemoStationRow:
    code: str
    name: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class DemoShiftRow:
    code: str
    name: str
    start_time: time
    end_time: time
    paid_hours: Decimal
    is_off_shift: bool = False


def _derive_worker_code(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_")
    return normalized.upper()


def _normalize_station_skill_codes(*raw_codes: str) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_code in raw_codes:
        code = raw_code.strip().lower()
        if not code or code in seen:
            continue
        normalized.append(code)
        seen.add(code)
    return tuple(normalized)


_WORKER_SOURCE_ROWS = (
    ("Takahashi_chef", "chef", ()),
    ("Funatsu", "chef", ()),
    ("Spencer", "employee", ("mise_en_place",)),
    ("Chung", "employee", ("mise_en_place", "glaze_and_fruit")),
    ("Ishikawa", "employee", ("glaze_and_fruit", "mise_en_place", "GATEAU")),
    ("Mochizuki", "employee", ("mise_en_place", "glaze_and_fruit", "GATEAU")),
    ("Takai", "employee", ("mise_en_place", "glaze_and_fruit", "GATEAU")),
    ("Tarutani", "employee", ("mise_en_place", "GATEAU")),
    ("Komura", "employee", ("mise_en_place", "petit_four")),
    ("Kim", "employee", ("mise_en_place", "petit_four", "GATEAU")),
    ("Sera", "employee", ("mise_en_place", "petit_four")),
    ("Miyazawa", "employee", ("mise_en_place", "petit_four")),
)

DEMO_WORKERS = tuple(
    DemoWorkerRow(
        code=_derive_worker_code(name),
        name=name,
        role=role,
        station_skills=_normalize_station_skill_codes(*station_skills),
    )
    for name, role, station_skills in _WORKER_SOURCE_ROWS
)

DEMO_STATIONS = (
    DemoStationRow(code="gateau", name="gateau"),
    DemoStationRow(code="glaze_and_fruit", name="glaze_and_fruit"),
    DemoStationRow(code="mise_en_place", name="mise_en_place"),
    DemoStationRow(code="petit_four", name="petit_four"),
)

DEMO_SHIFTS = (
    DemoShiftRow(
        code="A",
        name="A",
        start_time=time(hour=10, minute=0),
        end_time=time(hour=20, minute=0),
        paid_hours=Decimal("9.00"),
    ),
    DemoShiftRow(
        code="B",
        name="B",
        start_time=time(hour=12, minute=0),
        end_time=time(hour=21, minute=0),
        paid_hours=Decimal("8.00"),
    ),
    DemoShiftRow(
        code="C",
        name="C",
        start_time=time(hour=13, minute=0),
        end_time=time(hour=23, minute=0),
        paid_hours=Decimal("9.00"),
    ),
    DemoShiftRow(
        code="D",
        name="D",
        start_time=time(hour=14, minute=0),
        end_time=time(hour=23, minute=0),
        paid_hours=Decimal("8.00"),
    ),
    DemoShiftRow(
        code="1",
        name="1",
        start_time=time(hour=9, minute=0),
        end_time=time(hour=20, minute=0),
        paid_hours=Decimal("10.00"),
    ),
    DemoShiftRow(
        code="2",
        name="2",
        start_time=time(hour=10, minute=0),
        end_time=time(hour=21, minute=0),
        paid_hours=Decimal("10.00"),
    ),
    DemoShiftRow(
        code="3",
        name="3",
        start_time=time(hour=11, minute=0),
        end_time=time(hour=22, minute=0),
        paid_hours=Decimal("10.00"),
    ),
    DemoShiftRow(
        code="4",
        name="4",
        start_time=time(hour=12, minute=0),
        end_time=time(hour=23, minute=0),
        paid_hours=Decimal("10.00"),
    ),
)

DEMO_CONSTRAINT_CONFIG = {
    "stations": {
        "gateau": 2,
        "petit_four": 2,
        "glaze_and_fruit": 2,
        "mise_en_place": 2,
    },
    "min_staff_weekday": 7,
    "min_staff_weekend": 8,
    "max_staff_per_day": 9,
    "min_rest_days_per_month": 9,
    "max_consecutive_days": 4,
    "require_one_chef": True,
    "count_chefs_in_headcount": True,
    "chefs_have_no_shift": True,
}

PRIMARY_DEMO_WORKER = next(worker for worker in DEMO_WORKERS if worker.name == "Spencer")
SECONDARY_DEMO_WORKER = next(worker for worker in DEMO_WORKERS if worker.name == "Chung")
PRIMARY_DEMO_STATION = DEMO_STATIONS[0]
PRIMARY_DEMO_SHIFT = DEMO_SHIFTS[0]
