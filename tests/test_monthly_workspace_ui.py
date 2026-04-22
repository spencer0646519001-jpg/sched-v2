from __future__ import annotations

import datetime as dt
import html
import re
from decimal import Decimal

import pytest
from django.test import RequestFactory

from app.api.django_runtime import build_django_monthly_workspace_page_urlpatterns
from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
)
from app.monthly_workspace_demo_data import (
    DEMO_TENANT_NAME,
    DEMO_TENANT_SLUG,
    PRIMARY_DEMO_SHIFT,
    PRIMARY_DEMO_STATION,
    PRIMARY_DEMO_WORKER,
)
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
    assert 'lang="zh"' in html_text
    assert "月度排班工作台" in html_text
    assert 'type="month"' in html_text
    assert "界面语言" in html_text
    assert ">中文</a>" in html_text
    assert ">日本語</a>" in html_text
    assert "请假申请" in html_text
    assert "预览、应用与保存" in html_text
    assert "工作区状态" in html_text
    assert "月度排班结果" in html_text
    assert "警告" in html_text
    assert "细化 / 说明" in html_text
    assert "result-grid-scroll" in html_text
    assert "require_one_chef" not in html_text
    assert "count_chefs_in_headcount" not in html_text


def test_workspace_page_renders_japanese_copy_when_ui_lang_is_ja() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

    response = view(
        RequestFactory().get(
            "/v2/monthly-workspace",
            data={
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert 'lang="ja"' in html_text
    assert "月次シフトワークスペース" in html_text
    assert "表示言語" in html_text
    assert "休暇申請" in html_text
    assert "プレビュー、適用、保存" in html_text
    assert "ワークスペース状態" in html_text
    assert "月次シフト結果" in html_text
    assert "調整 / 説明" in html_text
    assert 'name="ui_lang" value="ja"' in html_text
    assert 'locale-toggle-link is-selected' in html_text


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
                "ui_lang": "zh",
                "worker_id": str(
                    DjangoWorker.objects.get(
                        tenant=tenant,
                        code=PRIMARY_DEMO_WORKER.code,
                    ).pk
                ),
                "leave_date": "2026-04-10",
            },
        )
    )
    add_leave_html = add_leave_response.content.decode()

    assert add_leave_response.status_code == 200
    assert "已为 Spencer 添加 2026-04-10 的请假。" in add_leave_html
    assert "Spencer (SPENCER)" in add_leave_html
    assert DjangoLeaveRequest.objects.count() == 1

    preview_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "preview",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
            },
        )
    )
    preview_html = preview_response.content.decode()
    candidate_result_json = _extract_candidate_result_json(preview_html)

    assert preview_response.status_code == 200
    assert "候选预览已生成，可在应用前先进行审核。" in preview_html
    assert "候选预览" in preview_html
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
                "ui_lang": "zh",
                "candidate_result_json": candidate_result_json,
            },
        )
    )
    apply_html = apply_response.content.decode()

    assert apply_response.status_code == 200
    assert "已将候选预览应用到当前工作区" in apply_html
    assert "当前工作区" in apply_html
    assert DjangoMonthlyWorkspace.objects.count() == 1
    assert DjangoMonthlyAssignment.objects.count() == 29

    save_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "save",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_result_json": candidate_result_json,
                "save_label": "Reviewer baseline",
            },
        )
    )
    save_html = save_response.content.decode()

    assert save_response.status_code == 200
    assert "已保存 2026-04 的版本 1。" in save_html
    assert "已保存版本" in save_html
    assert DjangoMonthlyPlanVersion.objects.count() == 1
    assert DjangoMonthlyPlanVersion.objects.get().summary == "Reviewer baseline"


def test_workspace_preview_post_preserves_selected_japanese_ui_lang() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "preview",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert "候補プレビューの準備ができました。適用前に確認できます。" in html_text
    assert 'name="ui_lang" value="ja"' in html_text
    assert '>月をプレビュー<' in html_text


def test_workspace_page_orders_people_leave_and_grid_rows_chef_first() -> None:
    tenant = _seed_custom_month_context(
        workers=[
            ("Z_CHEF_1", "Chef Alpha", "chef"),
            ("A_COOK", "Cook Alpha", "employee"),
            ("Y_CHEF_2", "Chef Beta", "chef"),
        ]
    )
    chef_beta = DjangoWorker.objects.get(tenant=tenant, code="Y_CHEF_2")
    cook_alpha = DjangoWorker.objects.get(tenant=tenant, code="A_COOK")
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            preview_engine=_FixedPreviewEngine(
                _build_preview_result(
                    AssignmentOutput(
                        date=dt.date(2026, 4, 1),
                        worker_code="A_COOK",
                        shift_code="DAY",
                        station_code="GRILL",
                        source="preview",
                        note=None,
                    )
                )
            )
        )
    }["monthly_schedule_workspace"]

    DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=cook_alpha,
        leave_date=dt.date(2026, 4, 1),
        reason="vacation",
    )
    DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=chef_beta,
        leave_date=dt.date(2026, 4, 2),
        reason="vacation",
    )

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "preview",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert _extract_worker_option_labels(html_text) == [
        "请选择员工",
        "Chef Alpha (Z_CHEF_1)",
        "Chef Beta (Y_CHEF_2)",
        "Cook Alpha (A_COOK)",
    ]
    assert "Chef Beta (Y_CHEF_2): 1" in html_text
    assert "Cook Alpha (A_COOK): 1" in html_text
    assert html_text.index("Chef Beta (Y_CHEF_2): 1") < html_text.index(
        "Cook Alpha (A_COOK): 1"
    )
    assert html_text.index("<strong>Chef Beta (Y_CHEF_2)</strong>") < html_text.index(
        "<strong>Cook Alpha (A_COOK)</strong>"
    )
    assert _extract_grid_worker_names(html_text) == [
        "Chef Alpha",
        "Chef Beta",
        "Cook Alpha",
    ]


