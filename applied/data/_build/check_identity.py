"""番号・人物・求人の食い違いを調べる検査（check_all.py から呼ぶ）。

台帳（content/source_ats.json の応募・人物・求人・選考履歴・利用者・紹介会社）を正として、作った全ファイルが
「その応募の人・求人」を書いているかを、ファイルごとに調べる。

- メール（.eml を読み直す）: 件名・本文の応募番号 / 求人番号 / 氏名、宛先・差出人（利用者・紹介会社の担当者・応募者）、
  本文の宛名と署名、返信の相手、日付、本文の内容（内定・見送り・最終面接）と選考履歴の一致
- 職務経歴書（docx）: 表の氏名・応募番号・応募求人、本文に別の人・別の応募・別の求人が混ざっていないこと
- 求人票（pdf）: 求人番号・版・有効開始・職種が台帳と合うこと、応募番号や人名が入っていないこと
- 日付・時刻・担当: 本文の「M月D日（曜）」の曜日、メールの時点の求人担当者（recruiter_assignments）、面接官の「評価を○時○分に提出」
  「本日○時に行いました」と評価の行、経歴書の作成日と応募の受付日、評価の提出日時が面接の後であること
- 面接の評価（xlsx）: 行ごとの応募番号と人物キー・氏名・求人・面接官、点数と推奨の対応、文章に別の人が混ざっていないこと、
  「選考状況」「選考履歴」が台帳と一致すること
- スキャン: 書類に書く事実（make_scans.scan_facts）が台帳と合うこと（--ocr のときは OCR が別の応募番号を読んでいないことも）
- manifest: 各ファイルの応募番号・人物キー・求人番号が台帳と合うこと
"""
from __future__ import annotations

import email
import email.policy
import re
from datetime import datetime, timedelta

from lib_common import DATA, load_json

APP_RE = re.compile(r"APP-\d{4}")
REQ_RE = re.compile(r"REQ-\d{3}")
PK_RE = re.compile(r"(?<![A-Za-z0-9])C-\d{3}(?!\d)")
REC_BY_SCORE = {5: "強く推奨", 4: "推奨", 3: "保留", 2: "見送り", 1: "見送り"}


class Ledger:
    def __init__(self) -> None:
        a = load_json("source_ats.json")
        self.ats = a
        self.persons = {p["person_key"]: p["display_name"] for p in a["persons"]}
        self.apps = {x["application_id"]: x for x in a["applications"]}
        self.reqs = {r["req_id"]: r for r in a["requisitions"]}
        self.users = {u["user_id"]: u for u in a["users"]}
        self.user_by_email = {u["email"]: u for u in a["users"]}
        self.agencies = {g["agency_id"]: g for g in a["agencies"]}
        self.events: dict[str, list] = {}
        for e in a["stage_events"]:
            self.events.setdefault(e["application_id"], []).append(e)

    def name(self, app_id: str) -> str:
        return self.persons[self.apps[app_id]["person_key"]]


def identity_problems(L: Ledger, label: str, text: str, app_id: str | None, req_id: str | None,
                      app_in_text: bool = True) -> list[str]:
    """text に出る応募番号・求人番号・人物キー・氏名が、(app_id, req_id) の人・求人だけになっているか。"""
    probs: list[str] = []
    apps_found, reqs_found = set(APP_RE.findall(text)), set(REQ_RE.findall(text))
    if app_id:
        pk = L.apps[app_id]["person_key"]
        name = L.persons[pk]
        if apps_found - {app_id}:
            probs.append(f"{label}: 別の応募番号 {sorted(apps_found - {app_id})} が書かれています（本来 {app_id}）")
        if app_in_text and app_id not in apps_found:
            probs.append(f"{label}: 応募番号 {app_id} が書かれていません")
        if not app_in_text and apps_found:
            probs.append(f"{label}: 応募番号が付く前の文書なのに {sorted(apps_found)} が書かれています")
        if name not in text:
            probs.append(f"{label}: 氏名 {name} が書かれていません")
        for k, n in L.persons.items():
            if k != pk and n in text:
                probs.append(f"{label}: 別の人（{n}）が書かれています（本来 {name}）")
        extra = set(PK_RE.findall(text)) - {pk}
        if extra:
            probs.append(f"{label}: 別の人物キー {sorted(extra)} が書かれています（本来 {pk}）")
    else:
        if apps_found:
            probs.append(f"{label}: 応募番号 {sorted(apps_found)} が書かれています（応募に紐づかない文書のはず）")
        for n in L.persons.values():
            if n in text:
                probs.append(f"{label}: 人名（{n}）が書かれています（応募に紐づかない文書のはず）")
    if req_id and reqs_found - {req_id}:
        probs.append(f"{label}: 別の求人番号 {sorted(reqs_found - {req_id})} が書かれています（本来 {req_id}）")
    if req_id and req_id not in reqs_found:
        probs.append(f"{label}: 求人番号 {req_id} が書かれていません")
    return probs


