from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import re
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from app.api.django_workspace import _build_explain_result_context
from app.api.django_runtime import build_django_monthly_workspace_page_urlpatterns
from app.api.monthly_workspace_copy import get_monthly_workspace_copy
from app.ai.interfaces import AudioTranscriptionRequest, AudioTranscriptionResult, ModelUnavailableError
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
    MonthlyCandidatePreview as DjangoMonthlyCandidatePreview,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
)
from app.services.explain import (
    DayExplainNarrative,
    ExplainDayScheduleResponse,
    ExplainOutcome,
    ExplainSection,
)


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoMonthlyCandidatePreview.objects.all().delete()
    DjangoLeaveRequest.objects.all().delete()
    DjangoConstraintConfig.objects.all().delete()
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
    DjangoShiftDefinition.objects.all().delete()
    DjangoStation.objects.all().delete()
    DjangoWorker.objects.all().delete()
    DjangoTenant.objects.all().delete()


def test_workspace_page_routes_are_registered_separately_from_json_api() -> None:
    patterns = build_django_monthly_workspace_page_urlpatterns()

    assert [pattern.name for pattern in patterns] == [
        "monthly_schedule_workspace",
        "monthly_schedule_workspace_export_csv",
    ]
    assert [str(pattern.pattern) for pattern in patterns] == [
        "v2/monthly-workspace",
        "v2/monthly-workspace/export.csv",
    ]


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
    assert "介面語言" in html_text
    assert ">中文</a>" in html_text
    assert ">日本語</a>" in html_text
    assert "月份" in html_text
    assert "產生預覽" in html_text
    assert "套用候選班表" in html_text
    assert "儲存版本" in html_text
    assert "匯出 CSV" in html_text
    assert "請假申請" in html_text
    assert "評估結果" in html_text
    assert "完整月度排班" in html_text
    assert "說明 / 當日" in html_text
    assert "AI 排班助手" in html_text
    assert "尚未顯示 2026年4月 的候選預覽或目前工作區。" in html_text
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
    assert "月をプレビュー" in html_text
    assert "ワークスペース状態" in html_text
    assert "月次シフト結果" in html_text
    assert "担当者別シフト表" in html_text
    assert "担当者グリック" not in html_text
    assert "担当者グリッド" not in html_text
    assert "説明 / 日別" in html_text
    assert 'placeholder="例: この日のシフト理由を説明して"' in html_text
    assert "Why was 4/1 scheduled this way?" not in html_text
    assert "調整 / 説明" in html_text
    assert "音声入力を使う" in html_text
    assert "音声入力" in html_text
    assert html_text.count(">開始</button>") >= 2
    assert html_text.count(">停止して送信</button>") >= 2
    assert "音声から説明を生成" in html_text
    assert "音声からプレビュー生成" in html_text
    assert "Voice input" not in html_text
    assert "Start recording" not in html_text
    assert "Stop & Submit" not in html_text
    assert "Stop &amp; Submit" not in html_text
    assert "Transcribe & Preview" not in html_text
    assert "Transcribe &amp; Preview" not in html_text
    assert 'name="ui_lang" value="ja"' in html_text
    assert 'locale-toggle-link is-selected' in html_text


def test_workspace_page_shows_disabled_csv_action_without_current_workspace() -> None:
    tenant = _seed_month_context()
    page_copy = get_monthly_workspace_copy("zh")
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
    assert page_copy["actions"]["export_submit"] in html_text
    assert page_copy["actions"]["export_requires_current_workspace"] in html_text
    assert "/v2/monthly-workspace/export.csv" not in html_text


