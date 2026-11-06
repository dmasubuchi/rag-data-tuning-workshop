"""runner.run() が、例外の文に混じったキーを画面に出さないことを確かめる（通信なし）。

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config, runner  # noqa: E402
from lib.config import SetupError  # noqa: E402

OAI = "FAKE-OAI-a1b2c3"
SRC = "FAKE-SRCH-d4e5f6"
ENV = f"""AZURE_SEARCH_ENDPOINT=https://a.search.windows.net
AZURE_SEARCH_API_KEY={SRC}
AZURE_OPENAI_ENDPOINT=https://b.azure.com
AZURE_OPENAI_API_KEY={OAI}
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=e
AZURE_OPENAI_CHAT_DEPLOYMENT=c
EMBEDDING_DIMENSIONS=1536
AZURE_STORAGE_CONNECTION_STRING=AccountName=zz;AccountKey=FAKE-ACCT-g7h8==;EndpointSuffix=core.windows.net
"""
PROXY = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def run_capture(main):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with redirect_stdout(out), redirect_stderr(err):
        try:
            runner.run(main)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue() + err.getvalue()


class RedactTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / "x.env"
        self.env.write_text(ENV, encoding="utf-8")
        patch = {"WORKSHOP_ENV_FILE": str(self.env), **{k: "" for k in PROXY}}
        self.p = mock.patch.dict(os.environ, patch)
        self.p.start()
        for k in ("AZURE_OPENAI_API_KEY", "AZURE_SEARCH_API_KEY"):
            os.environ.pop(k, None)
        config.get_settings.cache_clear()

    def tearDown(self):
        self.p.stop()
        config.get_settings.cache_clear()
        self.tmp.cleanup()

    def check(self, exc, code):
        def main():
            raise exc
        c, text = run_capture(main)
        self.assertEqual(c, code)
        self.assertNotIn(OAI, text)
        self.assertNotIn(SRC, text)
        self.assertNotIn("FAKE-ACCT-g7h8", text)   # Storage の接続文字列の中のキー
        self.assertIn("***", text)

    def test_runtime_error(self):
        self.check(RuntimeError(f"bad header Authorization: Bearer {OAI} and api-key {SRC} FAKE-ACCT-g7h8=="), 1)

    def test_key_before_truncation(self):
        # 600字で切られる位置にキーがまたがっても出ない
        self.check(RuntimeError("x" * 590 + OAI), 1)

    def test_setup_error(self):
        self.check(SetupError(f"設定の問題 {OAI}"), 2)

    def test_settings_unreadable(self):
        # 設定が読めない（必須項目が欠ける）ときも、環境変数と .env.local の値で消す
        self.env.write_text(ENV.replace("EMBEDDING_DIMENSIONS=1536\n", ""), encoding="utf-8")
        config.get_settings.cache_clear()
        self.check(RuntimeError(f"fail {OAI} {SRC}"), 1)
        os.environ["AZURE_OPENAI_API_KEY"] = "ENV-ONLY-KEY-9999"
        self.env.unlink()
        config.get_settings.cache_clear()

        def main():
            raise RuntimeError("fail ENV-ONLY-KEY-9999")
        _, text = run_capture(main)
        self.assertNotIn("ENV-ONLY-KEY-9999", text)


if __name__ == "__main__":
    unittest.main()
