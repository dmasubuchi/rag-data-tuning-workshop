"""作ったファイルを読み直して検査する。問題があれば内容を出して 1 を返す。

- docx・xlsx・pdf・eml・png がライブラリで開けること。
- 文字のある文書から応募番号・求人番号が取れること。スキャンの書類からは文字が取れないこと。
- manifest の ID が、応募・選考履歴の台帳（content/source_ats.json）と合っていること。
- 求人 1 件ごとに「応募者 → 職務経歴書 → 面接の評価 → 連絡メール」がたどれること。
- 番号・人物・求人の食い違いが無いこと（check_identity.py。メール・職務経歴書・求人票・評価・スキャン・manifest を台帳と突き合わせる）。
- 使ってはいけない語、実在らしいメールアドレス・電話番号が無いこと。
- --ocr を付けると、tesseract があればスキャンの書類を OCR して応募番号が読めるかも調べる。

使ってはいけない語（固有名）の一覧は、このファイルに書かない。環境変数 PUBLIC_CHECK_BANNED が指すファイルから読む
（Repo 直下の tools/check_public.py と同じ形。1行1語、UTF-8。大文字小文字と全角半角は区別しない）。
変数がない・ファイルがない・空のときは、説明を出して 2 で止まる。見つけたときは、語そのものは画面に出さず、
「禁止語の一覧の 3 番目」のように番号で知らせる。
"""
from __future__ import annotations

import email
import email.policy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import check_identity
from lib_common import DATA, load_json

BANNED_ENV = "PUBLIC_CHECK_BANNED"
# 固有名ではない、生成の残りの目印。このファイル自身が検査（check_public）に当たらないように、2つに分けて書く
LEFTOVERS = [a + b for a, b in (("ZX", "7Q"), ("CAN", "ARY"), ("data", "gen"), ("シリ", "ーズ"), ("ser", "ies"))]
BANNED_RE = [re.compile(r"/Users/")]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)")
# メールの例に使ってよいドメイン（tools/check_public.py と同じ。RFC 2606 の予約名と、日本の example.jp）
EXAMPLE_DOMAINS = {"example.com", "example.net", "example.org", "example.jp"}
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")
PHONE_RE = re.compile(r"(?<!\d)(\d{2,4})-(\d{2,4})-(\d{4})(?!\d)")
FAILS: list[str] = []


def fail(msg: str) -> None:
    FAILS.append(msg)
    print("NG ", msg)


class BannedListError(Exception):
    """禁止語の一覧がない・読めない・空。"""


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def load_banned() -> list[str]:
    """環境変数 PUBLIC_CHECK_BANNED のファイルから、禁止語の一覧を読む（tools/check_public.py と同じ読み方）。

    ない・読めない・空のときは BannedListError。メッセージに、語は入れない。
    """
    value = os.environ.get(BANNED_ENV, "").strip()
    if not value:
        raise BannedListError(f"禁止語の一覧の場所が分かりません。環境変数 {BANNED_ENV} に、一覧のファイルの場所を入れてください"
                              "（1行1語、UTF-8。tools/check_public.py と同じ形）。")
    path = Path(value).expanduser()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise BannedListError(f"禁止語の一覧のファイルを読めません（{BANNED_ENV} の指す場所。{e.strerror or type(e).__name__}）。") from e
    except UnicodeDecodeError:
        raise BannedListError(f"禁止語の一覧のファイルが UTF-8 ではありません（{BANNED_ENV} の指す場所）。") from None
    words = [w for w in (line.strip() for line in text.split("\n")) if w]
    if not words:
        raise BannedListError(f"禁止語の一覧のファイルが空です（{BANNED_ENV} の指す場所）。")
    return words


def banned_hits(name: str, text: str, banned: list[str]) -> list[str]:
    """text に、禁止語（と、生成の残りの目印）が入っていれば、問題の文を返す。語そのものは文に入れず、一覧の番号で言う。"""
    body = nfkc(text)
    out = []
    for i, w in enumerate(banned, start=1):
        if re.search(re.escape(nfkc(w)), body, re.IGNORECASE):
            out.append(f"{name} に禁止語の一覧の {i} 番目の語があります")
    for w in LEFTOVERS:
        if w.lower() in body.lower():
            out.append(f"{name} に生成の残りの目印 {w!r} があります")
    return out


def is_example_domain(domain: str) -> bool:
    domain = domain.lower()
    return domain in EXAMPLE_DOMAINS or domain.endswith(RESERVED_SUFFIXES)


