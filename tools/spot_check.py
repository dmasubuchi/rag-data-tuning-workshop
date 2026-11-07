"""評価の質問を、人が抜き取りで確かめる一覧（1枚の HTML）にする（標準ライブラリだけ。通信しない）。

質問の種類ごとにほぼ均等に N 問を選び、問ごとに「問・種類・why・正解の文書」を1つの画面に出す。
正解の文書は、根拠の語句（evidence）を黄色で強調した、前後の本文つき。人事の本文は、tools/check_questions.py が
語句を探すのと同じもの（tools/evallib/questions.py の hr_source_text）、ホテルは hotel_texts を読む（二重には書かない）。
各問に「正しい」「直す」のチェックと、メモの欄がある。結果は、ページのボタンで Markdown に書き出せる
（ブラウザの中だけで動く。ファイルを開くだけでよく、通信も外部の読み込みもない）。

使い方（Repo 直下で）：
  python tools/spot_check.py --dataset hr --n 10 --seed 1 --out spot-hr.html
  python tools/spot_check.py --dataset hotel --n 8 --seed 1 --hotel-data <ホテルのデータの JSON> --out spot-hotel.html
  --dataset     hr / hotel / sengoku
  --n           選ぶ問の数（既定 10）。全部の問より多ければ、全部
  --seed        選び方の種（既定 1）。同じ seed・同じ質問なら、同じ問が選ばれる
  --file PATH   質問のファイルを変える（省くと、データごとの既定の場所）
  --hotel-data  ホテルのデータ（HotelsData_toAzureBlobs_ja.json）の場所。省くと _work/hotel-vectors/ の中
  --out FILE    書く HTML

選び方：種類（質問の type）の並びの順に、1問ずつ配るのを N 問になるまで繰り返す。N が種類の数より少なければ、先頭の種類から
1問ずつ。種類の中は、質問の番号（qid）と seed から決まる順（質問の並びには依らない）。一覧は、種類の並びの順、種類の中は
質問のファイルの順。

正解の文書ごとに出すもの：
  人事      文書の ID・種類・evidence の句と前後の本文（前後 60 字。「前後を広げる」で 300 字）。permission の質問は、
            hidden_ids の文書を「見えないはずの文書」として別に出す。画像だけの文書は、本文のもと（記述と描く指示）から
  ホテル    名前（日本語・英語）・カテゴリ・評価・駐車場・住所。evidence の句は、日本語・英語の項目のどちらにあるかと前後の文。
            evidence のない condition の質問は、条件に当たる項目の値（Rooms/… は条件に合う客室の値）と、検索の $filter の文字
  武将      名前と、profile の先頭 120 字（evidence があれば、その句の前後）
語句が本文のもとに見つからなければ、赤い印で出し、画面にも 1 行出す（一覧は書く）。

終了コード：0 = 書けた／1 = HTML が書けない／2 = 質問・データのファイルが読めない、または引数が使えない
"""
import argparse
import collections
import hashlib
import html
import json
import re
import sys
from pathlib import Path

from evallib import questions as ev
from evallib.questions import DATASETS, QUESTION_FILES, DataError, allowed_types, load_data, load_questions

NARROW = 60            # 根拠の語句の前後に出す字数
WIDE = 300             # 「前後を広げる」で出す字数
HEAD = 120             # 根拠の語句がない文書で、本文の先頭から出す字数

DATASET_LABEL = {"hr": "人事（採用の文書）", "hotel": "ホテル", "sengoku": "戦国武将"}
TYPE_LABEL = {
    "paraphrase": "言い換え", "proper-noun": "固有名詞", "numeric": "数値", "multi-doc": "複数の文書", "scan": "スキャン",
    "permission": "権限", "condition": "条件", "ja-en": "日本語と英語", "amenity": "設備",
    "keyword-wins": "キーワードが強い", "vector-wins": "ベクトルが強い", "hybrid-improves": "ハイブリッドで良くなる",
    "hybrid-worsens": "ハイブリッドで悪くなる", "climax": "意味の並べ直しで上がる",
}
ROLE_LABEL = {"role:employee": "一般社員", "role:recruiter": "採用担当"}
LANGUAGE_FIELD = {"ja": "日本語の項目", "en": "英語の項目"}
OTHER_LANGUAGE = {"ja": "en", "en": "ja"}


def e(text):
    """HTML に出す文字のエスケープ（データの文字は、かならずこれを通す）。"""
    return html.escape(str(text), quote=True)


# ------------------------------------------------------------------ 選ぶ

def type_order(dataset, questions):
    """質問にある種類を、そのデータの種類の並びの順に（並びにない種類は、出てきた順に最後）。"""
    present = [q["type"] for q in questions if isinstance(q.get("type"), str)]
    known = list(allowed_types(dataset))
    ordered = known + [t for t in dict.fromkeys(present) if t not in known]
    return [t for t in ordered if t in present]


def _rank(seed, q, index):
    key = q.get("qid") if isinstance(q.get("qid"), str) and q["qid"] else f"#{index}"
    return hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()