def test_workspace_page_shows_csv_download_link_for_current_workspace() -> None:
    tenant = _seed_month_context()
    page_copy = get_monthly_workspace_copy("zh")
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }
    page_view = views["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(page_view, tenant=tenant, ui_lang="zh")

    response = page_view(
        RequestFactory().get(
            "/v2/monthly-workspace",
            data={"tenant_slug": tenant.slug, "month_scope": "2026-04"},
        )
    )
    html_text = response.content.decode()

    expected_href = html.escape(
        f"/v2/monthly-workspace/export.csv?tenant_slug={tenant.slug}&month_scope=2026-04"
    )

    assert response.status_code == 200
    assert page_copy["actions"]["export_submit"] in html_text
    assert expected_href in html_text


def test_workspace_csv_export_returns_attachment_for_current_workspace() -> None:
    tenant = _seed_month_context()
    views = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }
    page_view = views["monthly_schedule_workspace"]
    export_view = views["monthly_schedule_workspace_export_csv"]
    _apply_current_workspace_via_page(page_view, tenant=tenant, ui_lang="zh")

    response = export_view(
        RequestFactory().get(
            "/v2/monthly-workspace/export.csv",
            data={"tenant_slug": tenant.slug, "month_scope": "2026-04"},
        )
    )
    csv_text = response.content.decode()
    csv_rows = list(csv.reader(io.StringIO(csv_text)))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert (
        response["Content-Disposition"]
        == f'attachment; filename="{tenant.slug}-2026-04-workspace.csv"'
    )
    assert csv_rows[0][:4] == ["worker", "role", "4/1", "4/2"]
    assert csv_rows[0][-1] == "4/30"
    assert csv_rows[1][:4] == [
        PRIMARY_DEMO_WORKER.name,
        PRIMARY_DEMO_WORKER.role,
        f"{PRIMARY_DEMO_SHIFT.code} / Gateau",
        f"{PRIMARY_DEMO_SHIFT.code} / Gateau",
    ]


def test_workspace_csv_export_renders_grid_cells_for_worker_and_chef_rows() -> None:
    tenant = _seed_custom_month_context(
        workers=[
            ("CHEF_A", "Chef Anna", "chef"),
            ("COOK_A", "Cook Ben", "employee"),
        ]
    )
    views = {
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
    }
    page_view = views["monthly_schedule_workspace"]
    export_view = views["monthly_schedule_workspace_export_csv"]
    _apply_current_workspace_via_page(page_view, tenant=tenant, ui_lang="zh")

    response = export_view(
        RequestFactory().get(
            "/v2/monthly-workspace/export.csv",
            data={"tenant_slug": tenant.slug, "month_scope": "2026-04"},
        )
    )
    csv_rows = list(csv.reader(io.StringIO(response.content.decode())))

    assert response.status_code == 200
    assert csv_rows[0][:5] == ["worker", "role", "4/1", "4/2", "4/3"]
    assert csv_rows[0][-1] == "4/30"
    assert csv_rows[1][:4] == ["Chef Anna", "chef", "WORK", "--"]
    assert csv_rows[2][:4] == ["Cook Ben", "employee", "DAY / Grill", "--"]


def test_workspace_csv_export_returns_not_found_without_current_workspace() -> None:
    tenant = _seed_month_context()
    export_view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace_export_csv"]

    response = export_view(
        RequestFactory().get(
            "/v2/monthly-workspace/export.csv",
            data={"tenant_slug": tenant.slug, "month_scope": "2026-04"},
        )
    )

    assert response.status_code == 404
    assert "No current workspace found" in response.content.decode()


