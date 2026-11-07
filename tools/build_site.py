"""読む形のページと入口のポータルを作る（site/index.html、site/pages/）。

手順書（guide/）、ハンズオン資料の Markdown（docs/lecture/md/）、README を HTML のページにし、入口 site/index.html から
たどれるようにする。同じ入力からは同じ出力ができる（日時などは入れない）。site/lecture/（HTML のスライド）には触れない。

  python tools/build_site.py            site/ を作り直す
  python tools/build_site.py --check    作り直した結果が site/ と同じかだけ確かめる（何も書き換えない）

必要なもの：markdown（requirements-dev.txt）。ほかは標準ライブラリだけ。Mermaid の図は、ページを開いたブラウザが
mermaid.js（版を固定した CDN）で描く。
"""

import argparse
import html
import posixpath
import re
import shutil
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as etree
from dataclasses import dataclass
from pathlib import Path

import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from githubmd import GithubSlugger  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
GITHUB_REPO = "https://github.com/dmasubuchi/rag-data-tuning-workshop"
MERMAID_SRC = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
MERMAID_SRI = "sha384-rbtjAdnIQE/aQJGEgXrVUlMibdfTSa4PQju4HDhN3sR2PmaKFzhEafuePsl9H/9I"
SITE_TITLE = "データに着目した RAG の研修"
LECTURE_IMG = "docs/lecture/md/img/"
# 生成物の置き場（site/ の下）。site/lecture/ は HTML のスライドで、ここでは作らない・消さない
PAGES_DIR = "pages"


# ------------------------------------------------------------------ 入力の一覧

def source_files(repo: Path = REPO_DIR) -> list:
    """ページにする Markdown（Repo 直下からの相対パス）。並びは決まっている。"""
    found = [p for pattern in ("README.md", "guide/**/*.md", "docs/lecture/README.md", "docs/lecture/md/*.md",
                               "basic/README.md", "basic/topics/*/README.md",
                               "applied/README.md", "applied/assistant/README.md", "applied/data/README.md",
                               "applied/topics/*/README.md")
             for p in sorted(repo.glob(pattern))]
    return [p.relative_to(repo).as_posix() for p in found]


def page_name(rel: str) -> str:
    """元のパスを - でつないだ名前：guide/setup/azure-setup.md → guide-setup-azure-setup.html"""
    return rel[: -len(".md")].replace("/", "-") + ".html"


def github_url(rel: str, kind: str = "blob") -> str:
    return f"{GITHUB_REPO}/{kind}/main/{urllib.parse.quote(rel)}"


# ------------------------------------------------------------------ リンクの書き換え

class LinkError(Exception):
    """Markdown の相対リンクの行き先がない・Repo の外。"""


class Linker:
    """Markdown の中の相対リンクと画像を、ページから見た行き先に直す。

    - ページになる .md → 生成した .html（飛び先の見出しはそのまま）
    - site/ の下（スライド）→ ページ（site/pages/）から見た相対パス
    - そのほかのファイル → GitHub の blob、フォルダー → GitHub の tree
    - 画像 → site/pages/img/ に写す（assets に記録）
    """

    def __init__(self, repo: Path, pages: set):
        self.repo = repo
        self.pages = pages
        self.assets = {}  # Repo 直下からの相対パス → site/pages/ からの相対パス

    def resolve(self, href: str, src_rel: str):
        """(Repo 直下からの相対パス, '#…') を返す。外部の URL と同じページ内の飛び先は None。"""
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href) or href.startswith("//"):
            return None
        path, hash_, fragment = href.partition("#")
        if not path:
            return None
        target = posixpath.normpath(posixpath.join(posixpath.dirname(src_rel), urllib.parse.unquote(path)))
        if target.startswith("../") or target == ".." or posixpath.isabs(target):
            raise LinkError(f"{src_rel}: Repo の外を指すリンク {href}")
        return target, hash_ + fragment

    def link(self, href: str, src_rel: str) -> str:
        found = self.resolve(href, src_rel)
        if found is None:
            return href
        target, frag = found
        if target in self.pages:
            return page_name(target) + frag
        if target == "site/index.html":
            return "../index.html" + frag
        if target.startswith("site/"):
            if not (self.repo / target).exists():
                raise LinkError(f"{src_rel}: リンク先がない {href}")
            return posixpath.relpath(target, "site/" + PAGES_DIR) + frag
        path = self.repo / target
        if not path.exists():
            raise LinkError(f"{src_rel}: リンク先がない {href}")
        if path.is_dir():
            return github_url(target, "tree")
        return github_url(target) + frag

    def image(self, src: str, src_rel: str) -> str:
        found = self.resolve(src, src_rel)
        if found is None:
            return src
        target = found[0]
        if not (self.repo / target).is_file():
            raise LinkError(f"{src_rel}: 画像がない {src}")
        name = ("img/" + target[len(LECTURE_IMG):] if target.startswith(LECTURE_IMG)
                else "img/" + target.replace("/", "-"))
        self.assets[target] = name
        return name


