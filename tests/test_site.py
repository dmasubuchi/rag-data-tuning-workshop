"""読む形のページと入口（tools/build_site.py、site/index.html、site/pages/）の試験。通信しない。

入口と各ページの相対リンク・飛び先の見出し・画像がすべてある、Markdown の全部がページになる、Mermaid は
ブラウザで描く（版を固定した CDN）、見出しの飛び先が GitHub と同じ、GitHub の書き方（入れ子の一覧・一覧の中のコード・
<details>）が同じ構造で読まれる、作り直すと今の site/ と同じ、を確かめる。markdown（requirements-dev.txt）が要る。
"""

import html
import json
import re
import sys
import tempfile
import unittest
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SITE = REPO_DIR / "site"
PAGES = SITE / "pages"
sys.path.insert(0, str(REPO_DIR / "tools"))

try:
    import markdown
    import build_site
    from githubmd import GithubSlugger
    HAVE_MARKDOWN = True
except ImportError:
    HAVE_MARKDOWN = False

GITHUB_FILE = re.compile(r"^https://github\.com/dmasubuchi/rag-data-tuning-workshop/(blob|tree)/main/(.+)$")
MERMAID_SCRIPT = re.compile(r'<script src="https://cdn\.jsdelivr\.net/npm/mermaid@(\d+\.\d+\.\d+)/dist/mermaid\.min\.js"')
# 消した呼び名。このファイル自身が grep に当たらないように、2つに分けて書く
REMOVED_TERMS = re.compile("|".join(a + b for a, b in [("講", "師"), ("受講", "生"), ("受講", "者"), ("講", "義")]))


def expected_sources() -> list:
    """ページにするはずの Markdown を、build_site とは別に数える。"""
    patterns = ["README.md", "guide/**/*.md", "docs/lecture/README.md", "docs/lecture/md/*.md", "basic/README.md",
                "basic/topics/*/README.md", "applied/README.md", "applied/assistant/README.md", "applied/data/README.md",
                "applied/topics/*/README.md"]
    return sorted(p.relative_to(REPO_DIR).as_posix() for pattern in patterns for p in REPO_DIR.glob(pattern))


class Refs(HTMLParser):
    """HTML の中の href・src と id を集める。"""

    def __init__(self, text: str):
        super().__init__()
        self.refs, self.ids = [], set()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src") and value is not None:
                self.refs.append((tag, name, value))
            elif name == "id":
                self.ids.add(value)


def refs_of(path: Path) -> Refs:
    return Refs(path.read_text(encoding="utf-8"))


def deck_slide_ids(slides_html: Path) -> set:
    """HTML のスライド（site/lecture/<部>/slides.html）の `const DECK = {…};` から、各スライドの id を集める。"""
    found = re.search(r"^const DECK = (\{.*\});\s*$", slides_html.read_text(encoding="utf-8"), re.M)
    assert found, f"{slides_html}: DECK がない"
    return {slide["id"] for slide in json.loads(found.group(1))["slides"]}


def render(text: str, rel: str = "guide/x.md", repo: Path = REPO_DIR, pages=("guide/x.md", "guide/other.md")):
    linker = build_site.Linker(repo, set(pages))
    return build_site.render_markdown(text, rel, linker)[0]


