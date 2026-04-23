from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest

from app.infra import models as infra_models
from app.infra.django_app.models import (
    ConstraintConfig as DjangoConstraintConfig,
    LeaveRequest as DjangoLeaveRequest,
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    RefineRequest as DjangoRefineRequest,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
    WorkerStationSkill as DjangoWorkerStationSkill,
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


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoRefineRequest.objects.all().delete()
    DjangoLeaveRequest.objects.all().delete()
    DjangoConstraintConfig.objects.all().delete()
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
    DjangoWorkerStationSkill.objects.all().delete()
    DjangoShiftDefinition.objects.all().delete()
    DjangoStation.objects.all().delete()
    DjangoWorker.objects.all().delete()
    DjangoTenant.objects.all().delete()


def test_master_data_repositories_return_framework_neutral_dataclasses() -> None:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    other_tenant = DjangoTenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        default_locale="en-US",
    )
    worker = DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
        scheduling_profile_json={
            "shift_prefs": ["DAY"],
            "fixed_days_off": ["Sun"],
            "core": True,
        },
    )
    DjangoWorker.objects.create(
        tenant=other_tenant,
        code="W2",
        name="Jordan",
        role="cashier",
        is_active=True,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code="GRILL",
        name="Grill",
        is_active=True,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    persisted_skill = DjangoWorkerStationSkill.objects.create(
        tenant=tenant,
        worker=worker,
        station=station,
    )

    tenant_repo = DjangoTenantRepository()
    worker_repo = DjangoWorkerRepository()
    station_repo = DjangoStationRepository()
    shift_repo = DjangoShiftRepository()

    by_id = tenant_repo.get_by_id(str(tenant.id))
    by_slug = tenant_repo.get_by_slug("tenant-a")
    workers = worker_repo.list_for_tenant(str(tenant.id))
    stations = station_repo.list_for_tenant(str(tenant.id))
    shifts = shift_repo.list_for_tenant(str(tenant.id))

    assert isinstance(by_id, infra_models.Tenant)
    assert isinstance(by_slug, infra_models.Tenant)
    assert by_id == by_slug
    assert by_id is not None
    assert by_id.id == str(tenant.id)
    assert by_id.name == "Tenant A"
    assert worker_repo.list_station_skills(str(tenant.id)) == [
        infra_models.WorkerStationSkill(
            id=str(persisted_skill.id),
            tenant_id=str(tenant.id),
            worker_id=str(worker.id),
            station_id=str(station.id),
            created_at=persisted_skill.created_at,
            updated_at=persisted_skill.updated_at,
        )
    ]
    assert workers == [
        infra_models.Worker(
            id=str(worker.id),
            tenant_id=str(tenant.id),
            name="Alex",
            role="cook",
            code="W1",
            is_active=True,
            scheduling_profile_json={
                "shift_prefs": ["DAY"],
                "fixed_days_off": ["Sun"],
                "core": True,
            },
        )
    ]
    assert stations == [
        infra_models.Station(
            id=str(station.id),
            tenant_id=str(tenant.id),
            name="Grill",
            code="GRILL",
            is_active=True,
        )
    ]
    assert shifts == [
        infra_models.ShiftDefinition(
            id=str(DjangoShiftDefinition.objects.get(tenant=tenant, code="DAY").id),
            tenant_id=str(tenant.id),
            code="DAY",
            name="Day",
            paid_hours=Decimal("8.00"),
            is_off_shift=False,
            is_active=True,
        )
    ]


def test_leave_request_repository_returns_framework_neutral_month_rows() -> None:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    other_tenant = DjangoTenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        default_locale="en-US",
    )
    alex = DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
    )
    blair = DjangoWorker.objects.create(
        tenant=tenant,
        code="W2",
        name="Blair",
        role="cook",
        is_active=True,
    )
    other_worker = DjangoWorker.objects.create(
        tenant=other_tenant,
        code="W1",
        name="Jordan",
        role="cashier",
        is_active=True,
    )
    first_leave = DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=alex,
        leave_date=dt.date(2026, 4, 2),
        reason="vacation",
    )
    second_leave = DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=blair,
        leave_date=dt.date(2026, 4, 5),
        reason=None,
    )
    DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=alex,
        leave_date=dt.date(2026, 5, 1),
        reason="next-month",
    )
    DjangoLeaveRequest.objects.create(
        tenant=other_tenant,
        worker=other_worker,
        leave_date=dt.date(2026, 4, 2),
        reason="other-tenant",
    )

    repository = DjangoLeaveRequestRepository()

    assert repository.list_for_month(str(tenant.id), 2026, 4) == [
        infra_models.LeaveRequest(
            id=str(first_leave.id),
            tenant_id=str(tenant.id),
            worker_id=str(alex.id),
            leave_date=dt.date(2026, 4, 2),
            reason="vacation",
            created_at=first_leave.created_at,
            updated_at=first_leave.updated_at,
        ),
        infra_models.LeaveRequest(
            id=str(second_leave.id),
            tenant_id=str(tenant.id),
            worker_id=str(blair.id),
            leave_date=dt.date(2026, 4, 5),
            reason=None,
            created_at=second_leave.created_at,
            updated_at=second_leave.updated_at,
        ),
    ]