# ------------------------------------------------------------------ Markdown の読み替え

LIST_ITEM = re.compile(r"^( *)([-+*]|\d{1,9}[.)])( +|$)(.*)$")
FENCE_OPEN = re.compile(r"^( *)(`{3,}|~{3,})\s*(.*)$")
THEMATIC_BREAK = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
BLOCK_START = re.compile(r"^(#{1,6}(\s|$)|>|<|`{3,}|~{3,})")
DETAILS_OPEN = re.compile(r"^<details(?![^>]*\bmarkdown=)([^>]*)>\s*$")


class Lines:
    """整えた行の置き場。Python-Markdown は空行で区切ったかたまり（ブロック）ごとに一覧を読む。字下げで始まったブロックの
    途中で字下げが浅くなる行が来ると、その行を前の一覧の続きに巻き込む。浅くなる所には空行を入れて、ブロックを分ける。"""

    def __init__(self):
        self.lines = []
        self.block_indent = 0

    def add(self, line: str):
        indent = len(line) - len(line.lstrip(" "))
        if self.lines and self.lines[-1] and indent < self.block_indent:
            self.lines.append("")
        if not self.lines or not self.lines[-1]:
            self.block_indent = indent
        self.lines.append(line)

    def blank(self):
        self.lines.append("")

    def last_is_blank(self) -> bool:
        return bool(self.lines) and not self.lines[-1]