@unittest.skipUnless(HAVE_MARKDOWN, "markdown が入っていないので飛ばす（教材を直す人の道具。requirements-dev.txt）")
class SiteOutputTest(unittest.TestCase):
    """今の site/index.html と site/pages/ の確認。"""

    def test_markdown_version_is_pinned(self):
        pinned = re.search(r"^markdown==(\S+)$", (REPO_DIR / "requirements-dev.txt").read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(pinned, "requirements-dev.txt に markdown==版 がない")
        self.assertEqual(markdown.__version__, pinned.group(1),
                         "入れている markdown の版が requirements-dev.txt と違う（ページの HTML が変わりうる）")

    def test_every_markdown_has_a_page(self):
        sources = expected_sources()
        self.assertGreaterEqual(len(sources), 34)
        pages = {p.name for p in PAGES.glob("*.html")}
        self.assertEqual(pages, {s[: -len(".md")].replace("/", "-") + ".html" for s in sources},
                         "Markdown とページが1対1でない")
        for rel in sources:
            page = PAGES / (rel[: -len(".md")].replace("/", "-") + ".html")
            text = page.read_text(encoding="utf-8")
            heading = re.search(r"^# (.+)$", (REPO_DIR / rel).read_text(encoding="utf-8"), re.M).group(1)
            self.assertIn("<h1", text, rel)
            self.assertIn(f'href="{build_site.github_url(rel)}"', text, f"{rel}：元の Markdown へのリンクがない")
            self.assertIn('href="../index.html"', text, f"{rel}：入口に戻るリンクがない")
            self.assertIn(f"<title>{html.escape(heading.replace('`', ''))} | ", text, rel)

    def test_portal_links_resolve(self):
        problems, ids_cache, checked = [], {}, 0
        files = [SITE / "index.html"] + sorted(PAGES.glob("*.html"))
        for html_file in files:
            shown = html_file.relative_to(SITE).as_posix()
            for tag, name, value in refs_of(html_file).refs:
                parts = urllib.parse.urlsplit(value)
                checked += 1
                if parts.scheme:
                    if parts.scheme != "https":
                        problems.append(f"{shown}: https 以外の外部リンク {value}")
                    m = GITHUB_FILE.match(value)
                    if m:
                        target = REPO_DIR / urllib.parse.unquote(m.group(2))
                        if not (target.is_dir() if m.group(1) == "tree" else target.is_file()):
                            problems.append(f"{shown}: GitHub のリンク先が Repo にない {value}")
                    elif value.startswith(build_site.GITHUB_REPO + "/"):
                        problems.append(f"{shown}: GitHub のリンクの形が違う {value}")
                    continue
                target = (html_file.parent / urllib.parse.unquote(parts.path)).resolve() if parts.path else html_file
                if not target.is_file():
                    problems.append(f"{shown}: 行き先のファイルがない {value}")
                elif parts.fragment and target.parent == PAGES and target.suffix == ".html":
                    if target not in ids_cache:
                        ids_cache[target] = refs_of(target).ids
                    if urllib.parse.unquote(parts.fragment) not in ids_cache[target]:
                        problems.append(f"{shown}: 飛び先の見出しがない {value}")
        self.assertGreater(checked, 500)
        self.assertEqual(problems, [])

    def test_slide_links_point_to_slides_that_exist(self):
        """`../lecture/<部>/slides.html#pNN` の #pNN が、その部の slides.html の DECK にあるスライドの id。"""
        ids_cache, problems, checked = {}, [], 0
        for html_file in [SITE / "index.html", *sorted(PAGES.glob("*.html"))]:
            for _, _, value in refs_of(html_file).refs:
                parts = urllib.parse.urlsplit(value)
                target = (html_file.parent / urllib.parse.unquote(parts.path)).resolve() if parts.path and not parts.scheme else None
                if target is None or target.name != "slides.html" or (SITE / "lecture") not in target.parents or not parts.fragment:
                    continue
                checked += 1
                if target not in ids_cache:
                    ids_cache[target] = deck_slide_ids(target)
                if parts.fragment not in ids_cache[target]:
                    problems.append(f"{html_file.relative_to(SITE).as_posix()}: {value}")
        self.assertGreaterEqual(checked, 20)
        self.assertEqual(problems, [], "スライドの id にない飛び先")

    def test_every_page_is_reachable_from_the_portal(self):
        seen, queue = set(), [SITE / "index.html"]
        while queue:
            current = queue.pop()
            for _, _, value in refs_of(current).refs:
                parts = urllib.parse.urlsplit(value)
                if parts.scheme or not parts.path.endswith(".html"):
                    continue
                target = (current.parent / parts.path).resolve()
                if target.parent == PAGES and target not in seen:
                    seen.add(target)
                    queue.append(target)
        self.assertEqual({p.name for p in seen}, {p.name for p in PAGES.glob("*.html")})

    def test_portal_has_the_sections(self):
        text = (SITE / "index.html").read_text(encoding="utf-8")
        for needle in ("この研修について", "始め方", "スライド", "読む形のスライド", "基礎編・応用編", "ソース",
                       'href="lecture/index.html"', "06 の次は 14", "Retrieve"):
            self.assertIn(needle, text)
        order = [m for m in re.findall(r'<ol class="links">(.*?)</ol>', text, re.S)[0].split("<li>")[1:]]
        self.assertEqual(len(order), 8, "始め方は手順書の8つ")
        self.assertIn("guide-evaluation.html", order[5])
        self.assertIn("guide-setup-windows-pc.html", order[0])
        self.assertIn("guide-facilitator.html", order[-1])
        self.assertNotIn("`", text, "説明の中の ` がそのまま出ている")

    def test_slide_links_become_relative_paths_to_site_lecture(self):
        text = (PAGES / "guide-facilitator.html").read_text(encoding="utf-8")
        found = re.findall(r'href="(\.\./lecture/[^"]+)"', text)
        self.assertTrue(found, "facilitator.md のスライドへのリンクが書き換わっていない")
        self.assertNotIn("../site/lecture", text)
        for href in found:
            self.assertTrue((PAGES / href.partition("#")[0]).resolve().is_file(), href)

    def test_mermaid_is_rendered_client_side(self):
        blocks = sum(len(re.findall(r"^```mermaid\s*$", (REPO_DIR / rel).read_text(encoding="utf-8"), re.M))
                     for rel in expected_sources())
        self.assertGreaterEqual(blocks, 1)
        rendered = 0
        for page in sorted(PAGES.glob("*.html")):
            text = page.read_text(encoding="utf-8")
            count = text.count('<pre class="mermaid">')
            rendered += count
            self.assertNotIn("language-mermaid", text, page.name)
            scripts = MERMAID_SCRIPT.findall(text)
            if count:
                self.assertEqual(scripts, ["11.4.1"], f"{page.name}：mermaid の版が固定されていない")
                self.assertIn('integrity="sha384-', text)
                self.assertIn('theme: dark ? "dark" : "default"', text, "暗い表示の theme がない")
            else:
                self.assertEqual(scripts, [], f"{page.name}：mermaid が要らないページで読んでいる")
                self.assertNotIn("mermaid.min.js", text, page.name)
        self.assertEqual(rendered, blocks, "Mermaid のブロックの数とページの数が合わない")
        self.assertNotIn("mermaid.min.js", (SITE / "index.html").read_text(encoding="utf-8"))

    def test_images_are_copied_next_to_the_pages(self):
        sources = REPO_DIR / "docs" / "lecture" / "md" / "img"
        self.assertEqual(sorted(p.name for p in (PAGES / "img").iterdir()), sorted(p.name for p in sources.iterdir()))
        for svg in sources.iterdir():
            self.assertEqual((PAGES / "img" / svg.name).read_bytes(), svg.read_bytes())
        self.assertIn('src="img/p01.svg"', (PAGES / "docs-lecture-md-part1-search.html").read_text(encoding="utf-8"))

    def test_rendered_heading_ids_match_github(self):
        """どのページでも、見出しの id が GitHub の飛び先（日本語のまま、重なれば -1）と同じ。"""
        for rel in expected_sources():
            slugger, expected, inside = GithubSlugger(), [], False
            for line in (REPO_DIR / rel).read_text(encoding="utf-8").splitlines():
                if re.match(r"^\s*(```|~~~)", line):
                    inside = not inside
                elif not inside and (m := re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)):
                    expected.append(slugger.slug(m.group(1)))
            page = PAGES / (rel[: -len(".md")].replace("/", "-") + ".html")
            found = re.findall(r'<h[1-6] id="([^"]*)"', page.read_text(encoding="utf-8").replace("&amp;", "&"))
            self.assertEqual(found, expected, rel)

    def test_pages_work_on_phones_and_in_both_color_schemes(self):
        css = (PAGES / "style.css").read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertRegex(css, r"img\s*\{[^}]*max-width:\s*100%;[^}]*height:\s*auto")
        self.assertRegex(css, r"\.table-wrap\s*\{[^}]*overflow-x:\s*auto")
        self.assertIn("var(--bg)", css)
        for page in [SITE / "index.html", *sorted(PAGES.glob("*.html"))]:
            text = page.read_text(encoding="utf-8")
            self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', text, page.name)
            self.assertIn('<html lang="ja">', text, page.name)
            self.assertIn('rel="stylesheet" href="' + ("pages/" if page.name == "index.html" else "") + 'style.css"', text)

    def test_site_has_no_removed_terms(self):
        for page in [SITE / "index.html", *sorted(PAGES.glob("*.html"))]:
            self.assertIsNone(REMOVED_TERMS.search(page.read_text(encoding="utf-8")), page.name)

    def test_site_is_up_to_date(self):
        """作り直した結果が、コミットしてある site/index.html・site/pages/ と同じ。違うなら python tools/build_site.py。"""
        with tempfile.TemporaryDirectory() as tmp:
            build_site.build(REPO_DIR, Path(tmp))
            fresh = build_site.tree_bytes(Path(tmp))
        current = build_site.tree_bytes(SITE)
        stale = sorted(k for k in fresh.keys() | current.keys() if fresh.get(k) != current.get(k))
        self.assertEqual(stale, [], "古いファイルがある：python tools/build_site.py で作り直す")


