"""トピックのスクリプトが、セルの形（# %%）の書き方を守っているかを確かめる（通信なし）。

セル形式のスクリプトは、上から順に実行するもの。スクリプト（python xxx.py）でも、Notebook（.ipynb）でも同じ中身で動く。
そのため、次の約束を守る。
  ・先頭は `# %% [markdown]` のセル（何をするか、実行の仕方、前提）
  ・初期化のセルで、__file__ がない Notebook でも basic/ を探索に加えられる（HERE の書き方）
  ・エラーの表示は cells.start()
  ・main() を作らない（`if __name__ == "__main__"` も、run(main) も使わない）
  ・引数は parse_known_args()（Jupyter が渡す余分な引数で止まらない）
  ・ほかのトピックのスクリプトを import しない（読み込むと動き出すため。共有する関数は lib/ に置く）

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import ast
import re
import sys
import unittest
from pathlib import Path

BASIC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASIC))

TOPIC_SCRIPTS = sorted((BASIC / "topics").glob("*/*.py"))
CELL_SCRIPTS = [p for p in TOPIC_SCRIPTS if re.search(r"^# %%", p.read_text(encoding="utf-8"), re.MULTILINE)]
SCRIPT_NAMES = {p.stem for p in TOPIC_SCRIPTS}
# 別のトピックのスクリプトを import している行（import xxx、from xxx import …）
CROSS_IMPORT = re.compile(r"^\s*(?:import|from)\s+(" + "|".join(sorted(map(re.escape, SCRIPT_NAMES))) + r")\b", re.MULTILINE)


def rel(p: Path) -> str:
    return str(p.relative_to(BASIC))


class CellFormatTest(unittest.TestCase):
    def test_there_are_cell_scripts(self):
        self.assertGreaterEqual(len(CELL_SCRIPTS), 21)

    def test_every_topic_script_is_in_cell_format(self):
        """トピックのスクリプトは、すべてセル形式（# %% を含む）。"""
        self.assertEqual([rel(p) for p in TOPIC_SCRIPTS if p not in CELL_SCRIPTS], [])

    def test_starts_with_markdown_cell(self):
        for p in CELL_SCRIPTS:
            first = next(line for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
            self.assertEqual(first, "# %% [markdown]", rel(p))

    def test_init_cell_works_without___file__(self):
        for p in CELL_SCRIPTS:
            text = p.read_text(encoding="utf-8")
            self.assertRegex(text, r"try:\n    HERE = Path\(__file__\)\.resolve\(\)\.parent\nexcept NameError:", rel(p))
            self.assertIn("HERE = Path.cwd()", text, rel(p))
            self.assertIn("sys.path.insert(0, str(HERE.parents[1]))", text, rel(p))
            self.assertNotIn("sys.path.insert(0, str(Path(__file__)", text, rel(p))

    def test_errors_are_shown_for_students(self):
        for p in CELL_SCRIPTS:
            text = p.read_text(encoding="utf-8")
            self.assertIn("\ncells.start()", text, rel(p))
            self.assertNotIn("friendly_errors", text, rel(p))

    def test_no_main_function(self):
        for p in CELL_SCRIPTS:
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"^def main\(", rel(p))
            self.assertNotIn('if __name__ == "__main__"', text, rel(p))
            self.assertNotIn("run(main)", text, rel(p))

    def test_arguments_use_parse_known_args(self):
        for p in CELL_SCRIPTS:
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\.parse_args\(", rel(p))
            if "ArgumentParser(" in text:
                self.assertIn("parse_known_args()", text, rel(p))

    def test_no_script_imports_another_script(self):
        """セル形式のスクリプトは、読み込むと上から順に動き出す。だから、スクリプトどうしで import しない。"""
        files = list(TOPIC_SCRIPTS) + sorted((BASIC / "lib").glob("*.py")) + sorted((BASIC / "tools").glob("*.py"))
        bad = []
        for p in files:
            for m in CROSS_IMPORT.finditer(p.read_text(encoding="utf-8")):
                bad.append(f"{rel(p)}: {m.group(0).strip()}")
        self.assertEqual(bad, [])

    def test_build_prompt_in_the_cell_matches_lib(self):
        """06 の build_prompt.py のセルに書いたプロンプトの組み立ては、generate_answer.py などが使う lib/rag_prompt.py と同じ結果になる。"""
        import lib  # noqa: F401
        from lib import rag_prompt

        text = (BASIC / "topics" / "06-answer-from-results" / "build_prompt.py").read_text(encoding="utf-8")
        func = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "build_prompt")
        scope: dict = {}
        exec(compile(ast.Module(body=[func], type_ignores=[]), "build_prompt.py", "exec"), scope)
        hits = [{"name": "武将A", "profile": "本文A"}, {"name": "武将B", "profile": "本文B\n二行目"}]
        self.assertEqual(scope["build_prompt"]("質問ですか。", hits), rag_prompt.build_prompt("質問ですか。", hits))

    def test_call_counts_are_for_this_run_only(self):
        """Notebook では llm.CALLS がカーネルに残る。呼び出しの回数を出すスクリプトは、この実行の分だけを出す。"""
        shown = 0
        for p in CELL_SCRIPTS:
            text = p.read_text(encoding="utf-8")
            if "api_calls_line(llm.CALLS" in text:
                shown += 1
                self.assertIn("api_calls_line(llm.CALLS - calls0)", text, rel(p))
                self.assertIn("calls0 = llm.CALLS.copy()", text, rel(p))
        self.assertGreaterEqual(shown, 2)      # 06 の generate_answer.py と compare_no_search.py

if __name__ == "__main__":
    unittest.main()
