#!/usr/bin/env python3
"""ハンズオン資料の原稿から、HTML のスライド（site/lecture/）を作る。標準ライブラリだけで動く（Python 3.10 以上）。

実行（Repo の直下で）：python3 docs/lecture/tools/build.py
  --decks  デッキの構成の JSON（既定は docs/lecture/decks.json）
  --out    書き出し先（既定は site/lecture）
HTML のスライドは、原稿（keywords.md・decks.json・diagrams/）から作る。
確認の check.py は playwright も使う（作る人の道具。参加者は要らない）。

読むもの（docs/lecture/）
- keywords.md   キーワードのページ（本文・サブタイトル・スピーカーノート。直すときはここ）
- decks.json    デッキ（部）の構成、ページの並び、各ページの「確かめる」トピック、新しく足したページ
- deck.html     描画のひな形（kw・diagram の部品と「確かめる」の欄がある）
- diagrams/pNN.json  図のページ（SVG）。diagrams/figures.py が書く

書くもの（site/lecture/）
- index.html          目次（プレイヤーの slideCatalog）
- <デッキの id>/slides.html
- player.js           docs/lecture/player.js の写し（プレイヤーとの約束は同じ）
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
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
    title = page["fields"].get("タイトル") or page["heading"]
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="build.py", allow_abbrev=False, description="ハンズオン資料の原稿から、HTML のスライドを作る")
    ap.add_argument("--decks", type=Path, default=LECTURE / "decks.json", help="デッキの構成の JSON（既定は docs/lecture/decks.json）")
    ap.add_argument("--out", type=Path, default=SITE_LECTURE, help="書き出し先（既定は site/lecture）")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    conf = json.loads(a.decks.resolve().read_text(encoding="utf-8"))
    pages = parse_keywords(LECTURE / "keywords.md")
    out = a.out.resolve()
    used_pages = {x["page"] for d in conf["decks"] for x in d["items"] if "page" in x}
    missing = sorted(set(pages) - used_pages)
    if missing:
        print("注意：デッキに入っていないページ", missing)
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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
