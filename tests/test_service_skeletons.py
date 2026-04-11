from __future__ import annotations

import ast
import datetime as dt
import importlib
import inspect
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.contracts import (
    AssignmentOutput,
    AssignmentPatchInput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
)
from app.infra.models import (
    ConstraintConfig,
    LeaveRequest,
    MonthlyAssignment,
    MonthlyWorkspace,
    RefineRequest,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
    WorkerStationSkill,
)
from app.infra.repositories import CurrentWorkspaceState
from app.services.apply import (
    ApplyMonthScheduleRequest,
    ApplyMonthScheduleService,
    apply_month_schedule,
)
from app.services.export import (
    ExportMonthScheduleRequest,
    ExportMonthScheduleService,
    export_month_schedule,
)
from app.services.preview import (
    PreviewMonthScheduleRequest,
    PreviewMonthScheduleService,
)
from app.services.refine import (
    RefineMonthScheduleRequest,
    RefineMonthScheduleService,
    RefineParserResult,
)
from app.services.save import (
    SaveMonthScheduleRequest,
    SaveMonthScheduleService,
    save_month_schedule,
)

SERVICE_MODULES = (
    "app.services.preview",
    "app.services.apply",
    "app.services.save",
    "app.services.refine",
    "app.services.export",
)
DISALLOWED_IMPORT_PREFIXES = (
    "django",
    "fastapi",
    "flask",
    "pydantic",
    "sqlalchemy",
    "app.api",
)


@pytest.mark.parametrize("module_name", SERVICE_MODULES)
def test_service_modules_are_importable_and_framework_neutral(
    module_name: str,
) -> None:
    module = importlib.import_module(module_name)
    source_path = Path(inspect.getsourcefile(module) or "")

    assert source_path.exists()

    imported_modules = _collect_imported_modules(source_path)
    disallowed_imports = sorted(
        name
        for name in imported_modules
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in DISALLOWED_IMPORT_PREFIXES
        )
    )

    assert disallowed_imports == []


def test_preview_service_smoke_flow_returns_engine_result() -> None:
    ctx = _sample_context()
    engine = _RecordingCallable(
        _sample_result(source_type="preview", refinement_applied=False)
    )
    service = PreviewMonthScheduleService(
        tenant_repository=_tenant_repo(ctx.tenant),
        worker_repository=_worker_repo(ctx, include_skills=True),
        station_repository=_station_repo(ctx),
        shift_repository=_shift_repo(ctx),
        leave_request_repository=_leave_repo(ctx),
        constraint_config_repository=_constraint_repo(ctx),
        engine_runner=engine,
    )

    response = service.preview_month_schedule(
        PreviewMonthScheduleRequest(tenant_slug=ctx.tenant.slug, year=2026, month=4)
    )

    assert response.request.tenant_slug == ctx.tenant.slug
    assert response.result == engine.result
    assert engine.requests[0].tenant_code == ctx.tenant.slug
    assert engine.requests[0].workers[0].worker_code == ctx.worker.code


def test_apply_service_smoke_flow_accepts_structural_result_payload() -> None:
    ctx = _sample_context()
    result = _sample_result(source_type="preview", refinement_applied=False)
    payload = SimpleNamespace(
        assignments=list(result.assignments),
        warnings=list(result.warnings),
        summary=result.summary,
        metadata=result.metadata,
    )
    workspace_repository = _workspace_repo(current_state=None)
    service = ApplyMonthScheduleService(
        tenant_repository=_tenant_repo(ctx.tenant),
        worker_repository=_worker_repo(ctx, include_skills=False),
        station_repository=_station_repo(ctx),
        shift_repository=_shift_repo(ctx),
        workspace_repository=workspace_repository,
    )

    response = apply_month_schedule(
        ApplyMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
            result=payload,
        ),
        service=service,
    )

    assert response.workspace_created is True
    assert response.assignment_count == 1
    assert response.warning_count == 0
    assert workspace_repository.replaced_assignments[response.workspace_id][0].worker_id == (
        ctx.worker.id
    )


def test_save_service_smoke_flow_persists_snapshot() -> None:
    ctx = _sample_context()
    workspace_repository = _workspace_repo(
        CurrentWorkspaceState(
            workspace=ctx.workspace,
            assignments=[ctx.assignment],
        )
    )
    plan_version_repository = _plan_version_repo(next_version_number=3)
    service = SaveMonthScheduleService(
        tenant_repository=_tenant_repo(ctx.tenant),
        workspace_repository=workspace_repository,
        plan_version_repository=plan_version_repository,
    )

    response = save_month_schedule(
        SaveMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
            label="Baseline",
            note="April draft",
        ),
        service=service,
    )

    assert response.version_number == 3
    assert response.assignment_count == 1
    assert len(plan_version_repository.saved_versions) == 1
    assert (
        plan_version_repository.saved_versions[0].snapshot_json["workspace"]["id"]
        == ctx.workspace.id
    )


