"""Bounded day-level scheduling explanation orchestration.

This service is intentionally read-only:
- explains one selected day only
- stays grounded in current schedule context
- may use a model only after deterministic request gating
- never mutates the workspace
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.engine.contracts import MonthPlanningInput, MonthPlanningResult
from app.infra.models import JsonObject, RecordId
from app.infra.repositories import (
    ConstraintConfigRepository,
    CurrentWorkspaceState,
    LeaveRequestRepository,
    ShiftRepository,
    StationRepository,
    TenantRepository,
    WorkerRepository,
    WorkspaceRepository,
)
from app.services.monthly_context import (
    build_month_planning_input,
    load_monthly_planning_bundle,
)

EXPLAIN_STATUS_READY = "ready"
EXPLAIN_STATUS_UNSUPPORTED = "unsupported"
EXPLAIN_STATUS_AMBIGUOUS = "ambiguous"

_FALLBACK_STATION_NOTE = "fallback_station_skill_mismatch"
_REQUIRED_CHEF_NOTE = "required_chef"
_REFINE_PREVIEW_NOTE = "langgraph_refine_preview"

_EXPLAIN_OUTCOME_TEMPLATES: dict[str, dict[str, str]] = {
    "zh": {
        "explain_ready": "已生成当日排班说明。",
        "explain_unsupported_request": "这里只支持排班相关的当日说明请求。",
        "explain_out_of_context_date": "请求必须与所选日期和当前排班上下文一致。",
        "explain_unknown_worker": "无法在当前排班上下文中安全识别该员工。",
        "explain_candidate_required": "当前没有可比较的候选预览。",
        "explain_no_schedule_surface": "当前没有可说明的排班结果。",
    },
    "ja": {
        "explain_ready": "この日の説明を生成しました。",
        "explain_unsupported_request": "この画面では排班関連の日別説明のみ対応しています。",
        "explain_out_of_context_date": "依頼内容は選択した日付と現在の排班文脈に一致している必要があります。",
        "explain_unknown_worker": "現在の排班文脈ではその担当者を安全に特定できませんでした。",
        "explain_candidate_required": "比較できる候補プレビューがありません。",
        "explain_no_schedule_surface": "説明に使える排班結果がありません。",
    },
    "en": {
        "explain_ready": "Day-level schedule explanation generated.",
        "explain_unsupported_request": (
            "Only scheduling-related day explanation requests are supported here."
        ),
        "explain_out_of_context_date": (
            "The request must match the selected day and current schedule context."
        ),
        "explain_unknown_worker": (
            "The worker could not be safely resolved from the current schedule context."
        ),
        "explain_candidate_required": "No candidate preview is available to compare.",
        "explain_no_schedule_surface": "There is no schedule surface available to explain.",
    },
    "unknown": {
        "explain_ready": "Day-level schedule explanation generated.",
        "explain_unsupported_request": (
            "Only scheduling-related day explanation requests are supported here."
        ),
        "explain_out_of_context_date": (
            "The request must match the selected day and current schedule context."
        ),
        "explain_unknown_worker": (
            "The worker could not be safely resolved from the current schedule context."
        ),
        "explain_candidate_required": "No candidate preview is available to compare.",
        "explain_no_schedule_surface": "There is no schedule surface available to explain.",
    },
}

_EXPLAIN_RENDER_COPY: dict[str, dict[str, Any]] = {
    "zh": {
        "headline_day": "{target_date} 的排班说明",
        "headline_worker": "{target_date} 的 {worker_name} 排班说明",
        "sections": {
            "assignments": "排班摘要",
            "warnings": "警告摘要",
            "fallback": "Fallback 摘要",
            "constraints": "相关约束",
            "changes": "预览变化",
        },
        "day_kinds": {"weekday": "工作日", "weekend": "周末"},
        "availability": {
            "leave": "当天已有请假记录。",
            "fixed_day_off": "当天属于固定休息日。",
            "ad_hoc_unavailable": "当天被标记为临时不可排班。",
            "wish_off_hard": "当天有强约束休假偏好。",
            "wish_off_soft": "当天有软性休假偏好。",
        },
        "warning_labels": {
            "understaffed_station_day": "岗位人手不足",
            "missing_required_chef": "缺少必需厨师",
            "missing_morning_station_coverage": "早班岗位覆盖不足",
            "worker_below_min_days_off": "员工休息天数不足",
            "duplicate_assignment_conflict": "重复排班冲突",
            "worker_unavailable_conflict": "员工不可排班冲突",
        },
        "notes": {
            "no_assignments": "当天没有排班记录。",
            "no_preview_warnings": "当天没有候选预览警告。",
            "current_warning_gap": "当前工作区不会持久化日警告；这里只能基于已显示排班说明。",
            "no_fallback": "当天没有 fallback 排班。",
            "required_chef": "当天包含必需厨师覆盖记录。",
            "no_change": "所选日期在候选预览与当前工作区之间没有排班变化。",
            "not_assigned": "{worker_name} ({worker_code}) 在这一天未被排班。",
            "assigned": "{worker_name} ({worker_code}) 已排班：{assignment}.",
            "no_blocking_reason": "当前上下文中没有记录到阻止该员工排班的硬性原因。",
            "skills_overlap": "{worker_name} 的岗位技能与当天岗位有重叠：{station_codes}。",
            "skills_no_overlap": "{worker_name} 的岗位技能与当天岗位没有重叠。",
            "min_staff": "{day_kind} 最低人数目标：{min_staff_target}。",
            "stations": "岗位最低覆盖：{stations}.",
            "max_staff": "单日最多排班人数：{max_staff_per_day}。",
            "max_consecutive_days": "最长连续排班天数限制：{max_consecutive_days}。",
            "min_rest_days_per_month": "每月最少休息天数：{min_rest_days_per_month}。",
            "require_one_chef": "该月启用了每日至少一名厨师约束。",
            "fallback_assignment": "{worker_name} ({worker_code}) 以 fallback 方式覆盖 {station_code}。",
            "required_chef_assignment": "{worker_name} ({worker_code}) 负责必需厨师覆盖。",
            "warning": "{warning_label}：{details}",
            "warning_no_details": "{warning_label}。",
            "change_added": "新增：{assignment}",
            "change_removed": "移除：{assignment}",
            "change_changed": "{worker_name} ({worker_code})：{current} -> {candidate}",
        },
    },
    "ja": {
        "headline_day": "{target_date} の日別説明",
        "headline_worker": "{target_date} の {worker_name} の説明",
        "sections": {
            "assignments": "割り当て概要",
            "warnings": "警告概要",
            "fallback": "フォールバック概要",
            "constraints": "関連制約",
            "changes": "プレビュー差分",
        },
        "day_kinds": {"weekday": "平日", "weekend": "週末"},
        "availability": {
            "leave": "この日は休暇登録があります。",
            "fixed_day_off": "この日は固定休です。",
            "ad_hoc_unavailable": "この日は臨時不可日です。",
            "wish_off_hard": "この日は強い休み希望があります。",
            "wish_off_soft": "この日は柔らかい休み希望があります。",
        },
        "warning_labels": {
            "understaffed_station_day": "持ち場の人員不足",
            "missing_required_chef": "必須シェフ不足",
            "missing_morning_station_coverage": "朝番カバー不足",
            "worker_below_min_days_off": "休日日数不足",
            "duplicate_assignment_conflict": "重複割り当て衝突",
            "worker_unavailable_conflict": "担当者不可日衝突",
        },
        "notes": {
            "no_assignments": "この日の割り当てはありません。",
            "no_preview_warnings": "この日の候補プレビュー警告はありません。",
            "current_warning_gap": "現在ワークスペースの日別警告は保持されないため、表示中の排班事実のみで説明します。",
            "no_fallback": "この日にフォールバック割り当てはありません。",
            "required_chef": "この日には必須シェフのカバー記録があります。",
            "no_change": "選択日の候補プレビューと現在ワークスペースの間に割り当て差分はありません。",
            "not_assigned": "{worker_name} ({worker_code}) はこの日に割り当てられていません。",
            "assigned": "{worker_name} ({worker_code}) は {assignment} に割り当てられています。",
            "no_blocking_reason": "現在の文脈では、この担当者を止める強い不可理由は見つかっていません。",
            "skills_overlap": "{worker_name} のスキルは当日の持ち場と重なっています: {station_codes}。",
            "skills_no_overlap": "{worker_name} のスキルは当日の持ち場と重なっていません。",
            "min_staff": "{day_kind} の最低人数目標は {min_staff_target} です。",
            "stations": "持ち場の最低カバー: {stations}。",
            "max_staff": "1日の最大人数は {max_staff_per_day} です。",
            "max_consecutive_days": "連続勤務上限は {max_consecutive_days} 日です。",
            "min_rest_days_per_month": "月間の最低休日日数は {min_rest_days_per_month} 日です。",
            "require_one_chef": "この月は毎日シェフ1名必須の制約があります。",
            "fallback_assignment": "{worker_name} ({worker_code}) は {station_code} をフォールバックで担当しています。",
            "required_chef_assignment": "{worker_name} ({worker_code}) は必須シェフ枠を担当しています。",
            "warning": "{warning_label}: {details}",
            "warning_no_details": "{warning_label}。",
            "change_added": "追加: {assignment}",
            "change_removed": "削除: {assignment}",
            "change_changed": "{worker_name} ({worker_code}): {current} -> {candidate}",
        },
    },
    "en": {
        "headline_day": "Schedule explanation for {target_date}",
        "headline_worker": "Schedule explanation for {worker_name} on {target_date}",
        "sections": {
            "assignments": "Assignments",
            "warnings": "Warnings",
            "fallback": "Fallback",
            "constraints": "Constraints",
            "changes": "Preview changes",
        },
        "day_kinds": {"weekday": "weekday", "weekend": "weekend"},
        "availability": {
            "leave": "The worker has approved leave on this day.",
            "fixed_day_off": "The day is a fixed day off.",
            "ad_hoc_unavailable": "The worker is marked unavailable for this day.",
            "wish_off_hard": "The worker has a hard wish-off for this day.",
            "wish_off_soft": "The worker has a soft wish-off for this day.",
        },
        "warning_labels": {
            "understaffed_station_day": "Station understaffed",
            "missing_required_chef": "Required chef missing",
            "missing_morning_station_coverage": "Morning coverage missing",
            "worker_below_min_days_off": "Minimum days off warning",
            "duplicate_assignment_conflict": "Duplicate assignment conflict",
            "worker_unavailable_conflict": "Worker unavailable conflict",
        },
        "notes": {
            "no_assignments": "No assignments are scheduled for this day.",
            "no_preview_warnings": "No candidate-preview warnings exist for this day.",
            "current_warning_gap": (
                "Current-workspace day warnings are not persisted, so this explanation is based on the visible schedule facts only."
            ),
            "no_fallback": "No fallback assignment was used on this day.",
            "required_chef": "This day includes required-chef coverage.",
            "no_change": "There is no assignment change between the candidate preview and current workspace for this day.",
            "not_assigned": "{worker_name} ({worker_code}) is not assigned on this day.",
            "assigned": "{worker_name} ({worker_code}) is assigned to {assignment}.",
            "no_blocking_reason": "No blocking hard-availability reason is recorded for this worker in the current context.",
            "skills_overlap": "{worker_name} has overlapping station skills for this day: {station_codes}.",
            "skills_no_overlap": "{worker_name} does not match the scheduled station skills for this day.",
            "min_staff": "The {day_kind} minimum staffing target is {min_staff_target}.",
            "stations": "Station minimums: {stations}.",
            "max_staff": "The daily max staff limit is {max_staff_per_day}.",
            "max_consecutive_days": "The max consecutive days limit is {max_consecutive_days}.",
            "min_rest_days_per_month": "The monthly minimum rest-days target is {min_rest_days_per_month}.",
            "require_one_chef": "The month requires at least one chef each day.",
            "fallback_assignment": "{worker_name} ({worker_code}) covered {station_code} via fallback.",
            "required_chef_assignment": "{worker_name} ({worker_code}) covers the required-chef slot.",
            "warning": "{warning_label}: {details}",
            "warning_no_details": "{warning_label}.",
            "change_added": "Added: {assignment}",
            "change_removed": "Removed: {assignment}",
            "change_changed": "{worker_name} ({worker_code}): {current} -> {candidate}",
        },
    },
}

_WARNING_DETAIL_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "station_code": "岗位",
        "required_staff": "需要人数",
        "assigned_staff": "已排人数",
        "missing_staff": "缺口",
        "required_role": "必需角色",
        "minimum_days_off": "最少休息天数",
        "actual_days_off": "实际休息天数",
        "operation": "操作",
        "assignment_count": "排班数",
        "shift_code": "班次",
    },
    "ja": {
        "station_code": "持ち場",
        "required_staff": "必要人数",
        "assigned_staff": "割当人数",
        "missing_staff": "不足人数",
        "required_role": "必須役割",
        "minimum_days_off": "最低休日日数",
        "actual_days_off": "実際の休日日数",
        "operation": "操作",
        "assignment_count": "割当数",
        "shift_code": "シフト",
    },
    "en": {
        "station_code": "station",
        "required_staff": "required",
        "assigned_staff": "assigned",
        "missing_staff": "missing",
        "required_role": "required role",
        "minimum_days_off": "minimum days off",
        "actual_days_off": "actual days off",
        "operation": "operation",
        "assignment_count": "assignment count",
        "shift_code": "shift",
    },
}


class DayExplainWorkflow(Protocol):
    """Bounded workflow boundary for day-level explain requests."""

    def __call__(
        self,
        request: "DayExplainWorkflowRequest",
    ) -> "DayExplainWorkflowResult":
        ...


@dataclass(slots=True)
class ExplainOutcome:
    """Structured bounded outcome that can be rendered per language."""

    language: str
    status: str
    message_key: str
    message_values: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class ExplainSection:
    """One bounded explanation section."""

    key: str
    title: str
    items: list[str]


@dataclass(slots=True)
class DayExplainNarrative:
    """Stable rendered explanation payload."""

    headline: str
    sections: list[ExplainSection]
    model_used: bool
    fallback_used: bool


@dataclass(slots=True)
class DayExplainWorkflowRequest:
    """Context passed to the explain workflow boundary."""

    tenant_slug: str
    year: int
    month: int
    target_date: dt.date
    request_text: str
    response_language_hint: str | None
    planning_input: MonthPlanningInput
    current_state: CurrentWorkspaceState | None
    candidate_result: MonthPlanningResult | None
    workers: list[Any]
    stations: list[Any]
    shifts: list[Any]


@dataclass(slots=True)
class DayExplainWorkflowResult:
    """Structured workflow result consumed by the explain service."""

    request_language: str
    response_language: str
    outcome: ExplainOutcome
    parsed_request_json: JsonObject
    context_facts: JsonObject
    explanation: DayExplainNarrative | None


@dataclass(slots=True)
class ExplainDayScheduleRequest:
    """Service-layer request for one day-level schedule explanation."""

    tenant_slug: str
    year: int
    month: int
    target_date: dt.date
    request_text: str | None = None
    response_language: str | None = None
    candidate_result: MonthPlanningResult | None = None


@dataclass(slots=True)
class ExplainDayScheduleResponse:
    """Bounded day-level explain response."""

    tenant_slug: str
    year: int
    month: int
    target_date: dt.date
    workspace_id: RecordId | None
    status: str
    request_language: str
    response_language: str
    outcome: ExplainOutcome
    parsed_request_json: JsonObject
    context_facts: JsonObject
    explanation: DayExplainNarrative | None


@dataclass(slots=True)
class ExplainDayScheduleService:
    """Load explain context and delegate bounded day-level explanation flow."""

    tenant_repository: TenantRepository
    worker_repository: WorkerRepository
    station_repository: StationRepository
    shift_repository: ShiftRepository
    leave_request_repository: LeaveRequestRepository
    constraint_config_repository: ConstraintConfigRepository
    workspace_repository: WorkspaceRepository
    workflow: DayExplainWorkflow

    def explain_day_schedule(
        self,
        request: ExplainDayScheduleRequest,
    ) -> ExplainDayScheduleResponse:
        """Explain one selected day using current scheduling context only."""

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
        if current_state is None and request.candidate_result is None:
            raise LookupError("No current workspace or candidate preview found.")

        bundle = load_monthly_planning_bundle(
            tenant=tenant,
            year=request.year,
            month=request.month,
            worker_repository=self.worker_repository,
            station_repository=self.station_repository,
            shift_repository=self.shift_repository,
            leave_request_repository=self.leave_request_repository,
            constraint_config_repository=self.constraint_config_repository,
        )
        if request.candidate_result is not None:
            _validate_candidate_result_scope(
                request.candidate_result,
                workers=bundle.workers,
                stations=bundle.stations,
                shifts=bundle.shifts,
            )
        planning_input = build_month_planning_input(bundle)

        workflow_result = self.workflow(
            DayExplainWorkflowRequest(
                tenant_slug=tenant.slug,
                year=request.year,
                month=request.month,
                target_date=request.target_date,
                request_text=(request.request_text or "").strip(),
                response_language_hint=request.response_language,
                planning_input=planning_input,
                current_state=current_state,
                candidate_result=request.candidate_result,
                workers=bundle.workers,
                stations=bundle.stations,
                shifts=bundle.shifts,
            )
        )

        return ExplainDayScheduleResponse(
            tenant_slug=tenant.slug,
            year=request.year,
            month=request.month,
            target_date=request.target_date,
            workspace_id=(
                _require_record_id(current_state.workspace.id, label="workspace.id")
                if current_state is not None and current_state.workspace.id is not None
                else None
            ),
            status=workflow_result.outcome.status,
            request_language=workflow_result.request_language,
            response_language=workflow_result.response_language,
            outcome=workflow_result.outcome,
            parsed_request_json=dict(workflow_result.parsed_request_json),
            context_facts=dict(workflow_result.context_facts),
            explanation=workflow_result.explanation,
        )

def explain_day_schedule(
    request: ExplainDayScheduleRequest,
    *,
    service: ExplainDayScheduleService,
) -> ExplainDayScheduleResponse:
    """Thin functional wrapper around the day explain service."""

    return service.explain_day_schedule(request)


def _validate_candidate_result_scope(
    candidate_result: MonthPlanningResult,
    *,
    workers: list[Any],
    stations: list[Any],
    shifts: list[Any],
) -> None:
    """Reject candidate previews that reference records outside tenant scope."""

    allowed_worker_codes = {
        _resolve_worker_scope_code(worker)
        for worker in workers
    }
    allowed_station_codes = {
        _resolve_station_scope_code(station)
        for station in stations
    }
    allowed_shift_codes = {
        str(shift.code)
        for shift in shifts
        if getattr(shift, "code", None)
    }

    for assignment in candidate_result.assignments:
        if assignment.worker_code not in allowed_worker_codes:
            raise LookupError(
                "Candidate preview references a worker outside the selected tenant scope."
            )
        if assignment.shift_code not in allowed_shift_codes:
            raise LookupError(
                "Candidate preview references a shift outside the selected tenant scope."
            )
        if (
            assignment.station_code is not None
            and assignment.station_code not in allowed_station_codes
        ):
            raise LookupError(
                "Candidate preview references a station outside the selected tenant scope."
            )

    for warning in candidate_result.warnings:
        if (
            warning.worker_code is not None
            and warning.worker_code not in allowed_worker_codes
        ):
            raise LookupError(
                "Candidate preview warning references a worker outside the selected tenant scope."
            )
        station_code = (
            warning.details.get("station_code")
            if isinstance(warning.details, dict)
            else None
        )
        if (
            station_code is not None
            and str(station_code) not in allowed_station_codes
        ):
            raise LookupError(
                "Candidate preview warning references a station outside the selected tenant scope."
            )


def _resolve_worker_scope_code(worker: Any) -> str:
    """Choose the stable worker identifier used by tenant-bound explain validation."""

    worker_code = getattr(worker, "code", None) or getattr(worker, "worker_code", None)
    if worker_code:
        return str(worker_code)
    worker_id = getattr(worker, "id", None)
    if worker_id:
        return str(worker_id)
    raise ValueError("Explain worker scope validation requires a worker code or id.")


def _resolve_station_scope_code(station: Any) -> str:
    """Choose the stable station identifier used by tenant-bound explain validation."""

    station_code = getattr(station, "code", None) or getattr(
        station,
        "station_code",
        None,
    )
    if station_code:
        return str(station_code)
    station_id = getattr(station, "id", None)
    if station_id:
        return str(station_id)
    raise ValueError("Explain station scope validation requires a station code or id.")


def render_explain_outcome(outcome: ExplainOutcome) -> str:
    """Render one bounded explain outcome message in the response language."""

    templates = _EXPLAIN_OUTCOME_TEMPLATES.get(
        outcome.language,
        _EXPLAIN_OUTCOME_TEMPLATES["unknown"],
    )
    template = templates.get(
        outcome.message_key,
        _EXPLAIN_OUTCOME_TEMPLATES["unknown"]["explain_unsupported_request"],
    )
    return template.format(**{key: str(value) for key, value in outcome.message_values.items()})


def build_day_explanation_headline(
    *,
    language: str,
    request_category: str,
    context_facts: JsonObject,
) -> str:
    """Build the canonical day-explain headline for stable UI rendering."""

    resolved_language = _resolve_render_language(language)
    copy = _EXPLAIN_RENDER_COPY[resolved_language]
    requested_worker = context_facts.get("requested_worker")
    worker_name = (
        str(requested_worker.get("worker_name"))
        if isinstance(requested_worker, dict) and requested_worker.get("worker_name")
        else None
    )
    headline_template = (
        copy["headline_worker"]
        if request_category == "worker_assignment_check" and worker_name
        else copy["headline_day"]
    )
    return headline_template.format(
        target_date=context_facts["target_date"],
        worker_name=worker_name or "",
    ).strip()


def build_day_explain_context(
    *,
    target_date: dt.date,
    request_category: str,
    request_worker_code: str | None,
    planning_input: MonthPlanningInput,
    current_state: CurrentWorkspaceState | None,
    candidate_result: MonthPlanningResult | None,
    workers: list[Any],
    stations: list[Any],
    shifts: list[Any],
) -> JsonObject:
    """Build the structured scheduling facts used by explain generation."""

    planning_workers_by_code = {
        worker.worker_code: worker
        for worker in planning_input.workers
    }
    worker_names_by_code = {
        worker.worker_code: worker.name
        for worker in planning_input.workers
    }
    worker_roles_by_code = {
        worker.worker_code: worker.role
        for worker in planning_input.workers
    }
    current_day_assignments = _build_current_day_assignments(
        target_date=target_date,
        current_state=current_state,
        workers=workers,
        stations=stations,
        shifts=shifts,
    )
    candidate_day_assignments = _build_candidate_day_assignments(
        target_date=target_date,
        candidate_result=candidate_result,
        worker_names_by_code=worker_names_by_code,
        worker_roles_by_code=worker_roles_by_code,
    )
    selected_source_mode = (
        "candidate_preview"
        if candidate_result is not None
        else "current_workspace"
    )
    selected_day_assignments = (
        candidate_day_assignments
        if selected_source_mode == "candidate_preview"
        else current_day_assignments
    )
    candidate_day_warnings = _build_candidate_day_warnings(
        target_date=target_date,
        candidate_result=candidate_result,
    )
    selected_station_codes = sorted(
        {
            str(assignment["station_code"])
            for assignment in selected_day_assignments
            if assignment.get("station_code")
        }
    )

    context_facts: JsonObject = {
        "target_date": target_date.isoformat(),
        "request_category": request_category,
        "source_mode": selected_source_mode,
        "source_metadata": {
            "candidate_present": candidate_result is not None,
            "current_workspace_present": current_state is not None,
            "candidate_refinement_applied": (
                candidate_result.metadata.refinement_applied
                if candidate_result is not None
                else None
            ),
            "candidate_source_type": (
                candidate_result.metadata.source_type
                if candidate_result is not None
                else None
            ),
        },
        "assignments": selected_day_assignments,
        "assignment_count": len(selected_day_assignments),
        "warnings": candidate_day_warnings if candidate_result is not None else [],
        "warning_count": len(candidate_day_warnings)
        if candidate_result is not None
        else 0,
        "warning_availability": {
            "available": candidate_result is not None,
            "source": "candidate_preview" if candidate_result is not None else None,
        },
        "fallback_assignments": [
            assignment
            for assignment in selected_day_assignments
            if assignment.get("note") == _FALLBACK_STATION_NOTE
        ],
        "required_chef_assignments": [
            assignment
            for assignment in selected_day_assignments
            if assignment.get("note") == _REQUIRED_CHEF_NOTE
        ],
        "constraints": _build_constraints_context(
            target_date=target_date,
            planning_input=planning_input,
        ),
        "comparison": _build_day_comparison(
            current_day_assignments=current_day_assignments,
            candidate_day_assignments=candidate_day_assignments,
        ),
        "requested_worker": _build_requested_worker_context(
            request_worker_code=request_worker_code,
            target_date=target_date,
            planning_input=planning_input,
            selected_day_assignments=selected_day_assignments,
            selected_station_codes=selected_station_codes,
            worker_names_by_code=worker_names_by_code,
            worker_roles_by_code=worker_roles_by_code,
            planning_workers_by_code=planning_workers_by_code,
        ),
        "day_station_codes": selected_station_codes,
    }
    return context_facts


def render_day_explanation_fallback(
    *,
    language: str,
    request_category: str,
    context_facts: JsonObject,
) -> DayExplainNarrative:
    """Render a deterministic bounded explanation from structured day facts."""

    resolved_language = _resolve_render_language(language)
    copy = _EXPLAIN_RENDER_COPY[resolved_language]
    notes = copy["notes"]
    sections_copy = copy["sections"]
    headline = build_day_explanation_headline(
        language=resolved_language,
        request_category=request_category,
        context_facts=context_facts,
    )

    sections: list[ExplainSection] = []

    assignment_items = _build_assignment_summary_items(
        language=resolved_language,
        context_facts=context_facts,
    )
    if assignment_items:
        sections.append(
            ExplainSection(
                key="assignments",
                title=sections_copy["assignments"],
                items=assignment_items,
            )
        )

    warning_items = _build_warning_summary_items(
        language=resolved_language,
        context_facts=context_facts,
    )
    if warning_items:
        sections.append(
            ExplainSection(
                key="warnings",
                title=sections_copy["warnings"],
                items=warning_items,
            )
        )

    fallback_items = _build_fallback_summary_items(
        language=resolved_language,
        context_facts=context_facts,
    )
    if fallback_items:
        sections.append(
            ExplainSection(
                key="fallback",
                title=sections_copy["fallback"],
                items=fallback_items,
            )
        )

    constraint_items = _build_constraint_summary_items(
        language=resolved_language,
        context_facts=context_facts,
    )
    if constraint_items:
        sections.append(
            ExplainSection(
                key="constraints",
                title=sections_copy["constraints"],
                items=constraint_items,
            )
        )

    comparison = context_facts.get("comparison")
    if request_category == "refine_change_summary" or (
        isinstance(comparison, dict) and comparison.get("has_comparison")
    ):
        change_items = _build_change_summary_items(
            language=resolved_language,
            context_facts=context_facts,
        )
        if change_items:
            sections.append(
                ExplainSection(
                    key="changes",
                    title=sections_copy["changes"],
                    items=change_items,
                )
            )

    if not sections:
        sections.append(
            ExplainSection(
                key="assignments",
                title=sections_copy["assignments"],
                items=[notes["no_assignments"]],
            )
        )

    return DayExplainNarrative(
        headline=headline,
        sections=sections,
        model_used=False,
        fallback_used=True,
    )


def coerce_day_explanation_payload(
    payload: JsonObject,
) -> DayExplainNarrative:
    """Validate model output and coerce it into the bounded narrative shape."""

    headline = str(payload.get("headline") or "").strip()
    raw_sections = payload.get("sections")
    if not headline or not isinstance(raw_sections, list):
        raise ValueError("Structured explain payload must contain a headline and sections.")

    sections: list[ExplainSection] = []
    for raw_section in raw_sections:
        if not isinstance(raw_section, dict):
            raise ValueError("Explain sections must be JSON objects.")
        key = str(raw_section.get("key") or "").strip()
        title = str(raw_section.get("title") or "").strip()
        raw_items = raw_section.get("items")
        if key not in {"assignments", "warnings", "fallback", "constraints", "changes"}:
            raise ValueError(f"Unsupported explain section key: {key!r}")
        if not title or not isinstance(raw_items, list):
            raise ValueError("Explain sections require a title and item list.")
        items = [
            str(item).strip()
            for item in raw_items
            if str(item).strip()
        ]
        if not items:
            raise ValueError("Explain sections must contain at least one item.")
        if len(items) > 3:
            raise ValueError("Explain sections may contain at most three items.")
        sections.append(ExplainSection(key=key, title=title, items=items))

    if not sections:
        raise ValueError("At least one explain section is required.")
    if len(sections) > 5:
        raise ValueError("At most five explain sections are allowed.")

    return DayExplainNarrative(
        headline=headline,
        sections=sections,
        model_used=True,
        fallback_used=False,
    )


def serialize_day_explanation_payload(
    explanation: DayExplainNarrative,
) -> JsonObject:
    """Serialize the explanation payload for transport and page rendering."""

    return {
        "headline": explanation.headline,
        "sections": [
            {
                "key": section.key,
                "title": section.title,
                "items": list(section.items),
            }
            for section in explanation.sections
        ],
        "model_used": explanation.model_used,
        "fallback_used": explanation.fallback_used,
    }


def _build_current_day_assignments(
    *,
    target_date: dt.date,
    current_state: CurrentWorkspaceState | None,
    workers: list[Any],
    stations: list[Any],
    shifts: list[Any],
) -> list[JsonObject]:
    if current_state is None:
        return []

    workers_by_id = {
        worker.id or "": worker
        for worker in workers
    }
    stations_by_id = {
        station.id or "": station
        for station in stations
    }
    shifts_by_id = {
        shift.id or "": shift
        for shift in shifts
    }
    normalized: list[JsonObject] = []
    for assignment in current_state.assignments:
        if assignment.assignment_date != target_date:
            continue
        worker = workers_by_id.get(assignment.worker_id)
        shift = shifts_by_id.get(assignment.shift_definition_id)
        station = (
            stations_by_id.get(assignment.station_id or "")
            if assignment.station_id is not None
            else None
        )
        normalized.append(
            {
                "worker_code": (
                    getattr(worker, "code", None)
                    or assignment.worker_id
                ),
                "worker_name": (
                    getattr(worker, "name", None)
                    or assignment.worker_id
                ),
                "worker_role": getattr(worker, "role", "") or "",
                "shift_code": (
                    getattr(shift, "code", None)
                    or assignment.shift_definition_id
                ),
                "station_code": (
                    getattr(station, "code", None)
                    if station is not None
                    else None
                ),
                "note": assignment.note,
                "source": "current_workspace",
            }
        )
    return sorted(normalized, key=_assignment_sort_key)


def _build_candidate_day_assignments(
    *,
    target_date: dt.date,
    candidate_result: MonthPlanningResult | None,
    worker_names_by_code: dict[str, str],
    worker_roles_by_code: dict[str, str],
) -> list[JsonObject]:
    if candidate_result is None:
        return []

    normalized: list[JsonObject] = []
    for assignment in candidate_result.assignments:
        if assignment.date != target_date:
            continue
        normalized.append(
            {
                "worker_code": assignment.worker_code,
                "worker_name": worker_names_by_code.get(
                    assignment.worker_code,
                    assignment.worker_code,
                ),
                "worker_role": worker_roles_by_code.get(assignment.worker_code, ""),
                "shift_code": assignment.shift_code,
                "station_code": assignment.station_code,
                "note": assignment.note,
                "source": assignment.source,
            }
        )
    return sorted(normalized, key=_assignment_sort_key)


def _build_candidate_day_warnings(
    *,
    target_date: dt.date,
    candidate_result: MonthPlanningResult | None,
) -> list[JsonObject]:
    if candidate_result is None:
        return []

    warnings: list[JsonObject] = []
    for warning in candidate_result.warnings:
        if warning.date != target_date:
            continue
        warnings.append(
            {
                "type": warning.type,
                "message_key": warning.message_key,
                "worker_code": warning.worker_code,
                "details": dict(warning.details or {}),
            }
        )
    return warnings


def _build_constraints_context(
    *,
    target_date: dt.date,
    planning_input: MonthPlanningInput,
) -> JsonObject:
    constraint_config = planning_input.constraint_config
    day_kind = "weekend" if target_date.weekday() >= 5 else "weekday"
    min_staff_key = "min_staff_weekend" if day_kind == "weekend" else "min_staff_weekday"
    raw_station_minimums = constraint_config.get("stations")
    station_minimums = (
        {
            str(station_code): int(required_staff)
            for station_code, required_staff in raw_station_minimums.items()
            if isinstance(required_staff, int) and required_staff > 0
        }
        if isinstance(raw_station_minimums, dict)
        else {}
    )
    morning_shift_codes = [
        str(shift_code)
        for shift_code in constraint_config.get("morning_shifts", [])
        if str(shift_code).strip()
    ] if isinstance(constraint_config.get("morning_shifts"), list) else []
    raw_morning_requirements = constraint_config.get("stations_require_morning")
    morning_requirements = (
        {
            str(station_code): int(required_staff)
            for station_code, required_staff in raw_morning_requirements.items()
            if isinstance(required_staff, int) and required_staff > 0
        }
        if isinstance(raw_morning_requirements, dict)
        else {}
    )

    return {
        "day_kind": day_kind,
        "min_staff_target": (
            int(constraint_config[min_staff_key])
            if isinstance(constraint_config.get(min_staff_key), int)
            else None
        ),
        "stations": station_minimums,
        "morning_shift_codes": morning_shift_codes,
        "stations_require_morning": morning_requirements,
        "max_staff_per_day": _coerce_optional_int(
            constraint_config.get("max_staff_per_day")
        ),
        "max_consecutive_days": _coerce_optional_int(
            constraint_config.get("max_consecutive_days")
        ),
        "min_rest_days_per_month": _coerce_optional_int(
            constraint_config.get("min_rest_days_per_month")
        ),
        "require_one_chef": bool(constraint_config.get("require_one_chef", False)),
        "count_chefs_in_headcount": bool(
            constraint_config.get("count_chefs_in_headcount", False)
        ),
        "chefs_have_no_shift": bool(constraint_config.get("chefs_have_no_shift", False)),
    }


def _build_day_comparison(
    *,
    current_day_assignments: list[JsonObject],
    candidate_day_assignments: list[JsonObject],
) -> JsonObject:
    if not current_day_assignments or not candidate_day_assignments:
        return {
            "has_comparison": False,
            "added_assignments": [],
            "removed_assignments": [],
            "changed_assignments": [],
        }

    current_by_worker = _group_assignments_by_worker_code(current_day_assignments)
    candidate_by_worker = _group_assignments_by_worker_code(candidate_day_assignments)

    added_assignments: list[JsonObject] = []
    removed_assignments: list[JsonObject] = []
    changed_assignments: list[JsonObject] = []

    for worker_code in sorted(set(current_by_worker) | set(candidate_by_worker)):
        current_rows = current_by_worker.get(worker_code, [])
        candidate_rows = candidate_by_worker.get(worker_code, [])
        if not current_rows and candidate_rows:
            added_assignments.extend(candidate_rows)
            continue
        if current_rows and not candidate_rows:
            removed_assignments.extend(current_rows)
            continue
        if _compact_assignment_rows(current_rows) != _compact_assignment_rows(candidate_rows):
            changed_assignments.append(
                {
                    "worker_code": worker_code,
                    "worker_name": (
                        candidate_rows[0].get("worker_name")
                        or current_rows[0].get("worker_name")
                        or worker_code
                    ),
                    "current": _compact_assignment_rows(current_rows),
                    "candidate": _compact_assignment_rows(candidate_rows),
                }
            )

    return {
        "has_comparison": True,
        "added_assignments": added_assignments,
        "removed_assignments": removed_assignments,
        "changed_assignments": changed_assignments,
    }


def _build_requested_worker_context(
    *,
    request_worker_code: str | None,
    target_date: dt.date,
    planning_input: MonthPlanningInput,
    selected_day_assignments: list[JsonObject],
    selected_station_codes: list[str],
    worker_names_by_code: dict[str, str],
    worker_roles_by_code: dict[str, str],
    planning_workers_by_code: dict[str, Any],
) -> JsonObject | None:
    if request_worker_code is None:
        return None

    worker = planning_workers_by_code.get(request_worker_code)
    if worker is None:
        return None

    assigned_rows = [
        assignment
        for assignment in selected_day_assignments
        if assignment["worker_code"] == request_worker_code
    ]
    leave_dates = {
        leave_request.date
        for leave_request in planning_input.leave_requests
        if leave_request.worker_code == request_worker_code
    }
    scheduling_profile = worker.scheduling_profile
    availability_facts: list[JsonObject] = []
    if target_date in leave_dates:
        availability_facts.append({"reason_code": "leave"})
    if target_date.weekday() in scheduling_profile.fixed_day_off_weekdays:
        availability_facts.append({"reason_code": "fixed_day_off"})
    if target_date in scheduling_profile.ad_hoc_unavailable:
        availability_facts.append({"reason_code": "ad_hoc_unavailable"})
    if target_date in scheduling_profile.wish_off.hard:
        availability_facts.append({"reason_code": "wish_off_hard"})
    if target_date in scheduling_profile.wish_off.soft:
        availability_facts.append({"reason_code": "wish_off_soft"})

    matched_station_skills = sorted(
        station_code
        for station_code in worker.station_skills
        if station_code in selected_station_codes
    )
    return {
        "worker_code": request_worker_code,
        "worker_name": worker_names_by_code.get(request_worker_code, request_worker_code),
        "worker_role": worker_roles_by_code.get(request_worker_code, ""),
        "assigned": bool(assigned_rows),
        "assignments": assigned_rows,
        "availability_facts": availability_facts,
        "station_skills": sorted(worker.station_skills),
        "matched_station_skills": matched_station_skills,
    }


def _group_assignments_by_worker_code(
    day_assignments: list[JsonObject],
) -> dict[str, list[JsonObject]]:
    grouped: dict[str, list[JsonObject]] = {}
    for assignment in day_assignments:
        worker_code = str(assignment["worker_code"])
        grouped.setdefault(worker_code, []).append(assignment)
    return {
        worker_code: sorted(rows, key=_assignment_sort_key)
        for worker_code, rows in grouped.items()
    }


def _compact_assignment_rows(rows: list[JsonObject]) -> list[JsonObject]:
    return [
        {
            "shift_code": row.get("shift_code"),
            "station_code": row.get("station_code"),
            "note": row.get("note"),
        }
        for row in sorted(rows, key=_assignment_sort_key)
    ]


def _assignment_sort_key(assignment: JsonObject) -> tuple[str, str, str, str]:
    return (
        str(assignment.get("worker_code") or ""),
        str(assignment.get("shift_code") or ""),
        str(assignment.get("station_code") or ""),
        str(assignment.get("note") or ""),
    )


def _build_assignment_summary_items(
    *,
    language: str,
    context_facts: JsonObject,
) -> list[str]:
    copy = _EXPLAIN_RENDER_COPY[language]
    notes = copy["notes"]
    requested_worker = context_facts.get("requested_worker")
    assignments = context_facts.get("assignments")
    if not isinstance(assignments, list):
        return [notes["no_assignments"]]

    items: list[str] = []
    if isinstance(requested_worker, dict):
        worker_name = str(requested_worker.get("worker_name") or "")
        worker_code = str(requested_worker.get("worker_code") or "")
        worker_assignments = requested_worker.get("assignments")
        if isinstance(worker_assignments, list) and worker_assignments:
            items.append(
                notes["assigned"].format(
                    worker_name=worker_name,
                    worker_code=worker_code,
                    assignment=_format_assignment_summary(
                        worker_assignments[0],
                    ),
                )
            )
        else:
            items.append(
                notes["not_assigned"].format(
                    worker_name=worker_name,
                    worker_code=worker_code,
                )
            )

    if not assignments:
        items.append(notes["no_assignments"])
        return _limit_items(items)

    for assignment in assignments:
        items.append(_format_assignment_line(assignment))
    return _limit_items(items)


def _build_warning_summary_items(
    *,
    language: str,
    context_facts: JsonObject,
) -> list[str]:
    copy = _EXPLAIN_RENDER_COPY[language]
    notes = copy["notes"]
    warning_availability = context_facts.get("warning_availability")
    if not isinstance(warning_availability, dict) or not warning_availability.get("available"):
        return [notes["current_warning_gap"]]

    warnings = context_facts.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        return [notes["no_preview_warnings"]]

    return _limit_items(
        [
            _format_warning_line(language=language, warning=warning)
            for warning in warnings
        ]
    )


def _build_fallback_summary_items(
    *,
    language: str,
    context_facts: JsonObject,
) -> list[str]:
    copy = _EXPLAIN_RENDER_COPY[language]
    notes = copy["notes"]
    fallback_assignments = context_facts.get("fallback_assignments")
    required_chef_assignments = context_facts.get("required_chef_assignments")

    items: list[str] = []
    if isinstance(fallback_assignments, list):
        for assignment in fallback_assignments:
            items.append(
                notes["fallback_assignment"].format(
                    worker_name=assignment.get("worker_name") or assignment.get("worker_code") or "",
                    worker_code=assignment.get("worker_code") or "",
                    station_code=assignment.get("station_code") or "-",
                )
            )
    if isinstance(required_chef_assignments, list):
        for assignment in required_chef_assignments:
            items.append(
                notes["required_chef_assignment"].format(
                    worker_name=assignment.get("worker_name") or assignment.get("worker_code") or "",
                    worker_code=assignment.get("worker_code") or "",
                )
            )
    if not items:
        items.append(notes["no_fallback"])
    return _limit_items(items)


def _build_constraint_summary_items(
    *,
    language: str,
    context_facts: JsonObject,
) -> list[str]:
    copy = _EXPLAIN_RENDER_COPY[language]
    notes = copy["notes"]
    constraints = context_facts.get("constraints")
    requested_worker = context_facts.get("requested_worker")
    items: list[str] = []

    if isinstance(requested_worker, dict):
        worker_name = str(requested_worker.get("worker_name") or requested_worker.get("worker_code") or "")
        availability_facts = requested_worker.get("availability_facts")
        if isinstance(availability_facts, list) and availability_facts:
            for fact in availability_facts:
                if not isinstance(fact, dict):
                    continue
                reason_code = str(fact.get("reason_code") or "")
                localized_reason = copy["availability"].get(reason_code)
                if localized_reason:
                    items.append(localized_reason)
        else:
            items.append(notes["no_blocking_reason"])

        matched_station_skills = requested_worker.get("matched_station_skills")
        if isinstance(matched_station_skills, list) and matched_station_skills:
            items.append(
                notes["skills_overlap"].format(
                    worker_name=worker_name,
                    station_codes=", ".join(str(code) for code in matched_station_skills),
                )
            )
        elif isinstance(requested_worker.get("station_skills"), list):
            items.append(
                notes["skills_no_overlap"].format(worker_name=worker_name)
            )

    if isinstance(constraints, dict):
        day_kind = copy["day_kinds"].get(str(constraints.get("day_kind") or ""), str(constraints.get("day_kind") or ""))
        min_staff_target = constraints.get("min_staff_target")
        if min_staff_target is not None:
            items.append(
                notes["min_staff"].format(
                    day_kind=day_kind,
                    min_staff_target=min_staff_target,
                )
            )
        stations = constraints.get("stations")
        if isinstance(stations, dict) and stations:
            station_summary = ", ".join(
                f"{station_code} x{required_staff}"
                for station_code, required_staff in sorted(stations.items())
            )
            items.append(notes["stations"].format(stations=station_summary))
        max_staff_per_day = constraints.get("max_staff_per_day")
        if max_staff_per_day is not None:
            items.append(
                notes["max_staff"].format(max_staff_per_day=max_staff_per_day)
            )
        max_consecutive_days = constraints.get("max_consecutive_days")
        if max_consecutive_days is not None:
            items.append(
                notes["max_consecutive_days"].format(
                    max_consecutive_days=max_consecutive_days
                )
            )
        min_rest_days_per_month = constraints.get("min_rest_days_per_month")
        if min_rest_days_per_month is not None:
            items.append(
                notes["min_rest_days_per_month"].format(
                    min_rest_days_per_month=min_rest_days_per_month
                )
            )
        if constraints.get("require_one_chef"):
            items.append(notes["require_one_chef"])
    return _limit_items(items, limit=4)


def _build_change_summary_items(
    *,
    language: str,
    context_facts: JsonObject,
) -> list[str]:
    copy = _EXPLAIN_RENDER_COPY[language]
    notes = copy["notes"]
    comparison = context_facts.get("comparison")
    if not isinstance(comparison, dict) or not comparison.get("has_comparison"):
        return []

    items: list[str] = []
    added_assignments = comparison.get("added_assignments")
    if isinstance(added_assignments, list):
        for assignment in added_assignments:
            items.append(
                notes["change_added"].format(
                    assignment=_format_assignment_line(assignment)
                )
            )

    removed_assignments = comparison.get("removed_assignments")
    if isinstance(removed_assignments, list):
        for assignment in removed_assignments:
            items.append(
                notes["change_removed"].format(
                    assignment=_format_assignment_line(assignment)
                )
            )

    changed_assignments = comparison.get("changed_assignments")
    if isinstance(changed_assignments, list):
        for change in changed_assignments:
            if not isinstance(change, dict):
                continue
            worker_name = str(change.get("worker_name") or change.get("worker_code") or "")
            worker_code = str(change.get("worker_code") or "")
            current_value = _format_compact_assignment_set(change.get("current"))
            candidate_value = _format_compact_assignment_set(change.get("candidate"))
            items.append(
                notes["change_changed"].format(
                    worker_name=worker_name,
                    worker_code=worker_code,
                    current=current_value,
                    candidate=candidate_value,
                )
            )

    if not items:
        items.append(notes["no_change"])
    return _limit_items(items, limit=4)


def _format_assignment_line(assignment: JsonObject) -> str:
    worker_name = str(assignment.get("worker_name") or assignment.get("worker_code") or "")
    worker_code = str(assignment.get("worker_code") or "")
    return f"{worker_name} ({worker_code}): {_format_assignment_summary(assignment)}"


def _format_assignment_summary(assignment: JsonObject) -> str:
    parts = [str(assignment.get("shift_code") or "-")]
    station_code = assignment.get("station_code")
    if station_code:
        parts.append(str(station_code))
    note = assignment.get("note")
    if note:
        if note == _FALLBACK_STATION_NOTE:
            parts.append("fallback")
        elif note == _REQUIRED_CHEF_NOTE:
            parts.append("required_chef")
        elif note == _REFINE_PREVIEW_NOTE:
            parts.append("refine_preview")
        else:
            parts.append(str(note))
    return " / ".join(parts)


def _format_compact_assignment_set(raw_rows: object) -> str:
    if not isinstance(raw_rows, list) or not raw_rows:
        return "-"
    return " ; ".join(
        _format_assignment_summary(row)
        for row in raw_rows
        if isinstance(row, dict)
    )


def _format_warning_line(
    *,
    language: str,
    warning: JsonObject,
) -> str:
    copy = _EXPLAIN_RENDER_COPY[language]
    notes = copy["notes"]
    warning_label = copy["warning_labels"].get(
        str(warning.get("type") or ""),
        str(warning.get("message_key") or warning.get("type") or "warning"),
    )
    details = warning.get("details")
    if isinstance(details, dict) and details:
        return notes["warning"].format(
            warning_label=warning_label,
            details=_format_warning_details(language=language, details=details),
        )
    return notes["warning_no_details"].format(warning_label=warning_label)


def _format_warning_details(
    *,
    language: str,
    details: JsonObject,
) -> str:
    labels = _WARNING_DETAIL_LABELS.get(language, _WARNING_DETAIL_LABELS["en"])
    return ", ".join(
        f"{labels.get(key, key)}={value}"
        for key, value in sorted(details.items())
    )


def _limit_items(items: list[str], *, limit: int = 3) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def _resolve_render_language(language: str) -> str:
    if language in _EXPLAIN_RENDER_COPY:
        return language
    return "en"


def _coerce_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _validate_request(request: ExplainDayScheduleRequest) -> None:
    if request.year < 1:
        raise ValueError("Explain year must be greater than zero.")
    if request.month < 1 or request.month > 12:
        raise ValueError("Explain month must be between 1 and 12.")
    if request.target_date.year != request.year or request.target_date.month != request.month:
        raise ValueError("Explain target date must stay within the selected month.")


def _require_record_id(record_id: RecordId | None, *, label: str) -> RecordId:
    if record_id is None:
        raise ValueError(f"{label} must be populated on repository results.")
    return record_id


__all__ = [
    "DayExplainNarrative",
    "DayExplainWorkflow",
    "DayExplainWorkflowRequest",
    "DayExplainWorkflowResult",
    "EXPLAIN_STATUS_AMBIGUOUS",
    "EXPLAIN_STATUS_READY",
    "EXPLAIN_STATUS_UNSUPPORTED",
    "ExplainDayScheduleRequest",
    "ExplainDayScheduleResponse",
    "ExplainDayScheduleService",
    "ExplainOutcome",
    "ExplainSection",
    "build_day_explanation_headline",
    "build_day_explain_context",
    "coerce_day_explanation_payload",
    "explain_day_schedule",
    "render_day_explanation_fallback",
    "render_explain_outcome",
    "serialize_day_explanation_payload",
]
