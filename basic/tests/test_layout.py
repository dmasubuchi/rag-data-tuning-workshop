"""トピックのフォルダの約束を確かめる（通信なし）。

  ・スクリプトのファイル名は、全トピックを通して重ならない（トピックをまたいで import するため）
  ・どのファイルも構文として読める
  ・授業の回の呼び名と、移植前のファイル名・設定名が、スクリプトと README に出ていない
  ・「組」（チームごとのインデックスの名前の仕組み）、移植前の設定ファイルの名前、「講師」「受講者」「講義」の呼び方が出ていない
  ・引数の読み取りは parse_known_args（Jupyter が渡す余分な引数で落ちない）
  ・各トピックのフォルダに README がある

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import ast
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

BASIC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASIC))

TOPIC_SCRIPTS = sorted((BASIC / "topics").glob("*/*.py"))
ALL_PY = sorted(p for p in BASIC.rglob("*.py") if "__pycache__" not in p.parts)
TEXT_FILES = ALL_PY + sorted(BASIC.rglob("README.md")) + [BASIC / "requirements.txt"]
# 禁止する語は、このファイル自身に載らないように、2つに分けて書く
_BANNED_PARTS = [
    ("第[0-9０-９一二三四五六]+", "回"), ("シリ", "ーズ"), (r"\bB-", "[0-9]"), (r"\bs[1-6]", "_[a-z]"),
    (r"\brag", "kit\\b"), ("rag-", "course"), ("INDEX_", "PREFIX"), ("include", "-demos"),
]
BANNED = re.compile("|".join(a + b for a, b in _BANNED_PARTS))

# 呼び方：「講師」→「進行役」、「受講生」「受講者」→「参加者」、「講義」→「ハンズオン資料」。どのファイルにも出さない
_CALLING_PARTS = [("講", "師"), ("受", "講"), ("講", "義")]
CALLING = re.compile("|".join(a + b for a, b in _CALLING_PARTS))
# 「組」の仕組み（組の名前、<組>-sengoku、.group、set_group、移植前の設定ファイル）。固定の名前に替えたので、出さない。
# 「組み立てる」「仕組み」「組織」などの別の語は除く。試験（tests/）のうち、なくなったことを確かめるものは除く
_GROUP_PARTS = [
    ("(?<![仕取番])", "組(?![みむんまめ織合成立])"), ("get", "_group"), ("set", "_group"), ("check", "_group"), ("WORKSHOP", "_GROUP"),
    (r"\.gro", r"up\b(?!\()"), ("work", r"shop\.(?:local\.)?env"), (r"shared", "-"),
]
GROUP = re.compile("|".join(a + b for a, b in _GROUP_PARTS))
CHECKS_REMOVED_NAMES = {"test_layout.py", "test_config.py"}      # なくなった名前そのものを確かめる試験


class LayoutTest(unittest.TestCase):
    def test_script_names_are_unique_across_topics(self):
        names = Counter(p.name for p in TOPIC_SCRIPTS)
        self.assertEqual([n for n, c in names.items() if c > 1], [])
        # lib や標準ライブラリのモジュールと重ならない
        for p in TOPIC_SCRIPTS:
            self.assertNotIn(p.stem, sys.stdlib_module_names, p.name)

    def test_no_instructor_or_student_words(self):
        for p in TEXT_FILES:
            if p.name == "test_layout.py":
                continue
            m = CALLING.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{p.relative_to(BASIC)}: {m.group(0) if m else ''}")

    def test_no_group_or_old_env_names(self):
        for p in TEXT_FILES:
            if p.name in CHECKS_REMOVED_NAMES:
                continue
            m = GROUP.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{p.relative_to(BASIC)}: {m.group(0) if m else ''}")

    def test_notebooks_have_no_removed_words_either(self):
        for p in sorted((BASIC / "topics").glob("*/*.ipynb")):
            text = p.read_text(encoding="utf-8")
            for pattern in (CALLING, GROUP):
                m = pattern.search(text)
                self.assertIsNone(m, f"{p.relative_to(BASIC)}: {m.group(0) if m else ''}")

    def test_all_python_files_parse(self):
        for p in ALL_PY:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))

    def test_no_series_or_session_names(self):
        for p in TEXT_FILES:
            if p.name == "test_layout.py":
                continue
            m = BANNED.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{p.relative_to(BASIC)}: {m.group(0) if m else ''}")

    def test_topic_scripts_use_parse_known_args(self):
        for p in TOPIC_SCRIPTS:
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("parse_args()", text.replace("def parse_args()", "").replace("= parse_args()", "").replace("parse_args():", ""),
                             p.name)
            if "ArgumentParser(" in text:
                self.assertIn("parse_known_args()", text, p.name)

    def test_every_topic_has_readme(self):
        for d in sorted((BASIC / "topics").iterdir()):
            if d.is_dir():
                self.assertTrue((d / "README.md").is_file(), d.name)


if __name__ == "__main__":
    unittest.main()
