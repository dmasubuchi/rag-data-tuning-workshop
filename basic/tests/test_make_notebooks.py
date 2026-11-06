"""作る人用の道具 tools/make_notebooks.py（セル形式の .py から .ipynb を作る）の動きを確かめる（通信なし）。

jupytext は作る人の道具なので、参加者の環境（basic/requirements.txt）には入っていない（requirements-dev.txt に入れる）。入っていなければ、この試験は飛ばす。

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOL = Path(__file__).resolve().parents[2] / "tools" / "make_notebooks.py"

try:
    import jupytext  # noqa: F401
    HAVE_JUPYTEXT = True
except ImportError:
    HAVE_JUPYTEXT = False

SAMPLE = '''# %% [markdown]
# # 見出し
# 説明です。

# %%
x = 1
print("こんにちは", x)

# %%
y = x + 1

# %%
y = x + 1
'''


def load_tool():
    spec = importlib.util.spec_from_file_location("make_notebooks_tool", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_JUPYTEXT, "jupytext が入っていないので飛ばす（作る人の道具。requirements-dev.txt）")
class MakeNotebooksTest(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.topic = self.repo / "basic" / "topics" / "01-sample"
        self.topic.mkdir(parents=True)
        self.py = self.topic / "sample.py"
        self.py.write_text(SAMPLE, encoding="utf-8")
        (self.topic / "plain.py").write_text("print('セルではない')\n", encoding="utf-8")   # # %% がないものは対象外
        self.nb = self.py.with_suffix(".ipynb")
        self.p = mock.patch.object(self.tool, "REPO", self.repo)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def build(self):
        with mock.patch("builtins.print"):
            self.tool.build(self.tool.cell_scripts())

    def kinds(self):
        return sorted((Path(path).name, kind) for path, kind, _ in self.tool.check(self.tool.cell_scripts()))

    def test_only_cell_scripts_are_targets(self):
        self.assertEqual([p.name for p in self.tool.cell_scripts()], ["sample.py"])

    def test_notebook_is_minimal_and_empty(self):
        text = self.tool.to_notebook_text(SAMPLE)
        nb = json.loads(text)
        self.assertEqual(nb["metadata"], {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})
        self.assertEqual([c["cell_type"] for c in nb["cells"]], ["markdown", "code", "code", "code"])
        for c in nb["cells"]:
            self.assertEqual(c["metadata"], {})
            if c["cell_type"] == "code":
                self.assertEqual(c["outputs"], [])
                self.assertIsNone(c["execution_count"])
        ids = [c["id"] for c in nb["cells"]]
        self.assertEqual(len(ids), len(set(ids)))            # 中身が同じセルが2つあっても、id は重ならない
        self.assertTrue(text.endswith("}\n"))

    def test_same_input_gives_same_bytes(self):
        self.assertEqual(self.tool.to_notebook_text(SAMPLE), self.tool.to_notebook_text(SAMPLE))
        self.build()
        first = self.nb.read_bytes()
        self.build()
        self.assertEqual(self.nb.read_bytes(), first)

    def test_check_reports_each_kind_of_problem(self):
        self.assertEqual(self.kinds(), [("sample.ipynb", "ない")])
        self.build()
        self.assertEqual(self.kinds(), [])

        nb = json.loads(self.nb.read_text(encoding="utf-8"))
        nb["cells"][1]["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]
        nb["cells"][1]["execution_count"] = 3
        self.nb.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.kinds(), [("sample.ipynb", "出力あり")])

        self.build()
        self.py.write_text(SAMPLE + "\n# %%\nz = 3\n", encoding="utf-8")
        self.assertEqual(self.kinds(), [("sample.ipynb", "ずれ")])

        self.build()
        (self.topic / "gone.ipynb").write_text("{}", encoding="utf-8")
        self.assertEqual(self.kinds(), [("gone.ipynb", "余分")])


if __name__ == "__main__":
    unittest.main()