def test_constraint_config_repository_resolves_monthly_before_default() -> None:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    other_tenant = DjangoTenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        default_locale="en-US",
    )
    default_config = DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {"GRILL": 1},
            "morning_shifts": ["1"],
            "stations_require_morning": {"GRILL": 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
            "required_chefs_weekday": 1,
            "required_chefs_weekend": 2,
            "allowed_auto_shifts_weekday": ["DAY"],
            "allowed_auto_shifts_weekend": ["M1", "DAY"],
            "max_weekly_hours": 40,
        },
    )
    monthly_config = DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="monthly",
        year=2026,
        month=4,
        config_json={
            "stations": {"GRILL": 2},
            "morning_shifts": ["M1"],
            "stations_require_morning": {"GRILL": 2},
            "min_staff_weekday": 2,
            "min_staff_weekend": 2,
            "max_staff_per_day": 2,
            "min_rest_days_per_month": 4,
            "max_consecutive_days": 5,
            "required_chefs_weekday": 1,
            "required_chefs_weekend": 2,
            "allowed_auto_shifts_weekday": ["DAY", "EVE"],
            "allowed_auto_shifts_weekend": ["M1", "DAY", "EVE"],
            "unsupported_key": "ignored",
        },
    )
    DjangoConstraintConfig.objects.create(
        tenant=other_tenant,
        scope_type="default",
        config_json={"min_staff_weekday": 9},
    )

    repository = DjangoConstraintConfigRepository()

    assert repository.get_resolved_for_month(str(tenant.id), 2026, 4) == (
        infra_models.ConstraintConfig(
            id=str(monthly_config.id),
            tenant_id=str(tenant.id),
            scope_type="monthly",
            year=2026,
            month=4,
            config_json={
                "stations": {"GRILL": 2},
                "morning_shifts": ["M1"],
                "stations_require_morning": {"GRILL": 2},
                "min_staff_weekday": 2,
                "min_staff_weekend": 2,
                "max_staff_per_day": 2,
                "min_rest_days_per_month": 4,
                "max_consecutive_days": 5,
                "required_chefs_weekday": 1,
                "required_chefs_weekend": 2,
                "allowed_auto_shifts_weekday": ["DAY", "EVE"],
                "allowed_auto_shifts_weekend": ["M1", "DAY", "EVE"],
            },
            created_at=monthly_config.created_at,
            updated_at=monthly_config.updated_at,
        )
    )
    assert repository.get_resolved_for_month(str(tenant.id), 2026, 5) == (
        infra_models.ConstraintConfig(
            id=str(default_config.id),
            tenant_id=str(tenant.id),
            scope_type="default",
            year=None,
            month=None,
            config_json={
                "stations": {"GRILL": 1},
                "morning_shifts": ["1"],
                "stations_require_morning": {"GRILL": 1},
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "min_rest_days_per_month": 0,
                "max_consecutive_days": 31,
                "required_chefs_weekday": 1,
                "required_chefs_weekend": 2,
                "allowed_auto_shifts_weekday": ["DAY"],
                "allowed_auto_shifts_weekend": ["M1", "DAY"],
            },
            created_at=default_config.created_at,
            updated_at=default_config.updated_at,
        )
    )
    assert repository.get_resolved_for_month(str(other_tenant.id), 2026, 4) == (
        infra_models.ConstraintConfig(
            id=str(
                DjangoConstraintConfig.objects.get(
                    tenant=other_tenant,
                    scope_type="default",
                ).id
            ),
            tenant_id=str(other_tenant.id),
            scope_type="default",
            year=None,
            month=None,
            config_json={"min_staff_weekday": 9},
            created_at=DjangoConstraintConfig.objects.get(
                tenant=other_tenant,
                scope_type="default",
            ).created_at,
            updated_at=DjangoConstraintConfig.objects.get(
                tenant=other_tenant,
                scope_type="default",
            ).updated_at,
        )
    )
    assert repository.get_resolved_for_month(str(tenant.id), 2027, 1) == (
        infra_models.ConstraintConfig(
            id=str(default_config.id),
            tenant_id=str(tenant.id),
            scope_type="default",
            year=None,
            month=None,
            config_json={
                "stations": {"GRILL": 1},
                "morning_shifts": ["1"],
                "stations_require_morning": {"GRILL": 1},
                "min_staff_weekday": 1,
                "min_staff_weekend": 1,
                "max_staff_per_day": 1,
                "min_rest_days_per_month": 0,
                "max_consecutive_days": 31,
                "required_chefs_weekday": 1,
                "required_chefs_weekend": 2,
                "allowed_auto_shifts_weekday": ["DAY"],
                "allowed_auto_shifts_weekend": ["M1", "DAY"],
            },
            created_at=default_config.created_at,
            updated_at=default_config.updated_at,
        )
    )
    assert repository.get_resolved_for_month("999", 2026, 4) is None