def prepare(lines: list, stash) -> list:
    """GitHub の Markdown を、Python-Markdown が同じ構造に読める形へ直す（行を返す）。

    - 入れ子の一覧：GitHub は親の項目の文字の位置から入れ子にする（- は2字、1. は3字）。Python-Markdown は
      4字ずつの字下げを求めるので、入れ子の深さから字下げを付け直す
    - コードのかたまり（```）：一覧の中のものも含めて全部ここで HTML にして stash に預け、前後に空行を置く
    - 段落の直後の一覧：GitHub は一覧として読む。Python-Markdown は空行を求めるので足す
    - <details>：中の Markdown も読ませるため markdown="1" を付ける

    既知の制限（この Repo の Markdown には、どれも使っていない。使うときは試験を足す）：
    - 引用（>）の中のコードのかたまり（```）は、HTML にしない
    - 行末の空白2つによる改行は、読み替えない（行末の空白を落とす）
    - 表の中の、`|` を含むコード（`a|b` など）は、列の区切りと読まれることがある
    - 字下げのタブは、読み替えない（空白で書く）
    """
    out = Lines()
    stack = []  # 開いている一覧の項目の、元の文字の位置（本文の開始位置）
    prev_kind = "blank"  # blank・item（項目の行）・para（本文の行）・other
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1
        if not line.strip():
            out.blank()
            prev_kind = "blank"
            continue
        n = len(line) - len(line.lstrip(" "))
        text = line.strip()

        fence = FENCE_OPEN.match(line)
        if fence and not (fence.group(2)[0] == "`" and "`" in fence.group(3)):
            open_items = [offset for offset in stack if offset <= n]
            relative = n - open_items[-1] if open_items else n
            if relative <= 3:
                stack = open_items
                marks, info = fence.group(2), fence.group(3).strip()
                code = []
                closing = re.compile(r"^ {0,%d}%s{%d,}\s*$" % (n + 3, re.escape(marks[0]), len(marks)))
                while i < len(lines):
                    inner = lines[i].rstrip()
                    i += 1
                    if closing.match(inner):
                        break
                    code.append(inner[min(n, len(inner) - len(inner.lstrip(" "))):])
                indent = " " * (4 * len(stack) + (relative if stack else 0))
                out.blank()
                out.add(indent + stash(fence_html(info.split(" ")[0] if info else "", code)))
                out.blank()
                prev_kind = "blank"
                continue

        item = LIST_ITEM.match(line)
        if item and not THEMATIC_BREAK.match(line):
            marker, rest = item.group(2), item.group(4)
            ordered = marker[0].isdigit()
            if ordered and not stack and prev_kind == "para" and int(marker[:-1]) != 1:
                item = None  # 1 以外で始まる番号は、段落を中断しない
        else:
            item = None

        if item:
            had_stack = bool(stack)
            while stack and n < stack[-1]:
                stack.pop()
            if not had_stack and prev_kind == "para":
                out.blank()
            spaces = len(item.group(3))
            width = len(marker) + (spaces if 1 <= spaces <= 4 and rest else 1)
            out.add(" " * (4 * len(stack)) + (marker[:-1] + "." if ordered else marker) + (" " + rest if rest else ""))
            stack.append(n + width)
            prev_kind = "item"
            continue

        if stack:
            lazy = prev_kind in ("item", "para") and not BLOCK_START.match(text)
            if lazy:
                out.add(" " * (4 * len(stack)) + text)
                prev_kind = "para"
                continue
            while stack and n < stack[-1]:
                stack.pop()
            if stack:
                out.add(" " * (4 * len(stack) + n - stack[-1]) + text)
                prev_kind = "para"
                continue

        if DETAILS_OPEN.match(line):
            line = DETAILS_OPEN.sub(lambda m: f'<details markdown="1"{m.group(1)}>', line)
        out.add(line)
        prev_kind = "other" if BLOCK_START.match(text) or THEMATIC_BREAK.match(line) else "para"
    return out.lines


def fence_html(lang: str, code: list) -> str:
    body = html.escape("\n".join(code) + "\n", quote=False)
    if lang == "mermaid":
        return f'<pre class="mermaid">{body}</pre>'
    lang = re.sub(r"[^\w+#.-]", "", lang)
    return f'<pre><code class="language-{lang}">{body}</code></pre>' if lang else f"<pre><code>{body}</code></pre>"


class PrepareProcessor(Preprocessor):
    def run(self, lines):
        return prepare(lines, self.md.htmlStash.store)


class BareUrlProcessor(InlineProcessor):
    """文中の https://… をリンクにする（GitHub と同じ）。行き先の外の全角の記号と、文末の記号・対にならない ) は含めない。"""

    ANCESTOR_EXCLUDES = ("a",)

    def handleMatch(self, m, data):
        url = m.group(1)
        trimmed = url.rstrip(".,:;!?'*")
        while trimmed.endswith(")") and trimmed.count(")") > trimmed.count("("):
            trimmed = trimmed[:-1].rstrip(".,:;!?'*")
        el = etree.Element("a", {"href": trimmed})
        el.text = trimmed
        return el, m.start(0), m.start(0) + len(trimmed)