@unittest.skipUnless(HAVE_MARKDOWN, "markdown が入っていないので飛ばす（教材を直す人の道具。requirements-dev.txt）")
class BuildTest(unittest.TestCase):
    def test_build_is_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = build_site.build(REPO_DIR, Path(a))
            second = build_site.build(REPO_DIR, Path(b))
            self.assertEqual(first, second)
            self.assertEqual(build_site.tree_bytes(Path(a)), build_site.tree_bytes(Path(b)))

    def test_build_leaves_site_lecture_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "lecture" / "intro").mkdir(parents=True)
            slides = out / "lecture" / "intro" / "slides.html"
            slides.write_text("<html>slides</html>", encoding="utf-8")
            stale = out / "pages" / "old.html"
            stale.parent.mkdir()
            stale.write_text("old", encoding="utf-8")
            build_site.build(REPO_DIR, out)
            self.assertEqual(slides.read_text(encoding="utf-8"), "<html>slides</html>")
            self.assertFalse(stale.exists(), "前の生成物（pages/）は消して作り直す")
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["index.html", "lecture", "pages"])

    def test_build_site_imports_only_the_standard_library_and_markdown(self):
        text = (REPO_DIR / "tools" / "build_site.py").read_text(encoding="utf-8")
        modules = set(re.findall(r"^(?:import|from) (\w+)", text, re.M))
        allowed = set(sys.stdlib_module_names) | {"markdown", "githubmd"}
        self.assertEqual(modules - allowed, set())


