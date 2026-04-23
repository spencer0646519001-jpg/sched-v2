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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.template import Context, Engine
from django.urls import URLPattern, path
from django.views.decorators.http import require_http_methods
from pydantic import ValidationError

from app.ai.openai_client import build_structured_output_model_client_from_env
from app.api.monthly_workspace_copy import (
    MONTHLY_WORKSPACE_UI_LANGUAGE_LABELS,
    format_monthly_workspace_month_label,
    get_monthly_workspace_copy,
    resolve_monthly_workspace_ui_lang,
)
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
    DjangoRefineRequestRepository,
    DjangoShiftRepository,
    DjangoStationRepository,
    DjangoTenantRepository,
    DjangoWorkerRepository,
    DjangoWorkspaceRepository,
)
from app.infra.models import ShiftDefinition, Station, Worker
from app.infra.repositories import CurrentWorkspaceState
from app.services.apply import ApplyMonthScheduleRequest, ApplyMonthScheduleService
from app.services.explain import (
    ExplainDayScheduleRequest,
    ExplainDayScheduleResponse,
    ExplainDayScheduleService,
    build_day_explanation_headline,
    render_explain_outcome,
)
from app.services.explain_langgraph import LangGraphDayExplainWorkflow
from app.services.preview import (
    MonthlySchedulePreviewEngine,
    PreviewMonthScheduleRequest,
    PreviewMonthScheduleService,
)
from app.services.refine import (
    RefineMonthScheduleRequest,
    RefineMonthScheduleResponse,
    RefineMonthScheduleService,
    render_refine_outcome,
)
from app.services.refine_langgraph import LangGraphRefineWorkflow
from app.services.save import SaveMonthScheduleRequest, SaveMonthScheduleService

_TEMPLATE_ENGINE = Engine(
    dirs=[str(Path(__file__).resolve().parent / "templates")],
    autoescape=True,
)

_REQUIRED_CHEF_NOTE = "required_chef"