class SiteTreeprocessor(Treeprocessor):
    """見出しの id（GitHub と同じ作り方）、リンク・画像の書き換え、チェックボックス、表の横スクロール枠。

    見出しの id は toc に任せない。toc は見出しの空白（全角の空白も）を半角1つにまとめてから id を作るので、GitHub の
    飛び先（全角の空白は消える）と違ってしまう。toc は、先に付いている id を上書きしない。
    コードの中の `<`・`&` は、木の中では &lt;・&amp; の形なので、html.unescape で戻してから id にする。
    """

    def __init__(self, md, linker, src_rel):
        super().__init__(md)
        self.linker = linker
        self.src_rel = src_rel
        self.slugger = GithubSlugger()

    def run(self, root):
        for el in root.iter():
            if isinstance(el.tag, str) and re.fullmatch(r"h[1-6]", el.tag) and not el.get("id"):
                el.set("id", self.slugger.slug(html.unescape("".join(el.itertext()))))
            elif el.tag == "a" and el.get("href"):
                el.set("href", self.linker.link(el.get("href"), self.src_rel))
            elif el.tag == "img" and el.get("src"):
                el.set("src", self.linker.image(el.get("src"), self.src_rel))
            elif el.tag == "li":
                self.checkbox(el)
        for parent in list(root.iter()):
            for index, child in enumerate(list(parent)):
                if child.tag == "table":
                    wrap = etree.Element("div", {"class": "table-wrap"})
                    wrap.append(child)
                    wrap.tail = child.tail
                    child.tail = None
                    parent[index] = wrap

    @staticmethod
    def checkbox(li):
        if li.text is not None and li.text.strip():
            holder = li
        elif len(li) and li[0].tag == "p":
            holder = li[0]
        else:
            return
        m = re.match(r"^\[([ xX])\]\s+", holder.text or "")
        if not m:
            return
        box = etree.Element("input", {"type": "checkbox"})
        if m.group(1) != " ":
            box.set("checked", "checked")
        box.tail = " " + holder.text[m.end():]
        holder.text = None
        holder.insert(0, box)
        li.set("class", "task")


class SiteExtension(Extension):
    def __init__(self, linker, src_rel):
        super().__init__()
        self.linker = linker
        self.src_rel = src_rel

    def extendMarkdown(self, md):
        md.preprocessors.register(PrepareProcessor(md), "site_prepare", 27)
        md.inlinePatterns.register(
            BareUrlProcessor(r"(?<![\w/@=\"'>])(https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+)", md), "site_bare_url", 115)
        md.treeprocessors.register(SiteTreeprocessor(md, self.linker, self.src_rel), "site_tree", 10)


@dataclass
class Page:
    rel: str  # 元の Markdown（Repo 直下からの相対パス）
    title: str
    body: str
    toc: list  # [(level, id, text)] の h2・h3
    mermaid: bool


def render_markdown(text: str, rel: str, linker: Linker) -> tuple:
    """(本文の HTML, 見出しの木) を返す。"""
    md = markdown.Markdown(extensions=["tables", "md_in_html", "sane_lists", "toc", SiteExtension(linker, rel)],
                           output_format="html")
    return md.convert(text), md.toc_tokens


def flatten_toc(tokens: list) -> list:
    found = []
    for token in tokens:
        if token["level"] in (2, 3):
            found.append((token["level"], token["id"], token["name"]))
        found += flatten_toc(token["children"])
    return found


def plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def make_page(rel: str, repo: Path, linker: Linker) -> Page:
    text = (repo / rel).read_text(encoding="utf-8")
    body, tokens = render_markdown(text, rel, linker)
    title = plain(tokens[0]["name"]) if tokens and tokens[0]["level"] == 1 else Path(rel).stem
    return Page(rel, title, body, flatten_toc(tokens), '<pre class="mermaid">' in body)


# ------------------------------------------------------------------ ページの HTML

