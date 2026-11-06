#!/usr/bin/env python3
"""ハンズオン資料の原稿から、HTML のスライド（site/lecture/）と Markdown（docs/lecture/md/）を作る。標準ライブラリだけで動く（Python 3.10 以上）。

実行（Repo の直下で）：python3 docs/lecture/tools/build.py
  --decks  デッキの構成の JSON（既定は docs/lecture/decks.json）
  --out    HTML のスライドの書き出し先（--out も --md も省くと site/lecture に作る）
  --md     Markdown の書き出し先（付けると Markdown を作る。--out は付けたときだけ HTML も作る）。docs/lecture/md に作る前提
           （「確かめる」のリンクは、そこから Repo の直下への相対パスで書く）
  両方を作り直す：python3 docs/lecture/tools/build.py --out site/lecture --md docs/lecture/md
HTML も Markdown も、同じ原稿（keywords.md・decks.json・diagrams/）を同じ関数で読んで作る。
確認の check.py は playwright も使う（教材を直す人の道具。参加者は要らない）。

読むもの（docs/lecture/）
- keywords.md   キーワードのページ（本文・サブタイトル・スピーカーノート。直すときはここ）
- decks.json    デッキ（部）の構成、ページの並び、各ページの「確かめる」トピック、新しく足したページ
- deck.html     描画のひな形（kw・diagram の部品と「確かめる」の欄がある）
- diagrams/pNN.json  図のページ（SVG）。diagrams/figures.py が書く

書くもの（--out、既定は site/lecture/）
- index.html          目次（プレイヤーの slideCatalog）
- <デッキの id>/slides.html
- player.js           docs/lecture/player.js の写し（プレイヤーとの約束は同じ）

書くもの（--md、docs/lecture/md/）
- index.md            各部へのリンクと1行の説明
- <デッキの id>.md    部ごとの Markdown（節・ページ・本文・図・「確かめる」のリンク・ノート）
- img/pNN.svg         図。1枚のファイルとして開ける SVG（xmlns・字体・白い背景つき。段ごとに隠す印は外し、全部の段が見える）
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
LECTURE = HERE.parent
REPO = LECTURE.parent.parent
SITE_LECTURE = REPO / "site" / "lecture"        # --out の既定
PLAYER_SRC = LECTURE / "player.js"
CATALOG_CSS = LECTURE / "catalog.css"     # 目次のページの見た目

PAGE_RE = re.compile(r"^## p\.(\d+) (.+)$")
# fmt（ひな形の文字の記法）で描く文字だけを HTML 用に直す。ノート・リンク・確かめるの欄はそのまま
NO_ESCAPE = {"notes", "check", "checkNote", "src", "links", "id", "type", "section", "colW", "tone", "kind",
             "cmd", "file", "prompt", "svg", "lines", "expect"}   # cmd・lines・expect などは、ひな形が描くときに esc() で変換する。svg は図そのもの


def esc_markup(s: str) -> str:
    """< と > を文字として出す（<br> だけは改行として残す）"""
    s = s.replace("&", "&amp;")
    s = re.sub(r"<(?!br\s*/?>)", "&lt;", s)
    return re.sub(r"(?<!<br)(?<!<br/)(?<!<br /)>", "&gt;", s)


def esc_tree(v, key=None):
    if key in NO_ESCAPE:
        return v
    if isinstance(v, str):
        return esc_markup(v)
    if isinstance(v, list):
        return [esc_tree(x) for x in v]
    if isinstance(v, dict):
        return {k: esc_tree(x, k) for k, x in v.items()}
    return v


# ---------------- keywords.md を読む ----------------

def indent(line: str) -> int:
    return (len(line) - len(line.lstrip(" "))) // 2


def strip_bold(s: str) -> str:
    m = re.fullmatch(r"\*\*(.+)\*\*", s.strip())
    return m.group(1) if m else s.strip()


def parse_keywords(path: Path) -> dict[int, dict]:
    pages: dict[int, dict] = {}
    cur = None
    sec = None
    for ln in path.read_text(encoding="utf-8").splitlines():
        m = PAGE_RE.match(ln)
        if m:
            cur = {"no": int(m.group(1)), "heading": m.group(2), "fields": {}, "本文": [],
                   "スピーカーノート": []}      # 上の3つ以外の節は読まない（制作用のメモを公開の出力に出さない）
            pages[cur["no"]] = cur
            sec = None
            continue
        if cur is None:
            continue
        if ln.strip() == "---":
            cur = None
            continue
        if ln.startswith("### "):
            sec = ln[4:].strip()
            continue
        if sec is None:
            fm = re.match(r"^- (タイトル|サブタイトル|出典)：(.*)$", ln)
            if fm:
                cur["fields"][fm.group(1)] = fm.group(2).strip()
            continue
        if sec in cur:
            cur[sec].append(ln)
    return pages


def parse_body(lines: list[str]) -> tuple[list[dict], list[dict]]:
    """本文を、段（一般的な説明・Azure での説明）と表に分ける"""
    cols: list[dict] = []
    tables: list[dict] = []
    tbl_title = ""
    tbl: list[list[str]] = []

    def flush_table():
        nonlocal tbl, tbl_title
        if tbl:
            head, rows = tbl[0], [r for r in tbl[1:] if not all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in r)]
            tables.append({"title": tbl_title, "head": head, "rows": rows})
        tbl, tbl_title = [], ""

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("|"):
            tbl.append([c.strip() for c in s.strip("|").split("|")])
            continue
        flush_table()
        if not s.startswith("- "):
            tbl_title = strip_bold(s)        # 表の上の見出し（「**比べる項目**」）
            continue
        text = s[2:].strip()
        lv = indent(ln)
        if lv == 0:
            cols.append({"title": strip_bold(text), "groups": []})
        elif lv == 1:
            if not cols:
                cols.append({"title": "", "groups": []})
            if re.fullmatch(r"\*\*.+\*\*", text):
                cols[-1]["groups"].append({"h": strip_bold(text), "items": []})
            else:
                cols[-1]["groups"].append({"h": "", "items": [text]})
        else:
            if not cols:
                cols.append({"title": "", "groups": []})
            if not cols[-1]["groups"]:
                cols[-1]["groups"].append({"h": "", "items": []})
            cols[-1]["groups"][-1]["items"].append(text)
    flush_table()
    return cols, tables


def page_title(page: dict) -> str:
    """ページの題（「- タイトル：」の欄。なければ「## p.N」の見出し）。HTML のスライドも Markdown も、ここで決める"""
    return page["fields"].get("タイトル") or page["heading"]


