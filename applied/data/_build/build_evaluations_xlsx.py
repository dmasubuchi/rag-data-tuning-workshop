"""面接の評価を Excel（.xlsx）1 ファイルにする。

骨組み（シートごとの書き出し）は Qwen（qwen3-coder:30b）が書き、次を手で直した:
表（Table）の範囲の誤り→オートフィルターに、列幅・折り返し・上揃え、評価基準シートの中身、
応募番号順の並び、見出しの折り返し、日時の整形の共通化。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from lib_common import DATA, FIXED_DT, NOTICE, load_json, normalize_zip

# カラーパレット
HEADER_BG = "1F3A5F"
HEADER_FG = "FFFFFF"


def build(out_path: Path) -> None:
    # 入力データの読み込み
    source_ats = load_json("source_ats.json")
    evaluations = load_json("evaluations.json")

    # データのマッピング用辞書作成
    persons_map = {p["person_key"]: p for p in source_ats["persons"]}
    applications_map = {a["application_id"]: a for a in source_ats["applications"]}
    requisitions_map = {r["req_id"]: r for r in source_ats["requisitions"]}
    agencies_map = {a["agency_id"]: a for a in source_ats["agencies"]}
    users_map = {u["user_id"]: u for u in source_ats["users"]}

    # Workbook作成とワークシート作成
    wb = Workbook()
    
    # 「面接評価」シート
    ws1 = wb.active
    ws1.title = "面接評価"
    
    # 見出し行のスタイルを設定
    header_font = Font(color=HEADER_FG, bold=True)
    header_fill = PatternFill(start_color=HEADER_BG, end_color=HEADER_BG, fill_type="solid")
    
    # 列ヘッダーデータ
    headers = [
        "評価ID", "応募番号", "人物キー", "候補者名", "求人番号", "求人名",
        "面接段階", "実施日時", "面接官ID", "面接官名", "技術力", "要件適合", "コミュニケーション", 
        "総合評価", "推奨", "提出状況", "提出日時", "確認できたこと", "確認できていないこと", "所見"
    ]
    
    # ヘッダーを設定
    for col, header in enumerate(headers, 1):
        cell = ws1.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
    
    # 評価データの記入
    for row_num, row in enumerate(evaluations["rows"], 2):
        app_id = row["application_id"]
        application = applications_map.get(app_id)
        
        if not application:
            continue
            
        person = persons_map.get(application["person_key"])
        requisition = requisitions_map.get(application["req_id"])
        user = users_map.get(row["interviewer_id"])
        
        # 候補者名/人物キー
        candidate_name = person["display_name"] if person else ""
        person_key = application["person_key"]
        
        # 求人番号/求人名
        req_id = application["req_id"]
        req_title = requisition["title"] if requisition else ""
        
        # 経路名変換
        route_map = {"agency": "紹介会社", "direct": "直接応募", "referral": "社員紹介"}
        route_name = route_map.get(application["route"], "")
        
        # 紹介会社名取得
        agency_name = ""
        if application["agency_id"] and application["agency_id"] in agencies_map:
            agency_name = agencies_map[application["agency_id"]]["name"]
            
        # 面接官名
        interviewer_name = user["name"] if user else ""
        
        # 点数を数値として設定（null はNoneに）
        skill_value = row["skill"] or None
        fit_value = row["fit"] or None
        communication_value = row["communication"] or None
        overall_value = row["overall"] or None
        
        # 推奨の判定
        recommendation = row["recommendation"] or ""
        
        # 提出状況の文字列
        status_str = row["status"]
        
        # 日付を文字列から変換して整形
        held_at = row.get("held_at", "")
        submitted_at = row.get("submitted_at")
        
        # 行を挿入
        ws1.cell(row=row_num, column=1, value=row["evaluation_id"])
        ws1.cell(row=row_num, column=2, value=app_id)
        ws1.cell(row=row_num, column=3, value=person_key)
        ws1.cell(row=row_num, column=4, value=candidate_name)
        ws1.cell(row=row_num, column=5, value=req_id)
        ws1.cell(row=row_num, column=6, value=req_title)
        ws1.cell(row=row_num, column=7, value=row["stage"])
        ws1.cell(row=row_num, column=8, value=held_at)
        ws1.cell(row=row_num, column=9, value=row["interviewer_id"])
        ws1.cell(row=row_num, column=10, value=interviewer_name)
        ws1.cell(row=row_num, column=11, value=skill_value)
        ws1.cell(row=row_num, column=12, value=fit_value)
        ws1.cell(row=row_num, column=13, value=communication_value)
        ws1.cell(row=row_num, column=14, value=overall_value)
        ws1.cell(row=row_num, column=15, value=recommendation)
        ws1.cell(row=row_num, column=16, value=status_str)
        ws1.cell(row=row_num, column=17, value=submitted_at)
        ws1.cell(row=row_num, column=18, value=row["confirmed"])
        ws1.cell(row=row_num, column=19, value=row["unconfirmed"])
        ws1.cell(row=row_num, column=20, value=row["comment"])
        
    # コンテンツの折り返し・フォント
    alignment_wrap = Alignment(wrap_text=True)
    font_gothic = Font(name="游ゴシック", size=11)
    
    for row in ws1.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = alignment_wrap
            cell.font = font_gothic
            
    # 特定列の中央寄せと幅調整（点数列）
    for col in [11, 12, 13, 14]:
        ws1.column_dimensions[get_column_letter(col)].width = 10
        for row in ws1.iter_rows(min_row=2):
            cell = row[col-1]
            if not isinstance(cell.value, str) and cell.value is not None:
                cell.alignment = Alignment(horizontal='center')
                
    # 長い列の幅調整（所見）
    ws1.column_dimensions[get_column_letter(20)].width = 50
    
    # 固定行とフィルター
    ws1.freeze_panes = 'A2'
    
    ws1.auto_filter.ref = ws1.dimensions
    
    # 「選考状況」シート
    ws2 = wb.create_sheet("選考状況")
    headers2 = ["応募番号", "人物キー", "候補者名", "求人番号", "求人名", 
                "応募日時", "経路", "紹介会社", "現在の段階", "状況", "次回の面接", "最終更新"]
    for col, header in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        
    for row_num, app in enumerate(sorted(source_ats["applications"], key=lambda a: a["application_id"]), 2):
        person_key = app["person_key"]
        person = persons_map.get(person_key)
        req_id = app["req_id"]
        requisition = requisitions_map.get(req_id)

        # 日付を"YYYY-MM-DD HH:MM"形式へ整形
        received_at = datetime.strptime(app["received_at"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d %H:%M")
        
        # 経路名変換
        route_name = {"direct": "直接応募", "agency": "紹介会社", "referral": "社員紹介"}.get(app["route"], "")
        
        # 紹介会社名
        agency_name = ""
        if app["agency_id"] and app["agency_id"] in agencies_map:
            agency_name = agencies_map[app["agency_id"]]["name"]
            
        interview_at = ""
        if app.get("interview_at"):
            interview_at = datetime.strptime(app["interview_at"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d %H:%M")
            
        # 最終更新
        updated_at = datetime.strptime(app["updated_at"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d %H:%M")

        ws2.cell(row=row_num, column=1, value=app["application_id"])
        ws2.cell(row=row_num, column=2, value=person_key)
        ws2.cell(row=row_num, column=3, value=person["display_name"] if person else "")
        ws2.cell(row=row_num, column=4, value=req_id)
        ws2.cell(row=row_num, column=5, value=requisition["title"] if requisition else "")
        ws2.cell(row=row_num, column=6, value=received_at)
        ws2.cell(row=row_num, column=7, value=route_name)
        ws2.cell(row=row_num, column=8, value=agency_name)
        ws2.cell(row=row_num, column=9, value=app["step"])
        ws2.cell(row=row_num, column=10, value=app["status"])
        ws2.cell(row=row_num, column=11, value=interview_at)
        ws2.cell(row=row_num, column=12, value=updated_at)
        
    ws2.freeze_panes = 'A2'
    ws2.auto_filter.ref = ws2.dimensions
    
    # 「選考履歴」
    ws3 = wb.create_sheet("選考履歴")
    headers3 = ["応募番号", "候補者名", "求人番号", "段階", "出来事", "日時"]
    for col, header in enumerate(headers3, 1):
        cell = ws3.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        
    # stage_eventsを整理して入れる
    events = sorted(source_ats["stage_events"], key=lambda e: (e["application_id"], e["at"], e["event_id"]))
    
    for row_num, event in enumerate(events, 2):
        app_id = event["application_id"]
        application = applications_map.get(app_id)
        person = persons_map.get(application["person_key"]) if application else None
        requisition = requisitions_map.get(application["req_id"]) if application else None
        
        day = datetime.strptime(event["at"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d %H:%M")
        
        ws3.cell(row=row_num, column=1, value=app_id)
        ws3.cell(row=row_num, column=2, value=person["display_name"] if person else "")
        ws3.cell(row=row_num, column=3, value=application["req_id"] if application else "")
        ws3.cell(row=row_num, column=4, value=event["step"])
        ws3.cell(row=row_num, column=5, value=event["event_type"])
        ws3.cell(row=row_num, column=6, value=day)
        
    ws3.freeze_panes = 'A2'
    ws3.auto_filter.ref = ws3.dimensions
    
    # 「評価基準」シート
    ws4 = wb.create_sheet("評価基準")
    headers4 = ["項目", "説明"]
    for col, header in enumerate(headers4, 1):
        cell = ws4.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        
    row_index = 2
    # 点数の意味
    points_meaning = [
        ("5", "期待を大きく上回る"),
        ("4", "期待を上回る"),
        ("3", "期待どおり"),
        ("2", "期待をやや下回る"),
        ("1", "期待を大きく下回る")
    ]
    
    for point, desc in points_meaning:
        ws4.cell(row=row_index, column=1, value=f"点数 {point}")
        ws4.cell(row=row_index, column=2, value=desc)
        row_index += 1

    # 推奨の意味（点数との対応）
    for rec, desc in [("強く推奨", "総合 5。ぜひ採用したい"), ("推奨", "総合 4。採用してよい"),
                      ("保留", "総合 3。確認したい点が残る。次の段階で確かめる前提で進める場合がある"),
                      ("見送り", "総合 2 以下。今回は見送る")]:
        ws4.cell(row=row_index, column=1, value=rec)
        ws4.cell(row=row_index, column=2, value=desc)
        row_index += 1
    ws4.column_dimensions["A"].width = 14
    ws4.column_dimensions["B"].width = 70

    # 注記シート
    ws5 = wb.create_sheet("注記")
    users_used = sorted({r["interviewer_id"] for r in evaluations["rows"]})
    note_texts = [
        f"このファイルは{NOTICE}です。実在の人物・企業とは関係ありません。",
        "面接官ID と面接官名は、採用管理システムの利用者（users）に対応します。"
        + "　".join(f"{u}={users_map[u]['name']}" for u in users_used),
        "提出状況が「下書き（未提出）」の行は、面接官が提出していない評価で、確定した評価ではありません。",
        "点数は 5 段階（5 が最も高い）。",
        "応募番号と人物キーは、応募書類・メールなど他の文書と共通の番号です。",
        "実施日時は選考履歴の「面接実施」の日時と同じです。",
    ]
    for i, text in enumerate(note_texts, 1):
        ws5.cell(row=i, column=1, value=text).alignment = Alignment(wrap_text=True, vertical="top")
    ws5.column_dimensions["A"].width = 110

    # --- 体裁（見出し行の折り返し、列幅、フォント、上揃え） ---
    font_body = Font(name="游ゴシック", size=10)
    font_head = Font(name="游ゴシック", size=10, bold=True, color=HEADER_FG)
    widths = {
        "面接評価": [9, 11, 9, 12, 10, 28, 10, 17, 9, 11, 8, 8, 10, 8, 10, 14, 17, 48, 48, 48],
        "選考状況": [11, 9, 12, 10, 28, 17, 10, 10, 10, 10, 17, 17],
        "選考履歴": [11, 12, 10, 10, 10, 17],
    }
    for ws in (ws1, ws2, ws3):
        for c in ws[1]:
            c.font = font_head
            c.fill = header_fill
            c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font = font_body
                c.alignment = Alignment(wrap_text=True, vertical="top")
        for i, wd in enumerate(widths[ws.title], 1):
            ws.column_dimensions[get_column_letter(i)].width = wd
    for row in ws1.iter_rows(min_row=2, min_col=11, max_col=14):
        for c in row:
            c.alignment = Alignment(horizontal="center", vertical="top")
    for ws in (ws4,):
        for c in ws[1]:
            c.font = font_head
            c.fill = header_fill
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font = font_body
                c.alignment = Alignment(wrap_text=True, vertical="top")
    for c in ws5["A"]:
        c.font = font_body

    # プロパティ設定
    wb.properties.title = "面接評価（2026年10月）"
    wb.properties.creator = "サンプルテック 採用（研修用）"
    wb.properties.lastModifiedBy = "サンプルテック 採用（研修用）"
    wb.properties.subject = NOTICE
    wb.properties.created = FIXED_DT.replace(tzinfo=None)
    wb.properties.modified = FIXED_DT.replace(tzinfo=None)
    
    # 保存&zip正規化
    wb.save(out_path)
    normalize_zip(out_path)


def main():
    out_path = DATA / "evaluations" / f"EVAL-INTERVIEWS-2026-10.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    build(out_path)
    
    print(out_path)


if __name__ == "__main__":
    main()
