"""Django-rendered monthly workspace page for reviewer-visible planning flows.

This page keeps the first vertical slice backend intact while adding a small,
server-rendered workspace surface for selecting a month, adding leave,
previewing a candidate, applying it to the current workspace, saving a version,
and reviewing the month grid.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.template import Context, Engine
from django.urls import URLPattern, path
from django.views.decorators.http import require_http_methods
from pydantic import ValidationError

from app.api.schemas import MonthPlanningResultSchema
from app.engine.monthly import generate_month_plan
from app.infra.django_app.models import (
    LeaveRequest as DjangoLeaveRequest,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
)
from app.infra.django_repositories import (
    DjangoConstraintConfigRepository,
    DjangoLeaveRequestRepository,
    DjangoPlanVersionRepository,
    DjangoShiftRepository,
    DjangoStationRepository,
    DjangoTenantRepository,
    DjangoWorkerRepository,
    DjangoWorkspaceRepository,
)
from app.infra.models import ShiftDefinition, Station, Worker
from app.infra.repositories import CurrentWorkspaceState
from app.services.apply import ApplyMonthScheduleRequest, ApplyMonthScheduleService
from app.services.preview import (
    MonthlySchedulePreviewEngine,
    PreviewMonthScheduleRequest,
    PreviewMonthScheduleService,
)
from app.services.save import SaveMonthScheduleRequest, SaveMonthScheduleService

_TEMPLATE_ENGINE = Engine(
    dirs=[str(Path(__file__).resolve().parent / "templates")],
    autoescape=True,
)


@dataclass(slots=True)
class MonthlyWorkspacePageDependencies:
    """Small bundle of services and repositories used by the UI page."""

    preview_service: PreviewMonthScheduleService
    apply_service: ApplyMonthScheduleService
    save_service: SaveMonthScheduleService
    worker_repository: DjangoWorkerRepository
    station_repository: DjangoStationRepository
    shift_repository: DjangoShiftRepository
    workspace_repository: DjangoWorkspaceRepository
    plan_version_repository: DjangoPlanVersionRepository


def build_django_monthly_workspace_urlpatterns(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
) -> list[URLPattern]:
    """Build the reviewer-visible monthly workspace page route."""

    return [
        path(
            "v2/monthly-workspace",
            build_django_monthly_workspace_view(preview_engine=preview_engine),
            name="monthly_schedule_workspace",
        )
    ]


def build_django_monthly_workspace_view(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
) -> Any:
    """Build the Django-rendered monthly workspace page view."""

    dependencies = _build_page_dependencies(preview_engine=preview_engine)

    @require_http_methods(["GET", "POST"])
    def view(request: HttpRequest) -> HttpResponse:
        messages: list[dict[str, str]] = []
        scope = _resolve_scope(request)
        if not scope["is_valid"]:
            messages.append(
                _message(
                    "error",
                    "Month selection must use the YYYY-MM month picker format.",
                )
            )

        tenants = list(DjangoTenant.objects.order_by("name", "slug", "id"))
        selected_tenant = _select_tenant(
            tenants,
            request.POST.get("tenant_slug") or request.GET.get("tenant_slug"),
        )
        candidate_result = _parse_candidate_result(
            request.POST.get("candidate_result_json"),
            messages,
        )
        prefer_current_result = False

        if request.method == "POST":
            action = (request.POST.get("form_action") or "").strip()
            if selected_tenant is None:
                messages.append(
                    _message(
                        "error",
                        "No tenant data is available yet for the monthly workspace.",
                    )
                )
                candidate_result = None
            elif action == "add_leave":
                _handle_add_leave(
                    request=request,
                    tenant=selected_tenant,
                    year=scope["year"],
                    month=scope["month"],
                    messages=messages,
                )
                candidate_result = None
            elif action == "preview":
                candidate_result = _handle_preview(
                    tenant_slug=selected_tenant.slug,
                    year=scope["year"],
                    month=scope["month"],
                    preview_service=dependencies.preview_service,
                    messages=messages,
                )
            elif action == "apply":
                if candidate_result is None:
                    messages.append(
                        _message(
                            "error",
                            "Generate a candidate preview before applying the month.",
                        )
                    )
                else:
                    prefer_current_result = _handle_apply(
                        tenant_slug=selected_tenant.slug,
                        year=scope["year"],
                        month=scope["month"],
                        candidate_result=candidate_result,
                        apply_service=dependencies.apply_service,
                        messages=messages,
                    )
            elif action == "save":
                prefer_current_result = True
                _handle_save(
                    request=request,
                    tenant_slug=selected_tenant.slug,
                    year=scope["year"],
                    month=scope["month"],
                    save_service=dependencies.save_service,
                    messages=messages,
                )
            elif action:
                messages.append(_message("error", "Unknown workspace action."))

        context = _build_workspace_context(
            request=request,
            tenants=tenants,
            selected_tenant=selected_tenant,
            scope=scope,
            candidate_result=candidate_result,
            prefer_current_result=prefer_current_result,
            dependencies=dependencies,
            messages=messages,
        )
        html = _TEMPLATE_ENGINE.get_template("monthly_workspace.html").render(
            Context(context)
        )
        return HttpResponse(html)

    view.__name__ = "monthly_schedule_workspace"
    view.__doc__ = (
        "Django-rendered monthly scheduling workspace that preserves the first "
        "UI flow while improving reviewer-visible hierarchy."
    )
    return view


def _build_page_dependencies(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
) -> MonthlyWorkspacePageDependencies:
    tenant_repository = DjangoTenantRepository()
    worker_repository = DjangoWorkerRepository()
    station_repository = DjangoStationRepository()
    shift_repository = DjangoShiftRepository()
    workspace_repository = DjangoWorkspaceRepository()

    return MonthlyWorkspacePageDependencies(
        preview_service=PreviewMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=DjangoLeaveRequestRepository(),
            constraint_config_repository=DjangoConstraintConfigRepository(),
            engine_runner=(
                preview_engine
                if preview_engine is not None
                else generate_month_plan
            ),
        ),
        apply_service=ApplyMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            workspace_repository=workspace_repository,
        ),
        save_service=SaveMonthScheduleService(
            tenant_repository=tenant_repository,
            workspace_repository=workspace_repository,
            plan_version_repository=DjangoPlanVersionRepository(),
        ),
        worker_repository=worker_repository,
        station_repository=station_repository,
        shift_repository=shift_repository,
        workspace_repository=workspace_repository,
        plan_version_repository=DjangoPlanVersionRepository(),
    )


def _resolve_scope(request: HttpRequest) -> dict[str, Any]:
    raw_month_scope = (
        request.POST.get("month_scope") or request.GET.get("month_scope") or ""
    ).strip()
    fallback_date = dt.date.today().replace(day=1)

    if raw_month_scope:
        try:
            selected_date = dt.date.fromisoformat(f"{raw_month_scope}-01")
            is_valid = True
        except ValueError:
            selected_date = fallback_date
            is_valid = False
    else:
        selected_date = fallback_date
        is_valid = True

    return {
        "year": selected_date.year,
        "month": selected_date.month,
        "month_value": f"{selected_date.year:04d}-{selected_date.month:02d}",
        "month_label": selected_date.strftime("%B %Y"),
        "is_valid": is_valid,
    }


def _select_tenant(
    tenants: list[DjangoTenant],
    requested_slug: str | None,
) -> DjangoTenant | None:
    if not tenants:
        return None
    if requested_slug:
        for tenant in tenants:
            if tenant.slug == requested_slug:
                return tenant
    return tenants[0]


def _parse_candidate_result(
    candidate_result_json: str | None,
    messages: list[dict[str, str]],
) -> MonthPlanningResultSchema | None:
    if not candidate_result_json:
        return None

    try:
        return MonthPlanningResultSchema.model_validate_json(candidate_result_json)
    except ValidationError:
        messages.append(
            _message(
                "error",
                "The stored candidate preview could not be reused. Preview the month again.",
            )
        )
        return None


def _handle_add_leave(
    *,
    request: HttpRequest,
    tenant: DjangoTenant,
    year: int,
    month: int,
    messages: list[dict[str, str]],
) -> None:
    worker_id = (request.POST.get("worker_id") or "").strip()
    leave_date_raw = (request.POST.get("leave_date") or "").strip()
    if not worker_id or not leave_date_raw:
        messages.append(
            _message("error", "Choose a person and date before adding leave.")
        )
        return

    worker = DjangoWorker.objects.filter(tenant=tenant, pk=worker_id).first()
    if worker is None:
        messages.append(_message("error", "The selected person was not found."))
        return

    try:
        leave_date = dt.date.fromisoformat(leave_date_raw)
    except ValueError:
        messages.append(
            _message("error", "Leave date must use the native date picker value.")
        )
        return

    if leave_date.year != year or leave_date.month != month:
        messages.append(
            _message(
                "error",
                "Leave requests must stay inside the selected month workspace.",
            )
        )
        return

    _leave_request, created = DjangoLeaveRequest.objects.update_or_create(
        tenant=tenant,
        worker=worker,
        leave_date=leave_date,
        defaults={"reason": "UI leave request"},
    )
    if created:
        messages.append(
            _message(
                "success",
                f"Added leave for {worker.name} on {leave_date.isoformat()}.",
            )
        )
    else:
        messages.append(
            _message(
                "info",
                f"Leave for {worker.name} on {leave_date.isoformat()} was already present.",
            )
        )


def _handle_preview(
    *,
    tenant_slug: str,
    year: int,
    month: int,
    preview_service: PreviewMonthScheduleService,
    messages: list[dict[str, str]],
) -> MonthPlanningResultSchema | None:
    try:
        response = preview_service.preview_month_schedule(
            PreviewMonthScheduleRequest(
                tenant_slug=tenant_slug,
                year=year,
                month=month,
            )
        )
    except (LookupError, ValueError) as exc:
        messages.append(_message("error", str(exc)))
        return None

    candidate_result = MonthPlanningResultSchema.model_validate(
        response.candidate_result,
        from_attributes=True,
    )
    messages.append(
        _message(
            "success",
            "Candidate preview is ready for review before you apply it.",
        )
    )
    return candidate_result


def _handle_apply(
    *,
    tenant_slug: str,
    year: int,
    month: int,
    candidate_result: MonthPlanningResultSchema,
    apply_service: ApplyMonthScheduleService,
    messages: list[dict[str, str]],
) -> bool:
    try:
        response = apply_service.apply_month_schedule(
            ApplyMonthScheduleRequest(
                tenant_slug=tenant_slug,
                year=year,
                month=month,
                result=candidate_result,
            )
        )
    except (LookupError, TypeError, ValueError) as exc:
        messages.append(_message("error", str(exc)))
        return False

    messages.append(
        _message(
            "success",
            "Applied the candidate preview to the current workspace "
            f"({response.assignment_count} assignments).",
        )
    )
    return True


def _handle_save(
    *,
    request: HttpRequest,
    tenant_slug: str,
    year: int,
    month: int,
    save_service: SaveMonthScheduleService,
    messages: list[dict[str, str]],
) -> None:
    save_label = (request.POST.get("save_label") or "").strip() or None

    try:
        response = save_service.save_month_schedule(
            SaveMonthScheduleRequest(
                tenant_slug=tenant_slug,
                year=year,
                month=month,
                label=save_label,
                note=None,
            )
        )
    except (LookupError, ValueError) as exc:
        messages.append(_message("error", str(exc)))
        return

    messages.append(
        _message(
            "success",
            f"Saved version {response.version_number} for {year}-{month:02d}.",
        )
    )


def _build_workspace_context(
    *,
    request: HttpRequest,
    tenants: list[DjangoTenant],
    selected_tenant: DjangoTenant | None,
    scope: dict[str, Any],
    candidate_result: MonthPlanningResultSchema | None,
    prefer_current_result: bool,
    dependencies: MonthlyWorkspacePageDependencies,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    tenant_options = [
        {
            "slug": tenant.slug,
            "name": tenant.name,
            "selected": selected_tenant is not None and tenant.pk == selected_tenant.pk,
        }
        for tenant in tenants
    ]
    selected_worker_id = (request.POST.get("worker_id") or "").strip()
    save_label_value = (request.POST.get("save_label") or "").strip()

    if selected_tenant is None:
        leave_rows: list[dict[str, str]] = []
        leave_summary: list[dict[str, str]] = []
        worker_options: list[dict[str, str]] = []
        state_cards = _build_state_cards(
            candidate_result=candidate_result,
            has_current_workspace=False,
            saved_version_count=0,
        )
        return {
            "messages": messages,
            "tenant_options": tenant_options,
            "selected_tenant": None,
            "month_value": scope["month_value"],
            "month_label": scope["month_label"],
            "selected_worker_id": selected_worker_id,
            "leave_date_value": _default_leave_date(scope["year"], scope["month"]),
            "worker_options": worker_options,
            "leave_rows": leave_rows,
            "leave_summary": leave_summary,
            "state_cards": state_cards,
            "display_surface": None,
            "warnings": [],
            "warnings_note": (
                "Preview warnings appear here after you generate a candidate preview."
            ),
            "candidate_result_json": (
                candidate_result.model_dump_json() if candidate_result is not None else ""
            ),
            "apply_disabled": True,
            "save_disabled": True,
            "save_label_value": save_label_value,
            "workflow_steps": _workflow_steps(),
        }

    tenant_id = str(selected_tenant.pk)
    workers = dependencies.worker_repository.list_for_tenant(tenant_id)
    stations = dependencies.station_repository.list_for_tenant(tenant_id)
    shifts = dependencies.shift_repository.list_for_tenant(tenant_id)
    current_state = dependencies.workspace_repository.load_current(
        tenant_id,
        scope["year"],
        scope["month"],
    )
    saved_versions = dependencies.plan_version_repository.list_for_month(
        tenant_id,
        scope["year"],
        scope["month"],
    )
    leave_rows = _load_leave_rows(
        tenant=selected_tenant,
        year=scope["year"],
        month=scope["month"],
    )
    leave_summary = _build_leave_summary(leave_rows)
    worker_options = _build_worker_options(workers, selected_worker_id)
    display_surface = _choose_display_surface(
        candidate_result=candidate_result,
        current_state=current_state,
        workers=workers,
        shifts=shifts,
        stations=stations,
        year=scope["year"],
        month=scope["month"],
        prefer_current_result=prefer_current_result,
    )

    warnings = _build_warning_rows(candidate_result)
    warnings_note = (
        "Preview warnings appear here after you generate a candidate preview. "
        "Current workspace warnings are not persisted yet."
    )

    return {
        "messages": messages,
        "tenant_options": tenant_options,
        "selected_tenant": {
            "slug": selected_tenant.slug,
            "name": selected_tenant.name,
        },
        "month_value": scope["month_value"],
        "month_label": scope["month_label"],
        "selected_worker_id": selected_worker_id,
        "leave_date_value": request.POST.get("leave_date")
        or _default_leave_date(scope["year"], scope["month"]),
        "worker_options": worker_options,
        "leave_rows": leave_rows,
        "leave_summary": leave_summary,
        "state_cards": _build_state_cards(
            candidate_result=candidate_result,
            has_current_workspace=current_state is not None,
            saved_version_count=len(saved_versions),
        ),
        "display_surface": display_surface,
        "warnings": warnings,
        "warnings_note": warnings_note,
        "candidate_result_json": (
            candidate_result.model_dump_json() if candidate_result is not None else ""
        ),
        "apply_disabled": candidate_result is None,
        "save_disabled": current_state is None,
        "save_label_value": save_label_value,
        "workflow_steps": _workflow_steps(),
    }


def _workflow_steps() -> list[str]:
    return [
        "1. Select month",
        "2. Add leave requests",
        "3. Preview",
        "4. Apply",
        "5. Save",
        "6. View monthly schedule result",
    ]


def _build_worker_options(
    workers: list[Worker],
    selected_worker_id: str,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for worker in workers:
        worker_id = worker.id or ""
        worker_code = worker.code or worker_id
        label = f"{worker.name} ({worker_code})"
        if not worker.is_active:
            label = f"{label} - inactive"
        options.append(
            {
                "id": worker_id,
                "label": label,
                "selected": "selected" if worker_id == selected_worker_id else "",
            }
        )
    return options


def _load_leave_rows(
    *,
    tenant: DjangoTenant,
    year: int,
    month: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    leave_requests = (
        DjangoLeaveRequest.objects.filter(
            tenant=tenant,
            leave_date__year=year,
            leave_date__month=month,
        )
        .select_related("worker")
        .order_by("leave_date", "worker__code", "worker_id", "id")
    )
    for row in leave_requests:
        rows.append(
            {
                "worker_name": row.worker.name,
                "worker_code": row.worker.code,
                "date": row.leave_date.isoformat(),
            }
        )
    return rows


def _build_leave_summary(leave_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    counts = Counter(
        f"{row['worker_name']} ({row['worker_code']})" for row in leave_rows
    )
    return [
        {"label": label, "count": str(count)}
        for label, count in sorted(counts.items(), key=lambda item: item[0])
    ]


def _build_state_cards(
    *,
    candidate_result: MonthPlanningResultSchema | None,
    has_current_workspace: bool,
    saved_version_count: int,
) -> list[dict[str, str]]:
    evaluation_label = "none"
    evaluation_note = "Generate a preview to evaluate the month."
    evaluation_tone = "tone-neutral"
    if candidate_result is not None and candidate_result.evaluation is not None:
        evaluation_label = candidate_result.evaluation.schedule_quality_label
        evaluation_note = "Evaluation reflects the visible candidate preview."
        evaluation_tone = _evaluation_tone(evaluation_label)

    return [
        {
            "label": "Candidate preview",
            "value": "present" if candidate_result is not None else "none",
            "note": "Read-only result from the latest preview action.",
            "tone": "tone-good" if candidate_result is not None else "tone-neutral",
        },
        {
            "label": "Current workspace",
            "value": "present" if has_current_workspace else "none",
            "note": "Mutable month state that Apply updates.",
            "tone": "tone-good" if has_current_workspace else "tone-neutral",
        },
        {
            "label": "Saved versions",
            "value": str(saved_version_count),
            "note": "Immutable month snapshots created by Save.",
            "tone": "tone-neutral",
        },
        {
            "label": "Evaluation",
            "value": evaluation_label,
            "note": evaluation_note,
            "tone": evaluation_tone,
        },
    ]


def _evaluation_tone(label: str) -> str:
    if label == "good":
        return "tone-good"
    if label == "needs_review":
        return "tone-warn"
    if label == "invalid":
        return "tone-error"
    return "tone-neutral"


def _choose_display_surface(
    *,
    candidate_result: MonthPlanningResultSchema | None,
    current_state: CurrentWorkspaceState | None,
    workers: list[Worker],
    shifts: list[ShiftDefinition],
    stations: list[Station],
    year: int,
    month: int,
    prefer_current_result: bool,
) -> dict[str, Any] | None:
    if prefer_current_result and current_state is not None:
        return _build_current_workspace_surface(
            current_state=current_state,
            workers=workers,
            shifts=shifts,
            stations=stations,
            year=year,
            month=month,
        )
    if candidate_result is not None:
        return _build_candidate_surface(
            candidate_result=candidate_result,
            workers=workers,
            year=year,
            month=month,
        )
    if current_state is not None:
        return _build_current_workspace_surface(
            current_state=current_state,
            workers=workers,
            shifts=shifts,
            stations=stations,
            year=year,
            month=month,
        )
    return None


def _build_candidate_surface(
    *,
    candidate_result: MonthPlanningResultSchema,
    workers: list[Worker],
    year: int,
    month: int,
) -> dict[str, Any]:
    normalized_assignments = [
        {
            "worker_code": assignment.worker_code,
            "date": assignment.date,
            "shift_code": assignment.shift_code,
            "station_code": assignment.station_code,
            "note": assignment.note,
        }
        for assignment in candidate_result.assignments
    ]
    return {
        "badge": "Candidate preview",
        "description": (
            "Showing the current read-only preview before it is applied to the workspace."
        ),
        "meta": [
            {"label": "Source", "value": candidate_result.metadata.source_type},
            {
                "label": "Assignments",
                "value": str(candidate_result.summary.total_assignments),
            },
            {
                "label": "Warnings",
                "value": str(candidate_result.summary.total_warnings),
            },
        ],
        "days": _build_day_headers(year, month),
        "rows": _build_grid_rows(
            worker_identities=_worker_identities_from_workers(workers),
            normalized_assignments=normalized_assignments,
            year=year,
            month=month,
        ),
    }


def _build_current_workspace_surface(
    *,
    current_state: CurrentWorkspaceState,
    workers: list[Worker],
    shifts: list[ShiftDefinition],
    stations: list[Station],
    year: int,
    month: int,
) -> dict[str, Any]:
    workers_by_id = {
        worker.id or "": {
            "worker_code": worker.code or worker.id or "",
            "worker_name": worker.name,
            "worker_role": worker.role,
        }
        for worker in workers
    }
    shifts_by_id = {shift.id or "": shift.code for shift in shifts}
    stations_by_id = {station.id or "": station.code or station.id or "" for station in stations}

    normalized_assignments: list[dict[str, Any]] = []
    for assignment in current_state.assignments:
        worker_identity = workers_by_id.get(
            assignment.worker_id,
            {
                "worker_code": assignment.worker_id,
                "worker_name": assignment.worker_id,
                "worker_role": "",
            },
        )
        normalized_assignments.append(
            {
                "worker_code": worker_identity["worker_code"],
                "date": assignment.assignment_date,
                "shift_code": shifts_by_id.get(
                    assignment.shift_definition_id,
                    assignment.shift_definition_id,
                ),
                "station_code": (
                    stations_by_id.get(assignment.station_id, assignment.station_id)
                    if assignment.station_id is not None
                    else None
                ),
                "note": None,
            }
        )

    return {
        "badge": "Current workspace",
        "description": "Showing the mutable workspace that Apply updates and Save snapshots.",
        "meta": [
            {"label": "Status", "value": current_state.workspace.status},
            {
                "label": "Assignments",
                "value": str(len(current_state.assignments)),
            },
            {"label": "Month", "value": f"{year:04d}-{month:02d}"},
        ],
        "days": _build_day_headers(year, month),
        "rows": _build_grid_rows(
            worker_identities=_worker_identities_from_workers(workers),
            normalized_assignments=normalized_assignments,
            year=year,
            month=month,
        ),
    }


def _worker_identities_from_workers(workers: list[Worker]) -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for worker in workers:
        worker_code = worker.code or worker.id or ""
        identities.append(
            {
                "worker_code": worker_code,
                "worker_name": worker.name,
                "worker_role": worker.role,
            }
        )
    return identities


def _build_grid_rows(
    *,
    worker_identities: list[dict[str, str]],
    normalized_assignments: list[dict[str, Any]],
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    days = _build_day_headers(year, month)
    assignments_by_worker_day: dict[str, dict[int, dict[str, Any]]] = {}

    for assignment in normalized_assignments:
        worker_code = str(assignment["worker_code"])
        day = assignment["date"].day
        worker_day_map = assignments_by_worker_day.setdefault(worker_code, {})
        cell = worker_day_map.get(day)
        main_value = str(assignment["shift_code"])
        subvalue = _build_cell_subvalue(
            assignment.get("station_code"),
            assignment.get("note"),
        )
        if cell is None:
            worker_day_map[day] = {
                "value": main_value,
                "subvalue": subvalue,
                "assigned": True,
            }
            continue

        cell["value"] = f"{cell['value']} / {main_value}"
        if subvalue:
            existing_subvalue = cell["subvalue"]
            cell["subvalue"] = (
                f"{existing_subvalue} / {subvalue}"
                if existing_subvalue
                else subvalue
            )

    rows: list[dict[str, Any]] = []
    seen_worker_codes: set[str] = set()
    for worker in worker_identities:
        seen_worker_codes.add(worker["worker_code"])
        rows.append(
            {
                "worker_code": worker["worker_code"],
                "worker_name": worker["worker_name"],
                "worker_role": worker["worker_role"],
                "cells": _build_worker_cells(
                    assignments_by_worker_day.get(worker["worker_code"], {}),
                    days,
                ),
            }
        )

    for worker_code in sorted(code for code in assignments_by_worker_day if code not in seen_worker_codes):
        rows.append(
            {
                "worker_code": worker_code,
                "worker_name": worker_code,
                "worker_role": "",
                "cells": _build_worker_cells(assignments_by_worker_day[worker_code], days),
            }
        )

    return rows


def _build_worker_cells(
    assignments_by_day: dict[int, dict[str, Any]],
    days: list[int],
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for day in days:
        cell = assignments_by_day.get(day)
        if cell is None:
            cells.append({"value": "--", "subvalue": "", "assigned": False})
            continue
        cells.append(cell)
    return cells


def _build_cell_subvalue(
    station_code: object | None,
    note: object | None,
) -> str:
    parts: list[str] = []
    if station_code:
        parts.append(str(station_code))
    if note:
        parts.append(str(note))
    return " / ".join(parts)


def _build_day_headers(year: int, month: int) -> list[int]:
    day_count = calendar.monthrange(year, month)[1]
    return list(range(1, day_count + 1))


def _build_warning_rows(
    candidate_result: MonthPlanningResultSchema | None,
) -> list[dict[str, str]]:
    if candidate_result is None:
        return []

    rows: list[dict[str, str]] = []
    for warning in candidate_result.warnings:
        details_text = ", ".join(
            f"{key.replace('_', ' ')}: {value}"
            for key, value in sorted((warning.details or {}).items())
        )
        rows.append(
            {
                "title": warning.type.replace("_", " "),
                "message": warning.message_key.replace("_", " "),
                "date": warning.date.isoformat() if warning.date is not None else "month",
                "worker": warning.worker_code or "system",
                "details": details_text or "No extra details.",
            }
        )
    return rows


def _default_leave_date(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-01"


def _message(level: str, text: str) -> dict[str, str]:
    return {"level": level, "text": text}


__all__ = [
    "build_django_monthly_workspace_urlpatterns",
    "build_django_monthly_workspace_view",
]