def select_questions(dataset, questions, n, seed):
    """種類ごとにほぼ均等に n 問（足りない種類の分は、ほかの種類へ）。同じ seed・同じ質問なら同じ問。

    種類の並びの順に1問ずつ配ることを n 問になるまで繰り返す（n が種類の数より少なければ、先頭の種類から1問ずつ）。
    種類の中は、qid と seed のハッシュの順に取る。返す並びは、種類の並びの順、種類の中は質問のファイルの順。
    """
    questions = [(i, q) for i, q in enumerate(questions) if isinstance(q, dict) and isinstance(q.get("type"), str)]
    order = type_order(dataset, [q for _, q in questions])
    pools = {kind: sorted((p for p in questions if p[1]["type"] == kind), key=lambda p: _rank(seed, p[1], p[0]))
             for kind in order}
    taken = dict.fromkeys(order, 0)
    total = 0
    while total < n and any(taken[kind] < len(pools[kind]) for kind in order):
        for kind in order:
            if total < n and taken[kind] < len(pools[kind]):
                taken[kind] += 1
                total += 1
    picked = []
    for kind in order:
        picked += [q for _, q in sorted(pools[kind][:taken[kind]], key=lambda p: p[0])]
    return picked


# ------------------------------------------------------------------ 本文の中の語句を探す

def _normalize(text):
    """改行をふくむ空白の並びは改行1つに（本文の見た目を整える。語句の探し方は、空白を無視するので変わらない）。"""
    return re.sub(r"[ \t\r　]*\n\s*", "\n", text).strip()


def locate(text, phrase):
    """text の中の phrase の位置 (始め, 終わり)。空白（全角を含む）は無視して探す（check_questions と同じ探し方）。なければ None。"""
    where = [i for i, ch in enumerate(text) if not ch.isspace()]
    squashed = "".join(text[i] for i in where)
    target = "".join(ch for ch in phrase if not ch.isspace())
    if not target:
        return None
    pos = squashed.find(target)
    if pos < 0:
        return None
    return where[pos], where[pos + len(target) - 1] + 1


def excerpt(text, phrase, width=NARROW):
    """phrase の前後 width 字ずつの抜き書き。なければ None。前後の本文と、強調する句に分けて返す。"""
    text = _normalize(text)
    span = locate(text, phrase)
    if span is None:
        return None
    start, end = span
    low, high = max(0, start - width), min(len(text), end + width)
    return {"before": text[low:start], "hit": text[start:end], "after": text[end:high],
            "cut_before": low > 0, "cut_after": high < len(text)}


def _flow(text, newline):
    return e(text).replace("\n", newline) if newline else e(text)


def render_excerpt(exc, newline=None):
    """抜き書きを HTML にする。強調する句だけを <mark> で囲む。newline があれば、本文の改行をその文字にする。"""
    return ("…" if exc["cut_before"] else "") + _flow(exc["before"], newline) + "<mark>" + _flow(exc["hit"], newline) \
        + "</mark>" + _flow(exc["after"], newline) + ("…" if exc["cut_after"] else "")


def _phrases(value):
    """evidence の値（語句、または語句の並び）を、語句の並びにする。形が違えば空。"""
    if isinstance(value, str):
        value = [value]
    return [x for x in value if isinstance(x, str) and x.strip()] if isinstance(value, list) else []


def _snippet(text, phrase, label=None):
    return {"label": label, "phrase": phrase, "narrow": excerpt(text, phrase, NARROW), "wide": excerpt(text, phrase, WIDE)}


# ------------------------------------------------------------------ 文書ごとの出し方（共通の形：辞書）
#
# doc = {"id", "title", "sub", "tags": [札], "source": 出どころ, "facts": [(項目, 値)], "snippets": [...],
#        "head": 先頭の文字（語句がないとき）, "problem": 読めない理由,
#        "what": スキャンの記述, "form": スキャンの形, "link": (file:// の URL, 名前) または None, "missing": 画像がない旨}

def _doc(doc_id, title, **fields):
    return {"id": doc_id, "title": title, "sub": "", "tags": [], "source": None, "facts": [], "snippets": [],
            "head": None, "problem": None, "what": None, "form": None, "link": None, "missing": None, **fields}


def hr_doc(doc_id, q, ctx, warnings):
    file = ctx["files"].get(doc_id)
    if file is None:
        warnings.append(f"{q.get('qid')}：{doc_id} が manifest にありません")
        return _doc(doc_id, "（データにない文書）", problem="データ（manifest）にない文書です")
    if file.get("kind") == "scan":
        return scan_doc(doc_id, file, q, ctx, warnings)
    tags = ["画像だけ（OCR が要る）"] if file.get("ocr_required") else []
    # メールの札は、manifest の kind_label（面接の連絡メール）を使わない（全部が面接の連絡ではない）。件名を添える
    title = "メール" if file.get("kind") == "mail" else file.get("kind_label") or file.get("kind") or ""
    doc = _doc(doc_id, title, tags=tags)
    if doc_id not in ctx["cache"]:
        try:
            ctx["cache"][doc_id] = ev.hr_source_text(doc_id, file, ctx["content_dir"])
        except ev.DataShapeError:
            raise
        except DataError as error:
            ctx["cache"][doc_id] = error
    found = ctx["cache"][doc_id]
    if isinstance(found, DataError):
        warnings.append(f"{q.get('qid')}：{found}")
        doc["problem"] = f"本文のもとを読めません（{found}）"
        return doc
    text, doc["source"] = found
    if file.get("kind") == "mail":
        doc["sub"] = text.split("\n", 1)[0]          # hr_source_text は、メールを「件名\n本文」で返す
    evidence = q.get("evidence") if isinstance(q.get("evidence"), dict) else {}
    phrases = _phrases(evidence.get(doc_id))
    for phrase in phrases:
        snippet = _snippet(text, phrase)
        doc["snippets"].append(snippet)
        if snippet["narrow"] is None:
            warnings.append(f"{q.get('qid')}：{doc_id} の語句「{phrase}」が本文のもと（{doc['source']}）にありません")
    if not phrases:
        doc["head"] = _normalize(text)[:HEAD]
    return doc