def head(title: str, css: str) -> str:
    return (f'<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="color-scheme" content="light dark">\n'
            f"<title>{html.escape(title)}</title>\n"
            f'<link rel="stylesheet" href="{css}">\n</head>\n')


MERMAID_SCRIPT = f"""<script src="{MERMAID_SRC}" integrity="{MERMAID_SRI}" crossorigin="anonymous"></script>
<script>
if (window.mermaid) {{
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  mermaid.initialize({{ startOnLoad: true, theme: dark ? "dark" : "default", securityLevel: "strict" }});
}}
</script>
"""


def toc_html(toc: list) -> str:
    if len(toc) < 5:
        return ""
    items = "".join(f'<li class="l{level}"><a href="#{html.escape(anchor, quote=True)}">{name}</a></li>\n'
                    for level, anchor, name in toc)
    return f'<nav class="toc"><details><summary>このページの目次</summary>\n<ul>\n{items}</ul>\n</details></nav>\n'


def page_html(page: Page) -> str:
    body = page.body
    if "</h1>" in body:
        body = body.replace("</h1>", "</h1>\n" + toc_html(page.toc), 1)
    source = github_url(page.rel)
    bar = (f'<a class="home" href="../index.html">← 入口に戻る</a>'
           f'<a class="source" href="{html.escape(source, quote=True)}">元の Markdown（GitHub）</a>')
    return (head(f"{page.title} | {SITE_TITLE}", "style.css")
            + f'<body>\n<header class="bar">{bar}</header>\n<main>\n<article class="doc">\n{body}\n</article>\n</main>\n'
            + f'<footer class="bar">{bar}</footer>\n'
            + (MERMAID_SCRIPT if page.mermaid else "") + "</body>\n</html>\n")


# ------------------------------------------------------------------ 入口

LIST_LINK = re.compile(r"^(?:\d+\.|[-*])\s+\[([^\]]+)\]\(([^)\s]+)\)\s*[：:]\s*(.*?)\s*$")


def linked_items(repo: Path, rel: str, section: str = "") -> list:
    """Markdown の一覧の `- [名前](リンク)：説明` を (名前, 行き先の rel, 説明) で返す。section を指せば、その見出しの下だけ。"""
    lines = (repo / rel).read_text(encoding="utf-8").splitlines()
    if section:
        start = lines.index(f"## {section}") + 1
        end = next((k for k in range(start, len(lines)) if lines[k].startswith("## ")), len(lines))
        lines = lines[start:end]
    found = []
    for line in lines:
        m = LIST_LINK.match(line)
        if m:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), m.group(2).partition("#")[0]))
            found.append((m.group(1), target, m.group(3)))
    return found


def inline_code(text: str) -> str:
    """説明の中の `…` を <code> にする（それ以外の記号はそのまま文字として出す）。"""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text, quote=False))