def test_workspace_repository_upserts_single_current_workspace() -> None:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    repository = DjangoWorkspaceRepository()

    first = repository.save_current_workspace(
        infra_models.MonthlyWorkspace(
            tenant_id=str(tenant.id),
            year=2026,
            month=4,
            status="draft",
        )
    )
    second = repository.save_current_workspace(
        replace(first, status="published")
    )

    workspace = DjangoMonthlyWorkspace.objects.get(pk=int(second.id or "0"))
    assert first.id == second.id
    assert second.is_current is True
    assert second.status == "published"
    assert workspace.tenant_id == tenant.id
    assert workspace.source_type == "preview"
    assert DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).count() == 1


def test_workspace_repository_replaces_assignments_and_loads_current_state() -> None:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    worker = DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
    )
    station = DjangoStation.objects.create(
        tenant=tenant,
        code="GRILL",
        name="Grill",
        is_active=True,
    )
    shift = DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    workspace = DjangoMonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=4,
        status="draft",
        source_type="preview",
    )
    old_assignment = DjangoMonthlyAssignment.objects.create(
        workspace=workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker=worker,
        shift_definition=shift,
        station=station,
        assignment_source="seed",
    )

    repository = DjangoWorkspaceRepository()
    replacement = repository.replace_assignments(
        str(workspace.id),
        [
            infra_models.MonthlyAssignment(
                workspace_id=str(workspace.id),
                worker_id=str(worker.id),
                assignment_date=dt.date(2026, 4, 2),
                shift_definition_id=str(shift.id),
                station_id=str(station.id),
            ),
            infra_models.MonthlyAssignment(
                workspace_id=str(workspace.id),
                worker_id=str(worker.id),
                assignment_date=dt.date(2026, 4, 3),
                shift_definition_id=str(shift.id),
                station_id=None,
                note="required_chef",
            ),
        ],
    )
    current = repository.load_current(str(tenant.id), 2026, 4)

    assert current is not None
    assert current.workspace == infra_models.MonthlyWorkspace(
        id=str(workspace.id),
        tenant_id=str(tenant.id),
        year=2026,
        month=4,
        status="draft",
        is_current=True,
        source_version_id=None,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )
    assert len(replacement) == 2
    assert all(isinstance(row, infra_models.MonthlyAssignment) for row in replacement)
    assert {row.assignment_date for row in replacement} == {
        dt.date(2026, 4, 2),
        dt.date(2026, 4, 3),
    }
    assert DjangoMonthlyAssignment.objects.filter(workspace=workspace).count() == 2
    assert not DjangoMonthlyAssignment.objects.filter(pk=old_assignment.pk).exists()
    assert list(
        DjangoMonthlyAssignment.objects.filter(workspace=workspace).values_list(
            "assignment_source",
            flat=True,
        )
    ) == ["apply", "apply"]
    assert list(
        DjangoMonthlyAssignment.objects.filter(workspace=workspace)
        .order_by("assignment_date", "worker_id", "id")
        .values_list("note", flat=True)
    ) == [None, "required_chef"]
    assert current.assignments == replacement