def notes_text(page: dict) -> str:
    out = []
    for ln in page["スピーカーノート"]:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("- "):
            s = s[2:]
            out.append(("・" + s) if indent(ln) >= 1 else s)
    # ノートはプレイヤーが文字のまま出すので、Markdown の記号を外す
    return re.sub(r"\*\*(.+?)\*\*", r"\1", "\n".join(out)).replace("`", "")


# ---------------- デッキを組み立てる ----------------

def edition(path: str) -> str:
    """トピックのフォルダ（decks.json の path）の先頭で、基礎編か応用編かを決める（番号では決めない）"""
    head = path.split("/")[0]
    if head == "basic":
        return "基礎"
    if head == "applied":
        return "応用"
    raise SystemExit(f"トピックのフォルダ {path} が basic/ でも applied/ でも始まらない")


def topic_ref(topics: dict, no: str) -> dict:
    t = topics[no]
    return {"ed": edition(t["path"]), "no": no, "name": t["name"], "dir": t["path"].split("/")[-1]}


def load_diagram(no: int) -> dict | None:
    """図のページ（diagrams/pNN.json：title・caption・svg・notes）。なければ None。HTML も Markdown も、ここから読む"""
    dpath = LECTURE / "diagrams" / f"p{no:02d}.json"
    return json.loads(dpath.read_text(encoding="utf-8")) if dpath.exists() else None