def test_workspace_page_selected_tenant_does_not_show_other_tenant_current_workspace() -> None:
    tenant = _seed_named_month_context(
        slug="tenant-a",
        name="Tenant A",
        worker_code="ALEX_A",
        worker_name="Alex A",
        station_code="GRILL_A",
        station_name="Grill A",
        shift_code="DAY_A",
        shift_name="Day A",
    )
    other_tenant = _seed_named_month_context(
        slug="tenant-b",
        name="Tenant B",
        worker_code="BLAIR_B",
        worker_name="Blair B",
        station_code="GRILL_B",
        station_name="Grill B",
        shift_code="DAY_B",
        shift_name="Day B",
    )
    page_copy = get_monthly_workspace_copy("zh")
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=other_tenant, ui_lang="zh")

    response = view(
        RequestFactory().get(
            "/v2/monthly-workspace",
            data={
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert "Alex A" in html_text
    assert "Blair B" not in html_text
    assert page_copy["actions"]["export_requires_current_workspace"] in html_text
    assert html.escape(
        f"/v2/monthly-workspace/export.csv?tenant_slug={tenant.slug}&month_scope=2026-04"
    ) not in html_text


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


def test_workspace_page_places_controls_assistant_evaluation_before_grid() -> None:
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
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    controls_index = html_text.index('id="monthly-controls-title"')
    preview_index = html_text.index(
        '<input type="hidden" name="form_action" value="preview">'
    )
    refine_index = html_text.index(
        '<input type="hidden" name="form_action" value="refine">'
    )
    evaluation_index = html_text.index("<h2>評估結果</h2>")
    grid_index = html_text.index('<div class="result-grid-scroll">')

    assert controls_index < preview_index < refine_index < evaluation_index < grid_index


def test_workspace_preview_summarizes_warnings_before_schedule_grid() -> None:
    tenant = _seed_month_context()
    worker = DjangoWorker.objects.get(
        tenant=tenant,
        code=PRIMARY_DEMO_WORKER.code,
    )
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
                "worker_id": str(worker.pk),
                "leave_date": "2026-04-10",
            },
        )
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

    assert add_leave_response.status_code == 200
    assert response.status_code == 200
    assert "評估結果" in html_text
    assert "有需要注意的排班警告" in html_text
    assert "點擊展開查看詳細警告" in html_text
    assert "詳細警告" in html_text
    assert '<ul class="warning-list">' in html_text
    assert '<div class="result-grid-scroll">' in html_text
    details_match = re.search(
        r'<details class="technical-details">\s*<summary>詳細警告</summary>',
        html_text,
    )
    assert details_match is not None
    assert '<details class="technical-details" open>' not in html_text
    assert html_text.index("<h2>評估結果</h2>") < html_text.index(
        '<div class="result-grid-scroll">'
    )
    assert html_text.index("詳細警告") < html_text.index("understaffed station day")


def test_workspace_preview_shows_neutral_evaluation_when_no_warnings() -> None:
    tenant = _seed_custom_month_context(workers=[("COOK_A", "Cook Alpha", "employee")])
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            preview_engine=_FixedPreviewEngine(
                _build_preview_result(
                    AssignmentOutput(
                        date=dt.date(2026, 4, 1),
                        worker_code="COOK_A",
                        shift_code="DAY",
                        station_code="GRILL",
                        source="preview",
                        note=None,
                    )
                )
            )
        )
    }["monthly_schedule_workspace"]

    response = view(
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
    html_text = response.content.decode()

    assert response.status_code == 200
    assert "評估結果" in html_text
    assert "目前沒有需要注意的警告。" in html_text
    assert "詳細警告" not in html_text
    assert '<ul class="warning-list">' not in html_text


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
    assert "已為 Spencer 新增 2026-04-10 的請假。" in add_leave_html
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
    candidate_id = _extract_candidate_id(preview_html)

    assert preview_response.status_code == 200
    assert "候選預覽已產生，可在套用前先審核。" in preview_html
    assert "候選預覽" in preview_html
    assert "needs_review" in preview_html
    assert "understaffed station day" in preview_html
    assert candidate_id
    assert 'name="candidate_result_json"' not in preview_html

    apply_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_id": candidate_id,
            },
        )
    )
    apply_html = apply_response.content.decode()

    assert apply_response.status_code == 200
    assert "已將候選預覽套用到目前工作區" in apply_html
    assert "目前工作區" in apply_html
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
                "candidate_id": candidate_id,
                "save_label": "Reviewer baseline",
            },
        )
    )
    save_html = save_response.content.decode()

    assert save_response.status_code == 200
    assert "已儲存 2026-04 的版本 1。" in save_html
    assert "已儲存版本" in save_html
    assert DjangoMonthlyPlanVersion.objects.count() == 1
    assert DjangoMonthlyPlanVersion.objects.get().summary == "Reviewer baseline"


def test_workspace_refine_candidate_can_be_applied_via_server_side_candidate_id() -> None:
    tenant = _seed_month_context()
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="zh")

    refine_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "request_text": (
                    f"請把 {PRIMARY_DEMO_WORKER.code} "
                    f"安排到 2026-04-01 的 EVE 在 {PRIMARY_DEMO_STATION.code}"
                ),
            },
        )
    )
    candidate_id = _extract_candidate_id(refine_response.content.decode())

    apply_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_id": candidate_id,
            },
        )
    )
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    current_first_assignment = DjangoMonthlyAssignment.objects.get(
        workspace=current_workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker__code=PRIMARY_DEMO_WORKER.code,
    )

    assert refine_response.status_code == 200
    assert apply_response.status_code == 200
    assert current_first_assignment.shift_definition.code == "EVE"
    assert current_first_assignment.station is not None
    assert current_first_assignment.station.code == PRIMARY_DEMO_STATION.code
    assert current_first_assignment.assignment_source == "apply"