def text_of(path) -> str:
    """文書の本文を文字列で取り出す（スキャンは空になるはず）。"""
    suf = path.suffix.lower()
    if suf == ".docx":
        from docx import Document
        d = Document(path)
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts += [c.text for c in row.cells]
        for s in d.sections:
            parts += [p.text for p in s.footer.paragraphs]
        parts += [d.core_properties.title or "", d.core_properties.subject or "", d.core_properties.comments or ""]
        return "\n".join(parts)
    if suf == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path)
        parts = [wb.properties.title or "", wb.properties.subject or ""]
        for ws in wb.worksheets:
            parts.append(ws.title)
            for row in ws.iter_rows(values_only=True):
                parts += [str(v) for v in row if v is not None]
        return "\n".join(parts)
    if suf == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(path))
        meta = r.metadata or {}
        return "\n".join([(pg.extract_text() or "") for pg in r.pages] + [str(meta.get("/Title", "")), str(meta.get("/Subject", ""))])
    if suf == ".eml":
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
        return "\n".join([str(msg["From"]), str(msg["To"]), str(msg["Subject"]), msg.get_content()])
    return ""


def ocr_text(path) -> str:
    """スキャンの書類を tesseract で OCR して文字列を返す（--ocr のとき）。"""
    with tempfile.TemporaryDirectory() as td:
        if path.suffix == ".pdf":
            subprocess.run(["pdftoppm", "-r", "200", "-png", str(path), f"{td}/pg"], check=True)
            img = f"{td}/pg-1.png"
        else:
            img = str(path)
        return subprocess.run(["tesseract", img, "-", "-l", "jpn+eng", "--psm", "6"], capture_output=True, text=True).stdout