# スキャン（画像だけの文書）：本文のもとの Python のコードは出さない。語句が出る場所を札で示し、その行だけを出す。
SCAN_CODE_LABEL = "画像に印字する文字（make_scans.py の該当行から）"
SCAN_CODE_RAW_LABEL = "make_scans.py の該当行（コード）"
SCAN_DATES_LABEL = "日付の書き方（道具が補った別の書き方）"
SCAN_JSON_LABEL = "scans.json の項目"
_LITERAL = re.compile(r"""f?"((?:[^"\\]|\\.)*)"|f?'((?:[^'\\]|\\.)*)'""")


def _covering_lines(text, span):
    """text の中の span（始め, 終わり）をふくむ行の並び。"""
    start, end = span
    first = text.count("\n", 0, start)
    last = text.count("\n", 0, max(start, end - 1))
    return text.split("\n")[first:last + 1]


def _literals(line):
    """コードの 1 行にある文字列のリテラル（"…"・'…'）の中身。x["key"] の key は、印字する文字でないので除く。"""
    found = []
    for match in _LITERAL.finditer(line):
        if match.start() > 0 and line[match.start() - 1] == "[":
            continue
        found.append(match.group(1) if match.group(1) is not None else match.group(2))
    return [text for text in found if text.strip()]


def scan_snippet(parts, phrase):
    """スキャンの語句が出る場所を、画像に近い順（描く指示 → scans.json → 補った日付の書き方）に探して、その行だけを返す。"""
    shown = None
    span = locate(parts["code"], phrase) if parts["code"] else None
    if span:
        lines = _covering_lines(parts["code"], span)
        text = "\n".join(x for x in (" ｜ ".join(_literals(line)) for line in lines) if x)
        shown = (SCAN_CODE_LABEL, text) if locate(text, phrase) else (SCAN_CODE_RAW_LABEL, "\n".join(x.strip() for x in lines))
    else:
        for label, text in ((SCAN_JSON_LABEL, parts["json"]), (SCAN_DATES_LABEL, parts["dates"])):
            span = locate(text, phrase)
            if span:
                shown = (label, "\n".join(_covering_lines(text, span)))
                break
    exc = excerpt(shown[1], phrase, len(shown[1])) if shown else None
    return {"label": shown[0] if exc else None, "phrase": phrase, "narrow": exc, "wide": None}


def scan_doc(doc_id, file, q, ctx, warnings):
    """スキャンの文書：記述（what・form）・語句が出る行・実際のスキャンのファイルへのリンク（画像を目で確かめる）。"""
    tags = ["画像だけ（OCR が要る）"] if file.get("ocr_required") else []
    doc = _doc(doc_id, "スキャンした書類", tags=tags)
    key = f"scan:{doc_id}"
    if key not in ctx["cache"]:
        try:
            ctx["cache"][key] = ev.hr_scan_parts(doc_id, ctx["content_dir"])
        except ev.DataShapeError:
            raise
        except DataError as error:
            ctx["cache"][key] = error
    parts = ctx["cache"][key]
    if isinstance(parts, DataError):
        warnings.append(f"{q.get('qid')}：{parts}")
        doc["problem"] = f"本文のもとを読めません（{parts}）"
        return doc
    for note in parts["notes"]:
        warnings.append(f"{q.get('qid')}：{doc_id}：{note}")
    doc["what"], doc["form"] = parts["scan"].get("what"), parts["scan"].get("form")
    path = file.get("path")
    if isinstance(path, str) and path:
        image = (Path(ctx["data_dir"]) / path).resolve()
        if image.is_file():
            doc["link"] = (image.as_uri(), f"スキャンの画像を開く（{path}）")
        else:
            doc["missing"] = f"スキャンのファイルが見つかりません（{path}）"
    evidence = q.get("evidence") if isinstance(q.get("evidence"), dict) else {}
    for phrase in _phrases(evidence.get(doc_id)):
        snippet = scan_snippet(parts, phrase)
        doc["snippets"].append(snippet)
        if snippet["narrow"] is None:
            warnings.append(f"{q.get('qid')}：{doc_id} の語句「{phrase}」が本文のもと（scans.json・make_scans.py）にありません")
    return doc


def _name(hotel):
    return hotel.get("HotelName_ja") or hotel.get("HotelName") or ""


def _plain(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, bool) else str(value)


def condition_facts(hotel, condition):
    """condition に出てくる項目の、このホテルの値。Rooms/… は、条件に合う客室の値（客室ごとの条件は、まとめて満たす客室）。"""
    rooms_condition = {key: spec for key, spec in condition.items() if key.startswith("Rooms/")}
    rooms = [r for r in (hotel.get("Rooms") or []) if isinstance(r, dict)]
    matching = [r for r in rooms if ev.matches({"Rooms": [r]}, rooms_condition)] if rooms_condition else []
    facts = []
    for key in condition:
        if key.startswith("Rooms/"):
            values = list(dict.fromkeys(_plain(ev.value_at(r, key[len("Rooms/"):])) for r in matching))
            facts.append((key, "、".join(values[:6]) + (f"（ほか {len(values) - 6} 件）" if len(values) > 6 else "") or "（合う客室がない）"))
        else:
            facts.append((key, _plain(ev.value_at(hotel, key))))
    return facts