def test_workspace_apply_requires_server_side_candidate_id_and_ignores_browser_json() -> None:
    tenant = _seed_month_context()
    page_copy = get_monthly_workspace_copy("zh")
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

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
    candidate_id = _extract_candidate_id(preview_response.content.decode())
    tampered_candidate_result = _load_candidate_result_json(candidate_id)
    tampered_candidate_result["assignments"][0]["date"] = "2026-05-01"

    apply_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_result_json": json.dumps(tampered_candidate_result),
            },
        )
    )
    html_text = apply_response.content.decode()

    assert preview_response.status_code == 200
    assert apply_response.status_code == 200
    assert page_copy["messages"]["apply_requires_candidate"] in html_text
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_workspace_apply_prefers_server_side_candidate_id_over_tampered_browser_json() -> None:
    tenant = _seed_month_context()
    page_copy = get_monthly_workspace_copy("zh")
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

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
    candidate_id = _extract_candidate_id(preview_response.content.decode())
    tampered_candidate_result = _load_candidate_result_json(candidate_id)
    tampered_candidate_result["assignments"][0]["date"] = "2026-05-01"

    apply_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_id": candidate_id,
                "candidate_result_json": json.dumps(tampered_candidate_result),
            },
        )
    )
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    first_assignment = DjangoMonthlyAssignment.objects.filter(
        workspace=current_workspace
    ).order_by("assignment_date", "worker_id", "id")[0]

    assert preview_response.status_code == 200
    assert apply_response.status_code == 200
    assert (
        page_copy["messages"]["candidate_reuse_failed"]
        not in apply_response.content.decode()
    )
    assert first_assignment.assignment_date == dt.date(2026, 4, 1)
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_apply_rejects_unknown_candidate_id() -> None:
    tenant = _seed_month_context()
    page_copy = get_monthly_workspace_copy("zh")
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_id": "999999",
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert page_copy["messages"]["candidate_reuse_failed"] in html_text
    assert page_copy["messages"]["apply_requires_candidate"] not in html_text
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_workspace_apply_rejects_stale_candidate_after_leave_changes() -> None:
    tenant = _seed_month_context()
    page_copy = get_monthly_workspace_copy("zh")
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

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
    candidate_id = _extract_candidate_id(preview_response.content.decode())
    worker = DjangoWorker.objects.get(tenant=tenant, code=PRIMARY_DEMO_WORKER.code)
    DjangoLeaveRequest.objects.create(
        tenant=tenant,
        worker=worker,
        leave_date=dt.date(2026, 4, 10),
        reason="vacation",
    )

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_id": candidate_id,
            },
        )
    )
    html_text = response.content.decode()

    assert preview_response.status_code == 200
    assert response.status_code == 200
    assert page_copy["messages"]["candidate_reuse_failed"] in html_text
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


def test_workspace_apply_still_rejects_server_side_off_month_candidate_preview() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]

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
    candidate_id = _extract_candidate_id(preview_response.content.decode())
    candidate_preview = DjangoMonthlyCandidatePreview.objects.get(pk=int(candidate_id))
    candidate_preview.result_json["assignments"][0]["date"] = "2026-05-01"
    candidate_preview.save(update_fields=["result_json"])

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "candidate_id": candidate_id,
            },
        )
    )
    html_text = response.content.decode()

    assert preview_response.status_code == 200
    assert response.status_code == 200
    assert (
        "Apply result assignment_date 2026-05-01 must stay within target month 2026-04."
        in html_text
    )
    assert not DjangoMonthlyWorkspace.objects.filter(
        tenant=tenant,
        year=2026,
        month=4,
    ).exists()


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


def test_workspace_page_replaces_refine_placeholder_with_working_form() -> None:
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
    assert 'name="form_action" value="refine"' in html_text
    assert 'name="request_text"' in html_text
    assert "請先把目前計畫套用到月度工作區，再執行調整預覽。" in html_text
    assert "產生調整預覽" in html_text
    assert (
        'class="btn btn-secondary" name="form_action" value="refine" disabled'
        in html_text
    )


def test_workspace_page_renders_bounded_day_explain_form() -> None:
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
    assert 'name="form_action" value="explain"' in html_text
    assert 'name="explain_day"' in html_text
    assert 'name="explain_request_text"' in html_text
    assert "請先產生候選預覽或套用目前工作區，再請求當日說明。" in html_text
    assert "產生當日說明" in html_text
    assert (
        'class="btn btn-secondary" name="form_action" value="explain" disabled'
        in html_text
    )