@unittest.skipUnless(HAVE_MARKDOWN, "markdown が入っていないので飛ばす（教材を直す人の道具。requirements-dev.txt）")
class HeadingIdTest(unittest.TestCase):
    def test_heading_ids_match_github(self):
        html = render("# 手順\n\n## 4. 接続の設定を作る\n\n## 3-4. Cosmos DB（NoSQL）\n\n## `.env.local` を作る\n\n"
                      "## 5. 補助：az で作る\n\n## 手順\n\n## 手順\n")
        ids = re.findall(r'<h\d id="([^"]*)"', html)
        self.assertEqual(ids, ["手順", "4-接続の設定を作る", "3-4-cosmos-dbnosql", "envlocal-を作る", "5-補助az-で作る",
                               "手順-1", "手順-2"])

    def test_angle_brackets_and_ampersands_in_code_follow_github(self):
        """見出しのコードの中の `<`・`&` は、GitHub と同じく id から消える（&lt; の文字が残らない）。"""
        html = render("# 題\n\n## `rg-<org>` を開く\n\n## `a&b` を読む\n")
        self.assertEqual(re.findall(r'<h\d id="([^"]*)"', html), ["題", "rg-org-を開く", "ab-を読む"])

    def test_anchor_links_to_japanese_headings_resolve_on_the_page(self):
        html = render("# 題\n\n[下へ](#2-つまずいたとき)\n\n## 2. つまずいたとき\n")
        self.assertIn('href="#2-つまずいたとき"', html)
        self.assertIn('id="2-つまずいたとき"', html)


