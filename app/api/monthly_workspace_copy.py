"""Page-scoped copy helpers for the monthly workspace locale slice."""

from __future__ import annotations

import calendar
from typing import Any

MONTHLY_WORKSPACE_UI_LANGUAGE_LABELS: dict[str, str] = {
    "zh": "中文",
    "ja": "日本語",
}

_MONTHLY_WORKSPACE_COPY: dict[str, dict[str, Any]] = {
    "zh": {
        "html_lang": "zh",
        "page_title": "月度排班工作台",
        "hero": {
            "eyebrow": "月度排班工作区",
            "title": "月度排班工作台",
            "description": (
                "按月查看排班：添加请假、预览候选结果、应用到当前工作区、"
                "保存版本，并在同一页面检查人员月历表。"
            ),
        },
        "toggle": {
            "label": "界面语言",
            "aria_label": "切换界面语言",
        },
        "workflow_steps": [
            "1. 选择月份",
            "2. 添加请假",
            "3. 预览",
            "4. 应用",
            "5. 保存",
            "6. 查看月度排班结果",
        ],
        "scope": {
            "kicker": "月份范围",
            "title": "打开月度工作台",
            "description": "保留熟悉的月份选择流程，同时确定当前工作区范围。",
            "workspace_label": "工作区",
            "no_tenant": "暂无租户数据",
            "month_label": "月份",
            "submit": "打开月份",
        },
        "leave": {
            "kicker": "请假申请",
            "title": "让请假在流程中保持可见",
            "description": "在预览排班前，先用同一套面向审核者的请假流程。",
            "person_label": "员工",
            "select_worker": "请选择员工",
            "date_label": "请假日期",
            "submit": "添加请假",
            "summary_note": "当前 {month_label} 请假汇总",
            "empty": "尚未为 {month_label} 添加请假申请。",
        },
        "actions": {
            "kicker": "主要操作",
            "title": "预览、应用与保存",
            "description": "让主流程保持清晰，次要细节尽量收起。",
            "preview_title": "预览",
            "preview_description": "基于所选月份和请假输入生成新的候选结果。",
            "preview_submit": "预览月份",
            "apply_title": "应用",
            "apply_description": "将当前可见的候选预览提升为可编辑的当前工作区。",
            "apply_submit": "应用预览",
            "save_title": "保存",
            "save_description": "把当前工作区快照为不可变的已保存版本。",
            "save_label": "版本标签",
            "save_placeholder": "可选，供审核者识别",
            "save_submit": "保存版本",
            "footer_note": (
                "预览是只读的。应用会更新当前工作区。保存会为所选月份创建不可变历史。"
            ),
        },
        "state": {
            "kicker": "工作区状态",
            "title": "让当前系统状态一目了然",
            "description": (
                "用轻量摘要帮助审核者理解此工作区当前已有内容，而不暴露规划器配置开关。"
            ),
        },
        "result": {
            "kicker": "月度排班结果",
            "title": "查看人员排班表",
            "description": "在窄屏上优先使用横向滚动，保持月度表格可读。",
            "person_header": "员工",
            "empty": "尚未显示 {month_label} 的候选预览或当前工作区。",
        },
        "warnings": {
            "kicker": "警告",
            "title": "让面向审核者的警告保持可读",
            "description": (
                "预览警告会显示在这里，但不会宣称后端已支持超出当前范围的能力。"
            ),
            "date_label": "日期",
            "worker_label": "员工",
            "month_value": "当月",
            "system_value": "系统",
            "no_details": "无额外详情。",
            "empty_no_current": "生成候选预览后，预览警告会显示在这里。",
            "empty_with_current": (
                "生成候选预览后，预览警告会显示在这里。当前工作区警告尚未持久化。"
            ),
        },
        "refine": {
            "kicker": "细化 / 说明",
            "title": "为后续阶段预留",
            "description": "保留这块区域，但不假装本 PR 已完成自然语言调整流程。",
            "body": (
                "自然语言细化和说明目前仍是一个诚实的占位区。这个页面会先预留工作区"
                "位置，但不会伪装成已完成实现。"
            ),
            "placeholder": "预留：自然语言调整与说明将在后续阶段加入。",
            "button": "后续阶段开放",
        },
        "messages": {
            "invalid_scope": "月份选择必须使用 YYYY-MM 月份选择器格式。",
            "no_tenant": "月度工作台目前还没有可用的租户数据。",
            "candidate_reuse_failed": "无法复用已保存的候选预览，请重新预览该月份。",
            "apply_requires_candidate": "请先生成候选预览，再应用到月份工作区。",
            "unknown_action": "未知的工作台操作。",
            "choose_person_and_date": "添加请假前请先选择员工和日期。",
            "selected_person_not_found": "未找到所选员工。",
            "invalid_leave_date": "请假日期必须使用原生日期选择器的值。",
            "leave_outside_scope": "请假申请必须保留在当前所选月份工作区内。",
            "leave_added": "已为 {worker_name} 添加 {leave_date} 的请假。",
            "leave_exists": "{worker_name} 在 {leave_date} 的请假已存在。",
            "candidate_ready": "候选预览已生成，可在应用前先进行审核。",
            "applied_candidate": "已将候选预览应用到当前工作区（{assignment_count} 条排班）。",
            "saved_version": "已保存 {month_value} 的版本 {version_number}。",
        },
        "state_cards": {
            "candidate_preview_label": "候选预览",
            "current_workspace_label": "当前工作区",
            "saved_versions_label": "已保存版本",
            "evaluation_label": "评估",
            "present": "有",
            "none": "无",
            "candidate_preview_note": "来自最近一次预览操作的只读结果。",
            "current_workspace_note": "“应用”会更新的可变月份状态。",
            "saved_versions_note": "通过“保存”创建的不可变月份快照。",
            "evaluation_note": "先生成预览，再评估该月份。",
            "evaluation_visible_note": "评估结果反映当前可见的候选预览。",
        },
        "display": {
            "candidate_badge": "候选预览",
            "candidate_description": "显示的是尚未应用到工作区的当前只读预览。",
            "current_badge": "当前工作区",
            "current_description": "显示的是“应用”会更新、“保存”会快照的可变工作区。",
            "source_label": "来源",
            "assignments_label": "排班数",
            "warnings_label": "警告数",
            "status_label": "状态",
            "month_label": "月份",
        },
    },
    "ja": {
        "html_lang": "ja",
        "page_title": "月次シフトワークスペース",
        "hero": {
            "eyebrow": "月次計画ワークスペース",
            "title": "月次シフトワークスペース",
            "description": (
                "1か月ずつ確認しながら、休暇追加、候補プレビュー、現在ワークスペース"
                "への適用、バージョン保存、月次の担当者グリッド確認を同じ画面で行います。"
            ),
        },
        "toggle": {
            "label": "表示言語",
            "aria_label": "表示言語を切り替える",
        },
        "workflow_steps": [
            "1. 月を選択",
            "2. 休暇を追加",
            "3. プレビュー",
            "4. 適用",
            "5. 保存",
            "6. 月次シフト結果を確認",
        ],
        "scope": {
            "kicker": "対象月",
            "title": "月次ワークスペースを開く",
            "description": "慣れた月選択フローを保ちながら、表示対象のワークスペースを決めます。",
            "workspace_label": "ワークスペース",
            "no_tenant": "利用可能なテナントデータはありません",
            "month_label": "月",
            "submit": "月を開く",
        },
        "leave": {
            "kicker": "休暇申請",
            "title": "休暇をワークフロー内で見えるままにする",
            "description": "月次プレビューの前に、同じレビュアー向けの休暇フローを使います。",
            "person_label": "担当者",
            "select_worker": "担当者を選択",
            "date_label": "休暇日",
            "submit": "休暇を追加",
            "summary_note": "{month_label} の休暇サマリー",
            "empty": "{month_label} にはまだ休暇申請がありません。",
        },
        "actions": {
            "kicker": "主要アクション",
            "title": "プレビュー、適用、保存",
            "description": "主要フローを読みやすく保ち、補足情報は必要以上に前面へ出しません。",
            "preview_title": "プレビュー",
            "preview_description": "選択した月と休暇入力から新しい候補結果を作成します。",
            "preview_submit": "月をプレビュー",
            "apply_title": "適用",
            "apply_description": "表示中の候補プレビューを、編集可能な現在ワークスペースへ反映します。",
            "apply_submit": "プレビューを適用",
            "save_title": "保存",
            "save_description": "現在ワークスペースを不変の保存版としてスナップショットします。",
            "save_label": "バージョンラベル",
            "save_placeholder": "任意: レビュアー向けラベル",
            "save_submit": "バージョンを保存",
            "footer_note": (
                "プレビューは読み取り専用です。適用は現在ワークスペースを更新します。"
                "保存は選択月の不変な履歴を作成します。"
            ),
        },
        "state": {
            "kicker": "ワークスペース状態",
            "title": "現在のシステム状態をひと目で把握できるようにする",
            "description": (
                "軽いサマリーで、このワークスペースに何が存在するかをレビュアーが理解"
                "しやすくしつつ、プランナー設定のトグルは見せません。"
            ),
        },
        "result": {
            "kicker": "月次シフト結果",
            "title": "担当者グリッドを確認する",
            "description": "狭い画面ではセルを詰め込むより横スクロールを優先して可読性を保ちます。",
            "person_header": "担当者",
            "empty": "{month_label} ではまだ候補プレビューも現在ワークスペースも表示されていません。",
        },
        "warnings": {
            "kicker": "警告",
            "title": "レビュアー向け警告を読みやすく保つ",
            "description": (
                "プレビュー警告はここに表示しますが、現在のバックエンド範囲を超える"
                "機能があるかのようには見せません。"
            ),
            "date_label": "日付",
            "worker_label": "担当者",
            "month_value": "当月",
            "system_value": "システム",
            "no_details": "追加の詳細はありません。",
            "empty_no_current": "候補プレビューを生成すると、プレビュー警告がここに表示されます。",
            "empty_with_current": (
                "候補プレビューを生成すると、プレビュー警告がここに表示されます。"
                "現在ワークスペースの警告はまだ永続化されていません。"
            ),
        },
        "refine": {
            "kicker": "調整 / 説明",
            "title": "後続フェーズ用の予約領域",
            "description": "自然言語による調整フローがこの PR で完成しているかのようには見せません。",
            "body": (
                "自然言語の調整と説明は、今のところ正直なプレースホルダーのままです。"
                "このページでは領域だけ確保し、完成済みの実装を装いません。"
            ),
            "placeholder": "予約済み: 自然言語による調整と説明は後続フェーズで追加されます。",
            "button": "後続フェーズで対応",
        },
        "messages": {
            "invalid_scope": "月の選択には YYYY-MM 形式の月ピッカー値を使用してください。",
            "no_tenant": "月次ワークスペースで利用できるテナントデータがまだありません。",
            "candidate_reuse_failed": "保存済みの候補プレビューを再利用できませんでした。もう一度月をプレビューしてください。",
            "apply_requires_candidate": "月へ適用する前に、候補プレビューを生成してください。",
            "unknown_action": "不明なワークスペース操作です。",
            "choose_person_and_date": "休暇を追加する前に、担当者と日付を選択してください。",
            "selected_person_not_found": "選択した担当者が見つかりません。",
            "invalid_leave_date": "休暇日はネイティブの日付ピッカー値を使用してください。",
            "leave_outside_scope": "休暇申請は選択中の月次ワークスペース内に収めてください。",
            "leave_added": "{worker_name} の {leave_date} の休暇を追加しました。",
            "leave_exists": "{worker_name} の {leave_date} の休暇はすでに登録されています。",
            "candidate_ready": "候補プレビューの準備ができました。適用前に確認できます。",
            "applied_candidate": "候補プレビューを現在ワークスペースへ適用しました（{assignment_count} 件の割り当て）。",
            "saved_version": "{month_value} のバージョン {version_number} を保存しました。",
        },
        "state_cards": {
            "candidate_preview_label": "候補プレビュー",
            "current_workspace_label": "現在ワークスペース",
            "saved_versions_label": "保存済みバージョン",
            "evaluation_label": "評価",
            "present": "あり",
            "none": "なし",
            "candidate_preview_note": "直近のプレビュー操作から得られた読み取り専用の結果です。",
            "current_workspace_note": "「適用」で更新される可変の月次状態です。",
            "saved_versions_note": "「保存」で作成された不変の月次スナップショットです。",
            "evaluation_note": "まずプレビューを生成して、この月を評価してください。",
            "evaluation_visible_note": "評価は現在表示中の候補プレビューを反映しています。",
        },
        "display": {
            "candidate_badge": "候補プレビュー",
            "candidate_description": "現在表示している、ワークスペースへまだ適用していない読み取り専用プレビューです。",
            "current_badge": "現在ワークスペース",
            "current_description": "「適用」で更新され、「保存」でスナップショットされる可変ワークスペースです。",
            "source_label": "ソース",
            "assignments_label": "割り当て数",
            "warnings_label": "警告数",
            "status_label": "状態",
            "month_label": "月",
        },
    },
}


def resolve_monthly_workspace_ui_lang(
    requested_ui_lang: str | None,
    *,
    fallback_locale: str | None = None,
) -> str:
    """Resolve the page-local UI language without introducing global locale state."""

    normalized = (requested_ui_lang or "").strip().lower()
    if normalized in _MONTHLY_WORKSPACE_COPY:
        return normalized

    locale = (fallback_locale or "").strip().lower()
    if locale.startswith("ja"):
        return "ja"
    if locale.startswith("zh"):
        return "zh"
    return "zh"


def get_monthly_workspace_copy(ui_lang: str) -> dict[str, Any]:
    """Return the page copy catalog for one supported language."""

    return _MONTHLY_WORKSPACE_COPY[ui_lang]


def format_monthly_workspace_month_label(year: int, month: int, ui_lang: str) -> str:
    """Format the visible month label for the scoped workspace UI."""

    if ui_lang in {"zh", "ja"}:
        return f"{year:04d}年{month}月"
    return f"{calendar.month_name[month]} {year}"


__all__ = [
    "MONTHLY_WORKSPACE_UI_LANGUAGE_LABELS",
    "format_monthly_workspace_month_label",
    "get_monthly_workspace_copy",
    "resolve_monthly_workspace_ui_lang",
]