WEEKDAY = "月火水木金土日"
WD_RE = re.compile(r"(\d{1,2})月(\d{1,2})日（([月火水木金土日])）")


def weekday_problems(label: str, text: str) -> list[str]:
    """「10月21日（水）」の曜日が 2026 年のカレンダーと合うか。"""
    out = []
    for m_, d_, w in WD_RE.findall(text):
        actual = WEEKDAY[datetime(2026, int(m_), int(d_)).weekday()]
        if actual != w:
            out.append(f"{label}: {m_}月{d_}日の曜日が（{w}）と書かれていますが、2026 年は（{actual}）です")
    return out


def recruiter_at(L: Ledger, req_id: str, when: datetime):
    for a in L.ats["recruiter_assignments"]:
        if a["req_id"] == req_id and datetime.fromisoformat(a["assigned_from"]) <= when and (
                a["assigned_to"] is None or when < datetime.fromisoformat(a["assigned_to"])):
            return a["user_id"]
    return None


# ---------------------------------------------------------------- メール
def check_mails(L: Ledger, fail) -> None:
    mails = load_json("mail.json")["mails"]
    by_id = {m["id"]: m for m in mails}
    base = datetime.fromisoformat(L.ats["base_time"])
    for m in mails:
        label = f"mail/{m['file']}"
        path = DATA / "mail" / m["file"]
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
        subject, body = str(msg["Subject"]), msg.get_content()
        app = L.apps.get(m["application_id"])
        if not app:
            fail(f"{label}: 応募番号 {m['application_id']} が台帳にありません"); continue
        if app["req_id"] != m["req_id"]:
            fail(f"{label}: mail.json の求人 {m['req_id']} が応募 {m['application_id']} の求人 {app['req_id']} と違います")
        in_text = m.get("application_id_in_text", True)
        for p in identity_problems(L, label + " 件名+本文", subject + "\n" + body, m["application_id"], app["req_id"], in_text):
            fail(p)
        # 件名は求人番号（と、応募番号が付いていれば応募番号・氏名）を持つ
        if app["req_id"] not in subject:
            fail(f"{label}: 件名に求人番号 {app['req_id']} がありません")
        if in_text and m["application_id"] not in subject + body:
            fail(f"{label}: 応募番号がありません")
        subj_apps = set(APP_RE.findall(subject))
        if subj_apps - {m["application_id"]}:
            fail(f"{label}: 件名の応募番号 {sorted(subj_apps)} が違います")

        # 差出人・宛先
        frm = msg["From"].addresses[0]
        tos = list(msg["To"].addresses)
        agency = L.agencies.get(app["agency_id"]) if app["agency_id"] else None
        contacts = {c["email"]: c["name"] for c in agency["contacts"]} if agency else {}
        for who, addr in [("差出人", frm)] + [("宛先", t) for t in tos]:
            mail_addr = addr.addr_spec
            if mail_addr in L.user_by_email:
                if L.user_by_email[mail_addr]["name"] != addr.display_name:
                    fail(f"{label}: {who}の表示名 {addr.display_name} が利用者 {mail_addr} の名前と違います")
            elif app["route"] == "agency":
                if mail_addr not in contacts:
                    fail(f"{label}: {who} {mail_addr} は応募 {m['application_id']} の紹介会社（{app['agency_id']}）の担当者ではありません")
                elif contacts[mail_addr] != addr.display_name:
                    fail(f"{label}: {who}の表示名 {addr.display_name} が紹介会社の担当者名と違います")
            else:
                if not mail_addr.endswith("@candidate.example") or addr.display_name != L.name(m["application_id"]):
                    fail(f"{label}: {who} {addr.display_name} <{mail_addr}> は応募者本人（{L.name(m['application_id'])}）ではありません")
        # 本文の宛名と署名
        lines = [ln for ln in body.splitlines() if ln.strip()]
        first, signature = lines[0], lines[-2]
        names = [t.display_name for t in tos]
        if not any(first in (f"{n}様", f"{n.split()[0]}様") for n in names):
            fail(f"{label}: 本文の宛名「{first}」が宛先 {names} と合いません")
        if signature != frm.display_name:
            fail(f"{label}: 本文の署名「{signature}」が差出人 {frm.display_name} と合いません")
        # 返信
        parent = by_id.get(m.get("in_reply_to")) if m.get("in_reply_to") else None
        if m.get("in_reply_to"):
            if not parent or (parent["application_id"], parent["req_id"]) != (m["application_id"], m["req_id"]):
                fail(f"{label}: 返信の元メールの応募・求人が違います")
            elif parent["from"]["email"] not in [t["email"] for t in m["to"]]:
                fail(f"{label}: 返信の宛先が元メールの差出人ではありません")
        # 日付
        sent = msg["Date"].datetime
        if sent != datetime.fromisoformat(m["date"]):
            fail(f"{label}: Date ヘッダーが mail.json と違います")
        if sent > base:
            fail(f"{label}: 基準日時（{base:%Y-%m-%d %H:%M}）より後の日付です")
        if sent < datetime.fromisoformat(app["received_at"]) - timedelta(days=1):
            fail(f"{label}: 応募の受付（{app['received_at']}）より 1 日以上前のメールです")
        # 曜日
        for p in weekday_problems(label, subject + "\n" + body):
            fail(p)
        # その時点の求人担当者（採用担当）・面接官
        want_rec = recruiter_at(L, app["req_id"], sent)
        recs = {L.user_by_email[a.addr_spec]["user_id"] for a in [frm] + tos
                if a.addr_spec in L.user_by_email and L.user_by_email[a.addr_spec]["role"] == "recruiter"}
        if recs and recs != {want_rec}:
            fail(f"{label}: 採用担当 {sorted(recs)} が、{sent:%m/%d} 時点の求人 {app['req_id']} の担当 {want_rec} と違います")
        sender = L.user_by_email.get(frm.addr_spec)
        if sender and sender["role"] == "interviewer":
            rows = [r for r in load_json("evaluations.json")["rows"]
                    if r["interviewer_id"] == sender["user_id"] and r["application_id"] == m["application_id"]]
            if not rows:
                fail(f"{label}: 面接官 {sender['name']} の評価が、この応募（{m['application_id']}）にありません")
            for hh, mm in re.findall(r"(\d{1,2})時(\d{2})分に提出", body):
                if not any(r["submitted_at"] == f"{sent:%Y-%m-%d} {int(hh):02d}:{mm}" for r in rows):
                    fail(f"{label}: 「{hh}時{mm}分に提出」が評価の提出日時と合いません")
            for hh in re.findall(r"本日(\d{1,2})時に行いました", body):
                if not any(r["held_at"] == f"{sent:%Y-%m-%d} {int(hh):02d}:00" for r in rows):
                    fail(f"{label}: 「本日{hh}時に行いました」が評価の実施日時と合いません")
        # 本文の内容と選考履歴
        evs = L.events.get(m["application_id"], [])
        text = subject + body
        if "内定" in text and not any(e["event_type"] == "内定" and datetime.fromisoformat(e["at"]) <= sent for e in evs):
            fail(f"{label}: 「内定」と書いてあるが、この応募（{m['application_id']}）には、メールの日時までの内定の記録がありません")
        if "見送り" in text and not any(e["event_type"] == "不通過" and datetime.fromisoformat(e["at"]) <= sent for e in evs):
            fail(f"{label}: 「見送り」と書いてあるが、この応募には、メールの日時までの不通過の記録がありません")
        if "最終面接" in text and not (app["step"] == "最終面接" or any(e["step"] == "最終面接" for e in evs)):
            fail(f"{label}: 「最終面接」と書いてあるが、この応募は最終面接に進んでいません")