@unittest.skipUnless(HAVE_MARKDOWN, "markdown が入っていないので飛ばす（教材を直す人の道具。requirements-dev.txt）")
class LinkRewriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        for rel in ("guide/x.md", "guide/other.md", "basic/run.py", "basic/data/a.json", "site/lecture/p1/slides.html",
                    "docs/lecture/md/img/p01.svg", "docs/lecture/md/part.md"):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text("x", encoding="utf-8")
        (self.repo / "basic" / "topics").mkdir()
        self.pages = {"guide/x.md", "guide/other.md", "docs/lecture/md/part.md"}
        self.linker = build_site.Linker(self.repo, self.pages)

    def link(self, href, src="guide/x.md"):
        return self.linker.link(href, src)

    def test_page_markdown_becomes_page_html_keeping_the_fragment(self):
        self.assertEqual(self.link("other.md"), "guide-other.html")
        self.assertEqual(self.link("other.md#2-つまずき"), "guide-other.html#2-つまずき")
        self.assertEqual(self.link("../docs/lecture/md/part.md#p1"), "docs-lecture-md-part.html#p1")

    def test_other_files_and_folders_go_to_github(self):
        base = "https://github.com/dmasubuchi/rag-data-tuning-workshop"
        self.assertEqual(self.link("../basic/run.py"), f"{base}/blob/main/basic/run.py")
        self.assertEqual(self.link("../basic/data/a.json"), f"{base}/blob/main/basic/data/a.json")
        self.assertEqual(self.link("../basic/topics/"), f"{base}/tree/main/basic/topics")
        self.assertEqual(self.link("../basic"), f"{base}/tree/main/basic")

    def test_slides_become_paths_from_the_page(self):
        self.assertEqual(self.link("../site/lecture/p1/slides.html#p12"), "../lecture/p1/slides.html#p12")
        self.assertEqual(self.link("../site/lecture/p1/slides.html"), "../lecture/p1/slides.html")

    def test_untouched_links(self):
        for href in ("#section", "https://example.org/a#b", "mailto:a@b.test", "//example.org/x"):
            self.assertEqual(self.link(href), href)

    def test_missing_targets_and_paths_outside_the_repo_fail(self):
        with self.assertRaises(build_site.LinkError):
            self.link("nothing.py")
        with self.assertRaises(build_site.LinkError):
            self.link("../../outside.md")
        with self.assertRaises(build_site.LinkError):
            self.link("../site/lecture/none.html")

    def test_images_are_collected_for_copying(self):
        src = self.linker.image("../docs/lecture/md/img/p01.svg", "guide/x.md")
        self.assertEqual(src, "img/p01.svg")
        self.assertEqual(self.linker.assets, {"docs/lecture/md/img/p01.svg": "img/p01.svg"})
        self.assertEqual(self.linker.image("img/p01.svg", "docs/lecture/md/part.md"), "img/p01.svg")
        with self.assertRaises(build_site.LinkError):
            self.linker.image("missing.png", "guide/x.md")

    def test_rendered_markdown_uses_the_rules(self):
        html = render("[a](other.md#x) [b](../basic/run.py) ![図](../docs/lecture/md/img/p01.svg)",
                      repo=self.repo, pages=self.pages)
        self.assertIn('<a href="guide-other.html#x">a</a>', html)
        self.assertIn('<a href="https://github.com/dmasubuchi/rag-data-tuning-workshop/blob/main/basic/run.py">b</a>', html)
        self.assertIn('<img alt="図" src="img/p01.svg">', html)


