"""登録の失敗メッセージ（lib/indexing.py）が、応答の文に混じったキーを画面に出さないことを確かめる（通信なし）。

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lib  # noqa: E402,F401
from lib import config, indexing  # noqa: E402
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
"""


class FakeClient:
    """一部の文書だけ失敗し、失敗の理由にキーが混じる応答を返す。"""

    def _send(self, documents):
        return [SimpleNamespace(succeeded=(i != 1), key=d["id"],
                                error_message=None if i != 1 else f"Unauthorized: api-key {SRC} and Bearer {OAI} were rejected")
                for i, d in enumerate(documents)]

    upload_documents = merge_or_upload_documents = lambda self, documents: self._send(documents)


class IndexingRedactTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = Path(self.tmp.name) / ".env.local"
        env.write_text(ENV, encoding="utf-8")
        self.p = mock.patch.dict(os.environ, {"WORKSHOP_ENV_FILE": str(env)})
        self.p.start()
        config.get_settings.cache_clear()

    def tearDown(self):
        self.p.stop()
        config.get_settings.cache_clear()
        self.tmp.cleanup()

    def run_upload(self, mode):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SetupError) as cm:
            indexing.upload(FakeClient(), [{"id": "a"}, {"id": "b"}, {"id": "c"}], mode=mode)
        return out.getvalue(), str(cm.exception)

    def test_individual_failure_message_has_no_key(self):
        for mode in ("upload", "merge"):
            out, err = self.run_upload(mode)
            self.assertNotIn(OAI, out + err)
            self.assertNotIn(SRC, out + err)
            self.assertIn("失敗: b: Unauthorized", out)      # 理由そのものは読める
            self.assertIn("***", out)
            self.assertIn("1 件の登録に失敗", err)

    def test_keys_are_masked_even_when_settings_cannot_be_read(self):
        (Path(self.tmp.name) / ".env.local").write_text(ENV.replace("EMBEDDING_DIMENSIONS=1536\n", ""), encoding="utf-8")
        config.get_settings.cache_clear()
        out, err = self.run_upload("upload")
        self.assertNotIn(OAI, out + err)
        self.assertNotIn(SRC, out + err)


if __name__ == "__main__":
    unittest.main()