# ---------------------------------------------------------------- 職務経歴書
def check_resumes(L: Ledger, mf: dict, texts: dict, fail) -> None:
    from docx import Document
    for e in mf["files"]:
        if e["kind"] != "resume":
            continue
        app_id = e["application_ids"][0]
        app = L.apps[app_id]
        label = e["path"]
        for p in identity_problems(L, label, texts[label], app_id, app["req_id"]):
            fail(p)
        meta = {r.cells[0].text: r.cells[1].text for r in Document(DATA / label).tables[0].rows}
        if meta.get("応募番号") != app_id:
            fail(f"{label}: 表の応募番号 {meta.get('応募番号')} が {app_id} と違います")
        if meta.get("氏名") != L.name(app_id):
            fail(f"{label}: 表の氏名 {meta.get('氏名')} が {L.name(app_id)} と違います")
        want = f"{app['req_id']} {L.reqs[app['req_id']]['title']}"
        if meta.get("応募求人") != want:
            fail(f"{label}: 表の応募求人 {meta.get('応募求人')} が {want} と違います")
        made = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", meta.get("作成日", ""))
        rec = datetime.fromisoformat(app["received_at"])
        if not made or (int(made[1]), int(made[2]), int(made[3])) != (rec.year, rec.month, rec.day):
            fail(f"{label}: 作成日 {meta.get('作成日')} が応募の受付日 {rec:%Y-%m-%d} と違います")
        if label != f"resumes/CV-{app_id}.docx":
            fail(f"{label}: ファイル名の応募番号が {app_id} と違います")