def page_slides(page: dict, item: dict, topics: dict) -> list[dict]:
    no = page["no"]
    title = page_title(page)
    short = page["heading"] if len(title) > 26 else title     # 表・図のページの題（長い題は見出しの短い方を使う）
    sub = page["fields"].get("サブタイトル", "")
    cols, tables = parse_body(page["本文"])
    check = [topic_ref(topics, x) for x in item.get("check", [])]
    note = notes_text(page)
    common = {"section": item["section"], "check": check}
    if page["fields"].get("出典"):      # 出典はうす字で小さく出す（本文のページと図のページ）
        common["source"] = page["fields"]["出典"]
    if item.get("checkNote"):
        common["checkNote"] = item["checkNote"]
    slides = [{"id": f"p{no:02d}", "type": "kw", "title": title, "sub": sub, "cols": cols,
               "kicker": f"p.{no}", "notes": note, **common}]
    for k, t in enumerate(tables):
        slides.append({"id": f"p{no:02d}t{k + 1}", "type": "table", "title": f"{short}：{t['title'] or '比べる'}",
                       "kicker": f"p.{no}", "head": t["head"], "rows": t["rows"],
                       "notes": f"p.{no} の表。{t['title']}", **common})
    dg = load_diagram(no)      # SVG の図（diagrams/figures.py が書く）
    if dg:
        slides.append({"id": f"p{no:02d}d", "type": "diagram", "title": dg["title"], "kicker": f"p.{no}",
                       "svg": dg["svg"], "caption": dg.get("caption", ""), "notes": dg["notes"], **common})
    else:
        print(f"  p.{no}：図（diagrams/p{no:02d}.json）がないので、図なしで作る")
    return slides


def auto_slide(item: dict, conf: dict, decks: list[dict], pages: dict) -> dict:
    topics = conf["topics"]
    if item["auto"] == "topics":
        a, b = item["range"]
        rows = [[f"{edition(t['path'])} {n}", t["name"], t["data"], t["path"]]
                for n, t in topics.items() if a <= n <= b]
        return {"id": item["id"], "type": "table", "section": item["section"], "title": item["title"],
                "head": ["番号", "トピック", "データ", "フォルダ"], "rows": rows, "colW": ["11%", "38%", "10%", "41%"],
                **({"foot": item["foot"]} if item.get("foot") else {}),         # 表の下の1行（応用編の番号が 14 から始まる理由など）
                "notes": item.get("notes", "トピックの一覧。番号はデータと前提の順で、この順なら必ず動く。進行は部の順で、各ページの「確かめる」のトピックを開く。")}
    if item["auto"] == "chapter_map":
        rows = []
        for d in decks:
            if d["id"] == "intro":
                continue
            nos = [x["page"] for x in d["items"] if "page" in x]
            pg = f"p.{min(nos)}〜{max(nos)}"
            used = sorted({c for x in d["items"] for c in (x.get("check") or x.get("slide", {}).get("check") or [])})
            rows.append([d["title"].replace("　", " "), pg, "・".join(used) or "（スライドだけ）"])
        return {"id": item["id"], "type": "table", "section": item["section"], "title": item["title"],
                "head": ["部", "ページ", "確かめるトピック"], "rows": rows, "colW": ["38%", "26%", "36%"],
                "notes": "進行は部の順。各部のページから、右の列のトピックを開いて振る舞いを確かめる。部の順とトピックの番号は別。"}
    raise SystemExit(f"未知の auto：{item['auto']}")


def deck_meta(d: dict) -> list[str]:
    """部の表紙の下に出す2行（ページの範囲と、確かめるトピック）。HTML の表紙も Markdown の冒頭も同じ"""
    nos = [x["page"] for x in d["items"] if "page" in x]
    used = sorted({c for x in d["items"] for c in (x.get("check") or x.get("slide", {}).get("check") or [])})
    meta = []
    if nos:
        meta.append(f"ハンズオン資料 p.{min(nos)}〜{max(nos)}")
    if used:
        meta.append("確かめるトピック：" + "・".join(used))
    return meta


