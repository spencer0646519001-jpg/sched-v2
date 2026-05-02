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
            "eyebrow": "月度排班工作區",
            "title": "月度排班工作台",
            "description": (
                "按月份查看排班：新增請假、產生候選預覽、套用到目前工作區、"
                "儲存版本，並在同一頁面檢查人員月曆表。"
            ),
        },
        "toggle": {
            "label": "介面語言",
            "aria_label": "切換介面語言",
        },
        "workflow_steps": [
            "1. 選擇月份",
            "2. 產生預覽",
            "3. 調整候選班表",
            "4. 檢查評估結果",
            "5. 套用或儲存",
            "6. 查看完整月度排班",
        ],
        "scope": {
            "kicker": "月份與操作",
            "title": "選擇月份並執行主要操作",
            "description": "先確認工作區與月份，再產生預覽、套用、儲存或匯出。",
            "workspace_label": "工作區",
            "no_tenant": "暫無租戶資料",
            "month_label": "月份",
            "submit": "切換月份",
        },
        "leave": {
            "kicker": "請假申請",
            "title": "讓請假在流程中保持可見",
            "description": "在產生預覽前，先用同一套面向審核者的請假流程。",
            "person_label": "員工",
            "select_worker": "請選擇員工",
            "date_label": "請假日期",
            "submit": "新增請假",
            "summary_note": "目前 {month_label} 請假彙總",
            "empty": "尚未為 {month_label} 新增請假申請。",
        },
        "actions": {
            "kicker": "主要操作",
            "title": "預覽、套用與儲存",
            "description": "主流程保持清楚，細節需要時再展開。",
            "preview_title": "產生預覽",
            "preview_description": "依所選月份與請假輸入產生新的候選班表。",
            "preview_submit": "產生預覽",
            "apply_title": "套用候選班表",
            "apply_description": "將目前可見的候選預覽套用到可編輯的目前工作區。",
            "apply_submit": "套用候選班表",
            "save_title": "儲存版本",
            "save_description": "把目前工作區快照為不可變的已儲存版本。",
            "save_label": "版本標籤",
            "save_placeholder": "選填，供審核者識別",
            "save_submit": "儲存版本",
            "export_title": "匯出 CSV",
            "export_description": "下載目前工作區的月度排班 CSV。不會匯出候選預覽。",
            "export_submit": "匯出 CSV",
            "export_requires_current_workspace": (
                "請先把目前計畫套用到月度工作區，再匯出 CSV。"
            ),
            "footer_note": (
                "預覽是唯讀的。套用會更新目前工作區。儲存會為所選月份建立不可變歷史。"
            ),
        },
        "state": {
            "kicker": "工作區狀態",
            "title": "查看目前系統狀態",
            "description": (
                "用輕量摘要協助審核者理解此工作區目前已有內容。"
            ),
        },
        "result": {
            "kicker": "完整月度排班",
            "title": "查看人員排班表",
            "description": "完整月度表格放在頁面下方；窄螢幕可橫向捲動。",
            "person_header": "員工",
            "empty": "尚未顯示 {month_label} 的候選預覽或目前工作區。",
        },
        "evaluation": {
            "kicker": "評估",
            "title": "評估結果",
            "description": "先看摘要；需要時再展開完整警告。",
            "empty": "產生候選預覽後，這裡會顯示評估結果。",
            "no_warnings": "目前沒有需要注意的警告。",
            "has_warnings": "有需要注意的排班警告",
            "expand_hint": "點擊展開查看詳細警告",
            "details_title": "詳細警告",
            "warning_count": "{count} 則警告",
        },
        "warnings": {
            "kicker": "警告",
            "title": "排班警告",
            "description": (
                "預覽警告會顯示在這裡；完整細節預設收合，避免干擾主流程。"
            ),
            "date_label": "日期",
            "worker_label": "員工",
            "month_value": "當月",
            "system_value": "系統",
            "no_details": "無額外詳情。",
            "empty_no_current": "產生候選預覽後，預覽警告會顯示在這裡。",
            "empty_with_current": (
                "產生候選預覽後，預覽警告會顯示在這裡。目前工作區警告尚未持久化。"
            ),
        },
        "explain": {
            "kicker": "說明 / 當日",
            "title": "產生當日排班說明",
            "description": "選擇某一天，查看該日為何以目前方式排班。",
            "body": (
                "這裡只說明目前顯示的排班結果：如果有候選預覽，就說明候選預覽；"
                "否則說明目前工作區。支援的請求限於排班相關的當日說明。"
            ),
            "day_label": "說明日期",
            "request_label": "說明請求（選填）",
            "placeholder": "例如：請說明 4/1 為什麼這樣排班",
            "button": "產生當日說明",
            "default_note": "留空時會回傳該日的預設排班說明。",
            "result_empty": "選擇日期並送出請求後，這裡會顯示受限的當日說明。",
            "requires_schedule_surface": (
                "請先產生候選預覽或套用目前工作區，再請求當日說明。"
            ),
            "request_language_label": "請求語言",
            "response_language_label": "回應語言",
            "intent_status_label": "請求狀態",
            "category_label": "說明類型",
            "source_mode_label": "說明來源",
            "model_used_label": "已使用模型",
            "fallback_used_label": "已使用回退範本",
            "language_values": {
                "zh": "中文",
                "ja": "日文",
                "en": "英文",
                "unknown": "未識別",
            },
            "intent_status_values": {
                "supported": "可解析",
                "unsupported": "不支援",
                "ambiguous": "需釐清",
            },
            "category_values": {
                "day_overview": "當日概覽",
                "worker_assignment_check": "員工排班檢查",
                "warnings_summary": "警告摘要",
                "fallback_summary": "回退摘要",
                "refine_change_summary": "預覽變化",
            },
            "source_mode_values": {
                "candidate_preview": "候選預覽",
                "current_workspace": "目前工作區",
            },
            "boolean_yes": "是",
            "boolean_no": "否",
        },
        "refine": {
            "kicker": "AI 排班助手",
            "title": "AI 排班助手",
            "description": "先描述想怎麼調整班表，系統只會產生候選預覽。",
            "body": (
                "輸入排班調整請求後，會走現有的受限後端流程。"
                "只返回解析結果和候選預覽，不會自動套用，也不會自動儲存。"
            ),
            "request_label": "調整請求",
            "prompt_label": "想怎麼調整班表？",
            "placeholder": "例如：請把 SPENCER 安排到 2026-04-01 的 EVE 在 GRILL",
            "button": "產生調整預覽",
            "preview_only_note": (
                "只會產生候選預覽，不會自動套用或儲存。"
            ),
            "result_empty": (
                "送出調整請求後，這裡會顯示理解結果和預覽狀態。"
            ),
            "requires_current_workspace": (
                "請先把目前計畫套用到月度工作區，再執行調整預覽。"
            ),
            "request_language_label": "請求語言",
            "intent_status_label": "解析狀態",
            "intent_type_label": "意圖類型",
            "preview_executed_label": "已執行預覽",
            "candidate_result_label": "候選預覽",
            "reason_label": "原因",
            "canonical_title": "我理解你要做的是：",
            "adjustment_title": "變更",
            "technical_details_title": "技術詳細資訊",
            "understanding_executable_title": "我理解你要做的是：",
            "understanding_limited_title": "我理解這是排班相關請求：",
            "non_scheduling_message": "這個助手只處理排班調整。請輸入排班相關請求。",
            "status_label": "狀態",
            "executable_status": "可以產生候選預覽",
            "not_executable_status": "目前尚不能自動執行",
            "suggestion_label": "建議改寫",
            "default_suggestion": "請改成單日、單一員工、班次與崗位明確的調整，例如：請把 SPENCER 安排到 2026-04-01 的 EVE 在 GRILL。",
            "outcome_messages": {
                "refine_preview_ready_set": "已產生調整預覽。",
                "refine_preview_ready_remove": "已產生移除預覽。",
                "refine_unsupported_language": "暫不支援這類輸入語言。",
                "refine_unsupported_intent": "暫不支援這類調整請求。",
                "refine_understood_but_not_executable": "我理解這是排班相關請求，但目前尚不能自動執行。",
                "refine_non_scheduling_request": "這個助手只處理排班調整。請輸入排班相關請求。",
                "refine_ambiguous_missing_information": "需要更多資訊才能安全產生預覽。",
                "refine_ambiguous_reference": "無法安全解析這筆調整請求。",
            },
            "candidate_ready_note": (
                "候選預覽已產生；如需寫入目前工作區，請點擊「套用候選班表」。"
            ),
            "candidate_missing_note": (
                "這次請求沒有產生候選預覽；目前工作區不會被修改。"
            ),
            "language_values": {
                "zh": "中文",
                "ja": "日文",
                "unknown": "未識別",
            },
            "intent_status_values": {
                "supported": "可解析",
                "unsupported": "不支援",
                "ambiguous": "需釐清",
            },
            "intent_type_values": {
                "set_assignment": "設定排班",
                "remove_assignment": "移除排班",
            },
            "operation_values": {
                "set": "設定",
                "remove": "移除",
            },
            "reason_values": {
                "date_required": "缺少日期",
                "worker_required": "缺少員工",
                "shift_required": "缺少班次",
                "station_required": "缺少崗位",
                "bulk_change_not_supported": "目前僅支援單日調整",
                "unsupported_intent": "目前不支援這類調整",
                "non_scheduling_request": "不是排班調整請求",
            },
            "field_labels": {
                "date": "日期",
                "worker_code": "員工",
                "shift_code": "班次",
                "station_code": "崗位",
            },
            "boolean_yes": "是",
            "boolean_no": "否",
        },
        "voice": {
            "summary": "使用語音輸入",
            "input_label": "語音輸入（Whisper）",
            "start_recording": "開始錄音",
            "stop_submit": "停止並送出",
            "transcribe_explain": "轉錄並產生說明",
            "transcribe_preview": "轉錄並產生預覽",
            "upload_note": "音訊會先轉成文字，再送入既有流程。",
            "initial_status": "可上傳音訊，或在瀏覽器中錄音後送出。",
            "disabled_status": "此語音動作啟用後，才可使用麥克風錄音。",
            "unsupported_status": "此瀏覽器不支援頁面內錄音。你仍可上傳音訊。",
            "requesting_permission": "正在請求麥克風權限...",
            "permission_denied": "麥克風權限遭拒。你仍可改用音訊上傳。",
            "start_failed": "無法開始錄音。你仍可改用音訊上傳。",
            "unavailable_status": "此瀏覽器無法使用麥克風錄音。你仍可上傳音訊。",
            "recording_failed": "錄音失敗。你仍可改用音訊上傳。",
            "empty_recording": "沒有錄到音訊，請再試一次。",
            "submitting": "正在送出錄音進行轉錄...",
            "submit_failed": "無法送出錄音。你仍可改用音訊上傳。",
            "recording": "正在錄音。點擊停止即可送出。",
            "stopping": "正在停止錄音...",
            "select_audio_error": "使用語音輸入前，請先選擇音訊檔。",
            "named_audio_error": "語音輸入需要有檔名的音訊上傳。",
            "unsupported_type_error": "語音輸入僅支援 mp3、mp4、m4a、ogg、wav、webm 檔案。",
            "too_large_error": "語音輸入檔案必須小於或等於 25 MB。",
            "empty_audio_error": "上傳的音訊檔是空的。",
            "unusable_transcript_error": "音訊無法轉錄成可使用的排班請求。",
            "success_message": "語音{mode}請求已透過 {model} 轉錄：{text}",
            "mode_labels": {
                "explain": "說明",
                "refine": "調整",
            },
        },
        "messages": {
            "invalid_scope": "月份選擇必須使用 YYYY-MM 月份選擇器格式。",
            "no_tenant": "月度工作台目前還沒有可用的租戶資料。",
            "candidate_reuse_failed": "無法復用已儲存的候選預覽，請重新預覽該月份。",
            "apply_requires_candidate": "請先產生候選預覽，再套用到月份工作區。",
            "unknown_action": "未知的工作台操作。",
            "choose_person_and_date": "新增請假前請先選擇員工和日期。",
            "selected_person_not_found": "找不到所選員工。",
            "invalid_leave_date": "請假日期必須使用原生日期選擇器的值。",
            "leave_outside_scope": "請假申請必須保留在目前所選月份工作區內。",
            "leave_added": "已為 {worker_name} 新增 {leave_date} 的請假。",
            "leave_exists": "{worker_name} 在 {leave_date} 的請假已存在。",
            "candidate_ready": "候選預覽已產生，可在套用前先審核。",
            "applied_candidate": "已將候選預覽套用到目前工作區（{assignment_count} 筆排班）。",
            "saved_version": "已儲存 {month_value} 的版本 {version_number}。",
            "explain_day_required": "請選擇需要說明的日期。",
            "invalid_explain_day": "說明日期必須使用原生日期選擇器的值。",
            "explain_day_outside_scope": "說明日期必須保留在目前所選月份工作區內。",
            "refine_request_required": "請輸入調整請求。",
            "refine_requires_current_workspace": (
                "目前月份還沒有已套用的工作區計畫，暫時無法產生調整預覽。"
            ),
        },
        "state_cards": {
            "candidate_preview_label": "候選預覽",
            "current_workspace_label": "目前工作區",
            "saved_versions_label": "已儲存版本",
            "evaluation_label": "評估",
            "present": "有",
            "none": "無",
            "candidate_preview_note": "來自最近一次預覽操作的唯讀結果。",
            "current_workspace_note": "「套用」會更新的可變月份狀態。",
            "saved_versions_note": "透過「儲存」建立的不可變月份快照。",
            "evaluation_note": "先產生預覽，再評估該月份。",
            "evaluation_visible_note": "評估結果反映目前可見的候選預覽。",
        },
        "display": {
            "candidate_badge": "候選預覽",
            "candidate_description": "顯示的是尚未套用到工作區的目前唯讀預覽。",
            "current_badge": "目前工作區",
            "current_description": "顯示的是「套用」會更新、「儲存」會快照的可變工作區。",
            "source_label": "來源",
            "assignments_label": "排班數",
            "warnings_label": "警告數",
            "status_label": "狀態",
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
                "への適用、バージョン保存、月次の担当者別シフト表の確認を同じ画面で行います。"
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
            "description": "表示するワークスペースと月を選びます。",
            "workspace_label": "ワークスペース",
            "no_tenant": "利用可能なテナントデータはありません",
            "month_label": "月",
            "submit": "月を開く",
        },
        "leave": {
            "kicker": "休暇申請",
            "title": "休暇を追加する",
            "description": "休暇を追加して、月次プレビューに反映します。",
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
            "description": "月次シフトのプレビュー、適用、保存を実行します。",
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
            "export_title": "CSV を書き出す",
            "export_description": (
                "現在ワークスペースの月次シフトを CSV でダウンロードします。"
                "候補プレビューは含みません。"
            ),
            "export_submit": "CSV をダウンロード",
            "export_requires_current_workspace": (
                "先に現在ワークスペースへ月次計画を適用してから CSV をダウンロードしてください。"
            ),
            "footer_note": (
                "プレビューは読み取り専用です。適用は現在ワークスペースを更新します。"
                "保存は選択月の不変な履歴を作成します。"
            ),
        },
        "state": {
            "kicker": "ワークスペース状態",
            "title": "現在の状態",
            "description": "候補プレビュー、現在ワークスペース、保存版の有無を確認できます。",
        },
        "result": {
            "kicker": "月次シフト結果",
            "title": "担当者別シフト表",
            "description": "横スクロールで全体を確認できます。",
            "person_header": "担当者",
            "empty": "{month_label} ではまだ候補プレビューも現在ワークスペースも表示されていません。",
        },
        "evaluation": {
            "kicker": "評価",
            "title": "評価結果",
            "description": "まずサマリーを表示し、必要なときだけ詳細を展開します。",
            "empty": "候補プレビューを生成すると、ここに評価結果が表示されます。",
            "no_warnings": "現在注意が必要な警告はありません。",
            "has_warnings": "注意が必要なシフト警告があります",
            "expand_hint": "クリックして詳細警告を表示",
            "details_title": "詳細警告",
            "warning_count": "{count} 件の警告",
        },
        "warnings": {
            "kicker": "警告",
            "title": "シフト警告",
            "description": "注意が必要なシフト警告を確認できます。",
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
                "選択した日のシフト内容を説明します。"
                "候補プレビューがある場合は、その内容を優先して説明します。"
            ),
            "day_label": "説明対象日",
            "request_label": "説明依頼（任意）",
            "placeholder": "例: この日のシフト理由を説明して",
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
            "description": "調整したい内容から候補プレビューを生成します。",
            "body": (
                "入力した調整依頼をもとに、候補プレビューを作成します。"
                "自動適用や自動保存は行いません。"
            ),
            "request_label": "調整依頼",
            "prompt_label": "どのようにシフトを調整しますか？",
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
            "technical_details_title": "技術詳細",
            "understanding_executable_title": "理解した内容：",
            "understanding_limited_title": "シフト関連の依頼として理解しました：",
            "non_scheduling_message": "このアシスタントはシフト調整のみ対応しています。シフト関連の依頼を入力してください。",
            "status_label": "状態",
            "executable_status": "候補プレビューを生成できます",
            "not_executable_status": "現在は自動実行できません",
            "suggestion_label": "書き換え例",
            "default_suggestion": "日付、担当者、シフト、持ち場が明確な単日調整として入力してください。例: 2026-04-01 の SPENCER を EVE の GRILL にして。",
            "outcome_messages": {
                "refine_preview_ready_set": "調整プレビューを生成しました。",
                "refine_preview_ready_remove": "削除プレビューを生成しました。",
                "refine_unsupported_language": "この入力言語はまだ対応していません。",
                "refine_unsupported_intent": "この調整依頼にはまだ対応していません。",
                "refine_understood_but_not_executable": "シフト関連の依頼として理解しましたが、現在は自動実行できません。",
                "refine_non_scheduling_request": "このアシスタントはシフト調整のみ対応しています。シフト関連の依頼を入力してください。",
                "refine_ambiguous_missing_information": "安全にプレビューするには追加情報が必要です。",
                "refine_ambiguous_reference": "この調整依頼を安全に解釈できませんでした。",
            },
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
                "bulk_change_not_supported": "現在は単日調整のみ対応しています",
                "unsupported_intent": "この種類の調整にはまだ対応していません",
                "non_scheduling_request": "シフト調整ではありません",
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
        "voice": {
            "summary": "音声入力を使う",
            "input_label": "音声入力",
            "start_recording": "開始",
            "stop_submit": "停止して送信",
            "transcribe_explain": "音声から説明を生成",
            "transcribe_preview": "音声からプレビュー生成",
            "upload_note": "音声ファイルから依頼できます。",
            "initial_status": "音声をアップロードするか、ブラウザで録音して送信できます。",
            "disabled_status": "この音声アクションが有効になると、マイク録音を使えます。",
            "unsupported_status": "このブラウザはページ内録音に対応していません。音声アップロードは利用できます。",
            "requesting_permission": "マイク権限を要求しています...",
            "permission_denied": "マイク権限が拒否されました。音声アップロードは利用できます。",
            "start_failed": "録音を開始できませんでした。音声アップロードは利用できます。",
            "unavailable_status": "このブラウザではマイク録音を利用できません。音声アップロードは利用できます。",
            "recording_failed": "録音に失敗しました。音声アップロードは利用できます。",
            "empty_recording": "録音された音声がありません。もう一度お試しください。",
            "submitting": "録音を送信しています...",
            "submit_failed": "録音を送信できませんでした。音声アップロードは利用できます。",
            "recording": "録音中です。停止をクリックすると送信します。",
            "stopping": "録音を停止しています...",
            "select_audio_error": "音声入力を使う前に音声ファイルを選択してください。",
            "named_audio_error": "音声入力にはファイル名付きの音声アップロードが必要です。",
            "unsupported_type_error": "音声入力は mp3、mp4、m4a、ogg、wav、webm ファイルのみ対応しています。",
            "too_large_error": "音声入力ファイルは 25 MB 以下にしてください。",
            "empty_audio_error": "アップロードされた音声ファイルが空です。",
            "unusable_transcript_error": "音声を使用可能なシフト依頼に文字起こしできませんでした。",
            "success_message": "音声から{mode}依頼を生成しました：{text}",
            "mode_labels": {
                "explain": "説明",
                "refine": "調整",
            },
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