# ---------------------------------------------------------------- 求人票
def check_jobs(L: Ledger, mf: dict, texts: dict, fail) -> None:
    for e in mf["files"]:
        if e["kind"] != "job_posting":
            continue
        label, req = e["path"], e["req_id"]
        r = L.reqs[req]
        t = texts[label]
        for p in identity_problems(L, label, t, None, req) + weekday_problems(label, t):
            fail(p)
        cur = next(v for v in r["versions"] if v["version"] == r["current_version"])
        valid = datetime.fromisoformat(cur["valid_from"])
        for what, s in (("職種", r["title"]), ("版", f"\n{r['current_version']}\n"),
                        ("有効開始", f"{valid.year}年{valid.month}月{valid.day}日")):
            if s not in t:
                fail(f"{label}: {what}（{s.strip()}）が台帳と合いません")
        if e["doc_id"] != cur["doc_id"]:
            fail(f"{label}: 文書番号 {e['doc_id']} が台帳の現行版 {cur['doc_id']} と違います")


# ---------------------------------------------------------------- 旧い版の求人票（updates/）
def check_old_versions(L: Ledger, texts: dict, fail) -> None:
    """updates/ の求人票が、台帳に残っている旧い版（現行でない版）と合うこと。manifest には入れない。"""
    for label, t in texts.items():
        if not label.startswith("updates/"):
            continue
        m = re.fullmatch(r"updates/JOB-REQ(\d{3})-(v\d+)\.pdf", label)
        if not m:
            fail(f"{label}: 名前が JOB-REQnnn-vN.pdf の形ではありません"); continue
        req, ver = f"REQ-{m[1]}", m[2]
        r = L.reqs.get(req)
        v = next((x for x in (r or {}).get("versions", []) if x["version"] == ver), None)
        if not r or not v:
            fail(f"{label}: 求人 {req} の版 {ver} が台帳にありません"); continue
        if ver == r["current_version"]:
            fail(f"{label}: {ver} は現行の版です（現行の版は jobs/ に置く）")
        if v["doc_id"] != f"JOB-REQ{m[1]}-{ver}":
            fail(f"{label}: 文書番号 {v['doc_id']} が名前と違います")
        for p in identity_problems(L, label, t, None, req) + weekday_problems(label, t):
            fail(p)
        valid = datetime.fromisoformat(v["valid_from"])
        for what, s in (("職種", r["title"]), ("版", f"\n{ver}\n"),
                        ("有効開始", f"{valid.year}年{valid.month}月{valid.day}日")):
            if s not in t:
                fail(f"{label}: {what}（{s.strip()}）が台帳と合いません")