def build_index(pages: dict, repo: Path) -> str:
    def a(rel: str, text: str = "") -> str:
        return f'<a href="{PAGES_DIR}/{page_name(rel)}">{html.escape(text or pages[rel].title)}</a>'

    def items(entries: list) -> str:
        return "".join(f"<li>{a(rel, text)}" + (f'<span class="note">{inline_code(desc)}</span>' if desc else "") + "</li>\n"
                       for text, rel, desc in entries)

    steps = linked_items(repo, "guide/README.md", "順番")
    lecture = linked_items(repo, "docs/lecture/md/index.md")
    topics = lambda group: [(pages[r].title, r, "") for r in sorted(pages) if re.match(rf"^{group}/topics/[^/]+/README\.md$", r)]  # noqa: E731
    sources = [("guide", "tree", "手順書（Markdown）"), ("basic", "tree", "基礎編のスクリプト・Notebook・データ"),
               ("applied", "tree", "応用編のスクリプト・Notebook・データ"),
               ("evaluation", "tree", "評価の質問と、正解の文書（人事・ホテル）"),
               ("docs/lecture", "tree", "スライドの原稿と、作る道具"), ("tools", "tree", "チームを作る道具、評価の道具、ページを作る道具"),
               ("NOTICE.md", "blob", "データの出どころ、ライセンスの注意"), ("LICENSE", "blob", "コードのライセンス"),
               ("LICENSE-docs.md", "blob", "文書のライセンス")]
    source_items = "".join(
        f'<li><a href="{html.escape(github_url(path, kind), quote=True)}">{html.escape(path)}</a>'
        f'<span class="note">{html.escape(note)}</span></li>\n' for path, kind, note in sources)

    body = f"""<body class="portal">
<main>
<header class="hero">
<h1>{SITE_TITLE}</h1>
<p class="lead">検索の基盤の上にある、データの加工・運営・評価を、手を動かして学びます。</p>
</header>

<section>
<h2>この研修について</h2>
<dl>
<dt>何を学ぶか</dt>
<dd>基盤（Azure AI Search）を作るだけでは、よい検索になりません。基盤の上にある、データの加工・運営・評価を、手を動かして学びます。検索のしかたを変え、結果を数字で測り、直す。この繰り返しを、ホテル・戦国武将・採用の文書で体験します。</dd>
<dt>RAG の R</dt>
<dd>R は Retrieve（取ってくる）です。集める、順位を付ける、段階的に探す。この考え方を、基盤を作る段階から意識します。</dd>
<dt>だれ向けか</dt>
<dd>Azure の SI パートナー（とくにインフラ寄りの人）、企業の情報システム部門・DX 推進、データ・IR・BI・分析の担当。</dd>
</dl>
</section>

<section>
<h2>始め方</h2>
<p>チームで進めます。1人が構築する人（Azure にリソースを作る）、ほかの人はメンバー（検索と読み取り）です。人数は自由です。研修を進める人を進行役、研修に出る人を参加者と呼びます。手順書を、番号の順に進めます。</p>
<ol class="links">
{items(steps)}</ol>
<p class="more">{a("guide/README.md", "手順書の一覧")}</p>
</section>

<section>
<h2>スライド</h2>
<p>仕組みはスライドで見て、各ページの下の「確かめる」が指すトピックで、手元で確かめます。</p>
<p><a class="button" href="lecture/index.html">HTML のスライドを開く</a></p>
<p class="more">{a("docs/lecture/README.md", "スライドの原稿と作り方")}</p>
<h3>読む形のスライド</h3>
<p>同じ内容を、文章と図のページにしたものです。</p>
<ul class="links">
<li>{a("docs/lecture/md/index.md", "目次")}</li>
{items(lecture)}</ul>
</section>

<section>
<h2>基礎編・応用編</h2>
<p>トピックの番号は、基礎編が 01〜06、応用編が 14〜20 です。06 の次は 14 で、07〜13 はありません。</p>
<ul class="links">
<li>{a("basic/README.md")}</li>
<li>{a("applied/README.md")}</li>
<li>{a("applied/assistant/README.md")}</li>
<li>{a("applied/data/README.md")}</li>
</ul>
<div class="cols">
<div>
<h3>基礎編のトピック</h3>
<ul class="links">
{items(topics("basic"))}</ul>
</div>
<div>
<h3>応用編のトピック</h3>
<ul class="links">
{items(topics("applied"))}</ul>
</div>
</div>
</section>

<section>
<h2>ソース</h2>
<p>ここのページは、すべて Repo の Markdown から作っています。元のファイルは GitHub にあります。</p>
<ul class="links">
<li><a href="{GITHUB_REPO}">{GITHUB_REPO.removeprefix("https://")}</a><span class="note">Repo のトップ</span></li>
<li>{a("README.md", "README")}<span class="note">Repo の README</span></li>
{source_items}</ul>
</section>
</main>
</body>
</html>
"""
    return head(SITE_TITLE, f"{PAGES_DIR}/style.css") + body