@dataclass(slots=True)
class MonthlyWorkspacePageDependencies:
    """Small bundle of services and repositories used by the UI page."""

    preview_service: PreviewMonthScheduleService
    apply_service: ApplyMonthScheduleService
    save_service: SaveMonthScheduleService
    explain_service: ExplainDayScheduleService
    refine_service: RefineMonthScheduleService
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
        tenants = list(DjangoTenant.objects.order_by("name", "slug", "id"))
        selected_tenant = _select_tenant(
            tenants,
            request.POST.get("tenant_slug") or request.GET.get("tenant_slug"),
        )
        ui_lang = resolve_monthly_workspace_ui_lang(
            request.POST.get("ui_lang") or request.GET.get("ui_lang"),
            fallback_locale=(
                selected_tenant.default_locale if selected_tenant is not None else None
            ),
        )
        page_copy = get_monthly_workspace_copy(ui_lang)
        if not scope["is_valid"]:
            messages.append(
                _message("error", page_copy["messages"]["invalid_scope"])
            )
        candidate_result = _parse_candidate_result(
            request.POST.get("candidate_result_json"),
            messages,
            page_copy=page_copy,
        )
        explain_result: dict[str, Any] | None = None
        refine_result: dict[str, Any] | None = None
        prefer_current_result = False

        if request.method == "POST":
            action = (request.POST.get("form_action") or "").strip()
            if selected_tenant is None:
                messages.append(
                    _message("error", page_copy["messages"]["no_tenant"])
                )
                candidate_result = None
            elif action == "add_leave":
                _handle_add_leave(
                    request=request,
                    tenant=selected_tenant,
                    year=scope["year"],
                    month=scope["month"],
                    messages=messages,
                    page_copy=page_copy,
                )
                candidate_result = None
            elif action == "preview":
                candidate_result = _handle_preview(
                    tenant_slug=selected_tenant.slug,
                    year=scope["year"],
                    month=scope["month"],
                    preview_service=dependencies.preview_service,
                    messages=messages,
                    page_copy=page_copy,
                )
            elif action == "apply":
                if candidate_result is None:
                    messages.append(
                        _message(
                            "error",
                            page_copy["messages"]["apply_requires_candidate"],
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
                        page_copy=page_copy,
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
                    page_copy=page_copy,
                )
            elif action == "explain":
                explain_result = _handle_explain(
                    request=request,
                    tenant=selected_tenant,
                    year=scope["year"],
                    month=scope["month"],
                    ui_lang=ui_lang,
                    candidate_result=candidate_result,
                    explain_service=dependencies.explain_service,
                    messages=messages,
                    page_copy=page_copy,
                )
            elif action == "refine":
                candidate_result, refine_result = _handle_refine(
                    request=request,
                    tenant=selected_tenant,
                    year=scope["year"],
                    month=scope["month"],
                    ui_lang=ui_lang,
                    refine_service=dependencies.refine_service,
                    workspace_repository=dependencies.workspace_repository,
                    messages=messages,
                    page_copy=page_copy,
                )
            elif action:
                messages.append(
                    _message("error", page_copy["messages"]["unknown_action"])
                )

        context = _build_workspace_context(
            request=request,
            tenants=tenants,
            selected_tenant=selected_tenant,
            scope=scope,
            ui_lang=ui_lang,
            page_copy=page_copy,
            candidate_result=candidate_result,
            explain_result=explain_result,
            refine_result=refine_result,
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
    leave_request_repository = DjangoLeaveRequestRepository()
    constraint_config_repository = DjangoConstraintConfigRepository()
    resolved_preview_engine = (
        preview_engine if preview_engine is not None else generate_month_plan
    )

    return MonthlyWorkspacePageDependencies(
        preview_service=PreviewMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=leave_request_repository,
            constraint_config_repository=constraint_config_repository,
            engine_runner=(
                resolved_preview_engine
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
        explain_service=ExplainDayScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=leave_request_repository,
            constraint_config_repository=constraint_config_repository,
            workspace_repository=workspace_repository,
            workflow=LangGraphDayExplainWorkflow(
                model_client=build_structured_output_model_client_from_env()
            ),
        ),
        refine_service=RefineMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=leave_request_repository,
            constraint_config_repository=constraint_config_repository,
            workspace_repository=workspace_repository,
            refine_request_repository=DjangoRefineRequestRepository(),
            workflow=LangGraphRefineWorkflow(
                engine_runner=resolved_preview_engine
            ),
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
    *,
    page_copy: dict[str, Any],
) -> MonthPlanningResultSchema | None:
    if not candidate_result_json:
        return None

    try:
        return MonthPlanningResultSchema.model_validate_json(candidate_result_json)
    except ValidationError:
        messages.append(
            _message("error", page_copy["messages"]["candidate_reuse_failed"])
        )
        return None


def _handle_add_leave(
    *,
    request: HttpRequest,
    tenant: DjangoTenant,
    year: int,
    month: int,
    messages: list[dict[str, str]],
    page_copy: dict[str, Any],
) -> None:
    messages_copy = page_copy["messages"]
    worker_id = (request.POST.get("worker_id") or "").strip()
    leave_date_raw = (request.POST.get("leave_date") or "").strip()
    if not worker_id or not leave_date_raw:
        messages.append(
            _message("error", messages_copy["choose_person_and_date"])
        )
        return

    worker = DjangoWorker.objects.filter(tenant=tenant, pk=worker_id).first()
    if worker is None:
        messages.append(_message("error", messages_copy["selected_person_not_found"]))
        return

    try:
        leave_date = dt.date.fromisoformat(leave_date_raw)
    except ValueError:
        messages.append(
            _message("error", messages_copy["invalid_leave_date"])
        )
        return

    if leave_date.year != year or leave_date.month != month:
        messages.append(
            _message("error", messages_copy["leave_outside_scope"])
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
                messages_copy["leave_added"].format(
                    worker_name=worker.name,
                    leave_date=leave_date.isoformat(),
                ),
            )
        )
    else:
        messages.append(
            _message(
                "info",
                messages_copy["leave_exists"].format(
                    worker_name=worker.name,
                    leave_date=leave_date.isoformat(),
                ),
            )
        )


def _handle_preview(
    *,
    tenant_slug: str,
    year: int,
    month: int,
    preview_service: PreviewMonthScheduleService,
    messages: list[dict[str, str]],
    page_copy: dict[str, Any],
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
            page_copy["messages"]["candidate_ready"],
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
    page_copy: dict[str, Any],
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
            page_copy["messages"]["applied_candidate"].format(
                assignment_count=response.assignment_count,
            ),
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
    page_copy: dict[str, Any],
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
            page_copy["messages"]["saved_version"].format(
                version_number=response.version_number,
                month_value=f"{year:04d}-{month:02d}",
            ),
        )
    )