def test_plan_version_repository_persists_and_queries_month_history() -> None:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    april_workspace = DjangoMonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=4,
        status="draft",
        source_type="preview",
    )
    may_workspace = DjangoMonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=5,
        status="draft",
        source_type="preview",
    )
    existing_version = DjangoMonthlyPlanVersion.objects.create(
        workspace=april_workspace,
        tenant=tenant,
        version_number=1,
        label="Baseline",
        summary="Initial save",
        snapshot_json={"workspace_id": april_workspace.id},
    )
    DjangoMonthlyPlanVersion.objects.create(
        workspace=may_workspace,
        tenant=tenant,
        version_number=1,
        label="May baseline",
        summary="May save",
        snapshot_json={"workspace_id": may_workspace.id},
    )

    repository = DjangoPlanVersionRepository()

    assert repository.get_next_version_number(str(tenant.id), 2026, 4) == 2

    saved = repository.save(
        infra_models.MonthlyPlanVersion(
            tenant_id=str(tenant.id),
            year=2026,
            month=4,
            version_number=2,
            snapshot_json={
                "workspace_id": str(april_workspace.id),
                "assignment_ids": ["10", "11"],
            },
            workspace_id=str(april_workspace.id),
            summary="Second save",
        )
    )
    listed = repository.list_for_month(str(tenant.id), 2026, 4)
    loaded = repository.get_by_id(saved.id or "")

    assert isinstance(saved, infra_models.MonthlyPlanVersion)
    assert saved.id is not None
    assert saved.workspace_id == str(april_workspace.id)
    assert saved.year == 2026
    assert saved.month == 4
    assert [version.version_number for version in listed] == [1, 2]
    assert loaded == saved
    assert listed[0].id == str(existing_version.id)
    assert DjangoMonthlyPlanVersion.objects.get(pk=int(saved.id)).label is None


def test_refine_request_repository_persists_and_updates_preview_payloads() -> None:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    workspace = DjangoMonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=4,
        status="draft",
        source_type="preview",
    )
    repository = DjangoRefineRequestRepository()

    created = repository.create(
        infra_models.RefineRequest(
            tenant_id=str(tenant.id),
            workspace_id=str(workspace.id),
            request_text="2026-04-01 の W1 を外して",
            status="received",
        )
    )
    updated = repository.update_parsed_preview(
        created.id or "",
        status="completed",
        parsed_intent_json={
            "request_language": "ja",
            "intent_type": "remove_assignment",
        },
        result_preview_json={"summary": {"total_assignments": 0}},
    )
    listed = repository.list_for_workspace(str(workspace.id))

    assert created.id is not None
    assert updated is not None
    assert updated.status == "completed"
    assert updated.parsed_intent_json == {
        "request_language": "ja",
        "intent_type": "remove_assignment",
    }
    assert updated.result_preview_json == {"summary": {"total_assignments": 0}}
    assert listed == [updated]
