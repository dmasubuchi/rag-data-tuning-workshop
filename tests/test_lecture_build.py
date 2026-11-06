"""docs/lecture/tools/build.py の試験。

ハンズオン資料の原稿（keywords.md・decks.json・diagrams/）から、HTML のスライド（site/lecture/）が作られることと、
「確かめる」のリンクが、この Repo にあるトピックだけを指すことを確かめる。通信しない。
"""

import ast
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
LECTURE = REPO_DIR / "docs" / "lecture"
BUILD = LECTURE / "tools" / "build.py"
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