def build_deck(d: dict, conf: dict, pages: dict) -> dict:
    topics = conf["topics"]
    slides: list[dict] = []
    meta = deck_meta(d)
    slides.append({"id": "cover", "type": "cover", "label": conf["title"], "title": d["title"], "lead": d["lead"],
                   "meta": meta, "notes": d["lead"]})
    for item in d["items"]:
        if "page" in item:
            if item["page"] not in pages:
                raise SystemExit(f"{d['id']}：p.{item['page']} が keywords.md にない")
            slides.extend(page_slides(pages[item["page"]], item, topics))
        elif "slide" in item:
            s = dict(item["slide"])
            s["check"] = [topic_ref(topics, x) for x in s.get("check", [])]
            slides.append(s)
        elif "auto" in item:
            slides.append(auto_slide(item, conf, conf["decks"], pages))
    ids = [s["id"] for s in slides]
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        raise SystemExit(f"{d['id']}：id が重なっている {sorted(dup)}")
    return {"meta": {"id": d["id"], "title": d["title"], "short": d["short"], "accent": conf["accent"],
                     "home": "../index.html", "sections": d["sections"]},
            "slides": [esc_tree(s) for s in slides]}


def write_text(path: Path, text: str):
    """UTF-8・改行は LF で書く（Windows で作っても、生成物が変わらない）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_deck(deck: dict, template: str, out: Path):
    data = json.dumps(deck, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("__TITLE__", html.escape(deck["meta"]["title"].replace("　", " "))).replace("/*__DATA__*/null", data)
    write_text(out / deck["meta"]["id"] / "slides.html", page)


# ---------------- 目次 ----------------

def write_index(conf: dict, decks: list[dict], out: Path):
    cards = []
    for d, deck in zip(conf["decks"], decks):
        n = len(deck["slides"])
        cards.append({"id": d["id"], "href": f"{d['id']}/slides.html", "label": d["short"], "title": d["title"].replace("　", " "),
                      "color": conf["accent"], "items": [s["title"] for s in d["sections"]], "meta": f"{n}枚"})
    catalog = {"contract": 1, "title": conf["title"], "lead": conf["lead"], "decks": cards}
    style = "<style>" + CATALOG_CSS.read_text(encoding="utf-8") + "</style>"
    page = ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(conf['title'])}</title>\n{style}</head>\n<body>\n"
            "<!-- 目次のデータ（プレイヤーとの約束の window.slideCatalog）。カードの描き方はプレイヤーが持つ -->\n"
            f"<script>\nwindow.slideCatalog = {json.dumps(catalog, ensure_ascii=False, indent=1)};\n</script>\n"
            '<script src="player.js"></script>\n</body></html>\n')
    write_text(out / "index.html", page)


# ---------------- Markdown ----------------

GENERATED = "<!-- この Markdown は docs/lecture/tools/build.py --md が、keywords.md・decks.json・diagrams/ から作る。直すときは原稿を直す -->"
TOPIC_ROOT = "../../../"       # docs/lecture/md/ から Repo の直下への相対パス（--md は docs/lecture/md に作る前提）
FONT_FAMILY = "'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Meiryo', sans-serif"     # deck.html の .sp-target の font-family と同じ
SVG_NS = "http://www.w3.org/2000/svg"
SVG_ROOT = re.compile(r"\s*<svg\b([^>]*)>", re.S)
SVG_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:'([^']*)'|"([^"]*)")""")
DATA_STEP = re.compile(r"""\sdata-step\s*=\s*(?:'[^']*'|"[^"]*")""")
HIDDEN_INIT = re.compile(r"""opacity\s*[:=]\s*['"]?0(?![.\d])|visibility\s*[:=]\s*['"]?hidden|display\s*[:=]\s*['"]?none""")
CODE_SPAN = re.compile(r"`[^`]*`")