@unittest.skipUnless(HAVE_MARKDOWN, "markdown が入っていないので飛ばす（教材を直す人の道具。requirements-dev.txt）")
class GithubMarkdownTest(unittest.TestCase):
    """GitHub で読める書き方が、同じ構造で読まれる。"""

    def test_nested_lists_with_two_and_three_space_indents(self):
        html = render("- 親\n  - 子\n    - 孫\n  - 子2\n- 親2\n\n1. 一\n   - 入れ子\n2. 二\n")
        self.assertEqual(html.count("<ul>"), 4)
        self.assertRegex(html, r"<li>親<ul>\s*<li>子<ul>\s*<li>孫</li>\s*</ul>\s*</li>\s*<li>子2</li>")
        self.assertRegex(html, r"<ol>\s*<li>一<ul>\s*<li>入れ子</li>\s*</ul>\s*</li>\s*<li>二</li>")

    def test_a_list_right_after_a_paragraph(self):
        html = render("必須（この順に）\n- `python a.py`\n- `python b.py`\n")
        self.assertIn("<p>必須（この順に）</p>", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_fenced_code_in_a_list_and_after_a_list(self):
        html = render("1. 実行する\n   ```powershell\n   py a.py <x>\n   ```\n2. 次\n\n```json\n{\"a\": 1}\n```\n")
        self.assertIn('<pre><code class="language-powershell">py a.py &lt;x&gt;\n</code></pre>', html)
        self.assertIn('<pre><code class="language-json">{"a": 1}\n</code></pre>', html)
        self.assertEqual(html.count("<li>") + html.count("<li "), 2)

    def test_an_item_after_a_code_block_and_its_paragraph_stays_in_the_list(self):
        html = render("- 一\n- 二：\n\n  ```\n  code\n  ```\n\n  続き\n- 三\n- 四\n")
        self.assertEqual(html.count("<li>"), 4)
        self.assertEqual(html.count("<ul>"), 1)

    def test_a_nested_list_after_a_blank_line_does_not_swallow_the_next_item(self):
        html = render("- 一\n\n  - 入れ子1\n  - 入れ子2\n- 二\n")
        self.assertEqual(html.count("<ul>"), 2)
        self.assertRegex(html, r"</ul>\s*</li>\s*<li>[\s\S]*二")

    def test_details_content_is_markdown(self):
        html = render("<details>\n<summary>ノート</summary>\n\n- **太字**と `code`\n\n```\nx < y\n```\n\n</details>\n")
        self.assertRegex(html, r"<details>\s*<summary>ノート</summary>")
        self.assertIn("<strong>太字</strong>", html)
        self.assertIn("<code>code</code>", html)
        self.assertIn("x &lt; y", html)
        self.assertIn("</details>", html)

    def test_mermaid_block_becomes_pre_mermaid(self):
        html = render("```mermaid\nflowchart LR\n  A -->|\"x\"| B\n```\n")
        self.assertIn('<pre class="mermaid">flowchart LR', html)
        self.assertIn("A --&gt;|", html)
        self.assertNotIn("<code", html)

    def test_task_list_becomes_checkboxes(self):
        html = render("- [ ] 未\n- [x] 済\n\n1. [ ] 番号つき\n")
        self.assertEqual(html.count('<input type="checkbox">'), 2)
        self.assertEqual(html.count('<input checked type="checkbox">'), 1)
        self.assertNotIn("[ ]", html)
        self.assertEqual(html.count('class="task"'), 3)

    def test_table_scrolls_sideways_by_itself(self):
        html = render("| a | b |\n|---|---|\n| 1 | 2 |\n")
        self.assertRegex(html, r'<div class="table-wrap">\s*<table>')

    def test_bare_urls_become_links(self):
        html = render("出典：https://learn.microsoft.com/a/b?c=1。次（https://example.org/x）と `https://no.example/`\n")
        self.assertIn('<a href="https://learn.microsoft.com/a/b?c=1">https://learn.microsoft.com/a/b?c=1</a>。', html)
        self.assertIn('<a href="https://example.org/x">https://example.org/x</a>）', html)
        self.assertIn("<code>https://no.example/</code>", html)

    def test_angle_brackets_in_code_are_escaped(self):
        self.assertIn("<code>rg-&lt;org&gt;</code>", render("`rg-<org>`\n"))

    def test_real_files_keep_every_list_item(self):
        """入れ子の多い実物のファイルで、元の一覧の項目の数と HTML の <li> の数が同じ（巻き込まれて消えた項目がない）。"""
        for rel in ("applied/README.md", "docs/lecture/md/part5-wrapup.md", "applied/topics/19-agentic-retrieval/README.md",
                    "basic/README.md"):
            text = (REPO_DIR / rel).read_text(encoding="utf-8")
            inside, items = False, 0
            for line in text.splitlines():
                if re.match(r"^\s*(```|~~~)", line):
                    inside = not inside
                elif not inside and re.match(r"^\s*([-*+]|\d+\.)\s", line) and not re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
                    items += 1
            linker = build_site.Linker(REPO_DIR, set(expected_sources()))
            html = build_site.render_markdown(text, rel, linker)[0]
            self.assertEqual(len(re.findall(r"<li[ >]", html)), items, rel)


if __name__ == "__main__":
    unittest.main()
