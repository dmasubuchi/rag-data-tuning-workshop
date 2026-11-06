"""docs/lecture/tools/build.py --md の試験。

ハンズオン資料の原稿（keywords.md・decks.json・diagrams/）から、HTML のスライドと同じ元で Markdown（docs/lecture/md/）が
作られることと、図の SVG が1枚のファイルとして開ける形（xmlns・字体・白い背景・全部の段が見える）であることを確かめる。通信しない。
"""

import html
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
LECTURE = REPO_DIR / "docs" / "lecture"
BUILD = LECTURE / "tools" / "build.py"
DECKS = LECTURE / "decks.json"
MD_DIR = LECTURE / "md"
SVG_NS = "http://www.w3.org/2000/svg"
DECK_JSON = re.compile(r"const DECK = (\{.*\});\nconst META", re.S)


def load_build():
    spec = importlib.util.spec_from_file_location("lecture_build_md", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_build(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BUILD), *args], capture_output=True, text=True, check=True)


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def deck_slides(slides_html: Path) -> list[dict]:
    m = DECK_JSON.search(slides_html.read_text(encoding="utf-8"))
    assert m, f"{slides_html} に DECK のデータがない"
    return json.loads(m.group(1))["slides"]


class MdTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.html = cls.root / "html"
        cls.md = cls.root / "md"
        run_build("--out", str(cls.html), "--md", str(cls.md))
        cls.conf = json.loads(DECKS.read_text(encoding="utf-8"))
        cls.build = load_build()
        cls.pages = cls.build.parse_keywords(LECTURE / "keywords.md")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_md_and_html_from_same_source(self):
        # keywords.md の各ページの題が、HTML のスライドと Markdown の両方にある。図の題・図の中の文字も同じ元から
        html_titles: dict[str, str] = {}
        html_svgs: dict[str, str] = {}
        for d in self.conf["decks"]:
            for s in deck_slides(self.html / d["id"] / "slides.html"):
                html_titles[s["id"]] = html.unescape(s["title"])
                if s["type"] == "diagram":
                    html_svgs[s["id"]] = s["svg"]
        md_all = "\n".join((self.md / f"{d['id']}.md").read_text(encoding="utf-8") for d in self.conf["decks"])
        self.assertEqual(len(self.pages), 52)
        for no, page in self.pages.items():
            title = page["fields"].get("タイトル") or page["heading"]
            self.assertEqual(html_titles.get(f"p{no:02d}"), title, f"p.{no} の題が HTML のスライドにない")
            self.assertEqual(md_all.count(f"\n### p.{no} {title}\n"), 1, f"p.{no} の題が Markdown にない")
            dpath = LECTURE / "diagrams" / f"p{no:02d}.json"
            dg = json.loads(dpath.read_text(encoding="utf-8"))
            self.assertIn(f"](img/p{no:02d}.svg)", md_all)
            self.assertEqual(html_svgs[f"p{no:02d}d"], dg["svg"])
            svg_file = (self.md / "img" / f"p{no:02d}.svg").read_text(encoding="utf-8")
            texts = lambda s: re.findall(r"<text\b[^>]*>(.*?)</text>", s, re.S)
            self.assertEqual(texts(svg_file), texts(dg["svg"]), f"p.{no} の SVG の文字が、図の元と違う")
        # 手で書いたスライド・自動の表の題も、HTML と Markdown の両方にある
        for d in self.conf["decks"]:
            md = (self.md / f"{d['id']}.md").read_text(encoding="utf-8")
            deck = {s["id"]: html.unescape(s["title"]) for s in deck_slides(self.html / d["id"] / "slides.html")}
            for item in d["items"]:
                sid = item["slide"]["id"] if "slide" in item else item.get("id")
                if sid:
                    plain = re.sub(r"==|\+\+|\*\*", "", deck[sid])
                    self.assertRegex(md, rf"(?m)^### (p\.\d+ )?{re.escape(plain)}$", f"{d['id']} の {sid} の題が Markdown にない")

    def test_svg_files_are_standalone(self):
        files = sorted((self.md / "img").glob("p*.svg"))
        self.assertEqual(len(files), 52)
        deck_html = (LECTURE / "deck.html").read_text(encoding="utf-8")
        stack = re.search(r"font-family: (\"Hiragino Sans\"[^;]*);", deck_html).group(1)
        for f in files:
            raw = f.read_text(encoding="utf-8")
            self.assertIn(f'xmlns="{SVG_NS}"', raw, f.name)
            root = ET.fromstring(raw)           # XML として読めること
            self.assertEqual(root.tag, f"{{{SVG_NS}}}svg", f.name)
            vb = [float(x) for x in root.get("viewBox").split()]
            self.assertEqual([float(root.get("width")), float(root.get("height"))], vb[2:], f.name)
            self.assertEqual(root.get("font-family").replace("'", '"'), stack, f"{f.name} の字体が、HTML のスライドと違う")
            bg = root[0]                         # 最初の要素が、図の全体を覆う白の rect
            self.assertEqual(bg.tag, f"{{{SVG_NS}}}rect", f.name)
            self.assertIn(bg.get("fill").lower(), ("#fff", "#ffffff", "white"), f.name)
            self.assertEqual([float(bg.get(k)) for k in ("x", "y", "width", "height")], vb, f.name)
            self.assertGreater(len(root.findall(f".//{{{SVG_NS}}}text")), 0, f.name)
            # 段ごとに隠す印は付けない（Markdown の表示で全部の段が見える）
            self.assertNotIn("data-step", raw, f.name)
            self.assertIsNone(re.search(r"opacity\s*[:=]\s*['\"]?0(?![.\d])|visibility\s*[:=]\s*['\"]?hidden|display\s*[:=]\s*['\"]?none", raw), f.name)
            for bad in ("<script", "<foreignObject", "href="):
                self.assertNotIn(bad, raw, f"{f.name} に {bad} がある")

    def test_standalone_svg_rejects_hidden_initial_state(self):
        build = self.build
        ok = build.standalone_svg("<svg viewBox='0 50 100 40'><g data-step='2'><text x='1' y='2'>a</text></g></svg>")
        self.assertNotIn("data-step", ok)
        self.assertIn("<rect x='0' y='50' width='100' height='40' fill='#ffffff'/>", ok)
        for bad in ("opacity='0'", "style='visibility:hidden'", "display='none'"):
            with self.assertRaises(SystemExit):
                build.standalone_svg(f"<svg viewBox='0 0 10 10'><g {bad}></g></svg>")
        with self.assertRaises(SystemExit):
            build.standalone_svg("<svg><g></g></svg>")        # viewBox がない

    def test_md_text_and_slide_parts(self):
        b = self.build
        self.assertEqual(b.md_text("==外れ== と ++当たり++ と **太字** と [[リンク]]"), "**外れ** と **当たり** と **太字** と リンク")
        self.assertEqual(b.md_text("**a ==b== c**"), "**a b c**")                       # 太字の中では二重にしない
        self.assertEqual(b.md_text("`a<b` と a<b と a<br>b"), "`a<b` と a&lt;b と a<br>b")  # コードの中はそのまま
        self.assertEqual(b.md_plain("==x== と `y`<br>z"), "x と y z")
        self.assertEqual(b.md_cell("a|b\nc"), "a\\|b<br>c")
        self.assertEqual(b.md_notes("言う：a\n・x\n・y\n注意：z"), ["言う：a", "", "- x", "- y", "", "注意：z"])
        # compare（見出し・箇条・callouts・verdict）と、矢印が足りない flow
        out = b.md_slide_body({"type": "compare", "id": "c", "cols": [{"title": "A", "rows": [{"label": "l", "text": "t"}]}],
                               "callouts": [{"title": "T", "items": ["i1"]}, {"text": "x"}], "verdict": {"text": "v"}})
        self.assertEqual(out, ["#### A", "- **l**：t", "> **T**\n> - i1", "> x", "> v"])
        flow = b.md_slide_body({"type": "flow", "id": "f", "rows": [{"nodes": [{"t": "a"}, {"t": "b", "s": "sb"}, {"t": "c"}],
                                                                       "arrows": [{"text": "x"}]}]})
        self.assertEqual(flow[0], "**a** →（x）→ **b** → **c**")
        with self.assertRaises(SystemExit):
            b.md_slide_body({"type": "quiz", "id": "q"})

    def test_rebuild_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            run_build("--md", str(a))
            run_build("--md", str(b))
            fa, fb = tree(a), tree(b)
            self.assertEqual(sorted(fa), sorted(fb))
            self.assertGreater(len(fa), 52)
            for name, data in fa.items():
                self.assertEqual(data, fb[name], name)
                self.assertNotIn(b"\r", data, f"{name} に CR がある（改行は LF だけ）")
            self.assertEqual(fa, tree(self.md))      # HTML といっしょに作っても同じ

    def test_md_only_does_not_touch_site(self):
        # --md だけのときは Markdown だけを書き、HTML（既定の site/lecture）には触れない（同じ中身でも書き直さない）
        site = REPO_DIR / "site" / "lecture"
        before = {p: p.stat().st_mtime_ns for p in site.rglob("*") if p.is_file()}
        with tempfile.TemporaryDirectory() as tmp:
            r = run_build("--md", str(Path(tmp) / "md"))
            self.assertIn("Markdown", r.stdout)
            self.assertFalse((Path(tmp) / "md" / "index.html").exists())
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in site.rglob("*") if p.is_file()})

    def test_md_is_up_to_date(self):
        # 生成物 docs/lecture/md/ は Git に入れる。原稿を直したら build.py --md で作り直す
        fresh, kept = tree(self.md), tree(MD_DIR)
        self.assertEqual(sorted(fresh), sorted(kept), "docs/lecture/md/ のファイルが、作り直したものと違う（古いものは消す）")
        for name, data in fresh.items():
            self.assertEqual(data, kept[name], f"docs/lecture/md/{name} が古い。python3 docs/lecture/tools/build.py --md docs/lecture/md で作り直す")

    def test_md_files_and_links(self):
        ids = [d["id"] for d in self.conf["decks"]]
        names = sorted(p.name for p in self.md.glob("*.md"))
        self.assertEqual(names, sorted(["index.md", *[f"{i}.md" for i in ids]]))
        index = (self.md / "index.md").read_text(encoding="utf-8")
        for d in self.conf["decks"]:
            self.assertIn(f"]({d['id']}.md)", index)
        n_topic_links = 0
        for md in self.md.glob("*.md"):
            text = md.read_text(encoding="utf-8")
            self.assertNotIn("```mermaid", text)
            for target in re.findall(r"\]\(([^)\s]+)\)", text):
                if re.match(r"[a-z]+:|#", target):
                    continue
                if target.startswith("../../../"):       # トピックの README。本物の場所（docs/lecture/md/）からの相対パスで確かめる
                    n_topic_links += 1
                    self.assertTrue((MD_DIR / target).resolve().is_file(), f"{md.name} のトピックのリンク {target} がない")
                else:                                     # 部の Markdown・図。作った場所からの相対パス
                    self.assertTrue((self.md / target).is_file(), f"{md.name} のリンク先 {target} がない")
        self.assertGreater(n_topic_links, 50)

    def test_md_page_shape(self):
        md = (self.md / "part1-search.md").read_text(encoding="utf-8")
        self.assertIn("\n### p.1 BM25\n\n*単語の一致で点数を付けるキーワード検索*\n", md)
        self.assertIn("![BM25 の点数は、出現回数・珍しさ・文書の長さの3つで決まる](img/p01.svg)", md)
        self.assertIn("**確かめる**：[基礎 01 キーワード検索](../../../basic/topics/01-keyword-search/README.md)", md)
        self.assertIn("<details>\n<summary>ノート</summary>\n", md)
        self.assertNotIn("==", md)               # スライドの強調の記法は、Markdown の太字にしてある
        self.assertIn("## A　4つの検索方式\n", md)
        self.assertNotIn("\r", md)


if __name__ == "__main__":
    unittest.main()