def standalone_svg(svg: str, name: str = "") -> str:
    """スライドの中の図（<svg viewBox=…>）を、1枚のファイルとして開ける SVG にする。
    xmlns と字体（HTML のスライドと同じ）と、図の全体を覆う白い背景（最初の要素）をつける。
    段ごとに出す印 data-step は外す（Markdown の表示では、全部の段が見える）。最初から隠す指定（opacity 0 など）は作り手の誤りなので止める"""
    m = SVG_ROOT.match(svg)
    if not m:
        raise SystemExit(f"{name}図の SVG が <svg …> で始まらない")
    attrs = {k: a if a is not None else b for k, a, b in SVG_ATTR.findall(m.group(1))}
    box = re.split(r"[\s,]+", (attrs.get("viewBox") or "").strip())
    try:
        x, y, w, h = box
        [float(v) for v in box]
    except ValueError:
        raise SystemExit(f"{name}図の SVG に、x y 幅 高さ の viewBox がない") from None
    body = svg[m.end():]
    if not body.rstrip().endswith("</svg>"):
        raise SystemExit(f"{name}図の SVG が </svg> で終わらない")
    tags = re.findall(r"<[^>]*>", body)          # 文字（text の中身）でなく、要素の属性だけを見る
    if any(HIDDEN_INIT.search(t) for t in tags):
        raise SystemExit(f"{name}図の SVG に、最初から隠す指定（opacity 0・visibility hidden・display none）がある。段ごとに出す部分は data-step だけで書く")
    root = {"xmlns": SVG_NS, "viewBox": attrs["viewBox"], "width": w, "height": h, "font-family": FONT_FAMILY}
    root.update(attrs)                       # もとの SVG にあるものは、もとの値を使う
    head = " ".join(f'{k}="{v.replace(chr(34), "&quot;")}"' for k, v in root.items())
    body = re.sub(r"<[^>]*>", lambda t: DATA_STEP.sub("", t.group(0)), body)      # 段ごとに出す印を外す（要素の属性だけ）
    out = f"<svg {head}><rect x='{x}' y='{y}' width='{w}' height='{h}' fill='#ffffff'/>{body}"
    out = out.rstrip() + "\n"
    try:
        ET.fromstring(out)
    except ET.ParseError as e:
        raise SystemExit(f"{name}図の SVG が XML として読めない：{e}") from None
    return out


def md_text(s) -> str:
    """スライドの文字の記法を Markdown にする。==赤== と ++緑++ は太字に、[[リンク]] はラベルだけに。コードの中はそのまま。
    < は文字として出す（<br> だけ残す）"""
    codes: list[str] = []

    def keep(m):
        codes.append(m.group(0))
        return f"\x00{len(codes) - 1}\x00"

    t = CODE_SPAN.sub(keep, "" if s is None else str(s))
    t = re.sub(r"\[\[(.+?)\]\]", r"\1", t)
    t = re.sub(r"\*\*(.+?)\*\*", lambda m: "**" + re.sub(r"==|\+\+", "", m.group(1)) + "**", t)     # 太字の中の ==・++ は外す
    t = re.sub(r"==(.+?)==", r"**\1**", t)
    t = re.sub(r"\+\+(.+?)\+\+", r"**\1**", t)
    t = re.sub(r"<(?!br\s*/?>)", "&lt;", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], t)


def md_plain(s) -> str:
    """題・図の代わりの文字など、飾りを外した1行の文字（deck.html の plain と同じ決まり）"""
    t = "" if s is None else str(s)
    t = re.sub(r"<br\s*/?>", " ", t)
    for pat in (r"\[\[(.+?)\]\]", r"==(.+?)==", r"\+\+(.+?)\+\+", r"\*\*(.+?)\*\*", r"`([^`]+)`"):
        t = re.sub(pat, r"\1", t)
    return t.replace("<", "&lt;").strip()


def md_cell(s) -> str:
    return md_text(s).replace("|", "\\|").replace("\n", "<br>")