def _handle_refine(
    *,
    request: HttpRequest,
    tenant: DjangoTenant,
    year: int,
    month: int,
    ui_lang: str,
    refine_service: RefineMonthScheduleService,
    workspace_repository: DjangoWorkspaceRepository,
    messages: list[dict[str, str]],
    page_copy: dict[str, Any],
) -> tuple[MonthPlanningResultSchema | None, dict[str, Any] | None]:
    messages_copy = page_copy["messages"]
    request_text = (request.POST.get("request_text") or "").strip()
    if not request_text:
        messages.append(
            _message("error", messages_copy["refine_request_required"])
        )
        return None, None

    tenant_id = str(tenant.pk)
    current_state = workspace_repository.load_current(tenant_id, year, month)
    if current_state is None:
        messages.append(
            _message("info", messages_copy["refine_requires_current_workspace"])
        )
        return None, None

    try:
        response = refine_service.refine_month_schedule(
            RefineMonthScheduleRequest(
                tenant_slug=tenant.slug,
                year=year,
                month=month,
                request_text=request_text,
            )
        )
    except (LookupError, ValueError) as exc:
        messages.append(_message("error", str(exc)))
        return None, None

    candidate_result = (
        MonthPlanningResultSchema.model_validate(
            response.candidate_result,
            from_attributes=True,
        )
        if response.candidate_result is not None
        else None
    )
    return candidate_result, _build_refine_result_context(
        response=response,
        candidate_result=candidate_result,
        ui_lang=ui_lang,
        page_copy=page_copy,
    )


def _handle_explain(
    *,
    request: HttpRequest,
    tenant: DjangoTenant,
    year: int,
    month: int,
    ui_lang: str,
    candidate_result: MonthPlanningResultSchema | None,
    explain_service: ExplainDayScheduleService,
    messages: list[dict[str, str]],
    page_copy: dict[str, Any],
) -> dict[str, Any] | None:
    messages_copy = page_copy["messages"]
    explain_day_raw = (request.POST.get("explain_day") or "").strip()
    if not explain_day_raw:
        messages.append(
            _message("error", messages_copy["explain_day_required"])
        )
        return None

    try:
        target_date = dt.date.fromisoformat(explain_day_raw)
    except ValueError:
        messages.append(
            _message("error", messages_copy["invalid_explain_day"])
        )
        return None

    if target_date.year != year or target_date.month != month:
        messages.append(
            _message("error", messages_copy["explain_day_outside_scope"])
        )
        return None

    try:
        response = explain_service.explain_day_schedule(
            ExplainDayScheduleRequest(
                tenant_slug=tenant.slug,
                year=year,
                month=month,
                target_date=target_date,
                request_text=(request.POST.get("explain_request_text") or "").strip(),
                response_language=ui_lang,
                candidate_result=candidate_result,
            )
        )
    except (LookupError, ValueError) as exc:
        messages.append(_message("error", str(exc)))
        return None

    return _build_explain_result_context(
        response=response,
        page_copy=page_copy,
    )