def test_workspace_page_renders_bounded_voice_upload_controls() -> None:
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
    assert html_text.count('enctype="multipart/form-data"') >= 2
    assert 'name="explain_audio"' in html_text
    assert 'name="refine_audio"' in html_text
    assert 'data-voice-capture="explain"' in html_text
    assert 'data-voice-capture="refine"' in html_text
    assert 'data-audio-field="explain_audio"' in html_text
    assert 'data-audio-field="refine_audio"' in html_text
    assert 'data-submit-action="explain_voice"' in html_text
    assert 'data-submit-action="refine_voice"' in html_text
    assert html_text.count('<details class="voice-details">') >= 2
    assert "語音輸入（Whisper）" in html_text
    assert html_text.count("開始錄音") >= 2
    assert html_text.count("停止並送出") >= 2
    assert "Voice input" not in html_text
    assert "Start recording" not in html_text
    assert "Stop &amp; Submit" not in html_text
    assert "Transcribe &amp; Preview" not in html_text
    assert 'aria-live="polite"' in html_text
    assert "轉錄並產生說明" in html_text
    assert "轉錄並產生預覽" in html_text
    assert "navigator.mediaDevices.getUserMedia" in html_text
    assert "MediaRecorder" in html_text
    assert "此瀏覽器不支援頁面內錄音。你仍可上傳音訊。" in html_text


@pytest.mark.parametrize(
    ("ui_lang", "request_category", "expected_headline"),
    [
        ("zh", "day_overview", "2026-04-01 的排班說明"),
        ("ja", "refine_change_summary", "2026-04-01 の日別説明"),
    ],
)
def test_workspace_explain_result_context_uses_canonical_day_headline(
    ui_lang: str,
    request_category: str,
    expected_headline: str,
) -> None:
    explain_result = _build_explain_result_context(
        response=ExplainDayScheduleResponse(
            tenant_slug="tenant-a",
            year=2026,
            month=4,
            target_date=dt.date(2026, 4, 1),
            workspace_id=1,
            status="ready",
            request_language=ui_lang,
            response_language=ui_lang,
            outcome=ExplainOutcome(
                language=ui_lang,
                status="ready",
                message_key="explain_ready",
            ),
            parsed_request_json={
                "intent_status": "supported",
                "request_category": request_category,
                "model_used": True,
                "fallback_used": False,
            },
            context_facts={
                "target_date": "2026-04-01",
                "source_mode": (
                    "candidate_preview"
                    if request_category == "refine_change_summary"
                    else "current_workspace"
                ),
            },
            explanation=DayExplainNarrative(
                headline="model-authored headline",
                sections=[
                    ExplainSection(
                        key="assignments",
                        title="Assignments",
                        items=["W1 -> DAY / GRILL"],
                    )
                ],
                model_used=True,
                fallback_used=False,
            ),
        ),
        page_copy=get_monthly_workspace_copy(ui_lang),
    )

    assert explain_result["headline"] == expected_headline