# ------------------------------------------------------------------ 見た目

STYLE_CSS = """/* build_site.py が作る。明るい表示と暗い表示の両方（prefers-color-scheme）。色は変数にしてある */
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #1d2733;
  --muted: #5b6675;
  --line: #d6dce4;
  --soft: #f4f6f9;
  --code-bg: #eef1f5;
  --link: #0b5cad;
  --accent: #0b5cad;
  --accent-fg: #ffffff;
  --quote: #b7c3d3;
  --font: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo",
    "Noto Sans JP", "Segoe UI", sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, "Courier New", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14181d;
    --fg: #e3e8ee;
    --muted: #9aa6b5;
    --line: #333d49;
    --soft: #1b2128;
    --code-bg: #202831;
    --link: #7bb8f5;
    --accent: #4a9be8;
    --accent-fg: #0d1117;
    --quote: #4b5a6c;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: var(--font);
  font-size: 16px;
  line-height: 1.85;
  overflow-wrap: break-word;
}
a { color: var(--link); }
main { max-width: 50rem; margin: 0 auto; padding: 1rem 16px 3rem; }
.bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1.5rem;
  justify-content: space-between;
  max-width: 50rem;
  margin: 0 auto;
  padding: 0.75rem 16px;
  font-size: 0.9rem;
}
header.bar { border-bottom: 1px solid var(--line); }
footer.bar { border-top: 1px solid var(--line); margin-top: 2rem; }
.bar a { text-decoration: none; }
.bar a:hover { text-decoration: underline; }
h1, h2, h3, h4 { line-height: 1.4; margin: 2em 0 0.6em; scroll-margin-top: 1rem; }
h1 { font-size: 1.7rem; margin-top: 1rem; }
h2 { font-size: 1.35rem; padding-bottom: 0.3rem; border-bottom: 1px solid var(--line); }
h3 { font-size: 1.12rem; }
h4 { font-size: 1rem; }
p, ul, ol, dl, pre, blockquote, .table-wrap, details { margin: 0.8em 0; }
ul, ol { padding-left: 1.6rem; }
li > p { margin: 0.3em 0; }
li > ul, li > ol { margin: 0.2em 0; }
li.task { list-style: none; }
li.task input { width: 1rem; height: 1rem; margin: 0 0.5rem 0 -1.5rem; vertical-align: -0.12em; }
code {
  font-family: var(--mono);
  font-size: 0.9em;
  background: var(--code-bg);
  border-radius: 4px;
  padding: 0.1em 0.35em;
}
pre {
  background: var(--code-bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.8rem 1rem;
  overflow-x: auto;
  line-height: 1.6;
}
pre code { background: none; padding: 0; font-size: 0.88rem; overflow-wrap: normal; word-break: normal; }
pre.mermaid { background: var(--soft); text-align: center; font-family: var(--mono); font-size: 0.85rem; }
pre.mermaid[data-processed] { border: 1px solid var(--line); }
blockquote {
  margin-left: 0;
  padding: 0.1rem 1rem;
  border-left: 4px solid var(--quote);
  background: var(--soft);
}
img { max-width: 100%; height: auto; }
article img { border: 1px solid var(--line); border-radius: 6px; background: #ffffff; display: block; margin: 0.8rem 0; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; font-size: 0.92rem; line-height: 1.6; }
th, td { border: 1px solid var(--line); padding: 0.4rem 0.7rem; min-width: 7em; text-align: left; vertical-align: top; }
th { background: var(--soft); }
hr { border: 0; border-top: 1px solid var(--line); margin: 2rem 0; }
details { border: 1px solid var(--line); border-radius: 6px; padding: 0.2rem 1rem; background: var(--soft); }
details[open] { padding-bottom: 0.6rem; }
summary { cursor: pointer; font-weight: 600; padding: 0.4rem 0; }
details > :last-child { margin-bottom: 0.2rem; }
nav.toc { margin: 1rem 0 1.5rem; }
nav.toc ul { list-style: none; padding-left: 0; margin: 0.3rem 0; font-size: 0.93rem; line-height: 1.7; }
nav.toc li.l3 { padding-left: 1.4rem; }
nav.toc li.l3 a { color: var(--muted); }

/* 入口 */
.portal main { padding-top: 2rem; }
.hero h1 { font-size: 2rem; margin: 0 0 0.4rem; }
.lead { font-size: 1.15rem; color: var(--muted); margin-top: 0; }
.portal section { margin-top: 2.2rem; }
.portal h2 { margin-top: 0; }
dl { margin: 0.8em 0; }
dt { font-weight: 700; margin-top: 0.8rem; }
dd { margin: 0.1rem 0 0; }
ul.links, ol.links { padding-left: 1.4rem; }
ul.links li, ol.links li { margin: 0.35rem 0; line-height: 1.7; }
.note { display: block; color: var(--muted); font-size: 0.9rem; line-height: 1.6; }
.more { font-size: 0.92rem; }
a.button {
  display: inline-block;
  background: var(--accent);
  color: var(--accent-fg);
  text-decoration: none;
  font-weight: 700;
  padding: 0.55rem 1.2rem;
  border-radius: 6px;
}
a.button:hover { opacity: 0.9; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 0 2rem; }

@media (max-width: 40rem) {
  body { font-size: 15.5px; line-height: 1.8; }
  h1 { font-size: 1.45rem; }
  .hero h1 { font-size: 1.6rem; }
  h2 { font-size: 1.2rem; }
  details { padding: 0.1rem 0.7rem; }
}
"""