def _build_workspace_context(
    *,
    request: HttpRequest,
    tenants: list[DjangoTenant],
    selected_tenant: DjangoTenant | None,
    scope: dict[str, Any],
    ui_lang: str,
    page_copy: dict[str, Any],
    candidate_result: MonthPlanningResultSchema | None,
    explain_result: dict[str, Any] | None,
    refine_result: dict[str, Any] | None,
    prefer_current_result: bool,
    dependencies: MonthlyWorkspacePageDependencies,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    month_label = format_monthly_workspace_month_label(
        scope["year"],
        scope["month"],
        ui_lang,
    )
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
    explain_day_value = request.POST.get("explain_day") or _default_leave_date(
        scope["year"],
        scope["month"],
    )
    explain_request_text = (request.POST.get("explain_request_text") or "").strip()
    refine_request_text = (request.POST.get("request_text") or "").strip()
    leave_summary_note = page_copy["leave"]["summary_note"].format(
        month_label=month_label
    )
    leave_empty_text = page_copy["leave"]["empty"].format(month_label=month_label)
    result_empty_text = page_copy["result"]["empty"].format(month_label=month_label)
    language_options = _build_language_options(
        path=request.path,
        ui_lang=ui_lang,
        month_value=scope["month_value"],
        selected_tenant_slug=selected_tenant.slug if selected_tenant is not None else None,
    )

    if selected_tenant is None:
        leave_rows: list[dict[str, str]] = []
        leave_summary: list[dict[str, str]] = []
        worker_options: list[dict[str, str]] = []
        state_cards = _build_state_cards(
            candidate_result=candidate_result,
            has_current_workspace=False,
            saved_version_count=0,
            page_copy=page_copy,
        )
        return {
            "messages": messages,
            "ui_lang": ui_lang,
            "page_copy": page_copy,
            "language_options": language_options,
            "tenant_options": tenant_options,
            "selected_tenant": None,
            "month_value": scope["month_value"],
            "month_label": month_label,
            "leave_summary_note": leave_summary_note,
            "leave_empty_text": leave_empty_text,
            "result_empty_text": result_empty_text,
            "selected_worker_id": selected_worker_id,
            "leave_date_value": _default_leave_date(scope["year"], scope["month"]),
            "worker_options": worker_options,
            "leave_rows": leave_rows,
            "leave_summary": leave_summary,
            "state_cards": state_cards,
            "display_surface": None,
            "warnings": [],
            "warnings_note": page_copy["warnings"]["empty_no_current"],
            "candidate_result_json": (
                candidate_result.model_dump_json() if candidate_result is not None else ""
            ),
            "apply_disabled": True,
            "save_disabled": True,
            "save_label_value": save_label_value,
            "explain_day_value": explain_day_value,
            "explain_request_text": explain_request_text,
            "explain_result": explain_result,
            "explain_disabled": True,
            "explain_disabled_note": page_copy["messages"]["no_tenant"],
            "refine_request_text": refine_request_text,
            "refine_result": refine_result,
            "refine_disabled": True,
            "refine_disabled_note": page_copy["messages"]["no_tenant"],
            "workflow_steps": _workflow_steps(page_copy),
        }

    tenant_id = str(selected_tenant.pk)
    workers = _order_workers_for_workspace(
        dependencies.worker_repository.list_for_tenant(tenant_id)
    )
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
        workers=workers,
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
        page_copy=page_copy,
    )

    warnings = _build_warning_rows(candidate_result, page_copy=page_copy)
    warnings_note = page_copy["warnings"]["empty_with_current"]
    explain_disabled = current_state is None and candidate_result is None
    explain_disabled_note = (
        page_copy["explain"]["requires_schedule_surface"]
        if explain_disabled
        else ""
    )
    refine_disabled = current_state is None
    refine_disabled_note = (
        page_copy["refine"]["requires_current_workspace"]
        if refine_disabled
        else ""
    )

    return {
        "messages": messages,
        "ui_lang": ui_lang,
        "page_copy": page_copy,
        "language_options": language_options,
        "tenant_options": tenant_options,
        "selected_tenant": {
            "slug": selected_tenant.slug,
            "name": selected_tenant.name,
        },
        "month_value": scope["month_value"],
        "month_label": month_label,
        "leave_summary_note": leave_summary_note,
        "leave_empty_text": leave_empty_text,
        "result_empty_text": result_empty_text,
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
            page_copy=page_copy,
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
        "explain_day_value": explain_day_value,
        "explain_request_text": explain_request_text,
        "explain_result": explain_result,
        "explain_disabled": explain_disabled,
        "explain_disabled_note": explain_disabled_note,
        "refine_request_text": refine_request_text,
        "refine_result": refine_result,
        "refine_disabled": refine_disabled,
        "refine_disabled_note": refine_disabled_note,
        "workflow_steps": _workflow_steps(page_copy),
    }