def test_workspace_explain_post_supports_current_workspace_day_explanation() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="zh")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "explain",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "explain_day": "2026-04-01",
                "explain_request_text": "",
            },
        )
    )
    html_text = response.content.decode()
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )

    assert response.status_code == 200
    assert "已產生當日排班說明。" in html_text
    assert "2026-04-01 的排班說明" in html_text
    assert "目前工作區" in html_text
    assert 'name="ui_lang" value="zh"' in html_text
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_explain_post_supports_preview_change_explanation() -> None:
    tenant = _seed_month_context()
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="ja")

    refine_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
                "request_text": (
                    f"2026-04-01 の {PRIMARY_DEMO_WORKER.code} を "
                    f"EVE の {PRIMARY_DEMO_STATION.code} にして"
                ),
            },
        )
    )
    refine_html = refine_response.content.decode()

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "explain",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
                "explain_day": "2026-04-01",
                "explain_request_text": "このプレビューの変更を説明して",
                "candidate_id": _extract_candidate_id(refine_html),
            },
        )
    )
    html_text = response.content.decode()
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )

    assert response.status_code == 200
    assert "この日の説明を生成しました。" in html_text
    assert "2026-04-01 の日別説明" in html_text
    assert "候補プレビュー" in html_text
    assert "プレビュー差分" in html_text
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_explain_post_rejects_non_scheduling_request() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="ja")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "explain",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
                "explain_day": "2026-04-01",
                "explain_request_text": "春の俳句を書いて",
            },
        )
    )
    html_text = response.content.decode()
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )

    assert response.status_code == 200
    assert "この画面では排班関連の日別説明のみ対応しています。" in html_text
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_voice_refine_upload_transcribes_and_routes_into_preview_only_flow() -> None:
    tenant = _seed_month_context()
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
    transcriber = _RecordingAudioTranscriptionClient(
        text=(
            f"請把 {PRIMARY_DEMO_WORKER.code} "
            f"安排到 2026-04-01 的 EVE 在 {PRIMARY_DEMO_STATION.code}"
        ),
        language="zh",
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            transcription_client=transcriber
        )
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="zh")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine_voice",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "refine_audio": _audio_upload(
                    "refine.webm",
                    content=b"\x1aE\xdf\xa3schedv2-refine",
                    content_type="audio/webm",
                ),
            },
        )
    )
    html_text = response.content.decode()
    candidate_result = _load_candidate_result_json(_extract_candidate_id(html_text))
    refined_first_day_assignment = next(
        assignment
        for assignment in candidate_result["assignments"]
        if assignment["date"] == "2026-04-01"
        and assignment["worker_code"] == PRIMARY_DEMO_WORKER.code
    )
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    current_first_assignment = DjangoMonthlyAssignment.objects.get(
        workspace=current_workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker__code=PRIMARY_DEMO_WORKER.code,
    )

    assert response.status_code == 200
    assert len(transcriber.calls) == 1
    assert transcriber.calls[0]["filename"] == "refine.webm"
    assert transcriber.calls[0]["content_type"] == "audio/webm"
    assert "語音調整請求已透過 whisper-1 轉錄" in html_text
    assert "安排到 2026-04-01 的 EVE" in html_text
    assert refined_first_day_assignment == {
        "date": "2026-04-01",
        "worker_code": PRIMARY_DEMO_WORKER.code,
        "shift_code": "EVE",
        "source": "adjustment_patch",
        "station_code": PRIMARY_DEMO_STATION.code,
        "note": "langgraph_refine_preview",
    }
    assert current_first_assignment.shift_definition.code == PRIMARY_DEMO_SHIFT.code
    assert current_first_assignment.assignment_source == "apply"
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_voice_refine_does_not_use_other_tenant_current_workspace() -> None:
    tenant = _seed_named_month_context(
        slug="tenant-a",
        name="Tenant A",
        worker_code="ALEX_A",
        worker_name="Alex A",
        station_code="GRILL_A",
        station_name="Grill A",
        shift_code="DAY_A",
        shift_name="Day A",
    )
    other_tenant = _seed_named_month_context(
        slug="tenant-b",
        name="Tenant B",
        worker_code="BLAIR_B",
        worker_name="Blair B",
        station_code="GRILL_B",
        station_name="Grill B",
        shift_code="DAY_B",
        shift_name="Day B",
    )
    page_copy = get_monthly_workspace_copy("zh")
    transcriber = _RecordingAudioTranscriptionClient(
        text="請把 ALEX_A 安排到 2026-04-01。",
        language="zh",
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            transcription_client=transcriber
        )
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=other_tenant, ui_lang="zh")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine_voice",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "refine_audio": _audio_upload(
                    "refine.webm",
                    content=b"\x1aE\xdf\xa3schedv2-refine-tenant-a",
                    content_type="audio/webm",
                ),
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert len(transcriber.calls) == 1
    assert "語音調整請求已透過 whisper-1 轉錄" in html_text
    assert page_copy["messages"]["refine_requires_current_workspace"] in html_text
    assert "Blair B" not in html_text


