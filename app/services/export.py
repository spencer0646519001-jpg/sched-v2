"""Read-only export orchestration for the current monthly workspace state.

The export service loads the current workspace and its assignments for one
tenant/month, enriches those assignments with reference data, and returns
export-ready rows plus a human-readable CSV aligned to the current workspace
people grid. It intentionally stays separate from HTTP responses, file
streaming, and repository adapter details.
"""

from __future__ import annotations

import calendar
import csv
from dataclasses import dataclass
from io import StringIO

from app.infra.models import (
    MonthlyAssignment,
    RecordId,
    ShiftDefinition,
    Station,
    Worker,
)
from app.infra.repositories import (
    CurrentWorkspaceState,
    ShiftRepository,
    StationRepository,
    TenantRepository,
    WorkerRepository,
    WorkspaceRepository,
)

_GRID_EXPORT_FIXED_COLUMNS = ("worker", "role")
_EMPTY_GRID_CELL = "--"
_REQUIRED_CHEF_NOTE = "required_chef"


@dataclass(slots=True)
class ExportMonthScheduleRequest:
    """Service-layer request for exporting one tenant/month workspace."""

    tenant_slug: str
    year: int
    month: int


@dataclass(slots=True)
class ExportMonthScheduleRow:
    """Flat export-ready row for one persisted monthly assignment."""

    assignment_date: str
    worker_code: str
    worker_name: str
    worker_role: str
    shift_code: str
    shift_name: str
    station_code: str | None
    station_name: str | None


@dataclass(slots=True)
class ExportMonthScheduleResponse:
    """Small export result that an API layer can map to a download later."""

    tenant_slug: str
    year: int
    month: int
    workspace_id: RecordId
    workspace_status: str
    row_count: int
    rows: list[ExportMonthScheduleRow]
    csv_text: str


@dataclass(slots=True)
class ExportMonthScheduleService:
    """Coordinates current-state reads into export-ready monthly rows.

    Export is intentionally read-only. It requires the current workspace to
    exist, enriches persisted assignment ids with tenant reference data, and
    returns a transport-agnostic payload for future API/download adapters.
    """

    tenant_repository: TenantRepository
    worker_repository: WorkerRepository
    station_repository: StationRepository
    shift_repository: ShiftRepository
    workspace_repository: WorkspaceRepository

    def export_month_schedule(
        self,
        request: ExportMonthScheduleRequest,
    ) -> ExportMonthScheduleResponse:
        """Load the current workspace state and build export-ready output."""

        _validate_request(request)

        tenant = self.tenant_repository.get_by_slug(request.tenant_slug)
        if tenant is None:
            raise LookupError(f"Tenant not found: {request.tenant_slug!r}")

        tenant_id = _require_record_id(tenant.id, label="tenant.id")
        current_state = self.workspace_repository.load_current(
            tenant_id,
            request.year,
            request.month,
        )
        if current_state is None:
            raise LookupError(
                f"No current workspace found for {tenant.slug!r} "
                f"{request.year}-{request.month:02d}."
            )

        workers = self.worker_repository.list_for_tenant(tenant_id)
        stations = self.station_repository.list_for_tenant(tenant_id)
        shifts = self.shift_repository.list_for_tenant(tenant_id)

        rows = _translate_current_state_to_export_rows(
            current_state,
            workers=workers,
            stations=stations,
            shifts=shifts,
        )
        workspace_id = _require_record_id(
            current_state.workspace.id,
            label="workspace.id",
        )

        return ExportMonthScheduleResponse(
            tenant_slug=tenant.slug,
            year=request.year,
            month=request.month,
            workspace_id=workspace_id,
            workspace_status=current_state.workspace.status,
            row_count=len(rows),
            rows=rows,
            csv_text=_serialize_current_workspace_to_csv(
                current_state,
                workers=workers,
                stations=stations,
                shifts=shifts,
                year=request.year,
                month=request.month,
            ),
        )


def export_month_schedule(
    request: ExportMonthScheduleRequest,
    *,
    service: ExportMonthScheduleService,
) -> ExportMonthScheduleResponse:
    """Thin functional wrapper around the export service boundary."""

    return service.export_month_schedule(request)


def _translate_current_state_to_export_rows(
    current_state: CurrentWorkspaceState,
    *,
    workers: list[Worker],
    stations: list[Station],
    shifts: list[ShiftDefinition],
) -> list[ExportMonthScheduleRow]:
    """Flatten current workspace assignments into deterministic export rows."""

    workers_by_id = {
        _require_record_id(worker.id, label="worker.id"): worker for worker in workers
    }
    stations_by_id = {
        _require_record_id(station.id, label="station.id"): station
        for station in stations
    }
    shifts_by_id = {
        _require_record_id(shift.id, label="shift.id"): shift for shift in shifts
    }

    rows = [
        _build_export_row(
            assignment,
            workers_by_id=workers_by_id,
            stations_by_id=stations_by_id,
            shifts_by_id=shifts_by_id,
        )
        for assignment in current_state.assignments
    ]
    rows.sort(key=_export_row_sort_key)
    return rows