def _build_refine_result_context(
    *,
    response: RefineMonthScheduleResponse,
    candidate_result: MonthPlanningResultSchema | None,
    ui_lang: str,
    page_copy: dict[str, Any],
) -> dict[str, Any]:
    refine_copy = page_copy["refine"]
    parsed_intent_json = response.parsed_intent_json
    outcome_json = parsed_intent_json.get("outcome")
    outcome_message_values: dict[str, Any] = {}
    if isinstance(outcome_json, dict):
        message_values = outcome_json.get("message_values")
        if isinstance(message_values, dict):
            outcome_message_values = dict(message_values)
    preview_executed = bool(parsed_intent_json.get("preview_executed"))
    intent_status = str(
        parsed_intent_json.get("intent_status") or response.outcome.status
    )
    intent_type = parsed_intent_json.get("intent_type")
    canonical_intent = parsed_intent_json.get("canonical_intent")
    adjustment_patch = parsed_intent_json.get("adjustment_patch")

    meta_items = [
        {
            "label": refine_copy["request_language_label"],
            "value": _localize_refine_value(
                response.request_language,
                refine_copy["language_values"],
            ),
        },
        {
            "label": refine_copy["intent_status_label"],
            "value": _localize_refine_value(
                intent_status,
                refine_copy["intent_status_values"],
            ),
        },
        {
            "label": refine_copy["preview_executed_label"],
            "value": (
                refine_copy["boolean_yes"]
                if preview_executed
                else refine_copy["boolean_no"]
            ),
        },
        {
            "label": refine_copy["candidate_result_label"],
            "value": (
                refine_copy["boolean_yes"]
                if candidate_result is not None
                else refine_copy["boolean_no"]
            ),
        },
    ]
    if isinstance(intent_type, str) and intent_type:
        meta_items.insert(
            2,
            {
                "label": refine_copy["intent_type_label"],
                "value": _localize_refine_value(
                    intent_type,
                    refine_copy["intent_type_values"],
                ),
            },
        )
    reason_code = outcome_message_values.get("reason_code")
    if isinstance(reason_code, str) and reason_code:
        meta_items.append(
            {
                "label": refine_copy["reason_label"],
                "value": _localize_refine_value(
                    reason_code,
                    refine_copy["reason_values"],
                ),
            }
        )

    return {
        "message_tone": _refine_result_message_tone(response.outcome.status),
        "message_text": _render_page_refine_outcome(
            response=response,
            ui_lang=ui_lang,
        ),
        "meta": meta_items,
        "canonical_items": _build_refine_canonical_items(
            canonical_intent=canonical_intent,
            page_copy=page_copy,
        ),
        "adjustment_items": _build_refine_adjustment_items(
            adjustment_patch=adjustment_patch,
            page_copy=page_copy,
        ),
        "candidate_note": (
            refine_copy["candidate_ready_note"]
            if candidate_result is not None
            else refine_copy["candidate_missing_note"]
        ),
    }


def _render_page_refine_outcome(
    *,
    response: RefineMonthScheduleResponse,
    ui_lang: str,
) -> str:
    if response.outcome.language in {"zh", "ja"}:
        return render_refine_outcome(response.outcome)
    return render_refine_outcome(
        replace(
            response.outcome,
            language=ui_lang,
        )
    )