def hotel_doc(hotel_id, q, ctx, warnings):
    hotel = ctx["hotels"].get(hotel_id)
    if hotel is None:
        warnings.append(f"{q.get('qid')}：ホテル {hotel_id} がデータにありません")
        return _doc(hotel_id, "（データにないホテル）", problem="ホテルのデータにありません")
    address = hotel.get("Address") if isinstance(hotel.get("Address"), dict) else {}
    english = hotel.get("HotelName") or ""
    doc = _doc(hotel_id, _name(hotel), sub=english if english != _name(hotel) else "")
    condition = q.get("condition") if isinstance(q.get("condition"), dict) else None
    evidence = q.get("evidence") if isinstance(q.get("evidence"), dict) else {}
    phrases = _phrases(evidence.get(hotel_id))
    facts = None
    if condition and not phrases:
        try:
            facts = condition_facts(hotel, condition)
        except ValueError:
            facts = None
    doc["facts"] = facts if facts is not None else [
        ("カテゴリ", hotel.get("Category_ja") or hotel.get("Category") or ""), ("評価", _plain(hotel.get("Rating", ""))),
        ("駐車場", {True: "あり", False: "なし"}.get(hotel.get("ParkingIncluded"), "")),
        ("住所", " ".join(x for x in (address.get("City"), address.get("StateProvince")) if x))]
    texts = ev.hotel_texts(hotel)
    first = ev.question_language(q.get("question"))
    for phrase in phrases:
        for language in (first, OTHER_LANGUAGE[first]):
            snippet = _snippet(texts[language], phrase, LANGUAGE_FIELD[language])
            if snippet["narrow"] is not None:
                break
        else:
            snippet = {"label": None, "phrase": phrase, "narrow": None, "wide": None}
            warnings.append(f"{q.get('qid')}：ホテル {hotel_id} の語句「{phrase}」がデータにありません")
        doc["snippets"].append(snippet)
    return doc


def sengoku_doc(doc_id, q, ctx, warnings):
    person = ctx["people"].get(doc_id)
    if person is None:
        warnings.append(f"{q.get('qid')}：{doc_id} がデータにありません")
        return _doc(doc_id, "（データにない人物）", problem="武将のデータにありません")
    doc = _doc(doc_id, person.get("name", ""), facts=[(label, str(person[key])) for label, key in
                                                       (("家", "clan"), ("国", "province")) if person.get(key)])
    profile = person.get("profile") or ""
    evidence = q.get("evidence") if isinstance(q.get("evidence"), dict) else {}
    phrases = _phrases(evidence.get(doc_id))
    for phrase in phrases:
        snippet = _snippet(profile, phrase)
        doc["snippets"].append(snippet)
        if snippet["narrow"] is None:
            warnings.append(f"{q.get('qid')}：{doc_id} の語句「{phrase}」が profile にありません")
    if not phrases:
        doc["head"] = profile[:HEAD] + ("…" if len(profile) > HEAD else "")
    return doc


DOC_BUILDERS = {"hr": hr_doc, "hotel": hotel_doc, "sengoku": sengoku_doc}


def _ids(value):
    return [x for x in dict.fromkeys(value) if isinstance(x, str)] if isinstance(value, list) else []


def build_context(dataset, data, content_dir):
    if dataset == "hr":
        content_dir = Path(content_dir or ev.HR_CONTENT_DIR)
        return {"files": {str(f["doc_id"]): f for f in data["files"]}, "content_dir": content_dir,
                "data_dir": content_dir.parent.parent, "cache": {}}     # manifest の path は、この data_dir（applied/data）からの道
    if dataset == "hotel":
        return {"hotels": {str(h["HotelId"]): h for h in data}}
    return {"people": {str(p["id"]): p for p in data}}


# ------------------------------------------------------------------ HTML