# ---------------------------------------------------------------- 面接の評価
def check_workbook(L: Ledger, mf: dict, fail) -> None:
    import openpyxl
    path = "evaluations/EVAL-INTERVIEWS-2026-10.xlsx"
    wb = openpyxl.load_workbook(DATA / path)

    def rows(name):
        ws = wb[name]
        head = [c.value for c in ws[1]]
        return [dict(zip(head, r)) for r in ws.iter_rows(min_row=2, values_only=True)]

    src = {e["evaluation_id"]: e for e in load_json("evaluations.json")["rows"]}
    seen = set()
    for r in rows("面接評価"):
        label = f"{path} {r['評価ID']}"
        seen.add(r["評価ID"])
        s = src.get(r["評価ID"])
        app = L.apps.get(r["応募番号"])
        if not s or not app:
            fail(f"{label}: 応募番号 {r['応募番号']} または評価ID が入力にありません"); continue
        if s["application_id"] != r["応募番号"]:
            fail(f"{label}: 応募番号が evaluations.json と違います")
        want = {"人物キー": app["person_key"], "候補者名": L.name(r["応募番号"]), "求人番号": app["req_id"],
                "求人名": L.reqs[app["req_id"]]["title"], "面接官名": L.users[r["面接官ID"]]["name"]}
        for k, v in want.items():
            if r[k] != v:
                fail(f"{label}: {k} が {r[k]}（台帳では {v}）")
        if L.users[r["面接官ID"]]["role"] not in ("interviewer", "hiring_manager"):
            fail(f"{label}: 面接官ID {r['面接官ID']} が面接官ではありません")
        scores = [r["技術力"], r["要件適合"], r["コミュニケーション"], r["総合評価"]]
        if r["提出状況"] == "提出済み":
            if any(not isinstance(x, int) or not 1 <= x <= 5 for x in scores):
                fail(f"{label}: 点数が 1〜5 の整数ではありません {scores}")
            elif REC_BY_SCORE[r["総合評価"]] != r["推奨"]:
                fail(f"{label}: 総合評価 {r['総合評価']} と推奨「{r['推奨']}」が対応しません")
            if not r["提出日時"]:
                fail(f"{label}: 提出済みなのに提出日時がありません")
        else:
            if any(x is not None for x in scores) or r["推奨"] or r["提出日時"]:
                fail(f"{label}: 下書きなのに点数・推奨・提出日時が入っています")
        if r["提出状況"] == "提出済み" and r["提出日時"] and not (
                r["実施日時"] < r["提出日時"] and r["提出日時"][:10] == r["実施日時"][:10]):
            fail(f"{label}: 提出日時 {r['提出日時']} が実施日時 {r['実施日時']} と同じ日の後になっていません")
        # 文章に別の人・別の応募が混ざっていない（氏名は書かなくてよい）
        prose = "\n".join(str(r[k] or "") for k in ("確認できたこと", "確認できていないこと", "所見"))
        others = [n for k, n in L.persons.items() if k != app["person_key"] and n in prose]
        if others or (set(APP_RE.findall(prose)) - {r["応募番号"]}) or (set(REQ_RE.findall(prose)) - {app["req_id"]}):
            fail(f"{label}: 文章に別の人・応募・求人が書かれています（{others}）")
        # 実施日時は選考履歴の「面接実施」
        held = [e["at"][:16] for e in L.events[r["応募番号"]] if e["step"] == r["面接段階"] and e["event_type"] == "面接実施"]
        if r["実施日時"].replace(" ", "T") not in held:
            fail(f"{label}: 実施日時 {r['実施日時']} が選考履歴の面接実施 {held} と合いません")
    if seen != set(src):
        fail(f"{path}: 面接評価の行が evaluations.json と合いません（差 {sorted(seen ^ set(src))}）")

    # 選考状況・選考履歴が台帳と同じ
    for r in rows("選考状況"):
        a = L.apps.get(r["応募番号"])
        if not a:
            fail(f"{path} 選考状況: 応募番号 {r['応募番号']} が台帳にありません"); continue
        want = {"人物キー": a["person_key"], "候補者名": L.name(r["応募番号"]), "求人番号": a["req_id"],
                "求人名": L.reqs[a["req_id"]]["title"], "現在の段階": a["step"], "状況": a["status"]}
        for k, v in want.items():
            if r[k] != v:
                fail(f"{path} 選考状況 {r['応募番号']}: {k} が {r[k]}（台帳では {v}）")
        ag = L.agencies[a["agency_id"]]["name"] if a["agency_id"] else None
        if (r["紹介会社"] or None) != ag:
            fail(f"{path} 選考状況 {r['応募番号']}: 紹介会社が {r['紹介会社']}（台帳では {ag}）")
    hist = rows("選考履歴")
    want_hist = sorted((e["application_id"], e["at"][:16].replace("T", " "), e["step"], e["event_type"]) for e in L.ats["stage_events"])
    got_hist = sorted((r["応募番号"], r["日時"], r["段階"], r["出来事"]) for r in hist)
    if want_hist != got_hist:
        fail(f"{path} 選考履歴: 台帳の stage_events と一致しません")
    for r in hist:
        a = L.apps[r["応募番号"]]
        if r["候補者名"] != L.name(r["応募番号"]) or r["求人番号"] != a["req_id"]:
            fail(f"{path} 選考履歴 {r['応募番号']}: 氏名または求人番号が台帳と違います")