def _refine_result_message_tone(status: str) -> str:
    if status == "preview_ready":
        return "message-success"
    if status == "ambiguous":
        return "message-info"
    return "message-error"


def _build_explain_result_context(
    *,
    response: ExplainDayScheduleResponse,
    page_copy: dict[str, Any],
) -> dict[str, Any]:
    explain_copy = page_copy["explain"]
    parsed_request_json = response.parsed_request_json
    intent_status = str(
        parsed_request_json.get("intent_status") or response.status
    )
    request_category = parsed_request_json.get("request_category")
    source_mode = (
        parsed_request_json.get("source_mode")
        or response.context_facts.get("source_mode")
    )
    model_used = bool(parsed_request_json.get("model_used"))
    fallback_used = bool(parsed_request_json.get("fallback_used"))

    meta_items = [
        {
            "label": explain_copy["request_language_label"],
            "value": _localize_refine_value(
                response.request_language,
                explain_copy["language_values"],
            ),
        },
        {
            "label": explain_copy["response_language_label"],
            "value": _localize_refine_value(
                response.response_language,
                explain_copy["language_values"],
            ),
        },
        {
            "label": explain_copy["intent_status_label"],
            "value": _localize_refine_value(
                intent_status,
                explain_copy["intent_status_values"],
            ),
        },
    ]
    if isinstance(request_category, str) and request_category:
        meta_items.append(
            {
                "label": explain_copy["category_label"],
                "value": _localize_refine_value(
                    request_category,
                    explain_copy["category_values"],
                ),
            }
        )
    if isinstance(source_mode, str) and source_mode:
        meta_items.append(
            {
                "label": explain_copy["source_mode_label"],
                "value": _localize_refine_value(
                    source_mode,
                    explain_copy["source_mode_values"],
                ),
            }
        )
    meta_items.extend(
        [
            {
                "label": explain_copy["model_used_label"],
                "value": (
                    explain_copy["boolean_yes"]
                    if model_used
                    else explain_copy["boolean_no"]
                ),
            },
            {
                "label": explain_copy["fallback_used_label"],
                "value": (
                    explain_copy["boolean_yes"]
                    if fallback_used
                    else explain_copy["boolean_no"]
                ),
            },
        ]
    )

    return {
        "message_tone": _explain_result_message_tone(response.status),
        "message_text": render_explain_outcome(response.outcome),
        "headline": (
            build_day_explanation_headline(
                language=response.response_language,
                request_category=str(request_category or "day_overview"),
                context_facts=response.context_facts,
            )
            if response.explanation is not None
            else ""
        ),
        "meta": meta_items,
        "sections": (
            [
                {
                    "title": section.title,
                    "items": list(section.items),
                }
                for section in response.explanation.sections
            ]
            if response.explanation is not None
            else []
        ),
    }


def _explain_result_message_tone(status: str) -> str:
    if status == "ready":
        return "message-success"
    if status == "ambiguous":
        return "message-info"
    return "message-error"


def _build_refine_canonical_items(
    *,
    canonical_intent: object,
    page_copy: dict[str, Any],
) -> list[dict[str, str]]:
    if not isinstance(canonical_intent, dict):
        return []

    field_labels = page_copy["refine"]["field_labels"]
    items: list[dict[str, str]] = []
    for field_name in ("date", "worker_code", "shift_code", "station_code"):
        value = canonical_intent.get(field_name)
        if value in (None, ""):
            continue
        items.append(
            {
                "label": field_labels.get(field_name, field_name),
                "value": str(value),
            }
        )
    return items


def _build_refine_adjustment_items(
    *,
    adjustment_patch: object,
    page_copy: dict[str, Any],
) -> list[dict[str, str]]:
    if not isinstance(adjustment_patch, list):
        return []

    refine_copy = page_copy["refine"]
    field_labels = refine_copy["field_labels"]
    items: list[dict[str, str]] = []
    for patch in adjustment_patch:
        if not isinstance(patch, dict):
            continue
        operation = str(patch.get("operation") or "")
        summary_parts: list[str] = []
        for field_name in ("date", "worker_code", "shift_code", "station_code"):
            value = patch.get(field_name)
            if value in (None, ""):
                continue
            summary_parts.append(
                f"{field_labels.get(field_name, field_name)}: {value}"
            )
        items.append(
            {
                "title": _localize_refine_value(
                    operation,
                    refine_copy["operation_values"],
                ),
                "summary": " / ".join(summary_parts),
            }
        )
    return items