CSS = """
:root{color-scheme:light dark;--bg:#f4f5f8;--card:#fff;--ink:#1b2130;--mute:#596377;--line:#dbe0e8;--soft:#f0f2f7;
--accent:#2a5bd7;--ok:#17794a;--ok-bg:#e1f4ea;--fix:#b2530a;--fix-bg:#fdecd9;--mark:#ffe27a;--markink:#1b2130;
--hid:#b3261e;--hid-bg:#fdeceb;--warn:#8a5a00;--warn-bg:#fff4d6}
@media (prefers-color-scheme:dark){:root{--bg:#10141a;--card:#1a1f28;--ink:#e6e9ef;--mute:#9aa4b6;--line:#2d3441;--soft:#222934;
--accent:#86abff;--ok:#5fd39a;--ok-bg:#15301f;--fix:#ffb36a;--fix-bg:#3a2713;--mark:#735a00;--markink:#fff1bd;
--hid:#ff918a;--hid-bg:#391a19;--warn:#f0c15a;--warn-bg:#31290f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 system-ui,-apple-system,"Hiragino Sans","Yu Gothic UI","Noto Sans JP",sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:0 16px 64px}
h1{font-size:1.35rem;margin:28px 0 4px}
h1 .sub{font-size:1rem;font-weight:500;color:var(--mute);margin-left:.5em}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);margin:0 -16px;padding:8px 16px}
.bar .in{max-width:880px;margin:0 auto;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.count{display:flex;gap:14px;flex:1;min-width:200px;font-variant-numeric:tabular-nums}
.count strong{font-size:1.1rem}
.ok-c{color:var(--ok)}.fix-c{color:var(--fix)}
button{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.35em .9em;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
@media (prefers-color-scheme:dark){button.primary{color:#0b1020}}
button:focus-visible,a:focus-visible,textarea:focus-visible,input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
.summary{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:14px 0}
.summary dl{display:flex;flex-wrap:wrap;gap:6px 28px;margin:0 0 10px}
.summary dt{color:var(--mute);font-size:.8rem}.summary dd{margin:0;font-weight:600}
.types,.nav{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0;padding:0;list-style:none}
.types li{background:var(--soft);border-radius:999px;padding:1px 12px;font-size:.88rem}
.types small{color:var(--mute)}
.nav a{display:inline-block;min-width:2.4em;text-align:center;border:1px solid var(--line);border-radius:6px;padding:0 8px;font-size:.82rem;
color:var(--ink);text-decoration:none;background:var(--soft)}
.nav a.ok{background:var(--ok-bg);border-color:var(--ok);color:var(--ok)}
.nav a.fix{background:var(--fix-bg);border-color:var(--fix);color:var(--fix)}
.how{color:var(--mute);font-size:.88rem;margin:10px 0 0}
.q{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--line);border-radius:10px;padding:16px 20px;margin:18px 0;scroll-margin-top:64px}
.q[data-state=ok]{border-left-color:var(--ok)}.q[data-state=fix]{border-left-color:var(--fix)}
.qh{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.qid{font:600 .95rem ui-monospace,SFMono-Regular,Menlo,monospace}
.badge{font-size:.8rem;border:1px solid var(--line);background:var(--soft);border-radius:999px;padding:0 10px}
.badge.role{border-color:var(--hid);color:var(--hid);background:var(--hid-bg)}
.qtext{font-size:1.12rem;font-weight:600;margin:8px 0 4px;overflow-wrap:anywhere}
.why,.qnote{color:var(--mute);font-size:.9rem;border-left:3px solid var(--line);padding-left:10px;margin:8px 0;overflow-wrap:anywhere}
.cond{font:.85rem ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--soft);border-radius:6px;padding:4px 10px;margin:8px 0;overflow-wrap:anywhere}
h3{font-size:.82rem;font-weight:600;color:var(--mute);margin:16px 0 6px}
h3.hid{color:var(--hid)}
.docs{list-style:none;margin:0;padding:0}
.doc{border:1px solid var(--line);background:var(--soft);border-radius:8px;padding:10px 14px;margin:8px 0}
.doc.hid{border-color:var(--hid);background:var(--hid-bg)}
.dh{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px}
.did{font:600 .92rem ui-monospace,SFMono-Regular,Menlo,monospace}
.dt{font-weight:600}.ds{color:var(--mute);font-size:.88rem}
.tag{font-size:.75rem;border:1px solid var(--warn);color:var(--warn);background:var(--warn-bg);border-radius:999px;padding:0 8px}
.src{color:var(--mute);font-size:.78rem;overflow-wrap:anywhere}
.what{margin:6px 0 0;overflow-wrap:anywhere}.what .ds{display:block}
.open{margin:6px 0 0;font-size:.9rem;overflow-wrap:anywhere}.open a{color:var(--accent)}
.facts{display:flex;flex-wrap:wrap;gap:2px 18px;margin:4px 0 0;font-size:.88rem}
.facts div{display:flex;gap:6px}.facts dt{color:var(--mute)}.facts dd{margin:0}
blockquote{margin:8px 0 0;padding:0;white-space:pre-wrap;overflow-wrap:anywhere}
blockquote.snip{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px}
.lang{display:block;color:var(--mute);font-size:.75rem;margin-bottom:2px}
mark{background:var(--mark);color:var(--markink);font-weight:700;border-radius:3px;padding:0 .1em;
box-shadow:0 1px 0 var(--accent)}
.miss{color:var(--hid);background:var(--hid-bg);border:1px solid var(--hid);border-radius:6px;padding:6px 10px;margin:8px 0 0;font-size:.88rem}
.none{color:var(--mute);font-size:.9rem;margin:4px 0}
details{margin-top:6px;font-size:.85rem}
summary{cursor:pointer;color:var(--accent)}
.chk{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:16px}
.chk label{display:inline-flex;align-items:center;gap:.45em;padding:.3em .95em;border:1px solid var(--line);border-radius:999px;cursor:pointer;background:var(--card)}
.chk input{width:1.05em;height:1.05em;margin:0}
.chk label.on-ok{background:var(--ok-bg);border-color:var(--ok);color:var(--ok);font-weight:600}
.chk label.on-fix{background:var(--fix-bg);border-color:var(--fix);color:var(--fix);font-weight:600}
textarea{width:100%;font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-top:10px;
min-height:3.4em;resize:vertical}
dialog{width:min(760px,94vw);border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--ink);padding:16px 18px}
dialog::backdrop{background:rgba(0,0,0,.5)}
dialog textarea{height:min(55vh,420px);font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;margin:8px 0}
.dlg-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.dlg-bar .msg{color:var(--mute);font-size:.85rem;flex:1}
@media (max-width:560px){.q{padding:12px 14px}.wrap{padding:0 10px 48px}.bar{margin:0 -10px;padding:8px 10px}}
@media print{.bar,.chk button{display:none}.q{break-inside:avoid}}
"""