def main() -> int:
    FAILS.clear()
    try:
        banned = load_banned()
    except BannedListError as e:
        print("NG ", e)
        return 2
    ats = load_json("source_ats.json")
    with open(DATA / "manifest.json", encoding="utf-8") as fh:
        mf = json.load(fh)
    evals = load_json("evaluations.json")["rows"]
    mails = load_json("mail.json")["mails"]
    app_by_id = {a["application_id"]: a for a in ats["applications"]}
    persons = {p["person_key"]: p["display_name"] for p in ats["persons"]}
    reqs = {r["req_id"]: r for r in ats["requisitions"]}
    texts: dict[str, str] = {}

    # 1. ファイルが開けて、大きさが manifest と合う
    for e in mf["files"]:
        p = DATA / e["path"]
        if not p.exists():
            fail(f"{e['path']} がありません"); continue
        if p.stat().st_size != e["bytes"]:
            fail(f"{e['path']} の大きさが manifest と違います")
        try:
            if p.suffix == ".png":
                from PIL import Image
                im = Image.open(p); im.load()
                texts[e["path"]] = ""
            else:
                texts[e["path"]] = text_of(p)
        except Exception as ex:  # noqa: BLE001
            fail(f"{e['path']} が開けません: {ex!r}"); continue
        has_text = bool(re.sub(r"\s", "", texts[e["path"]].replace("研修用の架空データ", "")))
        if e["text_layer"] and not has_text:
            fail(f"{e['path']} から文字が取れません")
        if not e["text_layer"]:
            body = ""
            if p.suffix == ".pdf":
                from pypdf import PdfReader
                r = PdfReader(str(p))
                body = "".join((pg.extract_text() or "") for pg in r.pages)
                n_img = sum(len(pg.images) for pg in r.pages)
                if n_img < 1:
                    fail(f"{e['path']} に画像がありません")
            if body.strip():
                fail(f"{e['path']} は画像だけのはずなのに文字が取れました: {body[:30]!r}")

    # 1b. 旧い版の求人票（updates/）。トピック 17「更新と削除」だけで使う。manifest に入れない（build_hr_index.py も Storage に置かない）
    in_manifest = {e["path"] for e in mf["files"]}
    for p in sorted((DATA / "updates").glob("*")):
        rel = f"updates/{p.name}"
        if rel in in_manifest:
            fail(f"{rel} が manifest に入っています（旧い版は manifest に入れない）")
        try:
            texts[rel] = text_of(p)
        except Exception as ex:  # noqa: BLE001
            fail(f"{rel} が開けません: {ex!r}"); continue
        if "研修用の架空データ" not in texts[rel]:
            fail(f"{rel} に「研修用の架空データ」の記載がありません")

    # 2. 文書内の ID が manifest と合う
    for e in mf["files"]:
        t = texts.get(e["path"], "")
        if e["text_layer"] and e["kind"] != "interview_evaluations":
            if e["req_id"] and e["req_id"] not in t:
                fail(f"{e['path']} の本文に {e['req_id']} がありません")
            for aid in e["application_ids"]:
                if aid not in t and not (e["path"].startswith("mail/") and e["doc_id"] == "MAIL-08"):
                    fail(f"{e['path']} の本文に {aid} がありません")
            for pk in e["person_keys"]:
                if e["kind"] == "resume" and persons[pk] not in t:
                    fail(f"{e['path']} に氏名 {persons[pk]} がありません")

    # 3. 台帳（応募・選考履歴）との整合
    for a in mf["applications"]:
        src = app_by_id.get(a["application_id"])
        if not src:
            fail(f"{a['application_id']} が台帳にありません"); continue
        for k in ("person_key", "req_id", "req_version", "route", "agency_id", "step", "status", "interview_at", "updated_at"):
            if a[k] != src[k]:
                fail(f"{a['application_id']} の {k} が台帳と違います: {a[k]} / {src[k]}")
        if a["candidate_name"] != persons[src["person_key"]]:
            fail(f"{a['application_id']} の氏名が台帳と違います")
    for r in mf["requisitions"]:
        if r["title"] != reqs[r["req_id"]]["title"]:
            fail(f"{r['req_id']} の求人名が台帳と違います")
    events = {}
    for ev in ats["stage_events"]:
        events.setdefault(ev["application_id"], []).append(ev)
    for r in evals:
        if r["application_id"] not in app_by_id:
            fail(f"評価 {r['evaluation_id']} の応募番号が台帳にありません")
        held = r["held_at"].replace(" ", "T")[:16]
        done = [ev for ev in events.get(r["application_id"], []) if ev["step"] == r["stage"] and ev["event_type"] == "面接実施"
                and ev["at"][:16] == held]
        if not done:
            fail(f"評価 {r['evaluation_id']} の実施日時が選考履歴の「面接実施」と合いません（{r['application_id']} {r['stage']} {r['held_at']}）")
    for m in mails:
        a = app_by_id.get(m.get("application_id"))
        if m.get("application_id") and (not a or a["req_id"] != m["req_id"]):
            fail(f"メール {m['id']} の応募番号と求人番号が台帳と合いません")
        if m["req_id"] not in m["subject"]:
            fail(f"メール {m['id']} の件名に求人番号がありません")

    # 4. 求人ごとの連鎖（応募者 → 職務経歴書 → 面接の評価 → 連絡メール）
    for r in mf["requisitions"]:
        chain_ok = [a for a in mf["applications"] if a["req_id"] == r["req_id"]
                    and a["documents"]["resume"] and a["documents"]["evaluation_ids"] and a["documents"]["mail"]]
        print(f"  {r['req_id']}: 応募 {len(r['application_ids'])} 件のうち、経歴書・評価・メールが全部たどれる応募 {len(chain_ok)} 件 "
              + ", ".join(a["application_id"] for a in chain_ok))
        if not chain_ok:
            fail(f"{r['req_id']} に、応募→経歴書→評価→メールがたどれる応募がありません")

    # 4b. 番号・人物・求人の食い違い（全ファイルを台帳と突き合わせる）
    use_ocr = "--ocr" in sys.argv and shutil.which("tesseract") is not None
    check_identity.run(mf, texts, fail, ocr_text if use_ocr else None)

    # 5. 使ってはいけない語・個人情報らしいもの
    scan_targets = dict(texts)
    scan_targets["manifest.json"] = json.dumps(mf, ensure_ascii=False)
    for name, t in scan_targets.items():
        for msg in banned_hits(name, t, banned):
            fail(msg)
        for rx in BANNED_RE:
            if rx.search(t):
                fail(f"{name} に使わないパターン {rx.pattern!r} があります")
        for m in EMAIL_RE.finditer(t):
            if not is_example_domain(m.group(1)):
                fail(f"{name} に、メールの例に使ってよいドメイン（example.com・.example など）以外のメールアドレスがあります: {m.group(0)}")
        for m in PHONE_RE.finditer(t):
            if m.group(2) != "0000" and m.group(3) != "0000":
                fail(f"{name} に電話番号らしいものがあります: {m.group(0)}")
    # 文書の記載
    for e in mf["files"]:
        if e["text_layer"] and "研修用の架空データ" not in texts.get(e["path"], ""):
            fail(f"{e['path']} に「研修用の架空データ」の記載がありません")

    # 6. OCR（任意）: 読めた文字数と、応募番号が読めたか（別の番号が読めた場合は 4b で NG にしている）
    if use_ocr:
        for e in mf["files"]:
            if e["text_layer"]:
                continue
            out = ocr_text(DATA / e["path"])
            ok = [a for a in e["application_ids"] if re.sub(r"\s", "", a) in re.sub(r"\s", "", out)]
            print(f"  OCR {e['path']}: 文字数 {len(out.strip())}、応募番号が読めた: {ok or 'なし'}")

    print("検査: " + ("すべて問題なし" if not FAILS else f"{len(FAILS)} 件の問題"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