def _localize_refine_value(
    value: str,
    mapping: dict[str, str],
) -> str:
    localized = mapping.get(value)
    if localized:
        return localized
    return value


def _workflow_steps(page_copy: dict[str, Any]) -> list[str]:
    return list(page_copy["workflow_steps"])


def _build_language_options(
    *,
    path: str,
    ui_lang: str,
    month_value: str,
    selected_tenant_slug: str | None,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for language_code, label in MONTHLY_WORKSPACE_UI_LANGUAGE_LABELS.items():
        query_params = {
            "month_scope": month_value,
            "ui_lang": language_code,
        }
        if selected_tenant_slug:
            query_params["tenant_slug"] = selected_tenant_slug
        options.append(
            {
                "value": language_code,
                "label": label,
                "href": f"{path}?{urlencode(query_params)}",
                "selected": language_code == ui_lang,
            }
        )
    return options


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
    workers: list[Worker],
) -> list[dict[str, str]]:
    worker_order = _worker_order_lookup(workers)
    rows: list[dict[str, str]] = []
    leave_requests = (
        DjangoLeaveRequest.objects.filter(
            tenant=tenant,
            leave_date__year=year,
            leave_date__month=month,
        )
        .select_related("worker")
        .order_by("id")
    )
    sorted_leave_requests = sorted(
        leave_requests,
        key=lambda row: (
            worker_order.get(str(row.worker_id), len(worker_order)),
            row.leave_date,
            row.id,
        ),
    )
    for row in sorted_leave_requests:
        rows.append(
            {
                "worker_id": str(row.worker_id),
                "worker_name": row.worker.name,
                "worker_code": row.worker.code,
                "date": row.leave_date.isoformat(),
            }
        )
    return rows


