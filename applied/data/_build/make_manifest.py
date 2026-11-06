"""全ファイルの種類・対象の ID・元にしたデータを manifest.json にまとめる。"""
from __future__ import annotations

import json

from lib_common import CONTENT, DATA, FIXED_DT, NOTICE, load_json

ROUTE = {"direct": "直接応募", "agency": "紹介会社", "referral": "社員紹介"}
KIND_LABEL = {"job_posting": "求人票", "resume": "職務経歴書", "interview_evaluations": "面接の評価一覧",
              "mail": "面接の連絡メール", "scan": "スキャンした書類"}


def main() -> None:
    ats = load_json("source_ats.json")
    files_meta = load_json("files.json")["files"]
    mails = load_json("mail.json")["mails"]
    scans = load_json("scans.json")["scans"]
    evals = load_json("evaluations.json")["rows"]
    persons = {p["person_key"]: p["display_name"] for p in ats["persons"]}
    app_by_id = {a["application_id"]: a for a in ats["applications"]}
    reqs = {r["req_id"]: r for r in ats["requisitions"]}
    agencies = {a["agency_id"]: a["name"] for a in ats["agencies"]}

    entries = list(files_meta)
    for m in mails:
        app = app_by_id.get(m.get("application_id"))
        entries.append({
            "path": f"mail/{m['file']}", "kind": "mail", "doc_id": m["id"], "req_id": m["req_id"],
            "application_ids": [m["application_id"]] if m.get("application_id") else [],
            "person_keys": [app["person_key"]] if app else [],
            "mail": {"date": m["date"], "from": m["from"]["email"], "to": [t["email"] for t in m["to"]],
                     "subject": m["subject"], "in_reply_to": m.get("in_reply_to"), "topic": m.get("topic")},
            "text_layer": True, "ocr_required": False,
            "source": {"origin": "generated", "basis": m["basis"], "added": "本文はすべて新しく作成"}})
    for s in scans:
        app = app_by_id.get(s.get("application_id"))
        entries.append({
            "path": f"scans/{s['file']}", "kind": "scan", "doc_id": s["id"], "req_id": s["req_id"],
            "application_ids": [s["application_id"]] if s.get("application_id") else [],
            "person_keys": [app["person_key"]] if app else [],
            "scan": {"what": s["what"], "form": s["form"]},
            "text_layer": False, "ocr_required": True,
            "source": {"origin": "generated", "basis": s["basis"], "added": "画像だけの書類。傾き・汚れ・押印を足してある"}})

    for e in entries:
        p = DATA / e["path"]
        e["format"] = p.suffix.lstrip(".")
        e["bytes"] = p.stat().st_size
        e["kind_label"] = KIND_LABEL[e["kind"]]

    ev_by_app: dict[str, list[str]] = {}
    for r in evals:
        ev_by_app.setdefault(r["application_id"], []).append(r["evaluation_id"])
    xlsx = "evaluations/EVAL-INTERVIEWS-2026-10.xlsx"
    applications = []
    for a in ats["applications"]:
        aid = a["application_id"]
        by_kind = lambda k: [e["path"] for e in entries if e["kind"] == k and aid in e["application_ids"]]
        applications.append({
            "application_id": aid, "person_key": a["person_key"], "candidate_name": persons[a["person_key"]],
            "req_id": a["req_id"], "req_version": a["req_version"], "received_at": a["received_at"],
            "route": a["route"], "route_label": ROUTE[a["route"]], "agency_id": a["agency_id"],
            "agency_name": agencies.get(a["agency_id"]), "step": a["step"], "status": a["status"],
            "interview_at": a["interview_at"], "updated_at": a["updated_at"],
            "documents": {"resume": by_kind("resume"), "evaluation_ids": ev_by_app.get(aid, []),
                          "evaluation_workbook": xlsx if aid in ev_by_app else None,
                          "mail": by_kind("mail"), "scans": by_kind("scan")}})
    requisitions = []
    for rid, r in reqs.items():
        cur = next(v for v in r["versions"] if v["version"] == r["current_version"])
        requisitions.append({
            "req_id": rid, "title": r["title"], "current_version": r["current_version"],
            "valid_from": cur["valid_from"], "required_skills": r["required_skills"],
            "job_posting": [e["path"] for e in entries if e["kind"] == "job_posting" and e["req_id"] == rid],
            "application_ids": [a["application_id"] for a in ats["applications"] if a["req_id"] == rid]})

    manifest = {
        "dataset": "応用編の採用の文書", "version": "1.0", "synthetic": True,
        "notice": f"このフォルダーのデータはすべて{NOTICE}です。実在の人物・企業・メールアドレス・電話番号とは関係ありません。",
        "company": "サンプルテック（架空の会社）",
        "base_time": ats["base_time"],
        "id_conventions": {
            "req_id": "求人番号（REQ-nnn）。求人票・職務経歴書・メール・スキャンに共通",
            "application_id": "応募番号（APP-nnnn）。1 回の応募。職務経歴書・面接の評価・メール・スキャンに共通",
            "person_key": "人物キー（C-nnn）。同じ人の別の応募をつなぐ番号",
            "evaluation_id": "面接の評価の行の番号（EV-nnn）。面接の評価一覧の「面接評価」シートの 1 列目",
            "user_id": "社内の利用者（採用担当 U-1001 / U-1004、面接官 U-1006 / U-1007、部門長 U-1003 など）"},
        "counts": {k: sum(1 for e in entries if e["kind"] == k) for k in KIND_LABEL} | {"total": len(entries)},
        "requisitions": requisitions,
        "applications": applications,
        "files": sorted(entries, key=lambda e: e["path"]),
    }
    with open(DATA / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("manifest.json")


if __name__ == "__main__":
    main()
