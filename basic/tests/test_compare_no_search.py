"""compare_no_search.py が、保存された答えを使ってよい条件（質問・検索の方式・件数がすべて同じ）を確かめる（通信なし）。
判定の関数は lib/rag_prompt.py の can_reuse()。

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lib  # noqa: E402,F401
from lib import rag_prompt  # noqa: E402  06-answer-from-results のスクリプトが使う部品
from lib.rag_prompt import METHOD, TOP_N  # noqa: E402


def saved(**over):
    rec = {"question": "Q", "answer": "A", "names": ["武将"], "settings": {"method": METHOD, "top_n": TOP_N}}
    for k, v in over.items():
        if k in rec["settings"]:
            rec["settings"][k] = v
        else:
            rec[k] = v
    return rec


class CanReuseTest(unittest.TestCase):
    def test_same_conditions_reuse(self):
        self.assertTrue(rag_prompt.can_reuse(saved(), "Q"))

    def test_nothing_saved(self):
        self.assertFalse(rag_prompt.can_reuse(None, "Q"))

    def test_different_question(self):
        self.assertFalse(rag_prompt.can_reuse(saved(), "別の質問"))

    def test_different_method_or_top_n(self):
        self.assertFalse(rag_prompt.can_reuse(saved(method="keyword"), "Q"))
        self.assertFalse(rag_prompt.can_reuse(saved(top_n=TOP_N + 2), "Q"))

    def test_old_record_without_settings(self):
        rec = saved()
        del rec["settings"]
        self.assertFalse(rag_prompt.can_reuse(rec, "Q"))


if __name__ == "__main__":
    unittest.main()