def test_refine_service_smoke_flow_stores_candidate_preview() -> None:
    ctx = _sample_context()
    parser = _RecordingCallable(
        RefineParserResult(
            intent_json={"parser_hint": "adjustment"},
            adjustment_patch=[
                AssignmentPatchInput(
                    operation="set",
                    date=dt.date(2026, 4, 1),
                    worker_code=ctx.worker.code or "",
                    shift_code=ctx.shift.code,
                    station_code=ctx.station.code,
                    note="Refine smoke test",
                )
            ],
        )
    )
    engine = _RecordingCallable(
        _sample_result(source_type="refine", refinement_applied=True)
    )
    refine_request_repository = _refine_request_repo()
    service = RefineMonthScheduleService(
        tenant_repository=_tenant_repo(ctx.tenant),
        worker_repository=_worker_repo(ctx, include_skills=True),
        station_repository=_station_repo(ctx),
        shift_repository=_shift_repo(ctx),
        leave_request_repository=_leave_repo(ctx),
        constraint_config_repository=_constraint_repo(ctx),
        workspace_repository=_workspace_repo(
            CurrentWorkspaceState(workspace=ctx.workspace, assignments=[])
        ),
        refine_request_repository=refine_request_repository,
        parser=parser,
        engine_runner=engine,
    )

    response = service.refine_month_schedule(
        RefineMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
            request_text="Put Alex on grill for April 1.",
        )
    )

    assert response.status
    assert response.parsed_intent_json
    assert any(key != "adjustment_patch" for key in response.parsed_intent_json)
    assert parser.requests[0].workspace_id == ctx.workspace.id
    assert engine.requests[0].adjustment_patch is not None
    assert (
        refine_request_repository.requests[response.refine_request_id].result_preview_json
        is not None
    )


def test_export_service_smoke_flow_builds_rows_and_csv() -> None:
    ctx = _sample_context()
    service = ExportMonthScheduleService(
        tenant_repository=_tenant_repo(ctx.tenant),
        worker_repository=_worker_repo(ctx, include_skills=False),
        station_repository=_station_repo(ctx),
        shift_repository=_shift_repo(ctx),
        workspace_repository=_workspace_repo(
            CurrentWorkspaceState(
                workspace=ctx.workspace,
                assignments=[ctx.assignment],
            )
        ),
    )

    response = export_month_schedule(
        ExportMonthScheduleRequest(
            tenant_slug=ctx.tenant.slug,
            year=2026,
            month=4,
        ),
        service=service,
    )

    assert response.row_count == 1
    assert response.rows[0].worker_code == ctx.worker.code
    assert response.rows[0].station_code == ctx.station.code
    assert response.csv_text.strip()


def _collect_imported_modules(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)

    return names


def _sample_context() -> SimpleNamespace:
    tenant = Tenant(id="tenant-1", slug="tenant-a", name="Tenant A")
    worker = Worker(
        id="worker-1",
        tenant_id=tenant.id or "",
        name="Alex",
        role="cook",
        code="W1",
    )
    station = Station(
        id="station-1",
        tenant_id=tenant.id or "",
        name="Grill",
        code="GRILL",
    )
    shift = ShiftDefinition(
        id="shift-1",
        tenant_id=tenant.id or "",
        code="DAY",
        name="Day",
        paid_hours=Decimal("8"),
    )
    workspace = MonthlyWorkspace(
        id="workspace-1",
        tenant_id=tenant.id or "",
        year=2026,
        month=4,
        status="draft",
    )
    return SimpleNamespace(
        tenant=tenant,
        worker=worker,
        station=station,
        shift=shift,
        leave_request=LeaveRequest(
            id="leave-1",
            tenant_id=tenant.id or "",
            worker_id=worker.id or "",
            leave_date=dt.date(2026, 4, 2),
            reason="pto",
        ),
        station_skill=WorkerStationSkill(
            id="skill-1",
            tenant_id=tenant.id or "",
            worker_id=worker.id or "",
            station_id=station.id or "",
        ),
        constraint_config=ConstraintConfig(
            id="constraint-1",
            tenant_id=tenant.id or "",
            scope_type="monthly",
            year=2026,
            month=4,
            config_json={"max_weekly_hours": 40},
        ),
        workspace=workspace,
        assignment=MonthlyAssignment(
            id="assignment-1",
            workspace_id=workspace.id or "",
            worker_id=worker.id or "",
            assignment_date=dt.date(2026, 4, 1),
            shift_definition_id=shift.id or "",
            station_id=station.id or "",
        ),
    )