# ---------------------------------------------------------------- スキャン
def check_scans(L: Ledger, mf: dict, fail, ocr_text_of=None) -> None:
    import make_scans
    facts = make_scans.scan_facts()
    for e in mf["files"]:
        if e["kind"] != "scan":
            continue
        f = facts.get(e["doc_id"])
        label = e["path"]
        if not f or f["file"] != label.split("/")[-1]:
            fail(f"{label}: スキャンの事実（scan_facts）がありません"); continue
        app = L.apps[f["application_id"]]
        if (f["person_key"], f["candidate_name"], f["req_id"], f["req_title"]) != (
                app["person_key"], L.name(f["application_id"]), app["req_id"], L.reqs[app["req_id"]]["title"]):
            fail(f"{label}: 書類に書く人・求人が台帳と合いません")
        if [f["application_id"]] != e["application_ids"] or [f["person_key"]] != e["person_keys"] or f["req_id"] != e["req_id"]:
            fail(f"{label}: manifest の応募・人物・求人が書類に書く事実と違います")
        if "stage" in f:  # 面接メモ: 評価の行・面接官・実施日時と合う
            ev = load_json("evaluations.json")["rows"]
            row = next(x for x in ev if x["evaluation_id"] == f["evaluation_id"])
            if (row["application_id"], row["stage"], L.users[row["interviewer_id"]]["name"]) != (
                    f["application_id"], f["stage"], f["interviewer"]):
                fail(f"{label}: 面接メモが評価 {f['evaluation_id']} の応募・段階・面接官と合いません")
            if (row["overall"], row["recommendation"]) != (f["overall"], f["recommendation"]):
                fail(f"{label}: 面接メモの点数・推奨が評価 {f['evaluation_id']} と違います")
        evs = L.events[f["application_id"]]
        base = datetime.fromisoformat(L.ats["base_time"])
        if f["kind"] == "memo":
            held = [x["at"][:16] for x in evs if x["step"] == f["stage"] and x["event_type"] == "面接実施"]
            hd = datetime.fromisoformat(row["held_at"])
            if row["held_at"].replace(" ", "T") not in held:
                fail(f"{label}: 面接メモの面接日時 {row['held_at']} が選考履歴の面接実施 {held} と合いません")
            if not f["held_at"].startswith(f"{hd:%Y/%m/%d}"):
                fail(f"{label}: 面接メモに書く日付 {f['held_at']} が評価 {f['evaluation_id']} と違います")
        elif f["kind"] == "offer":
            offered = [datetime.fromisoformat(x["at"]) for x in evs if x["event_type"] == "内定"]
            if not offered:
                fail(f"{label}: 内定承諾書なのに、この応募（{f['application_id']}）に内定の記録がありません")
            else:
                w, r = datetime.fromisoformat(f["written_on"]).date(), datetime.fromisoformat(f["received_on"]).date()
                if not (offered[0].date() <= w <= r <= base.date()):
                    fail(f"{label}: 内定（{offered[0]:%m/%d}）→承諾書（{w:%m/%d}）→受付（{r:%m/%d}）の順になっていません")
        elif f["kind"] == "cover":
            a = L.apps[f["application_id"]]
            if a["route"] != "agency":
                fail(f"{label}: 紹介会社の送付状なのに、この応募は紹介会社経由ではありません")
            if f["agency_name"] != L.agencies[a["agency_id"]]["name"] or not f["contact_name"]:
                fail(f"{label}: 送付状の紹介会社・担当者が応募 {f['application_id']} の紹介会社と合いません")
            sent, rec = datetime.fromisoformat(f["sent_at"]), datetime.fromisoformat(a["received_at"])
            if not (sent <= rec and sent.date() == rec.date()):
                fail(f"{label}: 送付状の日時 {sent:%m/%d %H:%M} が応募の受付 {rec:%m/%d %H:%M} より後、または別の日です")
            if f["received_stamp"] != f"{rec:%Y.%m.%d}" or not f["recruiter"]:
                fail(f"{label}: 受付印の日付または受付した担当者が台帳と合いません")
        if ocr_text_of:  # OCR が読めた範囲に、別の応募・求人・人が出ていないこと
            t = ocr_text_of(DATA / label)
            wrong = (set(APP_RE.findall(t)) - {f["application_id"]}) | (set(REQ_RE.findall(t)) - {f["req_id"]})
            wrong_names = [n for k, n in L.persons.items() if k != f["person_key"] and n.replace(" ", "") in t.replace(" ", "")]
            if wrong or wrong_names:
                fail(f"{label}: OCR で別の番号・人物が読めました {sorted(wrong)} {wrong_names}")