def test_workspace_page_renders_required_chef_as_attendance_and_persists_note_on_apply() -> None:
    tenant = _seed_custom_month_context(
        workers=[
            ("CHEF_A", "Chef Anna", "chef"),
            ("COOK_A", "Cook Ben", "employee"),
        ]
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            preview_engine=_FixedPreviewEngine(
                _build_preview_result(
                    AssignmentOutput(
                        date=dt.date(2026, 4, 1),
                        worker_code="CHEF_A",
                        shift_code="DAY",
                        station_code=None,
                        source="preview",
                        note="required_chef",
                    ),
                    AssignmentOutput(
                        date=dt.date(2026, 4, 1),
                        worker_code="COOK_A",
                        shift_code="DAY",
                        station_code="GRILL",
                        source="preview",
                        note=None,
                    ),
                )
            )
        )
    }["monthly_schedule_workspace"]

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
    assert ">WORK<" in preview_html
    assert ">chef attendance<" in preview_html
    assert ">required_chef<" not in preview_html

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
    chef_assignment = DjangoMonthlyAssignment.objects.get(
        workspace__tenant=tenant,
        worker__code="CHEF_A",
    )

    assert apply_response.status_code == 200
    assert ">WORK<" in apply_html
    assert ">chef attendance<" in apply_html
    assert chef_assignment.note == "required_chef"
    assert chef_assignment.station_id is None


def _seed_month_context() -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug=DEMO_TENANT_SLUG,
        name=DEMO_TENANT_NAME,
        default_locale="en-US",
    )
    DjangoWorker.objects.create(
        tenant=tenant,
        code=PRIMARY_DEMO_WORKER.code,
        name=PRIMARY_DEMO_WORKER.name,
        role=PRIMARY_DEMO_WORKER.role,
        is_active=True,
    )
    DjangoStation.objects.create(
        tenant=tenant,
        code=PRIMARY_DEMO_STATION.code,
        name=PRIMARY_DEMO_STATION.name,
        is_active=True,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code=PRIMARY_DEMO_SHIFT.code,
        name=PRIMARY_DEMO_SHIFT.name,
        paid_hours=PRIMARY_DEMO_SHIFT.paid_hours,
        start_time=PRIMARY_DEMO_SHIFT.start_time,
        end_time=PRIMARY_DEMO_SHIFT.end_time,
        is_off_shift=False,
    )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {PRIMARY_DEMO_STATION.code: 1},
            "min_staff_weekday": 1,
            "min_staff_weekend": 1,
            "max_staff_per_day": 1,
            "min_rest_days_per_month": 0,
            "max_consecutive_days": 31,
        },
    )
    return tenant


def _seed_custom_month_context(
    *,
    workers: list[tuple[str, str, str]],
) -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug=DEMO_TENANT_SLUG,
        name=DEMO_TENANT_NAME,
        default_locale="en-US",
    )
    for code, name, role in workers:
        DjangoWorker.objects.create(
            tenant=tenant,
            code=code,
            name=name,
            role=role,
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
        start_time=None,
        end_time=None,
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


class _FixedPreviewEngine:
    def __init__(self, result: MonthPlanningResult) -> None:
        self.result = result

    def __call__(self, planning_input) -> MonthPlanningResult:
        del planning_input
        return self.result


def _build_preview_result(*assignments: AssignmentOutput) -> MonthPlanningResult:
    return MonthPlanningResult(
        assignments=list(assignments),
        warnings=[],
        summary=MonthPlanningSummary(
            total_assignments=len(assignments),
            total_warnings=0,
            assignments_by_worker={},
            paid_hours_by_worker={},
            warnings_by_type={},
        ),
        metadata=MonthPlanningMetadata(
            generated_at=dt.datetime(2026, 4, 12, tzinfo=dt.timezone.utc),
            source_type="preview",
            refinement_applied=False,
            notes=["ui-test"],
        ),
    )


def _extract_worker_option_labels(html_text: str) -> list[str]:
    match = re.search(r'<select name="worker_id">(.*?)</select>', html_text, re.S)
    assert match is not None
    return re.findall(r"<option[^>]*>([^<]+)</option>", match.group(1))


def _extract_grid_worker_names(html_text: str) -> list[str]:
    return re.findall(r'<span class="worker-name">([^<]+)</span>', html_text)


def _extract_candidate_result_json(html_text: str) -> str:
    match = re.search(
        r'name="candidate_result_json" value="([^"]+)"',
        html_text,
    )
    assert match is not None
    return html.unescape(match.group(1))