def _build_export_row(
    assignment: MonthlyAssignment,
    *,
    workers_by_id: dict[RecordId, Worker],
    stations_by_id: dict[RecordId, Station],
    shifts_by_id: dict[RecordId, ShiftDefinition],
) -> ExportMonthScheduleRow:
    """Enrich one persisted assignment row into export-friendly fields."""

    worker = workers_by_id.get(assignment.worker_id)
    if worker is None:
        raise LookupError(
            f"Monthly assignment references unknown worker_id "
            f"{assignment.worker_id!r}."
        )

    shift = shifts_by_id.get(assignment.shift_definition_id)
    if shift is None:
        raise LookupError(
            f"Monthly assignment references unknown shift_definition_id "
            f"{assignment.shift_definition_id!r}."
        )

    station: Station | None = None
    if assignment.station_id is not None:
        station = stations_by_id.get(assignment.station_id)
        if station is None:
            raise LookupError(
                f"Monthly assignment references unknown station_id "
                f"{assignment.station_id!r}."
            )

    return ExportMonthScheduleRow(
        assignment_date=assignment.assignment_date.isoformat(),
        worker_code=_resolve_worker_code(worker),
        worker_name=worker.name,
        worker_role=worker.role,
        shift_code=shift.code,
        shift_name=shift.name,
        station_code=_resolve_station_code(station) if station else None,
        station_name=station.name if station else None,
    )


def _export_row_sort_key(row: ExportMonthScheduleRow) -> tuple[str, str, str, str, str]:
    """Keep row ordering deterministic for CSV exports and tests."""

    return (
        row.assignment_date,
        row.worker_name.casefold(),
        row.worker_code.casefold(),
        row.shift_code.casefold(),
        (row.station_code or "").casefold(),
    )


def _serialize_current_workspace_to_csv(
    current_state: CurrentWorkspaceState,
    *,
    workers: list[Worker],
    stations: list[Station],
    shifts: list[ShiftDefinition],
    year: int,
    month: int,
) -> str:
    """Render the persisted current workspace as a human-readable people grid."""

    day_numbers = list(range(1, calendar.monthrange(year, month)[1] + 1))
    assignments_by_worker_day = _build_grid_assignments_by_worker_day(
        current_state,
        workers=workers,
        stations=stations,
        shifts=shifts,
    )
    ordered_workers = _order_workers_for_grid(workers)

    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            *_GRID_EXPORT_FIXED_COLUMNS,
            *[_format_grid_csv_day_header(month=month, day=day) for day in day_numbers],
        ]
    )

    seen_worker_codes: set[str] = set()
    for worker in ordered_workers:
        worker_code = _resolve_worker_code(worker)
        seen_worker_codes.add(worker_code)
        writer.writerow(
            [
                _build_worker_display_name(worker),
                worker.role,
                *[
                    _render_grid_csv_cell(
                        assignments_by_worker_day.get(worker_code, {}).get(day)
                    )
                    for day in day_numbers
                ],
            ]
        )

    for worker_code in sorted(
        code for code in assignments_by_worker_day if code not in seen_worker_codes
    ):
        writer.writerow(
            [
                worker_code,
                "",
                *[
                    _render_grid_csv_cell(
                        assignments_by_worker_day.get(worker_code, {}).get(day)
                    )
                    for day in day_numbers
                ],
            ]
        )

    return buffer.getvalue()


def _build_grid_assignments_by_worker_day(
    current_state: CurrentWorkspaceState,
    *,
    workers: list[Worker],
    stations: list[Station],
    shifts: list[ShiftDefinition],
) -> dict[str, dict[int, dict[str, str]]]:
    """Normalize persisted assignments into UI-like worker/day cell values."""

    workers_by_id = {
        _require_record_id(worker.id, label="worker.id"): worker for worker in workers
    }
    shifts_by_id = {
        _require_record_id(shift.id, label="shift.id"): shift.code for shift in shifts
    }
    stations_by_id = {
        _require_record_id(station.id, label="station.id"): station
        for station in stations
    }

    assignments_by_worker_day: dict[str, dict[int, dict[str, str]]] = {}
    for assignment in current_state.assignments:
        worker = workers_by_id.get(assignment.worker_id)
        if worker is None:
            raise LookupError(
                f"Monthly assignment references unknown worker_id "
                f"{assignment.worker_id!r}."
            )
        shift_code = shifts_by_id.get(assignment.shift_definition_id)
        if shift_code is None:
            raise LookupError(
                f"Monthly assignment references unknown shift_definition_id "
                f"{assignment.shift_definition_id!r}."
            )

        station: Station | None = None
        if assignment.station_id is not None:
            station = stations_by_id.get(assignment.station_id)
            if station is None:
                raise LookupError(
                    f"Monthly assignment references unknown station_id "
                    f"{assignment.station_id!r}."
                )

        worker_code = _resolve_worker_code(worker)
        day = assignment.assignment_date.day
        worker_day_map = assignments_by_worker_day.setdefault(worker_code, {})
        main_value = _build_grid_cell_main_value(shift_code, assignment.note)
        subvalue = _build_grid_cell_subvalue(station, assignment.note)
        cell = worker_day_map.get(day)
        if cell is None:
            worker_day_map[day] = {"value": main_value, "subvalue": subvalue}
            continue

        cell["value"] = f"{cell['value']} / {main_value}"
        if subvalue:
            existing_subvalue = cell["subvalue"]
            cell["subvalue"] = (
                f"{existing_subvalue} / {subvalue}"
                if existing_subvalue
                else subvalue
            )

    return assignments_by_worker_day