# ---------------------------------------------------------------- manifest
def check_manifest(L: Ledger, mf: dict, fail) -> None:
    by_path = {e["path"]: e for e in mf["files"]}
    for e in mf["files"]:
        apps = e["application_ids"]
        label = e["path"]
        for a in apps:
            if a not in L.apps:
                fail(f"{label}: 応募番号 {a} が台帳にありません"); continue
        if any(a not in L.apps for a in apps):
            continue
        if sorted(e["person_keys"]) != sorted({L.apps[a]["person_key"] for a in apps}):
            fail(f"{label}: manifest の人物キー {e['person_keys']} が応募番号 {apps} と合いません")
        reqs = {L.apps[a]["req_id"] for a in apps}
        if e["req_id"] and apps and reqs != {e["req_id"]}:
            fail(f"{label}: manifest の求人 {e['req_id']} が応募 {apps} の求人 {sorted(reqs)} と違います")
        if e["req_id"] and e["req_id"] not in L.reqs:
            fail(f"{label}: 求人番号 {e['req_id']} が台帳にありません")
    import openpyxl
    ws = openpyxl.load_workbook(DATA / "evaluations/EVAL-INTERVIEWS-2026-10.xlsx")["面接評価"]
    in_book: dict[str, list] = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        in_book.setdefault(r[1], []).append(r[0])
    for a in mf["applications"]:
        if sorted(a["documents"]["evaluation_ids"]) != sorted(in_book.get(a["application_id"], [])):
            fail(f"manifest: {a['application_id']} の評価番号 {a['documents']['evaluation_ids']} が Excel の行 {in_book.get(a['application_id'], [])} と違います")
    for a in mf["applications"]:
        docs = a["documents"]
        listed = docs["resume"] + docs["mail"] + docs["scans"] + ([docs["evaluation_workbook"]] if docs["evaluation_workbook"] else [])
        for p in listed:
            if a["application_id"] not in by_path[p]["application_ids"]:
                fail(f"manifest: {a['application_id']} の書類に {p}（別の応募の書類）が入っています")
    for e in mf["files"]:
        if e["kind"] == "mail":  # manifest のメール情報が .eml と同じ
            msg = email.message_from_bytes((DATA / e["path"]).read_bytes(), policy=email.policy.default)
            if (str(msg["Subject"]) != e["mail"]["subject"] or msg["From"].addresses[0].addr_spec != e["mail"]["from"]
                    or [t.addr_spec for t in msg["To"].addresses] != e["mail"]["to"]):
                fail(f"{e['path']}: manifest のメール情報が .eml と違います")


def run(mf: dict, texts: dict, fail, ocr_text_of=None) -> None:
    L = Ledger()
    check_manifest(L, mf, fail)
    check_mails(L, fail)
    check_resumes(L, mf, texts, fail)
    check_jobs(L, mf, texts, fail)
    check_old_versions(L, texts, fail)
    check_workbook(L, mf, fail)
    check_scans(L, mf, fail, ocr_text_of)