def md_table(head: list, rows: list) -> str:
    n = len(head)
    lines = ["| " + " | ".join(md_cell(h) for h in head) + " |", "|" + "---|" * n]
    for r in rows:
        cells = list(r) + [""] * (n - len(r))
        lines.append("| " + " | ".join(md_cell(c) for c in cells) + " |")
    return "\n".join(lines)


def md_details(summary: str, lines: list[str]) -> str:
    return "<details>\n<summary>" + summary + "</summary>\n\n" + "\n".join(lines) + "\n\n</details>"


def md_notes(text: str) -> list[str]:
    """行ごとの文字のノート（「・」で始まる行は箇条）を、Markdown の行にする"""
    out: list[str] = []
    prev_item = False
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        item = s.startswith("・")
        if out and (not item or not prev_item):
            out.append("")                      # 段落どうし、段落と箇条の間は空行
        out.append("- " + md_text(s[1:].strip()) if item else md_text(s))
        prev_item = item
    return out


def md_check(refs: list[dict], topics: dict, note: str = "") -> str:
    links = [f"[{c['ed']} {c['no']} {c['name']}]({TOPIC_ROOT}{topics[c['no']]['path']}/README.md)" for c in refs]
    return "**確かめる**：" + "／".join(links) + (f"（{md_text(note)}）" if note else "")


def trim_blank(lines: list[str]) -> list[str]:
    """行の終わりの空白を落とし、前後と続く空行を1つにまとめる"""
    out: list[str] = []
    for ln in (x.rstrip() for x in lines):
        if ln or (out and out[-1]):
            out.append(ln)
    while out and not out[-1]:
        out.pop()
    return out


def md_slide_body(s: dict) -> list[str]:
    """手で書いたスライド（decks.json の slide）と自動の表を、Markdown のブロックにする"""
    t = s["type"]
    if t == "table":
        return [md_table(s["head"], s["rows"])] + ([md_text(s["foot"])] if s.get("foot") else [])
    if t == "points":
        lines = []
        for i, it in enumerate(s["items"], 1):
            lines.append(f"{i}. {md_text(it['text'])}")
            if it.get("sub"):
                lines.append(f"   - {md_text(it['sub'])}")
        return ["\n".join(lines)]
    if t == "recap":
        blocks = ["\n".join(f"- {md_text(it['text'])}" for it in s["items"])]
        if s.get("next"):
            blocks.append(md_text(s["next"]["text"]))
        return blocks
    if t == "steps":
        lines = []
        for i, it in enumerate(s["items"], 1):
            lines.append(f"{i}. **{md_text(it['t'])}**" + (f"：{md_text(it['s'])}" if it.get("s") else ""))
            if it.get("cmd"):
                lines.append(f"   - `{it['cmd']}`")
        return ["\n".join(lines)] + ([md_text(s["foot"])] if s.get("foot") else [])
    if t == "flow":
        blocks = []
        for r in s.get("rows") or [{"nodes": s.get("nodes", []), "arrows": s.get("arrows", [])}]:
            chain = ""
            for i, n in enumerate(r["nodes"]):
                if i:
                    arrows = r.get("arrows") or []
                    a = arrows[i - 1] if i - 1 < len(arrows) else {}
                    chain += f" →（{md_text(a['text'])}）→ " if a.get("text") else " → "
                chain += f"**{md_text(n['t'])}**"
            blocks.append((f"**{md_text(r['label'])}**\n\n" if r.get("label") else "") + chain)
            blocks.append("\n".join(f"- **{md_text(n['t'])}**：{md_text(n['s'])}" for n in r["nodes"] if n.get("s")))
        blocks += [f"> {md_text(b['text'])}" for b in s.get("banners", [])]
        return [b for b in blocks if b]
    if t == "compare":
        blocks = []
        for col in s["cols"]:
            blocks.append(f"#### {md_plain(col['title'])}")
            blocks.append("\n".join(f"- {'**' + md_text(r['label']) + '**：' if r.get('label') else ''}{md_text(r['text'])}"
                                    for r in col.get("rows", [])))
        for c in s.get("callouts") or []:
            head = f"**{md_text(c['title'])}**" if c.get("title") else ""
            if c.get("items"):
                blocks.append("\n".join([f"> {head}"] * bool(head) + [f"> - {md_text(x)}" for x in c["items"]]))
            else:
                blocks.append("> " + (head + "：" if head else "") + md_text(c.get("text", "")))
        if s.get("verdict"):
            blocks.append(f"> {md_text(s['verdict']['text'])}")
        return [b for b in blocks if b]
    raise SystemExit(f"Markdown に出せない type：{t}（{s.get('id')}）")


