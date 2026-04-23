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
        "explain": {
            "kicker": "说明 / 当日",
            "title": "生成当日排班说明",
            "description": "选择某一天，并查看该日为何以当前方式排班。",
            "body": (
                "这里只解释当前显示的排班结果：如果有候选预览，就解释候选预览；"
                "否则解释当前工作区。支持的请求仅限排班相关的当日说明。"
            ),
            "day_label": "说明日期",
            "request_label": "说明请求（可选）",
            "placeholder": "例如：Why is Spencer not assigned on 4/1?",
            "button": "生成当日说明",
            "default_note": "留空时会返回该日的默认排班说明。",
            "result_empty": "选择日期并提交请求后，这里会显示受限的当日说明。",
            "requires_schedule_surface": (
                "请先生成候选预览或应用当前工作区，再请求当日说明。"
            ),
            "request_language_label": "请求语言",
            "response_language_label": "返回语言",
            "intent_status_label": "请求状态",
            "category_label": "说明类型",
            "source_mode_label": "说明来源",
            "model_used_label": "已使用模型",
            "fallback_used_label": "已使用回退模板",
            "language_values": {
                "zh": "中文",
                "ja": "日文",
                "en": "英文",
                "unknown": "未识别",
            },
            "intent_status_values": {
                "supported": "可解析",
                "unsupported": "不支持",
                "ambiguous": "需澄清",
            },
            "category_values": {
                "day_overview": "当日概览",
                "worker_assignment_check": "员工排班检查",
                "warnings_summary": "警告摘要",
                "fallback_summary": "Fallback 摘要",
                "refine_change_summary": "预览变化",
            },
            "source_mode_values": {
                "candidate_preview": "候选预览",
                "current_workspace": "当前工作区",
            },
            "boolean_yes": "是",
            "boolean_no": "否",
        },
        "refine": {
            "kicker": "细化 / 说明",
            "title": "预览细化请求",
            "description": "在当前月度工作区上提交受限的自然语言细化请求，并查看候选预览。",
            "body": (
                "这里会把中文或日文的细化请求送入现有的受限后端流程，"
                "只返回解析结果和候选预览，不会自动应用，也不会自动保存。"
            ),
            "request_label": "细化请求",
            "placeholder": "例如：请把 SPENCER 安排到 2026-04-01 的 EVE 在 GRILL",
            "button": "生成细化预览",
            "preview_only_note": (
                "这里只生成候选预览，不会自动应用，也不会自动保存。"
            ),
            "result_empty": (
                "提交中文或日文的细化请求后，这里会显示解析结果和预览状态。"
            ),
            "requires_current_workspace": (
                "请先把当前计划应用到月度工作区，再运行细化预览。"
            ),
            "request_language_label": "请求语言",
            "intent_status_label": "解析状态",
            "intent_type_label": "意图类型",
            "preview_executed_label": "已执行预览",
            "candidate_result_label": "候选预览",
            "reason_label": "未完成原因",
            "canonical_title": "规范化意图",
            "adjustment_title": "预览变更",
            "candidate_ready_note": (
                "候选预览已生成；如需写入当前工作区，请单独点击“应用预览”。"
            ),
            "candidate_missing_note": (
                "这次请求没有生成候选预览；当前工作区不会被修改。"
            ),
            "language_values": {
                "zh": "中文",
                "ja": "日文",
                "unknown": "未识别",
            },
            "intent_status_values": {
                "supported": "可解析",
                "unsupported": "不支持",
                "ambiguous": "需澄清",
            },
            "intent_type_values": {
                "set_assignment": "设置排班",
                "remove_assignment": "移除排班",
            },
            "operation_values": {
                "set": "设置",
                "remove": "移除",
            },
            "reason_values": {
                "date_required": "缺少日期",
                "worker_required": "缺少员工",
                "shift_required": "缺少班次",
                "station_required": "缺少岗位",
            },
            "field_labels": {
                "date": "日期",
                "worker_code": "员工",
                "shift_code": "班次",
                "station_code": "岗位",
            },
            "boolean_yes": "是",
            "boolean_no": "否",
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
            "explain_day_required": "请选择需要说明的日期。",
            "invalid_explain_day": "说明日期必须使用原生日期选择器的值。",
            "explain_day_outside_scope": "说明日期必须保留在当前所选月份工作区内。",
            "refine_request_required": "请输入细化请求。",
            "refine_requires_current_workspace": (
                "当前月份还没有已应用的工作区计划，暂时无法生成细化预览。"
            ),
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
        "explain": {
            "kicker": "説明 / 日別",
            "title": "日別シフト説明を生成",
            "description": "特定の日を選択して、その日の排班理由を確認します。",
            "body": (
                "ここでは現在表示中の排班結果だけを説明します。候補プレビューがあれば候補プレビューを、"
                "なければ現在ワークスペースを説明します。対応するのは排班関連の日別説明だけです。"
            ),
            "day_label": "説明対象日",
            "request_label": "説明依頼（任意）",
            "placeholder": "例: Why was 4/1 scheduled this way?",
            "button": "日別説明を生成",
            "default_note": "空欄の場合は、その日の標準説明を返します。",
            "result_empty": "日付を選んで依頼を送信すると、ここに制約付きの日別説明を表示します。",
            "requires_schedule_surface": (
                "候補プレビューを生成するか、現在ワークスペースを適用してから日別説明を依頼してください。"
            ),
            "request_language_label": "依頼言語",
            "response_language_label": "応答言語",
            "intent_status_label": "依頼状態",
            "category_label": "説明種別",
            "source_mode_label": "説明対象",
            "model_used_label": "モデル使用",
            "fallback_used_label": "テンプレート回退使用",
            "language_values": {
                "zh": "中国語",
                "ja": "日本語",
                "en": "英語",
                "unknown": "未判定",
            },
            "intent_status_values": {
                "supported": "解析可能",
                "unsupported": "未対応",
                "ambiguous": "要確認",
            },
            "category_values": {
                "day_overview": "日別概要",
                "worker_assignment_check": "担当者確認",
                "warnings_summary": "警告要約",
                "fallback_summary": "フォールバック要約",
                "refine_change_summary": "プレビュー差分",
            },
            "source_mode_values": {
                "candidate_preview": "候補プレビュー",
                "current_workspace": "現在ワークスペース",
            },
            "boolean_yes": "はい",
            "boolean_no": "いいえ",
        },
        "refine": {
            "kicker": "調整 / 説明",
            "title": "調整依頼プレビュー",
            "description": "現在の月次ワークスペースに対して、制約付きの自然言語調整依頼を送り、候補プレビューを確認します。",
            "body": (
                "ここでは中国語または日本語の調整依頼を、既存の制約付きバックエンドへ送ります。"
                "返るのは解析結果と候補プレビューだけで、自動適用も自動保存もしません。"
            ),
            "request_label": "調整依頼",
            "placeholder": "例: 2026-04-01 の SPENCER を外して",
            "button": "調整プレビューを生成",
            "preview_only_note": (
                "ここでは候補プレビューだけを生成します。自動適用も自動保存もしません。"
            ),
            "result_empty": (
                "中国語または日本語の調整依頼を送信すると、ここに解析結果とプレビュー状態を表示します。"
            ),
            "requires_current_workspace": (
                "先に現在ワークスペースへ月次計画を適用してから、調整プレビューを実行してください。"
            ),
            "request_language_label": "依頼言語",
            "intent_status_label": "解析状態",
            "intent_type_label": "意図種別",
            "preview_executed_label": "プレビュー実行",
            "candidate_result_label": "候補プレビュー",
            "reason_label": "未完了の理由",
            "canonical_title": "正規化された意図",
            "adjustment_title": "プレビュー差分",
            "candidate_ready_note": (
                "候補プレビューを生成しました。現在ワークスペースへ反映するには、別途「プレビューを適用」を実行してください。"
            ),
            "candidate_missing_note": (
                "今回は候補プレビューを生成していません。現在ワークスペースは変更されません。"
            ),
            "language_values": {
                "zh": "中国語",
                "ja": "日本語",
                "unknown": "未判定",
            },
            "intent_status_values": {
                "supported": "解析可能",
                "unsupported": "未対応",
                "ambiguous": "要確認",
            },
            "intent_type_values": {
                "set_assignment": "割り当て設定",
                "remove_assignment": "割り当て削除",
            },
            "operation_values": {
                "set": "設定",
                "remove": "削除",
            },
            "reason_values": {
                "date_required": "日付指定が必要",
                "worker_required": "スタッフ指定が必要",
                "shift_required": "シフト指定が必要",
                "station_required": "持ち場指定が必要",
            },
            "field_labels": {
                "date": "日付",
                "worker_code": "スタッフ",
                "shift_code": "シフト",
                "station_code": "持ち場",
            },
            "boolean_yes": "はい",
            "boolean_no": "いいえ",
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
            "explain_day_required": "説明したい日付を選択してください。",
            "invalid_explain_day": "説明日にはネイティブの日付ピッカー値を使用してください。",
            "explain_day_outside_scope": "説明日は現在選択中の月次ワークスペース内に収めてください。",
            "refine_request_required": "調整依頼を入力してください。",
            "refine_requires_current_workspace": (
                "この月にはまだ現在ワークスペースがないため、調整プレビューを生成できません。"
            ),
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
