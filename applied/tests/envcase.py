"""試験用の設定ファイル（.env.local の代わり）。本物の .env.local は読まない。

値は、公開前の検査（check_public）が「キーらしい文字列」と見ないように、20 文字より短い作り物にしてある。
使い方：EnvCase を継承すると、setUp で一時の .env.local を作り、環境変数 WORKSHOP_ENV_FILE をそこへ向ける。
既定は構築する人の設定（BUILDER。管理者キーと Storage つき）。メンバーの設定は self.write_env(MEMBER)。
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ENV = """AZURE_SEARCH_ENDPOINT=https://a.search.windows.net
AZURE_SEARCH_API_KEY=FAKE-SRCH-d4e5f6
AZURE_OPENAI_ENDPOINT=https://b.azure.com
AZURE_OPENAI_API_KEY=FAKE-OAI-a1b2c3
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=e
AZURE_OPENAI_CHAT_DEPLOYMENT=c
EMBEDDING_DIMENSIONS=1536
"""
STORAGE = "AZURE_STORAGE_CONNECTION_STRING=AccountName=x;AccountKey=FAKE-ACCT-g7h8\nAZURE_STORAGE_CONTAINER=hr-docs\n"
BUILDER = ENV + "AZURE_SEARCH_KEY_ROLE=admin\nAZURE_OPENAI_CHAT_MODEL=gpt-5-mini\nAZURE_OPENAI_REASONING_EFFORT=low\n" + STORAGE
MEMBER = ENV + "AZURE_SEARCH_KEY_ROLE=query\nAZURE_OPENAI_CHAT_MODEL=gpt-5-mini\nAZURE_OPENAI_REASONING_EFFORT=low\n"
BUILDER_MESSAGE = "この手順は構築する人の設定（--role builder）で実行します"


class EnvCase(unittest.TestCase):
    """一時の .env.local（既定は BUILDER）を使うテスト。"""
    ENV_TEXT = BUILDER

    def setUp(self):
        from lib import config

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / ".env.local").write_text(self.ENV_TEXT, encoding="utf-8")
        self.p = mock.patch.dict(os.environ, {"WORKSHOP_ENV_FILE": str(self.dir / ".env.local")})
        self.p.start()
        config.get_settings.cache_clear()

    def tearDown(self):
        from lib import config

        self.p.stop()
        config.get_settings.cache_clear()
        self.tmp.cleanup()

    def write_env(self, text):
        from lib import config

        (self.dir / ".env.local").write_text(text, encoding="utf-8")
        config.get_settings.cache_clear()