def md_slide(s: dict, topics: dict) -> list[str]:
    """手で書いたスライドと自動の表のページ：題・本文・「確かめる」・ノート"""
    blocks = ["### " + (f"{s['kicker']} " if s.get("kicker") else "") + md_plain(s["title"])]
    blocks += md_slide_body(s)
    refs = [topic_ref(topics, x) for x in s.get("check", [])]
    if refs:
        blocks.append(md_check(refs, topics, s.get("checkNote", "")))
    if s.get("notes"):
        blocks.append(md_details("ノート", md_notes(s["notes"])))
    return blocks


def md_page(page: dict, item: dict, topics: dict, files: dict[str, str]) -> list[str]:
    """keywords.md のページ：題・サブタイトル・本文（原稿のまま）・図とキャプション・「確かめる」・ノート。図の SVG は files に足す"""
    no = page["no"]
    blocks = [f"### p.{no} {md_plain(page_title(page))}"]
    if page["fields"].get("サブタイトル"):
        blocks.append(f"*{md_plain(page['fields']['サブタイトル'])}*")
    body = trim_blank(page["本文"])
    if body:
        blocks.append("\n".join(body))
    if page["fields"].get("出典"):
        blocks.append("出典：" + md_text(page["fields"]["出典"]))
    dg = load_diagram(no)
    fig_notes: list[str] = []
    if dg:
        files[f"img/p{no:02d}.svg"] = standalone_svg(dg["svg"], f"p.{no} ")
        alt = md_plain(dg["title"]).replace("[", "\\[").replace("]", "\\]")
        blocks.append(f"![{alt}](img/p{no:02d}.svg)")
        if dg.get("caption"):
            blocks.append(f"*{md_plain(dg['caption'])}*")
        fig_notes = md_notes(dg.get("notes", ""))
    else:
        print(f"  p.{no}：図（diagrams/p{no:02d}.json）がないので、図なしで作る")
    refs = [topic_ref(topics, x) for x in item.get("check", [])]
    if refs:
        blocks.append(md_check(refs, topics, item.get("checkNote", "")))
    notes = trim_blank(page["スピーカーノート"])
    if fig_notes:
        notes += ([""] if notes else []) + ["**図のノート**", ""] + fig_notes
    if notes:
        blocks.append(md_details("ノート", notes))
    return blocks


def md_deck(d: dict, conf: dict, pages: dict, files: dict[str, str]) -> str:
    topics = conf["topics"]
    blocks = [f"# {d['title'].replace('　', ' ')}", GENERATED, md_text(d["lead"])]
    meta = deck_meta(d)
    if meta:
        blocks.append("*" + "　／　".join(md_plain(m) for m in meta) + "*")
    blocks.append("[目次に戻る](index.md)")
    sec = None
    for item in d["items"]:
        item_sec = item.get("slide", item)["section"]      # 手で書いたスライドの節は、slide の中にある
        if item_sec != sec:
            sec = item_sec
            name = next((f"{x['id']}　{md_plain(x['title'])}" for x in d["sections"] if x["id"] == sec), sec)
            blocks.append(f"## {name}")
        if "page" in item:
            if item["page"] not in pages:
                raise SystemExit(f"{d['id']}：p.{item['page']} が keywords.md にない")
            blocks += md_page(pages[item["page"]], item, topics, files)
        elif "slide" in item:
            blocks += md_slide(item["slide"], topics)
        else:
            s = auto_slide(item, conf, conf["decks"], pages)
            if item["auto"] == "topics":      # フォルダの列は、トピックの README へのリンクにする
                s["rows"] = [[*r[:3], f"[`{r[3]}`]({TOPIC_ROOT}{r[3]}/README.md)"] for r in s["rows"]]
            blocks += md_slide(s, topics)
    return "\n\n".join(blocks) + "\n"