# ------------------------------------------------------------------ 全体

def build(repo: Path, out: Path) -> list:
    """out/index.html・out/pages/ を作り直す。out/lecture/ には触れない。作ったファイルの相対パスの一覧を返す。"""
    sources = source_files(repo)
    names = {}
    for rel in sources:
        name = page_name(rel)
        if name in names:
            raise ValueError(f"ページの名前がぶつかる：{rel} と {names[name]}")
        names[name] = rel
    linker = Linker(repo, set(sources))
    pages = {rel: make_page(rel, repo, linker) for rel in sources}

    pages_dir = out / PAGES_DIR
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    (pages_dir / "img").mkdir(parents=True)
    written = []

    def write(path: Path, text: str):
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path.relative_to(out).as_posix())

    write(pages_dir / "style.css", STYLE_CSS)
    for rel in sources:
        write(pages_dir / page_name(rel), page_html(pages[rel]))
    for target, name in sorted(linker.assets.items()):
        dest = pages_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / target, dest)
        written.append(dest.relative_to(out).as_posix())
    write(out / "index.html", build_index(pages, repo))
    return sorted(written)


def tree_bytes(out: Path) -> dict:
    """out/index.html と out/pages/ の中身（比べる用）。"""
    files = [out / "index.html"] + [p for p in (out / PAGES_DIR).rglob("*") if p.is_file()]
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in files if p.exists()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="読む形のページと入口（site/index.html、site/pages/）を作る")
    parser.add_argument("--check", action="store_true", help="作り直した結果が site/ と同じかだけ確かめる")
    args = parser.parse_args(argv)
    site = REPO_DIR / "site"
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            build(REPO_DIR, Path(tmp))
            fresh, current = tree_bytes(Path(tmp)), tree_bytes(site)
        stale = sorted(k for k in fresh.keys() | current.keys() if fresh.get(k) != current.get(k))
        for name in stale:
            print(f"古い：site/{name}")
        print("site/ は最新です" if not stale else "python tools/build_site.py で作り直してください")
        return 1 if stale else 0
    written = build(REPO_DIR, site)
    print(f"site/index.html と site/pages/ を作りました（ページ {sum(f.endswith('.html') for f in written) - 1}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