def test_workspace_voice_explain_upload_transcribes_and_routes_into_existing_gate() -> None:
    tenant = _seed_month_context()
    transcriber = _RecordingAudioTranscriptionClient(
        text="Why was 4/1 scheduled this way?",
        language="en",
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            transcription_client=transcriber
        )
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="zh")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "explain_voice",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "explain_day": "2026-04-01",
                "explain_audio": _audio_upload(
                    "explain.webm",
                    content=b"\x1aE\xdf\xa3schedv2-explain",
                    content_type="audio/webm",
                ),
            },
        )
    )
    html_text = response.content.decode()
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )

    assert response.status_code == 200
    assert len(transcriber.calls) == 1
    assert transcriber.calls[0]["filename"] == "explain.webm"
    assert transcriber.calls[0]["content_type"] == "audio/webm"
    assert "語音說明請求已透過 whisper-1 轉錄" in html_text
    assert "Why was 4/1 scheduled this way?" in html_text
    assert "Schedule explanation for 2026-04-01" in html_text
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_voice_explain_rejects_non_scheduling_transcript_through_existing_gate() -> None:
    tenant = _seed_month_context()
    transcriber = _RecordingAudioTranscriptionClient(
        text="Write a marketing slogan for my restaurant.",
        language="en",
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            transcription_client=transcriber
        )
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="ja")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "explain_voice",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
                "explain_day": "2026-04-01",
                "explain_audio": _audio_upload("explain.wav"),
            },
        )
    )
    html_text = response.content.decode()
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )

    assert response.status_code == 200
    assert len(transcriber.calls) == 1
    assert (
        "Only scheduling-related day explanation requests are supported here."
        in html_text
    )
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_voice_upload_rejects_invalid_audio_type_before_transcription() -> None:
    tenant = _seed_month_context()
    transcriber = _RecordingAudioTranscriptionClient(text="unused", language="en")
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            transcription_client=transcriber
        )
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="zh")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine_voice",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "refine_audio": _audio_upload(
                    "notes.txt",
                    content=b"not audio",
                    content_type="text/plain",
                ),
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert "語音輸入僅支援 mp3、mp4、m4a、ogg、wav、webm 檔案。" in html_text
    assert transcriber.calls == []


def test_workspace_voice_upload_reports_transcription_unavailable_safely() -> None:
    tenant = _seed_month_context()
    transcriber = _RecordingAudioTranscriptionClient(
        fail_reason="Voice transcription is unavailable for this workspace."
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns(
            transcription_client=transcriber
        )
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="zh")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine_voice",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "refine_audio": _audio_upload("refine.wav"),
            },
        )
    )
    html_text = response.content.decode()

    assert response.status_code == 200
    assert "Voice transcription is unavailable for this workspace." in html_text
    assert len(transcriber.calls) == 1


def test_workspace_refine_post_supports_bounded_chinese_preview_without_mutating_current_workspace() -> None:
    tenant = _seed_month_context()
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code="EVE",
        name="Evening",
        paid_hours=Decimal("6.00"),
        is_off_shift=False,
    )
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="zh")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "zh",
                "request_text": (
                    f"請把 {PRIMARY_DEMO_WORKER.code} "
                    f"安排到 2026-04-01 的 EVE 在 {PRIMARY_DEMO_STATION.code}"
                ),
            },
        )
    )
    html_text = response.content.decode()
    candidate_result = _load_candidate_result_json(_extract_candidate_id(html_text))
    refined_first_day_assignment = next(
        assignment
        for assignment in candidate_result["assignments"]
        if assignment["date"] == "2026-04-01"
        and assignment["worker_code"] == PRIMARY_DEMO_WORKER.code
    )
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )
    current_first_assignment = DjangoMonthlyAssignment.objects.get(
        workspace=current_workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker__code=PRIMARY_DEMO_WORKER.code,
    )

    assert response.status_code == 200
    assert "已產生調整預覽。" in html_text
    assert 'name="ui_lang" value="zh"' in html_text
    assert "我理解你要做的是：" in html_text
    assert "變更" in html_text
    assert refined_first_day_assignment == {
        "date": "2026-04-01",
        "worker_code": PRIMARY_DEMO_WORKER.code,
        "shift_code": "EVE",
        "source": "adjustment_patch",
        "station_code": PRIMARY_DEMO_STATION.code,
        "note": "langgraph_refine_preview",
    }
    assert current_first_assignment.shift_definition.code == PRIMARY_DEMO_SHIFT.code
    assert current_first_assignment.assignment_source == "apply"
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_refine_post_supports_bounded_japanese_remove_preview() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="ja")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
                "request_text": f"2026-04-01 の {PRIMARY_DEMO_WORKER.code} を外して",
            },
        )
    )
    html_text = response.content.decode()
    candidate_result = _load_candidate_result_json(_extract_candidate_id(html_text))
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )

    assert response.status_code == 200
    assert "削除プレビューを生成しました。" in html_text
    assert 'name="ui_lang" value="ja"' in html_text
    assert not any(
        assignment["date"] == "2026-04-01"
        and assignment["worker_code"] == PRIMARY_DEMO_WORKER.code
        for assignment in candidate_result["assignments"]
    )
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


