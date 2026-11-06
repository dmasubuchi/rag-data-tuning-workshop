"""人事のデータを作り直す道具（data/_build）の検査 check_all.py が、禁止語の一覧を環境変数から読むことを確かめる（通信なし）。

禁止語（固有名）の一覧は、Repo に書かない。環境変数 PUBLIC_CHECK_BANNED が指すファイルを読む（tools/check_public.py と同じ形）。
この試験は、本物の一覧を使わない。架空の語の一時のファイルを作って使う。applied フォルダで
    python -m unittest discover -s tests
"""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APPLIED = Path(__file__).resolve().parent.parent
REPO = APPLIED.parent
BUILD = APPLIED / "data" / "_build"
sys.path.insert(0, str(BUILD))
import check_all  # noqa: E402

FAKE_WORDS = ["ファントム商事", "PHANTOMCORP"]            # 架空の語。本物の一覧ではない


def load_check_public():
    spec = importlib.util.spec_from_file_location("check_public_tool", REPO / "tools" / "check_public.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BannedFromEnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def banned_file(self, text="\n".join(FAKE_WORDS) + "\n", name="banned-fake.txt", raw=None):
        p = self.dir / name
        p.write_bytes(raw if raw is not None else text.encode("utf-8"))
        return p

    def env(self, path=None):
        env = {k: v for k, v in os.environ.items() if k != check_all.BANNED_ENV}
        if path is not None:
            env[check_all.BANNED_ENV] = str(path)
        return mock.patch.dict(os.environ, env, clear=True)

    def run_main(self, path=None):
        out = io.StringIO()
        with self.env(path), contextlib.redirect_stdout(out):
            code = check_all.main()
        return code, out.getvalue()

    def test_check_all_reads_banned_from_env(self):
        p = self.banned_file("﻿" + "\n".join(FAKE_WORDS) + "\n\n   \n")       # BOM・空行・空白だけの行があっても、読める
        with self.env(p):
            words = check_all.load_banned()
        self.assertEqual(words, FAKE_WORDS)
        self.assertEqual(check_all.BANNED_ENV, "PUBLIC_CHECK_BANNED")
        # tools/check_public.py と同じ読み方（同じファイルから、同じ語の一覧になる）
        self.assertEqual(load_check_public().load_banned(p), words)

    def test_check_all_reads_banned_from_env_and_not_from_the_code(self):
        """固有名は、コードに書かない。一覧を変えれば、見つかる語も変わる。"""
        text = "運営は ファントム商事 です。"
        p1 = self.banned_file("ファントム商事\n", "a.txt")
        p2 = self.banned_file("別の架空の語\n", "b.txt")
        with self.env(p1):
            self.assertEqual(len(check_all.banned_hits("x", text, check_all.load_banned())), 1)
        with self.env(p2):
            self.assertEqual(check_all.banned_hits("x", text, check_all.load_banned()), [])

    def test_hits_say_the_number_not_the_word(self):
        hits = check_all.banned_hits("jobs/x.pdf", "運営は ＰＨＡＮＴＯＭＣＯＲＰ です（全角の英字）。", FAKE_WORDS)
        self.assertEqual(hits, ["jobs/x.pdf に禁止語の一覧の 2 番目の語があります"])
        for w in FAKE_WORDS:
            self.assertNotIn(w, "".join(hits))
        both = check_all.banned_hits("m.eml", "ファントム商事 と phantomcorp", FAKE_WORDS)         # 大文字小文字は区別しない
        self.assertEqual([h.split("一覧の ")[1].split(" 番目")[0] for h in both], ["1", "2"])
        self.assertEqual(check_all.banned_hits("clean.pdf", "問題のない文章です。", FAKE_WORDS), [])

    def test_stops_with_2_when_the_list_is_missing(self):
        code, out = self.run_main(None)                                    # 環境変数がない
        self.assertEqual(code, 2)
        self.assertIn("PUBLIC_CHECK_BANNED", out)
        code, out = self.run_main(self.dir / "no-such-file.txt")           # ファイルがない
        self.assertEqual(code, 2)
        self.assertIn("PUBLIC_CHECK_BANNED", out)
        code, _ = self.run_main(self.banned_file("\n  \n", "empty.txt"))   # 空
        self.assertEqual(code, 2)
        code, _ = self.run_main(self.banned_file(raw=b"\xff\xfe\x00", name="bad.txt"))     # UTF-8 ではない
        self.assertEqual(code, 2)

    def test_stop_messages_do_not_show_words_or_paths(self):
        p = self.banned_file(raw="ファントム商事\n".encode("utf-16"), name="utf16.txt")
        code, out = self.run_main(p)
        self.assertEqual(code, 2)
        self.assertNotIn("ファントム商事", out)
        self.assertNotIn(str(self.dir), out)

    def test_leftover_markers_and_reserved_domains(self):
        marks = [a + b for a, b in (("ZX", "7Q"), ("CAN", "ARY"))]
        for m in marks:
            self.assertTrue(check_all.banned_hits("x", f"…{m.lower()}…", []), m)        # 生成の残りの目印は、一覧がなくても見つける
        for ok in ("example.com", "example.net", "example.org", "example.jp", "gamma.example", "x.test", "y.invalid", "z.localhost",
                   "Example.COM"):
            self.assertTrue(check_all.is_example_domain(ok), ok)
        for ng in ("gmail.com", "example.com.evil.net", "notexample.com", "example.co.uk", "sample.org"):
            self.assertFalse(check_all.is_example_domain(ng), ng)

    def test_no_fixed_proper_names_in_the_checker(self):
        """検査のコードには、固有名の一覧も、生成の残りの目印も、そのままの形では書かない。"""
        text = (BUILD / "check_all.py").read_text(encoding="utf-8")
        self.assertNotIn("BANNED = [", text)
        for marker in (("ZX", "7Q"), ("CAN", "ARY")):
            self.assertNotIn("".join(marker), text)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow が入っていない（data/_build/requirements.txt）ので飛ばす")
    def test_main_finds_a_listed_word_in_the_data_without_printing_it(self):
        """実際のデータ（23 文書）に、一覧の語があれば、番号で知らせる。語は画面に出さない。"""
        word = "サンプルテック"                                          # データにある（架空の会社の名前）。一覧に入れて、見つかるかを見る
        p = self.banned_file(word + "\n", "word.txt")
        code, out = self.run_main(p)
        self.assertEqual(code, 1)
        self.assertIn("禁止語の一覧の 1 番目の語があります", out)
        self.assertNotIn(word, out)


if __name__ == "__main__":
    unittest.main()
