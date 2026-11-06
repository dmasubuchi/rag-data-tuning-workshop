"""応用編のフォルダの約束を確かめる（通信なし）。

  ・トピックのスクリプトのファイル名は、全トピックを通して重ならない。どのファイルも構文として読める
  ・呼び方：「講師」「受講者」「受講生」「講義」を、どのファイルにも出さない（進行役・参加者・ハンズオン資料・構築する人・メンバー）
  ・「組」（チームごとの名前の仕組み）、移植前の設定ファイルの名前、共有の名前（shared-…）、固定のモデル名が出ていない
  ・授業の回の呼び名や、環境の名前（class・prep）が出ていない
  ・Notebook は、セル形式のスクリプトから作ったものと同じ中身（jupytext が入っているとき）
  ・引数の読み取りは parse_known_args（Jupyter が渡す余分な引数で落ちない）
  ・各トピックのフォルダに README がある

実行（applied フォルダで）：python -m unittest discover -s tests
"""
import ast
import importlib.util
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

APPLIED = Path(__file__).resolve().parent.parent
REPO = APPLIED.parent
sys.path.insert(0, str(APPLIED))

TOPIC_SCRIPTS = sorted((APPLIED / "topics").glob("*/*.py"))
ALL_PY = sorted(p for p in APPLIED.rglob("*.py") if "__pycache__" not in p.parts)
TEXT_FILES = (ALL_PY + sorted(APPLIED.rglob("README.md")) + [APPLIED / "requirements.txt", APPLIED / "requirements-eval.txt"])
# 禁止する語は、このファイル自身に載らないように、2つに分けて書く
_BANNED_PARTS = [
    ("第[0-9０-９一二三四五六]+", "回"), ("シリ", "ーズ"), (r"\bB-", "[0-9]"), (r"\bs[1-6]", "_[a-z]"),
    (r"\brag", "kit\\b"), ("rag-", "course"), ("INDEX_", "PREFIX"), ("include", "-demos"),
    (r"\bcla", "ss の"), (r"\bpr", "ep の"), ("gpt-5", r"\.4"),
]
BANNED = re.compile("|".join(a + b for a, b in _BANNED_PARTS))
_CALLING_PARTS = [("講", "師"), ("受", "講"), ("講", "義")]
CALLING = re.compile("|".join(a + b for a, b in _CALLING_PARTS))
# 「組」の仕組み（組の名前、<組>、.group、set_group、移植前の設定ファイル、共有の名前、組の写し）。出さない。
# 「組み込む」「仕組み」「組織」などの別の語は除く。
_GROUP_PARTS = [
    ("(?<![仕取番])", "組(?![みむんまめ織合成立])"), ("get", "_group"), ("set", "_group"), ("check", "_group"), ("WORKSHOP", "_GROUP"),
    (r"\.gro", r"up\b(?!\()"), ("work", r"shop\.(?:local\.)?env"), (r"shared", "-"), ("SHA", "RED_"), ("refuse_", "unshared"),
    ("group", "copy"), ("group", " eq"), ("build_", "shared"), ("search_", "shared"), (r"shared", r"/"),
]
GROUP = re.compile("|".join(a + b for a, b in _GROUP_PARTS))
CHECKS_REMOVED_NAMES = {"test_layout.py", "test_config.py", "test_acl_errors.py", "test_docops_fake.py", "test_applied.py",
                       "test_topics_16_18.py"}      # なくなった名前そのものを確かめる試験


def rel(p: Path) -> str:
    return str(p.relative_to(APPLIED))


class LayoutTest(unittest.TestCase):
    def test_script_names_are_unique_across_topics(self):
        names = Counter(p.name for p in TOPIC_SCRIPTS)
        self.assertEqual([n for n, c in names.items() if c > 1], [])
        for p in TOPIC_SCRIPTS:
            self.assertNotIn(p.stem, sys.stdlib_module_names, p.name)

    def test_all_the_topics_14_to_20_are_here(self):
        folders = sorted(d.name for d in (APPLIED / "topics").iterdir() if d.is_dir())
        self.assertEqual(folders, ["14-mixed-documents", "15-azure-indexer", "16-security-filter", "17-update-delete", "18-relations",
                                   "19-agentic-retrieval", "20-answer-evaluation"])
        self.assertEqual(sorted(p.name for p in (APPLIED / "topics" / "17-update-delete").glob("*.py")),
                         ["cleanup.py", "revise_job_posting.py", "withdraw_application.py"])
        self.assertTrue((APPLIED / "topics" / "15-azure-indexer" / "search_documents.py").is_file())
        self.assertFalse((APPLIED / "topics" / "15-azure-indexer" / "search_shared.py").exists())
        self.assertFalse((APPLIED / "lib" / "groupcopy.py").exists())

    def test_no_instructor_or_student_words(self):
        for p in TEXT_FILES:
            if p.name == "test_layout.py":
                continue
            m = CALLING.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{rel(p)}: {m.group(0) if m else ''}")

    def test_no_group_shared_or_old_env_names(self):
        for p in TEXT_FILES:
            if p.name in CHECKS_REMOVED_NAMES:
                continue
            m = GROUP.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{rel(p)}: {m.group(0) if m else ''}")

    def test_no_series_session_environment_or_fixed_model_names(self):
        for p in TEXT_FILES:
            if p.name == "test_layout.py":
                continue
            m = BANNED.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{rel(p)}: {m.group(0) if m else ''}")

    def test_notebooks_have_no_removed_words_either(self):
        for p in sorted((APPLIED / "topics").glob("*/*.ipynb")):
            text = p.read_text(encoding="utf-8")
            for pattern in (CALLING, GROUP, BANNED):
                m = pattern.search(text)
                self.assertIsNone(m, f"{rel(p)}: {m.group(0) if m else ''}")

    def test_all_python_files_parse(self):
        for p in ALL_PY:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))

    def test_topic_scripts_use_parse_known_args(self):
        for p in TOPIC_SCRIPTS:
            text = p.read_text(encoding="utf-8")
            self.assertNotIn(".parse_args(", text, p.name)
            if "ArgumentParser(" in text:
                self.assertIn("parse_known_args()", text, p.name)

    def test_every_topic_has_readme(self):
        for d in sorted((APPLIED / "topics").iterdir()):
            if d.is_dir():
                self.assertTrue((d / "README.md").is_file(), d.name)

    def test_readmes_refer_to_files_that_exist(self):
        """README が書いているスクリプト名（`xxx.py`）は、その Repo のどこかにある。"""
        names = {p.name for p in ALL_PY} | {p.name for p in (REPO / "tools").glob("*.py")}
        for readme in sorted(APPLIED.rglob("README.md")):
            for name in set(re.findall(r"`([A-Za-z0-9_]+\.py)`", readme.read_text(encoding="utf-8"))):
                self.assertIn(name, names, f"{rel(readme)}: {name}")

    def test_notebooks_are_in_sync_with_the_scripts(self):
        try:
            import jupytext  # noqa: F401
        except ImportError:
            self.skipTest("jupytext が入っていないので飛ばす（教材を直す人の道具。requirements-dev.txt）")
        spec = importlib.util.spec_from_file_location("make_notebooks_tool", REPO / "tools" / "make_notebooks.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        applied_scripts = [p for p in tool.cell_scripts() if APPLIED in p.parents]
        self.assertEqual(len(applied_scripts), len(TOPIC_SCRIPTS))          # 全部がセル形式
        problems = [x for x in tool.check(applied_scripts) if x[0].startswith("applied/")]
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
