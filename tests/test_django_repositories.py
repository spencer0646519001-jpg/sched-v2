from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest

from app.infra import models as infra_models
from app.infra.django_app.models import (
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
)
from app.infra.django_repositories import (
    DjangoPlanVersionRepository,
    DjangoShiftRepository,
    DjangoStationRepository,
    DjangoTenantRepository,
    DjangoWorkerRepository,
    DjangoWorkspaceRepository,
)


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
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
    DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
    )
    DjangoWorker.objects.create(
        tenant=other_tenant,
        code="W2",
        name="Jordan",
        role="cashier",
        is_active=True,
    )
    DjangoStation.objects.create(
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
    assert worker_repo.list_station_skills(str(tenant.id)) == []
    assert workers == [
        infra_models.Worker(
            id=str(DjangoWorker.objects.get(tenant=tenant, code="W1").id),
            tenant_id=str(tenant.id),
            name="Alex",
            role="cook",
            code="W1",
            is_active=True,
        )
    ]
    assert stations == [
        infra_models.Station(
            id=str(DjangoStation.objects.get(tenant=tenant, code="GRILL").id),
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