def _render_grid_csv_cell(cell: dict[str, str] | None) -> str:
    """Collapse one grid cell into a single CSV-friendly string."""

    if cell is None:
        return _EMPTY_GRID_CELL
    if cell["subvalue"]:
        return f"{cell['value']} / {cell['subvalue']}"
    return cell["value"]


def _build_grid_cell_main_value(
    shift_code: object | None,
    note: object | None,
) -> str:
    """Mirror the workspace UI's main cell label semantics."""

    if note == _REQUIRED_CHEF_NOTE:
        return "WORK"
    return str(shift_code or "")


def _build_grid_cell_subvalue(
    station: Station | None,
    note: object | None,
) -> str:
    """Render only human-facing sublabels for CSV cells."""

    note_text = str(note) if note else ""
    if note_text == _REQUIRED_CHEF_NOTE:
        return ""
    if station is not None:
        return _build_grid_cell_station_label(station)
    return ""


def _format_grid_csv_day_header(*, month: int, day: int) -> str:
    """Render one month/day header for the grid CSV."""

    return f"{month}/{day}"


def _build_grid_cell_station_label(station: Station) -> str:
    """Prefer a short human-readable station label for CSV cells."""

    raw_label = station.name or _resolve_station_code(station)
    return _shorten_grid_csv_label(raw_label)


def _shorten_grid_csv_label(value: object | None) -> str:
    """Compress slug-like station values into Excel-friendly labels."""

    normalized = " ".join(str(value or "").replace("_", " ").replace("-", " ").split())
    if not normalized:
        return ""
    first_token = normalized.split(" ", maxsplit=1)[0]
    if first_token.isupper() or first_token.islower():
        return first_token.capitalize()
    return first_token


def _build_worker_display_name(worker: Worker) -> str:
    """Prefer the human-readable worker name for grid exports."""

    if worker.name:
        return worker.name
    return _resolve_worker_code(worker)


def _order_workers_for_grid(workers: list[Worker]) -> list[Worker]:
    """Match the monthly workspace's chef-first row ordering."""

    return sorted(
        workers,
        key=lambda worker: (
            0 if _is_chef_role(worker.role) else 1,
            _record_sort_key(worker.id),
        ),
    )


def _record_sort_key(record_id: str | None) -> tuple[int, int | str]:
    """Sort numeric ids numerically and fall back to string comparison."""

    if record_id and record_id.isdigit():
        return (0, int(record_id))
    return (1, record_id or "")


def _is_chef_role(role: str) -> bool:
    """Treat the canonical chef role case-insensitively."""

    return role.strip().casefold() == "chef"


def _validate_request(request: ExportMonthScheduleRequest) -> None:
    """Guard the export service boundary against invalid calendar inputs."""

    if request.year < 1:
        raise ValueError("Export year must be greater than zero.")
    if request.month < 1 or request.month > 12:
        raise ValueError("Export month must be between 1 and 12.")


def _resolve_worker_code(worker: Worker) -> str:
    """Prefer a business-facing worker code, falling back to the persisted id."""

    return _coalesce_export_code(worker.code, worker.id, label="worker")


def _resolve_station_code(station: Station) -> str:
    """Prefer a business-facing station code, falling back to the persisted id."""

    return _coalesce_export_code(station.code, station.id, label="station")


def _coalesce_export_code(
    code: str | None,
    record_id: RecordId | None,
    *,
    label: str,
) -> str:
    """Choose a stable export identifier for a reference record."""

    if code:
        return code
    if record_id:
        return record_id
    raise ValueError(f"{label.capitalize()} requires either a code or persisted id.")


def _require_record_id(record_id: RecordId | None, *, label: str) -> RecordId:
    """Ensure repository-loaded records are usable for downstream export."""

    if record_id is None:
        raise ValueError(f"{label} must be populated on repository results.")
    return record_id


__all__ = [
    "ExportMonthScheduleRequest",
    "ExportMonthScheduleResponse",
    "ExportMonthScheduleRow",
    "ExportMonthScheduleService",
    "export_month_schedule",
]