def _build_leave_summary(leave_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    counts: Counter[str] = Counter()
    ordered_labels: list[str] = []
    seen_labels: set[str] = set()
    for row in leave_rows:
        label = f"{row['worker_name']} ({row['worker_code']})"
        counts[label] += 1
        if label not in seen_labels:
            ordered_labels.append(label)
            seen_labels.add(label)
    return [{"label": label, "count": str(counts[label])} for label in ordered_labels]


def _build_state_cards(
    *,
    candidate_result: MonthPlanningResultSchema | None,
    has_current_workspace: bool,
    saved_version_count: int,
    page_copy: dict[str, Any],
) -> list[dict[str, str]]:
    card_copy = page_copy["state_cards"]
    evaluation_label = card_copy["none"]
    evaluation_note = card_copy["evaluation_note"]
    evaluation_tone = "tone-neutral"
    if candidate_result is not None and candidate_result.evaluation is not None:
        evaluation_label = candidate_result.evaluation.schedule_quality_label
        evaluation_note = card_copy["evaluation_visible_note"]
        evaluation_tone = _evaluation_tone(evaluation_label)

    return [
        {
            "label": card_copy["candidate_preview_label"],
            "value": (
                card_copy["present"]
                if candidate_result is not None
                else card_copy["none"]
            ),
            "note": card_copy["candidate_preview_note"],
            "tone": "tone-good" if candidate_result is not None else "tone-neutral",
        },
        {
            "label": card_copy["current_workspace_label"],
            "value": (
                card_copy["present"] if has_current_workspace else card_copy["none"]
            ),
            "note": card_copy["current_workspace_note"],
            "tone": "tone-good" if has_current_workspace else "tone-neutral",
        },
        {
            "label": card_copy["saved_versions_label"],
            "value": str(saved_version_count),
            "note": card_copy["saved_versions_note"],
            "tone": "tone-neutral",
        },
        {
            "label": card_copy["evaluation_label"],
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
    page_copy: dict[str, Any],
) -> dict[str, Any] | None:
    if prefer_current_result and current_state is not None:
        return _build_current_workspace_surface(
            current_state=current_state,
            workers=workers,
            shifts=shifts,
            stations=stations,
            year=year,
            month=month,
            page_copy=page_copy,
        )
    if candidate_result is not None:
        return _build_candidate_surface(
            candidate_result=candidate_result,
            workers=workers,
            year=year,
            month=month,
            page_copy=page_copy,
        )
    if current_state is not None:
        return _build_current_workspace_surface(
            current_state=current_state,
            workers=workers,
            shifts=shifts,
            stations=stations,
            year=year,
            month=month,
            page_copy=page_copy,
        )
    return None


def _build_candidate_surface(
    *,
    candidate_result: MonthPlanningResultSchema,
    workers: list[Worker],
    year: int,
    month: int,
    page_copy: dict[str, Any],
) -> dict[str, Any]:
    display_copy = page_copy["display"]
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
        "badge": display_copy["candidate_badge"],
        "description": display_copy["candidate_description"],
        "meta": [
            {"label": display_copy["source_label"], "value": candidate_result.metadata.source_type},
            {
                "label": display_copy["assignments_label"],
                "value": str(candidate_result.summary.total_assignments),
            },
            {
                "label": display_copy["warnings_label"],
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
    page_copy: dict[str, Any],
) -> dict[str, Any]:
    display_copy = page_copy["display"]
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
                "note": assignment.note,
            }
        )

    return {
        "badge": display_copy["current_badge"],
        "description": display_copy["current_description"],
        "meta": [
            {"label": display_copy["status_label"], "value": current_state.workspace.status},
            {
                "label": display_copy["assignments_label"],
                "value": str(len(current_state.assignments)),
            },
            {"label": display_copy["month_label"], "value": f"{year:04d}-{month:02d}"},
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
        main_value = _build_cell_main_value(
            assignment.get("shift_code"),
            assignment.get("note"),
        )
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
    note_text = str(note) if note else ""
    if note_text == _REQUIRED_CHEF_NOTE:
        return "chef attendance"

    parts: list[str] = []
    if station_code:
        parts.append(str(station_code))
    if note_text:
        parts.append(note_text)
    return " / ".join(parts)


def _build_cell_main_value(
    shift_code: object | None,
    note: object | None,
) -> str:
    if note == _REQUIRED_CHEF_NOTE:
        return "WORK"
    return str(shift_code)


def _order_workers_for_workspace(workers: list[Worker]) -> list[Worker]:
    return sorted(
        workers,
        key=lambda worker: (
            0 if _is_chef_role(worker.role) else 1,
            _record_sort_key(worker.id),
        ),
    )


def _worker_order_lookup(workers: list[Worker]) -> dict[str, int]:
    return {
        worker_id: index
        for index, worker in enumerate(workers)
        if (worker_id := worker.id) is not None
    }


def _record_sort_key(record_id: str | None) -> tuple[int, int | str]:
    if record_id and record_id.isdigit():
        return (0, int(record_id))
    return (1, record_id or "")


def _is_chef_role(role: str) -> bool:
    return role.strip().casefold() == "chef"


def _build_day_headers(year: int, month: int) -> list[int]:
    day_count = calendar.monthrange(year, month)[1]
    return list(range(1, day_count + 1))


def _build_warning_rows(
    candidate_result: MonthPlanningResultSchema | None,
    *,
    page_copy: dict[str, Any],
) -> list[dict[str, str]]:
    if candidate_result is None:
        return []

    warning_copy = page_copy["warnings"]
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
                "date": (
                    warning.date.isoformat()
                    if warning.date is not None
                    else warning_copy["month_value"]
                ),
                "worker": warning.worker_code or warning_copy["system_value"],
                "details": details_text or warning_copy["no_details"],
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