# ブラウザの中で動く部分。質問のデータは持たず、ページの中身（data-… と本文）を読む。localStorage は、使えなくても動く。
JS = """
(function () {
  'use strict';
  var sheet = document.getElementById('sheet');
  var cards = [].slice.call(document.querySelectorAll('.q'));
  var STATUS = {ok: '正しい', fix: '直す'};
  var storeKey = 'spot-check:' + sheet.getAttribute('data-sheet');

  function readCard(card) {
    var on = card.querySelector('input.st:checked');
    return {status: on ? on.value : '', note: card.querySelector('textarea.note').value};
  }
  function save() {
    var all = {};
    cards.forEach(function (card) { all[card.getAttribute('data-qid')] = readCard(card); });
    try { window.localStorage.setItem(storeKey, JSON.stringify(all)); } catch (e) { /* 保存できなくても使える */ }
  }
  function refresh() {
    var ok = 0, fix = 0;
    cards.forEach(function (card, i) {
      var s = readCard(card).status;
      card.setAttribute('data-state', s);
      card.querySelectorAll('.chk label').forEach(function (label) {
        var input = label.querySelector('input');
        label.className = input.checked ? 'on-' + input.value : '';
      });
      var chip = document.querySelectorAll('.nav a')[i];
      if (chip) { chip.className = s; }
      if (s === 'ok') { ok++; } else if (s === 'fix') { fix++; }
    });
    document.getElementById('c-ok').textContent = ok;
    document.getElementById('c-fix').textContent = fix;
    document.getElementById('c-left').textContent = cards.length - ok - fix;
  }
  function restore() {
    var all = {};
    try { all = JSON.parse(window.localStorage.getItem(storeKey) || '{}') || {}; } catch (e) { all = {}; }
    cards.forEach(function (card) {
      var saved = all[card.getAttribute('data-qid')];
      if (!saved) { return; }
      card.querySelectorAll('input.st').forEach(function (input) { input.checked = (input.value === saved.status); });
      card.querySelector('textarea.note').value = saved.note || '';
    });
  }

  cards.forEach(function (card) {
    card.addEventListener('change', function (event) {
      var target = event.target;
      if (target.classList.contains('st') && target.checked) {
        card.querySelectorAll('input.st').forEach(function (input) { if (input !== target) { input.checked = false; } });
      }
      refresh(); save();
    });
    card.querySelector('textarea.note').addEventListener('input', save);
  });

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function line(text) { return text.replace(/\\s*\\n\\s*/g, ' '); }
  function buildMarkdown() {
    var d = new Date();
    var rows = cards.map(function (card) { return {card: card, r: readCard(card)}; });
    var count = function (s) { return rows.filter(function (x) { return x.r.status === s; }).length; };
    var fixes = rows.filter(function (x) { return x.r.status === 'fix'; })
      .map(function (x) { return x.card.getAttribute('data-qid'); });
    var out = ['# 抜き取り確認の結果　' + sheet.getAttribute('data-label'), '',
      '- 確認日：' + d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()),
      '- 問の数：' + cards.length + '（全 ' + sheet.getAttribute('data-total') + ' 問から、seed ' + sheet.getAttribute('data-seed') + '）',
      '- 正しい ' + count('ok') + '・直す ' + count('fix') + '・未確認 ' + (cards.length - count('ok') - count('fix')),
      '- 直す問：' + (fixes.length ? fixes.join('、') : 'なし'), ''];
    rows.forEach(function (x) {
      var card = x.card, status = STATUS[x.r.status] || '未確認';
      out.push('## ' + card.getAttribute('data-qid') + '（' + card.getAttribute('data-type') + '）：' + status, '');
      out.push('- 問：' + line(card.querySelector('.qtext').textContent));
      out.push('- 正解の文書：' + (card.getAttribute('data-answers') || 'なし'));
      if (card.getAttribute('data-hidden')) { out.push('- 見えないはずの文書：' + card.getAttribute('data-hidden')); }
      var note = x.r.note.replace(/\\s+$/, '');
      if (note) { out.push('- メモ：' + note.replace(/\\n/g, '\\n  ')); }
      out.push('');
    });
    return out.join('\\n');
  }

  var dialog = document.getElementById('export');
  var area = document.getElementById('md');
  var msg = document.getElementById('msg');
  function say(text) { msg.textContent = text; }
  document.getElementById('open-export').addEventListener('click', function () {
    area.value = buildMarkdown();
    say('');
    if (dialog.showModal) { dialog.showModal(); } else { dialog.setAttribute('open', ''); }
    area.focus(); area.select();
  });
  document.getElementById('close-export').addEventListener('click', function () {
    if (dialog.close) { dialog.close(); } else { dialog.removeAttribute('open'); }
  });
  document.getElementById('copy-md').addEventListener('click', function () {
    function fallback() {
      area.focus(); area.select();
      var done = false;
      try { done = document.execCommand('copy'); } catch (e) { done = false; }
      say(done ? 'コピーしました' : '選択したので、Cmd/Ctrl+C でコピーしてください');
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(area.value).then(function () { say('コピーしました'); }, fallback);
    } else { fallback(); }
  });
  document.getElementById('save-md').addEventListener('click', function () {
    var blob = new Blob([area.value], {type: 'text/markdown;charset=utf-8'});
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = sheet.getAttribute('data-file');
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
    say('保存しました（' + link.download + '）');
  });

  restore();
  refresh();
})();
"""


def render_snippet(snippet, newline):
    if snippet["narrow"] is None:
        return f'<p class="miss">語句「{e(snippet["phrase"])}」が、本文のもとに見つかりません</p>'
    label = f'<span class="lang">{e(snippet["label"])}</span>' if snippet["label"] else ""
    out = f'<blockquote class="snip">{label}{render_excerpt(snippet["narrow"], newline)}</blockquote>'
    if snippet["wide"] and snippet["wide"] != snippet["narrow"]:
        out += (f'<details><summary>前後を広げる</summary><blockquote>{render_excerpt(snippet["wide"], newline)}</blockquote>'
                "</details>")
    return out