def test_workspace_refine_post_shows_safe_same_language_unsupported_state() -> None:
    tenant = _seed_month_context()
    view = {
        pattern.name: pattern.callback
        for pattern in build_django_monthly_workspace_page_urlpatterns()
    }["monthly_schedule_workspace"]
    _apply_current_workspace_via_page(view, tenant=tenant, ui_lang="ja")

    response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "refine",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": "ja",
                "request_text": f"2026-04-01 の {PRIMARY_DEMO_WORKER.code} を確認して",
            },
        )
    )
    html_text = response.content.decode()
    current_workspace = DjangoMonthlyWorkspace.objects.get(
        tenant=tenant,
        year=2026,
        month=4,
    )

    assert response.status_code == 200
    assert (
        "このアシスタントはシフト調整のみ対応しています。"
        "シフト関連の依頼を入力してください。"
    ) in html_text
    assert 'name="candidate_id" value=""' in html_text
    assert DjangoMonthlyAssignment.objects.filter(workspace=current_workspace).count() == 30


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
        "請選擇員工",
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
    candidate_id = _extract_candidate_id(preview_html)

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
                "candidate_id": candidate_id,
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


class _RecordingAudioTranscriptionClient:
    def __init__(
        self,
        *,
        text: str | None = None,
        language: str | None = None,
        fail_reason: str | None = None,
    ) -> None:
        self.text = text or ""
        self.language = language
        self.fail_reason = fail_reason
        self.calls: list[dict[str, object]] = []

    def transcribe_audio(
        self,
        *,
        request: AudioTranscriptionRequest,
    ) -> AudioTranscriptionResult:
        self.calls.append(
            {
                "filename": request.filename,
                "content_type": request.content_type,
                "audio_size": len(request.audio_bytes),
                "prompt": request.prompt,
            }
        )
        if self.fail_reason is not None:
            raise ModelUnavailableError(self.fail_reason)
        return AudioTranscriptionResult(
            text=self.text,
            language=self.language,
            model="whisper-1",
            provider="openai",
        )


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


def _seed_named_month_context(
    *,
    slug: str,
    name: str,
    worker_code: str,
    worker_name: str,
    station_code: str,
    station_name: str,
    shift_code: str,
    shift_name: str,
) -> DjangoTenant:
    tenant = DjangoTenant.objects.create(
        slug=slug,
        name=name,
        default_locale="en-US",
    )
    DjangoWorker.objects.create(
        tenant=tenant,
        code=worker_code,
        name=worker_name,
        role="cook",
        is_active=True,
    )
    DjangoStation.objects.create(
        tenant=tenant,
        code=station_code,
        name=station_name,
        is_active=True,
    )
    DjangoShiftDefinition.objects.create(
        tenant=tenant,
        code=shift_code,
        name=shift_name,
        paid_hours=Decimal("8.00"),
        start_time=None,
        end_time=None,
        is_off_shift=False,
    )
    DjangoConstraintConfig.objects.create(
        tenant=tenant,
        scope_type="default",
        config_json={
            "stations": {station_code: 1},
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


def _apply_current_workspace_via_page(view, *, tenant: DjangoTenant, ui_lang: str) -> None:
    preview_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "preview",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": ui_lang,
            },
        )
    )
    candidate_id = _extract_candidate_id(
        preview_response.content.decode()
    )

    apply_response = view(
        RequestFactory().post(
            "/v2/monthly-workspace",
            data={
                "form_action": "apply",
                "tenant_slug": tenant.slug,
                "month_scope": "2026-04",
                "ui_lang": ui_lang,
                "candidate_id": candidate_id,
            },
        )
    )

    assert preview_response.status_code == 200
    assert apply_response.status_code == 200


def _audio_upload(
    filename: str,
    *,
    content: bytes = b"RIFFschedv2",
    content_type: str = "audio/wav",
) -> SimpleUploadedFile:
    return SimpleUploadedFile(filename, content, content_type=content_type)


def _extract_worker_option_labels(html_text: str) -> list[str]:
    match = re.search(r'<select name="worker_id">(.*?)</select>', html_text, re.S)
    assert match is not None
    return re.findall(r"<option[^>]*>([^<]+)</option>", match.group(1))


def _extract_grid_worker_names(html_text: str) -> list[str]:
    return re.findall(r'<span class="worker-name">([^<]+)</span>', html_text)


def _extract_candidate_id(html_text: str) -> str:
    match = re.search(
        r'name="candidate_id" value="([^"]*)"',
        html_text,
    )
    assert match is not None
    return html.unescape(match.group(1))


def _load_candidate_result_json(candidate_id: str) -> dict[str, object]:
    return DjangoMonthlyCandidatePreview.objects.get(pk=int(candidate_id)).result_json
