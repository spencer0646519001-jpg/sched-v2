from __future__ import annotations

import html
import re
from decimal import Decimal

import pytest
from django.test import RequestFactory

from app.api.django_runtime import build_django_monthly_workspace_page_urlpatterns
from app.infra.django_app.models import (
    ConstraintConfig as DjangoConstraintConfig,
    LeaveRequest as DjangoLeaveRequest,
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
)


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoLeaveRequest.objects.all().delete()
    DjangoConstraintConfig.objects.all().delete()
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
    DjangoShiftDefinition.objects.all().delete()
    DjangoStation.objects.all().delete()
    DjangoWorker.objects.all().delete()
    DjangoTenant.objects.all().delete()


def test_workspace_page_route_is_registered_separately_from_json_api() -> None:
    patterns = build_django_monthly_workspace_page_urlpatterns()

    assert [pattern.name for pattern in patterns] == ["monthly_schedule_workspace"]
    assert [str(pattern.pattern) for pattern in patterns] == ["v2/monthly-workspace"]


def test_workspace_page_renders_reviewer_visible_structure_without_config_controls() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

    response = view(
        RequestFactory().get(
            "/v2/monthly-workspace",
            data={"tenant_slug": tenant.slug, "month_scope": "2026-04"},
        )
    )

    html_text = response.content.decode()

    assert response.status_code == 200
    assert "Monthly Scheduling Workspace" in html_text
    assert 'type="month"' in html_text
    assert "Leave requests" in html_text
    assert "Preview, apply, and save" in html_text
    assert "Workspace state" in html_text
    assert "Monthly schedule result" in html_text
    assert "Warnings" in html_text
    assert "Refine / explain" in html_text
    assert "result-grid-scroll" in html_text
    assert "require_one_chef" not in html_text
    assert "count_chefs_in_headcount" not in html_text


def test_workspace_page_css_keeps_overflow_scoped_to_grid_and_state_cards_wrapping() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

    response = view(
        RequestFactory().get(
            "/v2/monthly-workspace",
            data={"tenant_slug": tenant.slug, "month_scope": "2026-04"},
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert ".panel {" in html_text
    assert "min-width: 0;" in html_text
    assert "grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));" in html_text
    assert ".result-grid-scroll {" in html_text
    assert "max-width: 100%;" in html_text
    assert "overflow-x: auto;" in html_text


def test_workspace_page_supports_leave_preview_apply_and_save_flow() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

    add_leave_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "add_leave",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "worker_id": str(
                    DjangoWorker.objects.get(tenant=tenant, code="W1").pk
                ),
                "leave_date": "2026-04-10",
            },
        )
    )
    add_leave_html = add_leave_response.content.decode()

    assert add_leave_response.status_code == 200
    assert "Added leave for Alex on 2026-04-10." in add_leave_html
    assert "Alex (W1)" in add_leave_html
    assert DjangoLeaveRequest.objects.count() == 1

    preview_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "preview",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
            },
        )
    )
    preview_html = preview_response.content.decode()
    candidate_result_json = _extract_candidate_result_json(preview_html)

    assert preview_response.status_code == 200
    assert "Candidate preview is ready for review before you apply it." in preview_html
    assert "Candidate preview" in preview_html
    assert "needs_review" in preview_html
    assert "understaffed station day" in preview_html
    assert candidate_result_json

    apply_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "candidate_result_json": candidate_result_json,
            },
        )
    )
    apply_html = apply_response.content.decode()

    assert apply_response.status_code == 200
    assert "Applied the candidate preview to the current workspace" in apply_html
    assert "Current workspace" in apply_html
    assert DjangoMonthlyWorkspace.objects.count() == 1
    assert DjangoMonthlyAssignment.objects.count() == 29

    save_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "save",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "candidate_result_json": candidate_result_json,
                "save_label": "Reviewer baseline",
            },
        )
    )
    save_html = save_response.content.decode()

    assert save_response.status_code == 200
    assert "Saved version 1 for 2026-04." in save_html
    assert "Saved versions" in save_html
    assert DjangoMonthlyPlanVersion.objects.count() == 1
    assert DjangoMonthlyPlanVersion.objects.get().summary == "Reviewer baseline"


def _seed_month_context() -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    DjangoWorker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
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
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {"GRILL": 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
        },
    )
    return tenant


def _extract_candidate_result_json(html_text: str) -> str:
    match = re.search(
        r'name="candidate_result_json" value="([^"]+)"',
        html_text,
    )
    assert match is not None
    return html.unescape(match.group(1))
