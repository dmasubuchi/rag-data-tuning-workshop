"""作る人用の tools/make_embeddings.py と、同梱の埋め込み済みファイル（embeddings/sengoku.json）の整合を確かめる（通信なし）。

  ・埋め込む文字列は、武将ごとの「名前。本文」
  ・同梱のファイルが、いまの武将の全員分のベクトルを持っている（本文を書き換えたのに作り直し忘れると、ここで気づく）
  ・ファイルのモデル名・次元の記録が、.env.local の既定（text-embedding-3-small、1536 次元）と同じ

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import importlib.util
import sys
import unittest
from pathlib import Path

BASIC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASIC))

import lib  # noqa: E402,F401
from lib.config import SENGOKU_EMBEDDINGS  # noqa: E402
from lib.data import embedding_text, load_bushou  # noqa: E402
from lib.vectorstore import FORMAT, load_file, text_key  # noqa: E402


def load_tool():
    spec = importlib.util.spec_from_file_location("make_embeddings_tool", BASIC / "tools" / "make_embeddings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MakeEmbeddingsSengokuTest(unittest.TestCase):
    def test_texts_are_name_and_profile_of_each_person(self):
        people = load_bushou()
        texts = load_tool().sengoku_texts()
        self.assertEqual(len(texts), len(people))
        self.assertEqual(texts[0], f"{people[0]['name']}。{people[0]['profile']}")
        self.assertEqual(texts, [embedding_text(p) for p in people])

    def test_bundled_file_covers_every_person(self):
        data = load_file(SENGOKU_EMBEDDINGS)
        self.assertIsNotNone(data)
        self.assertEqual(data["format"], FORMAT)
        missing = [t for t in load_tool().sengoku_texts() if text_key(t) not in data["vectors"]]
        self.assertEqual(len(missing), 0, f"埋め込み済みファイルにない武将が {len(missing)} 人います。tools/make_embeddings.py で作り直してください")

    def test_bundled_file_records_model_and_dimensions(self):
        data = load_file(SENGOKU_EMBEDDINGS)
        self.assertEqual((data["model"], data["dimensions"]), ("text-embedding-3-small", 1536))
        self.assertTrue(all(len(v) == 1536 for v in data["vectors"].values()))

    def test_only_sengoku_is_built(self):
        tool = load_tool()
        for removed in ("kitei_texts", "resolve_kitei_settings"):
            self.assertFalse(hasattr(tool, removed), removed)


if __name__ == "__main__":
    unittest.main()