def md_index(conf: dict) -> str:
    blocks = [f"# {conf['title']}", GENERATED, md_text(conf["lead"]),
              "各ページの「確かめる」は、そのページのトピックの README へのリンクです。図は `img/` の SVG ファイルです。"
              "同じ原稿から作った HTML のスライドは `site/lecture/` にあります。",
              "\n".join(f"- [{d['title'].replace('　', ' ')}]({d['id']}.md)：{md_text(d['lead'])}" for d in conf["decks"])]
    return "\n\n".join(blocks) + "\n"


def build_markdown(conf: dict, pages: dict) -> dict[str, str]:
    """Markdown の全ファイルを、書き出し先からの相対パス → 中身で返す（部ごとの .md、index.md、img/pNN.svg）"""
    files: dict[str, str] = {}
    for d in conf["decks"]:
        files[f"{d['id']}.md"] = md_deck(d, conf, pages, files)
    files["index.md"] = md_index(conf)
    return files


def md_dir_note(md_out: Path) -> str:
    """--md が docs/lecture/md でないときの注意（「確かめる」のリンクは docs/lecture/md からの相対パスで書くため）。ふつうは空"""
    if md_out.resolve() == (LECTURE / "md").resolve():
        return ""
    return (f"注意：--md の書き出し先が docs/lecture/md ではない（{md_out.resolve()}）。「確かめる」のリンクは docs/lecture/md からの"
            "相対パス（../../../）で書くので、ここではリンク先がずれる。Repo に入れる Markdown は docs/lecture/md に作る")


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="build.py", allow_abbrev=False, description="ハンズオン資料の原稿から、HTML のスライドと Markdown を作る")
    ap.add_argument("--decks", type=Path, default=LECTURE / "decks.json", help="デッキの構成の JSON（既定は docs/lecture/decks.json）")
    ap.add_argument("--out", type=Path, help="HTML のスライドの書き出し先（--out も --md も省くと site/lecture）")
    ap.add_argument("--md", type=Path, help="Markdown の書き出し先（docs/lecture/md に作る前提）。付けると Markdown を作り、--out があるときだけ HTML も作る")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    conf = json.loads(a.decks.resolve().read_text(encoding="utf-8"))
    pages = parse_keywords(LECTURE / "keywords.md")
    out = a.out.resolve() if a.out else (None if a.md else SITE_LECTURE)
    used_pages = {x["page"] for d in conf["decks"] for x in d["items"] if "page" in x}
    missing = sorted(set(pages) - used_pages)
    if missing:
        print("注意：デッキに入っていないページ", missing)
    if out:
        template = (LECTURE / "deck.html").read_text(encoding="utf-8")
        decks = [build_deck(d, conf, pages) for d in conf["decks"]]
        for deck in decks:
            write_deck(deck, template, out)
        out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PLAYER_SRC, out / "player.js")
        write_index(conf, decks, out)
        total = sum(len(d["slides"]) for d in decks)
        print(f"{len(decks)} デッキ・{total} 枚を {out} に書いた")
        for deck in decks:
            print(f"  {deck['meta']['id']}: {len(deck['slides'])} 枚")
    if a.md:
        note = md_dir_note(a.md)
        if note:
            print(note, file=sys.stderr)
        files = build_markdown(conf, pages)
        for name, text in files.items():
            write_text(a.md.resolve() / name, text)
        n_svg = sum(1 for n in files if n.endswith(".svg"))
        print(f"{len(conf['decks'])} 部の Markdown と図 {n_svg} 枚を {a.md.resolve()} に書いた")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