def render_doc(doc, hidden, newline):
    head = f'<span class="did">{e(doc["id"])}</span><span class="dt">{e(doc["title"])}</span>'
    if doc["sub"]:
        head += f'<span class="ds">{e(doc["sub"])}</span>'
    head += "".join(f'<span class="tag">{e(tag)}</span>' for tag in doc["tags"])
    parts = [f'<div class="dh">{head}</div>']
    if doc["source"]:
        parts.append(f'<div class="src">本文のもと：{e(doc["source"])}</div>')
    if doc["what"]:
        parts.append(f'<p class="what">{e(doc["what"])}' + (f'<span class="ds">{e(doc["form"])}</span>' if doc["form"] else "") + "</p>")
    if doc["link"]:
        parts.append(f'<p class="open"><a href="{e(doc["link"][0])}" target="_blank" rel="noopener">{e(doc["link"][1])}</a></p>')
    if doc["missing"]:
        parts.append(f'<p class="miss">{e(doc["missing"])}</p>')
    facts = [(k, v) for k, v in doc["facts"] if v != ""]
    if facts:
        parts.append('<dl class="facts">' + "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in facts) + "</dl>")
    if doc["problem"]:
        parts.append(f'<p class="miss">{e(doc["problem"])}</p>')
    parts += [render_snippet(s, newline) for s in doc["snippets"]]
    if doc["head"]:
        parts.append(f'<blockquote class="snip"><span class="lang">先頭</span>{e(doc["head"])}</blockquote>')
    return f'<li class="doc hid">{"".join(parts)}</li>' if hidden else f'<li class="doc">{"".join(parts)}</li>'


def render_question(index, q, dataset, ctx, warnings):
    build = DOC_BUILDERS[dataset]
    answers, hidden = _ids(q.get("answer_ids")), _ids(q.get("hidden_ids"))
    newline = " ｜ " if dataset == "hotel" else None
    kind = q.get("type")
    qid = q.get("qid") if isinstance(q.get("qid"), str) else f"#{index}"
    answer_docs = [build(i, q, ctx, warnings) for i in answers]
    hidden_docs = [build(i, q, ctx, warnings) for i in hidden]
    role = q.get("as_role") if isinstance(q.get("as_role"), str) else ""
    role_text = f"{ROLE_LABEL[role]}（{role}）" if role in ROLE_LABEL else role

    head = f'<span class="qid">{e(qid)}</span><span class="badge">{e(kind)}'
    head += f'（{e(TYPE_LABEL[kind])}）</span>' if kind in TYPE_LABEL else "</span>"
    if role_text:
        head += f'<span class="badge role">聞く人：{e(role_text)}</span>'
    body = [f'<div class="qh">{head}</div>', f'<p class="qtext">{e(q.get("question", ""))}</p>']
    if isinstance(q.get("why"), str) and q["why"].strip():
        body.append(f'<p class="why">{e(q["why"])}</p>')
    if isinstance(q.get("note"), str) and q["note"].strip():
        body.append(f'<p class="qnote">作るときのメモ：{e(q["note"])}</p>')
    if isinstance(q.get("condition"), dict):
        try:
            body.append(f'<p class="cond">条件：{e(ev.condition_to_filter(q["condition"]))}</p>')
        except ValueError as error:
            body.append(f'<p class="miss">条件の形が違います（{e(error)}）</p>')
    if answer_docs:
        body.append(f'<h3>正解の文書（{len(answer_docs)} 件）</h3><ul class="docs">'
                    + "".join(render_doc(d, False, newline) for d in answer_docs) + "</ul>")
    else:
        body.append("<h3>正解の文書：なし" + ("（この人には何も見えないのが正しい）" if hidden_docs else "") + "</h3>")
    if hidden_docs:
        who = f"{role_text}には" if role_text else "この人には"
        body.append(f'<h3 class="hid">{e(who)}見えないはずの文書（{len(hidden_docs)} 件）</h3><ul class="docs">'
                    + "".join(render_doc(d, True, newline) for d in hidden_docs) + "</ul>")
    body.append('<div class="chk"><label><input type="checkbox" class="st" value="ok"><span>正しい</span></label>'
                '<label><input type="checkbox" class="st" value="fix"><span>直す</span></label></div>'
                '<textarea class="note" rows="2" placeholder="メモ（直すときは、どこをどう直すか）" aria-label="メモ"></textarea>')
    return (f'<article class="q" id="q{index}" data-qid="{e(qid)}" data-type="{e(kind)}" data-answers="{e("、".join(answers))}" '
            f'data-hidden="{e("、".join(hidden))}" data-state="">{"".join(body)}</article>')


def sheet_id(dataset, picked, seed):
    digest = hashlib.sha256(json.dumps([[q.get("qid"), q.get("question")] for q in picked], ensure_ascii=False).encode("utf-8"))
    return f"{dataset}-seed{seed}-{digest.hexdigest()[:10]}"


def make_sheet(dataset, questions, data, *, n, seed, content_dir=None):
    """1枚の HTML の文字列と、選んだ質問、画面に出す注意の文（語句が見つからない、など）を返す。

    questions は質問の並び、data は質問が指す文書のデータ（load_data の返り値）。content_dir は人事の本文のもと
    （省くと applied/data/_build/content）。文書のファイルの一番上の形が違えば DataShapeError。
    """
    if dataset not in DATASETS:
        raise ValueError(f"dataset は {'・'.join(DATASETS)} のどれかです：{dataset!r}")
    questions = [q for q in questions if isinstance(q, dict)]
    picked = select_questions(dataset, questions, n, seed)
    ctx = build_context(dataset, data, content_dir)
    warnings = []
    cards = [render_question(i, q, dataset, ctx, warnings) for i, q in enumerate(picked, 1)]

    pool = collections.Counter(q.get("type") for q in questions)
    chosen = collections.Counter(q.get("type") for q in picked)
    label = DATASET_LABEL[dataset]
    types = "".join(
        f'<li>{e(kind)}'
        + (f"（{e(TYPE_LABEL[kind])}）" if kind in TYPE_LABEL else "")
        + f' <strong>{chosen[kind]}</strong><small>／{pool[kind]}</small></li>'
        for kind in type_order(dataset, questions))
    nav = "".join(f'<a href="#q{i}" title="{e(q.get("question", ""))}">{e(q.get("qid", i))}</a>' for i, q in enumerate(picked, 1))
    name = f"spot-check-{dataset}-seed{seed}.md"
    summary = (
        '<section class="summary"><dl>'
        f"<div><dt>データ</dt><dd>{e(label)}</dd></div>"
        f"<div><dt>問の数</dt><dd>{len(picked)}（全 {len(questions)} 問から）</dd></div>"
        f"<div><dt>seed</dt><dd>{e(seed)}</dd></div></dl>"
        f'<ul class="types">{types}</ul><ul class="nav">{nav}</ul>'
        '<p class="how">問・正解の文書・黄色の根拠が合っているかを見て、「正しい」か「直す」を付けます。入力はこのブラウザに残ります。</p>'
        "</section>")
    bar = ('<div class="bar"><div class="in"><div class="count"><span>正しい <strong class="ok-c" id="c-ok">0</strong></span>'
           '<span>直す <strong class="fix-c" id="c-fix">0</strong></span><span>未確認 <strong id="c-left">0</strong></span></div>'
           '<button type="button" class="primary" id="open-export">Markdown に書き出す</button></div></div>')
    dialog = ('<dialog id="export" aria-label="書き出し"><div class="dlg-bar"><strong>確認の結果（Markdown）</strong></div>'
              '<textarea id="md" readonly aria-label="Markdown"></textarea>'
              '<div class="dlg-bar"><button type="button" class="primary" id="copy-md">コピー</button>'
              '<button type="button" id="save-md">ファイルに保存</button><span class="msg" id="msg" role="status"></span>'
              '<button type="button" id="close-export">閉じる</button></div></dialog>')
    page = (
        '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>抜き取り確認シート　{e(label)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<main class="wrap" id="sheet" data-sheet="{e(sheet_id(dataset, picked, seed))}" data-label="{e(label)}" '
        f'data-total="{len(questions)}" data-seed="{e(seed)}" data-file="{e(name)}">\n'
        f'<h1>抜き取り確認シート <span class="sub">{e(label)}</span></h1>\n{bar}\n{summary}\n' + "\n".join(cards)
        + f"\n</main>\n{dialog}\n"
        f"<script>{JS}</script>\n</body>\n</html>\n")
    return page, picked, warnings


# ------------------------------------------------------------------ CLI

def build_parser():
    parser = argparse.ArgumentParser(description="評価の質問を、人が抜き取りで確かめる一覧（1枚の HTML）にする")
    parser.add_argument("--dataset", required=True, choices=DATASETS, help="質問のデータ")
    parser.add_argument("--n", type=int, default=10, help="選ぶ問の数（既定 10）")
    parser.add_argument("--seed", type=int, default=1, help="選び方の種（既定 1）")
    parser.add_argument("--file", type=Path, help="質問のファイル（省くと、データごとの既定の場所）")
    parser.add_argument("--hotel-data", type=Path, help="ホテルのデータの JSON（--dataset hotel のときだけ）")
    parser.add_argument("--out", required=True, type=Path, help="書く HTML のファイル")
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.n < 1:
        print("--n は 1 以上で渡します。", file=sys.stderr)
        return 2
    if args.hotel_data and args.dataset != "hotel":
        print("--hotel-data は --dataset hotel のときだけ使えます。", file=sys.stderr)
        return 2
    question_file = args.file or QUESTION_FILES[args.dataset]
    try:
        questions = load_questions(question_file)
    except DataError as error:
        print(f"NG    {error}", file=sys.stderr)
        return 2
    try:
        data = load_data(args.dataset, args.hotel_data)
    except DataError as error:
        print(f"NG    {error}", file=sys.stderr)
        if args.dataset == "hotel" and not args.hotel_data:
            print("      ホテルのデータの JSON の場所は、--hotel-data で渡します。", file=sys.stderr)
        return 2
    try:
        page, picked, warnings = make_sheet(args.dataset, questions, data, n=args.n, seed=args.seed)
    except DataError as error:
        print(f"NG    {error}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"注意  {warning}", file=sys.stderr)
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(page, encoding="utf-8")
    except OSError as error:
        print(f"NG    {args.out} に書けません（{error.strerror or error}）", file=sys.stderr)
        return 1
    counts = collections.Counter(q["type"] for q in picked)
    print(f"書きました：{args.out}（{len(picked)} 問、seed {args.seed}。"
          + "・".join(f"{kind} {counts[kind]}" for kind in type_order(args.dataset, picked)) + "）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
