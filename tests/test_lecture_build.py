"""docs/lecture/tools/build.py の試験。

ハンズオン資料の原稿（keywords.md・decks.json・diagrams/）から、HTML のスライド（site/lecture/）が作られることと、
「確かめる」のリンクが、この Repo にあるトピックだけを指すことを確かめる。通信しない。
"""

import ast
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
LECTURE = REPO_DIR / "docs" / "lecture"
BUILD = LECTURE / "tools" / "build.py"
CHECK = LECTURE / "tools" / "check.py"
DECKS = LECTURE / "decks.json"
SITE_LECTURE = REPO_DIR / "site" / "lecture"

# 研修の Repo に入っていない基礎編のトピック（07〜13）を指す書き方
MISSING_TOPIC_TEXT = re.compile(r"基礎 ?(0[7-9]|1[0-3])")


def load_build():
    spec = importlib.util.spec_from_file_location("lecture_build", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_build(out: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BUILD), "--out", str(out)], capture_output=True, text=True, check=True)


class BuildTest(unittest.TestCase):
    def test_build_writes_six_decks(self):
        conf = json.loads(DECKS.read_text(encoding="utf-8"))
        ids = [d["id"] for d in conf["decks"]]
        self.assertEqual(len(ids), 6)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "lecture"
            run_build(out)
            for deck_id in ids:
                page = out / deck_id / "slides.html"
                self.assertTrue(page.is_file(), f"{deck_id}/slides.html がない")
                self.assertIn('<script src="../player.js">', page.read_text(encoding="utf-8"))
            self.assertEqual(sorted(p.parent.name for p in out.glob("*/slides.html")), sorted(ids))
            self.assertTrue((out / "index.html").is_file())
            self.assertTrue((out / "player.js").is_file())
            self.assertEqual((out / "player.js").read_bytes(), (LECTURE / "player.js").read_bytes())

    def test_no_check_links_to_missing_topics(self):
        conf = json.loads(DECKS.read_text(encoding="utf-8"))
        topics = conf["topics"]
        for no, t in topics.items():
            self.assertTrue((REPO_DIR / t["path"]).is_dir(), f"トピック {no} のフォルダ {t['path']} がない")
        build = load_build()
        pages = build.parse_keywords(LECTURE / "keywords.md")
        n_checks = 0
        for d in conf["decks"]:
            for item in d["items"]:
                ids = item.get("check", []) if "page" in item else item.get("slide", {}).get("check", [])
                for no in ids:
                    self.assertIn(no, topics, f"{d['id']} の {item.get('page') or item['slide']['id']} が、ないトピック {no} を指している")
            deck = build.build_deck(d, conf, pages)
            for s in deck["slides"]:
                for c in s.get("check", []):
                    n_checks += 1
                    self.assertTrue((REPO_DIR / topics[c["no"]]["path"]).is_dir())
        self.assertGreater(n_checks, 0)

    def test_no_text_mentions_of_missing_topics(self):
        files = [LECTURE / "keywords.md", DECKS, *sorted((LECTURE / "diagrams").glob("*.py")),
                 *sorted((LECTURE / "diagrams").glob("p*.json"))]
        for f in files:
            m = MISSING_TOPIC_TEXT.search(f.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{f.relative_to(REPO_DIR)} に、この Repo にないトピック（{m and m.group(0)}）の話がある")

    def test_build_is_stdlib_only(self):
        for path in (BUILD, LECTURE / "tools" / "svgparts.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [] if node.level else [(node.module or "").split(".")[0]]
                else:
                    continue
                for mod in mods:
                    self.assertIn(mod, sys.stdlib_module_names, f"{path.name} が標準ライブラリ以外（{mod}）を import している")

    def test_options_without_value_stop_with_usage(self):
        # 値のない --out・--decks・--md（check.py は --out・--site・--decks）は、IndexError でなく使い方を出して 2 で止まる
        # （check.py は playwright がなくても、引数を先に読むので同じ）
        for script, opts in ((BUILD, ("--out", "--decks", "--md")), (CHECK, ("--out", "--site", "--decks"))):
            for opt in opts:
                r = subprocess.run([sys.executable, str(script), opt], capture_output=True, text=True)
                self.assertEqual(r.returncode, 2, f"{script.name} {opt}")
                self.assertIn("usage:", r.stderr)
                self.assertNotIn("Traceback", r.stderr)

    def test_tools_parse_on_python_3_10(self):
        # README・docstring は Python 3.10 以上と書いている。3.12 だけの書き方（PEP 701：f-string の式の中で、外と同じ引用符を使う）を入れない
        sources = sorted((LECTURE / "tools").glob("*.py")) + [LECTURE / "diagrams" / "figures.py"]
        for path in sources:
            text = path.read_text(encoding="utf-8")
            ast.parse(text, filename=str(path), feature_version=(3, 10))       # 3.10 で使えない構文
            if sys.version_info >= (3, 12):
                # ast.parse(feature_version=…) は PEP 701 を通してしまうので、字句で調べる：f-string の中の式にある文字列が、外と同じ引用符
                stack: list[str] = []
                for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                    if tok.type == tokenize.FSTRING_START:
                        if stack and tok.string[-1] == stack[-1]:
                            self.fail(f"{path.name}:{tok.start[0]} の f-string の式の中で、外と同じ引用符を使っている（3.12 以上でしか動かない）")
                        stack.append(tok.string[-1])
                    elif tok.type == tokenize.FSTRING_END:
                        stack.pop()
                    elif tok.type == tokenize.STRING and stack and tok.string.lstrip("rbuRBU")[0] == stack[-1]:
                        self.fail(f"{path.name}:{tok.start[0]} の f-string の式の中で、外と同じ引用符を使っている（3.12 以上でしか動かない）")
        # 3.10・3.11 の実機があれば、本物の構文解析でも確かめる（なければ飛ばす）
        found = [p for p in (shutil.which("python3.10"), shutil.which("python3.11")) if p]
        for exe in found:
            for path in sources:
                r = subprocess.run([exe, "-c", "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())", str(path)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{exe} で {path.name} を読めない：{r.stderr[-300:]}")

    def test_edition_comes_from_topic_path(self):
        build = load_build()
        topics = json.loads(DECKS.read_text(encoding="utf-8"))["topics"]
        self.assertEqual(build.edition("basic/topics/01-keyword-search"), "基礎")
        self.assertEqual(build.edition("applied/topics/14-mixed-documents"), "応用")
        with self.assertRaises(SystemExit):
            build.edition("other/topics/99-x")
        for no, t in topics.items():
            self.assertEqual(build.topic_ref(topics, no)["ed"], "基礎" if t["path"].startswith("basic/") else "応用")
        # 番号が 13 以下でも、applied/ のフォルダなら応用編（番号では決めない）
        self.assertEqual(build.topic_ref({"05": {"name": "x", "path": "applied/topics/05-x"}}, "05")["ed"], "応用")

    def test_no_references_to_files_outside_this_repo(self):
        # この Repo にない道具・約束書を指さない（slide-player の写し player.js は元のまま）
        gone = ("CONTRACT.md", "CONTRACT §", "_common.py", "build_deck.py", "build_video.py", "lecture-short")
        files = [LECTURE / "deck.html", LECTURE / "README.md", LECTURE / "catalog.css", *sorted((LECTURE / "tools").glob("*.py")),
                 *sorted((LECTURE / "diagrams").glob("*.py"))]
        for f in files:
            text = f.read_text(encoding="utf-8")
            for word in gone:
                self.assertNotIn(word, text, f"{f.relative_to(REPO_DIR)} が、この Repo にない {word} を指している")

    def test_write_is_lf_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "lecture"
            run_build(out)
            htmls = list(out.rglob("*.html"))
            self.assertEqual(len(htmls), 7)
            for p in htmls:
                self.assertNotIn(b"\r", p.read_bytes(), p.name)

    def test_site_lecture_is_up_to_date(self):
        # 生成物 site/lecture/ は Git に入れる。原稿を直したら build.py で作り直す
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "lecture"
            run_build(out)
            fresh = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
            kept = {p.relative_to(SITE_LECTURE).as_posix(): p.read_bytes() for p in SITE_LECTURE.rglob("*") if p.is_file()}
            self.assertEqual(sorted(fresh), sorted(kept))
            for name, data in fresh.items():
                self.assertEqual(data, kept[name], f"site/lecture/{name} が古い。python3 docs/lecture/tools/build.py で作り直す")


if __name__ == "__main__":
    unittest.main()