def _sample_result(*, source_type: str, refinement_applied: bool) -> MonthPlanningResult:
    return MonthPlanningResult(
        assignments=[
            AssignmentOutput(
                date=dt.date(2026, 4, 1),
                worker_code="W1",
                shift_code="DAY",
                station_code="GRILL",
                source=source_type,
                note="Smoke test assignment",
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
            generated_at=dt.datetime(2026, 4, 11, 0, 0, tzinfo=dt.timezone.utc),
            source_type=source_type,
            refinement_applied=refinement_applied,
            notes=["service-smoke"],
        ),
    )


def _tenant_repo(tenant: Tenant) -> SimpleNamespace:
    return SimpleNamespace(
        get_by_id=lambda tenant_id: tenant if tenant.id == tenant_id else None,
        get_by_slug=lambda slug: tenant if tenant.slug == slug else None,
    )


def _worker_repo(ctx: SimpleNamespace, *, include_skills: bool) -> SimpleNamespace:
    return SimpleNamespace(
        list_for_tenant=lambda tenant_id: [ctx.worker],
        list_station_skills=lambda tenant_id: [ctx.station_skill] if include_skills else [],
    )


def _station_repo(ctx: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(list_for_tenant=lambda tenant_id: [ctx.station])


def _shift_repo(ctx: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(list_for_tenant=lambda tenant_id: [ctx.shift])


def _leave_repo(ctx: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        list_for_month=lambda tenant_id, year, month: [ctx.leave_request]
    )


def _constraint_repo(ctx: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        get_resolved_for_month=lambda tenant_id, year, month: ctx.constraint_config
    )


def _workspace_repo(current_state: CurrentWorkspaceState | None) -> SimpleNamespace:
    state = {"current": current_state}
    replaced_assignments: dict[str, list[MonthlyAssignment]] = {}
    saved_workspaces: list[MonthlyWorkspace] = []

    def save_current_workspace(workspace: MonthlyWorkspace) -> MonthlyWorkspace:
        persisted = replace(workspace, id=workspace.id or "workspace-1")
        saved_workspaces.append(persisted)
        assignments = state["current"].assignments if state["current"] is not None else []
        state["current"] = CurrentWorkspaceState(workspace=persisted, assignments=assignments)
        return persisted

    def replace_assignments_for_workspace(
        workspace_id: str,
        assignments: list[MonthlyAssignment],
    ) -> list[MonthlyAssignment]:
        persisted = [
            replace(assignment, id=f"assignment-{index}")
            for index, assignment in enumerate(assignments, start=1)
        ]
        replaced_assignments[workspace_id] = persisted
        if state["current"] is not None:
            state["current"] = CurrentWorkspaceState(
                workspace=state["current"].workspace,
                assignments=persisted,
            )
        return persisted

    return SimpleNamespace(
        load_current=lambda tenant_id, year, month: state["current"],
        save_current_workspace=save_current_workspace,
        replace_assignments=replace_assignments_for_workspace,
        replaced_assignments=replaced_assignments,
        saved_workspaces=saved_workspaces,
    )


def _plan_version_repo(*, next_version_number: int) -> SimpleNamespace:
    saved_versions = []

    def save(version):
        persisted = replace(version, id=f"version-{version.version_number}")
        saved_versions.append(persisted)
        return persisted

    return SimpleNamespace(
        get_next_version_number=lambda tenant_id, year, month: next_version_number,
        save=save,
        list_for_month=lambda tenant_id, year, month: list(saved_versions),
        get_by_id=lambda version_id: next(
            (version for version in saved_versions if version.id == version_id),
            None,
        ),
        saved_versions=saved_versions,
    )


def _refine_request_repo() -> SimpleNamespace:
    requests: dict[str, RefineRequest] = {}

    def create(request: RefineRequest) -> RefineRequest:
        persisted = replace(request, id="refine-1")
        requests[persisted.id or "refine-1"] = persisted
        return persisted

    def update_parsed_preview(
        refine_request_id: str,
        *,
        status: str,
        parsed_intent_json: dict[str, object] | None = None,
        result_preview_json: dict[str, object] | None = None,
    ) -> RefineRequest | None:
        existing = requests.get(refine_request_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            status=status,
            parsed_intent_json=parsed_intent_json,
            result_preview_json=result_preview_json,
        )
        requests[refine_request_id] = updated
        return updated

    return SimpleNamespace(
        create=create,
        list_for_workspace=lambda workspace_id: [
            request
            for request in requests.values()
            if request.workspace_id == workspace_id
        ],
        update_parsed_preview=update_parsed_preview,
        requests=requests,
    )


class _RecordingCallable:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[object] = []

    def __call__(self, request: object) -> object:
        self.requests.append(request)
        return self.result
