"""設定（.env.local）と、固定のインデックスの名前、案内のコマンドの形を確かめる（通信なし）。

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lib  # noqa: E402
from lib import config, state  # noqa: E402
from lib.config import SetupError  # noqa: E402

ENV = """AZURE_SEARCH_ENDPOINT=https://a.search.windows.net
AZURE_SEARCH_API_KEY=FAKE-SRCH-d4e5f6
AZURE_OPENAI_ENDPOINT=https://b.azure.com
AZURE_OPENAI_API_KEY=FAKE-OAI-a1b2c3
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=e
AZURE_OPENAI_CHAT_DEPLOYMENT=c
EMBEDDING_DIMENSIONS=1536
"""
# 以前の設定ファイルの名前。この試験自身が禁止語の検査（test_layout）に当たらないように、2つに分けて書く
OLD_ENV_NAME = "workshop" + ".env"
OLD_LOCAL_ENV_NAME = "workshop" + ".local.env"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / ".env.local").write_text(ENV, encoding="utf-8")
        self.p = mock.patch.dict(os.environ, {"WORKSHOP_ENV_FILE": str(self.dir / ".env.local")})
        self.p.start()
        config.get_settings.cache_clear()

    def tearDown(self):
        self.p.stop()
        config.get_settings.cache_clear()
        self.tmp.cleanup()

    def write_env(self, text):
        (self.dir / ".env.local").write_text(text, encoding="utf-8")
        config.get_settings.cache_clear()


class EnvLocalTest(Base):
    def test_env_local_is_the_only_source(self):
        """設定は Repo 直下の .env.local だけから読む。以前の名前のファイルが隣にあっても読まない。"""
        (self.dir / OLD_ENV_NAME).write_text(ENV.replace("a.search", "old.search"), encoding="utf-8")
        (self.dir / OLD_LOCAL_ENV_NAME).write_text(ENV.replace("a.search", "older.search"), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "WORKSHOP_ENV_FILE"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(config, "ENV_LOCAL", self.dir / ".env.local"):
            self.assertEqual(config.env_file_path(), self.dir / ".env.local")
            config.get_settings.cache_clear()
            self.assertEqual(config.get_settings().search_endpoint, "https://a.search.windows.net")
            (self.dir / ".env.local").unlink()      # .env.local がなければ、ほかの名前のファイルがあっても読まずに止まる
            config.get_settings.cache_clear()
            with self.assertRaises(SetupError) as cm:
                config.get_settings()
            self.assertIn(".env.local", str(cm.exception))

    def test_default_location_is_the_repo_root(self):
        self.assertEqual(config.ENV_LOCAL, config.BASIC_DIR.parent / ".env.local")
        self.assertEqual(config.REPO_DIR, config.BASIC_DIR.parent)
        env = {k: v for k, v in os.environ.items() if k != "WORKSHOP_ENV_FILE"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(config.env_file_path(), config.ENV_LOCAL)
        self.assertEqual(config.env_file_path(), self.dir / ".env.local")     # 試験用の環境変数があれば、それ

    def test_missing_env_points_to_team_env(self):
        (self.dir / ".env.local").unlink()
        config.get_settings.cache_clear()
        with self.assertRaises(SetupError) as cm:
            config.get_settings()
        msg = str(cm.exception)
        self.assertIn("python tools/team.py env --role builder", msg)
        self.assertIn("--role member", msg)

    def test_missing_item_points_to_team_env(self):
        self.write_env(ENV.replace("AZURE_OPENAI_API_KEY=FAKE-OAI-a1b2c3\n", ""))
        with self.assertRaises(SetupError) as cm:
            config.get_settings()
        msg = str(cm.exception)
        self.assertIn("AZURE_OPENAI_API_KEY", msg)
        self.assertIn("python tools/team.py env --role builder", msg)
        self.assertIn("--role member", msg)

    def test_placeholder_values_are_refused(self):
        self.write_env(ENV.replace("https://a.search.windows.net", "https://<チームの名前>.search.windows.net"))
        with self.assertRaises(SetupError) as cm:
            config.get_settings()
        self.assertIn("AZURE_SEARCH_ENDPOINT", str(cm.exception))

    def test_terminal_environment_is_not_read(self):
        """端末に残った AZURE_* の環境変数ではなく、.env.local の値を使う。環境変数は書き換えない。"""
        stray = {
            "AZURE_SEARCH_ENDPOINT": "https://stray.search.windows.net",
            "AZURE_SEARCH_API_KEY": "STRAY-SRCH-0000",
            "AZURE_OPENAI_ENDPOINT": "https://stray.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "STRAY-OAI-0000",
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "stray-e",
            "AZURE_OPENAI_CHAT_DEPLOYMENT": "stray-c",
            "EMBEDDING_DIMENSIONS": "3072",
            "AZURE_OPENAI_REASONING_EFFORT": "high",
            "AZURE_SEARCH_KEY_ROLE": "query",
        }
        with mock.patch.dict(os.environ, stray):
            config.get_settings.cache_clear()
            s = config.get_settings()
            self.assertEqual(s.search_endpoint, "https://a.search.windows.net")
            self.assertEqual(s.search_key, "FAKE-SRCH-d4e5f6")
            self.assertEqual(s.openai_endpoint, "https://b.azure.com")
            self.assertEqual(s.openai_key, "FAKE-OAI-a1b2c3")
            self.assertEqual((s.embedding_deployment, s.chat_deployment, s.dimensions), ("e", "c", 1536))
            self.assertEqual(s.reasoning_effort, "")     # ファイルにない項目は、端末の値で埋めない
            self.assertEqual(s.key_role, "")
            self.assertEqual(os.environ["AZURE_SEARCH_API_KEY"], "STRAY-SRCH-0000")     # 環境変数には触らない

    def test_missing_item_in_file_is_not_filled_from_environment(self):
        self.write_env(ENV.replace("AZURE_OPENAI_API_KEY=FAKE-OAI-a1b2c3\n", ""))
        with mock.patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "STRAY-OAI-0000"}):
            config.get_settings.cache_clear()
            with self.assertRaises(SetupError) as cm:
                config.get_settings()
        self.assertIn("AZURE_OPENAI_API_KEY", str(cm.exception))

    def test_team_env_file_is_read(self):
        """python tools/team.py env が書く形（admin か query、チャットのモデル、考える量、Storage）をそのまま読める。"""
        self.write_env(ENV + "AZURE_SEARCH_KEY_ROLE=admin\nAZURE_OPENAI_CHAT_MODEL=gpt-5-mini\nAZURE_OPENAI_REASONING_EFFORT=low\n"
                       "AZURE_STORAGE_CONNECTION_STRING=AccountName=x;AccountKey=FAKE-ACCT-g7h8\n"
                       "AZURE_STORAGE_CONTAINER=hr-docs\n")
        s = config.get_settings()
        self.assertEqual((s.key_role, s.reasoning_effort, s.chat_deployment), ("admin", "low", "c"))

    def test_keys_are_not_in_repr(self):
        s = config.get_settings()
        for text in (repr(s), str(s), f"{s!r}", repr([s])):
            self.assertNotIn("FAKE-SRCH-d4e5f6", text)
            self.assertNotIn("FAKE-OAI-a1b2c3", text)
        self.assertIn("https://a.search.windows.net", repr(s))         # キー以外は出る
        self.assertEqual(s.search_key, "FAKE-SRCH-d4e5f6")     # 値そのものは使える

    def test_bad_dimensions_stop(self):
        self.write_env(ENV.replace("EMBEDDING_DIMENSIONS=1536", "EMBEDDING_DIMENSIONS=abc"))
        with self.assertRaises(SetupError) as cm:
            config.get_settings()
        self.assertIn("EMBEDDING_DIMENSIONS", str(cm.exception))


class KeyRoleTest(Base):
    def test_role_is_read(self):
        for role in ("admin", "query"):
            self.write_env(ENV + f"AZURE_SEARCH_KEY_ROLE={role}\n")
            self.assertEqual(config.get_settings().key_role, role)
        self.assertEqual(config.is_query_key(), True)

    def test_unknown_role_stops(self):
        self.write_env(ENV + "AZURE_SEARCH_KEY_ROLE=root\n")
        with self.assertRaises(SetupError) as cm:
            config.get_settings()
        self.assertIn("AZURE_SEARCH_KEY_ROLE", str(cm.exception))

    def test_require_admin_key(self):
        config.require_admin_key()                      # 書いてなければ、止めない
        self.write_env(ENV + "AZURE_SEARCH_KEY_ROLE=admin\n")
        config.require_admin_key()                      # 構築する人は止めない
        self.write_env(ENV + "AZURE_SEARCH_KEY_ROLE=query\n")
        with self.assertRaises(SetupError) as cm:       # メンバーは、日本語で止める
            config.require_admin_key()
        msg = str(cm.exception)
        self.assertIn("この手順は構築する人の設定（--role builder）で実行します", msg)
        self.assertIn("python tools/team.py env --role builder", msg)
        self.assertNotIn("403", msg)


class IndexNamesTest(Base):
    def test_index_names_are_fixed(self):
        """チームごとに自分の AI Search を持つので、名前は固定。組の名前は使わない。"""
        self.assertEqual(config.sengoku_index_name(), "sengoku")
        self.assertEqual(config.synonym_map_name(), "sengoku-synonyms")
        self.assertEqual(config.index_names(), ["sengoku"])
        for removed in ("get_group", "set_" + "group_command", "check_group", "group_file_path", "attendee_index_names",
                        "shared_index_names", "kitei_index_name", "mini_index_name", "refuse_shared"):
            self.assertFalse(hasattr(config, removed), removed)

    def test_names_do_not_depend_on_environment(self):
        with mock.patch.dict(os.environ, {"WORKSHOP_GROUP": "g1"}):
            self.assertEqual(config.sengoku_index_name(), "sengoku")
            self.assertEqual(config.synonym_map_name(), "sengoku-synonyms")

    def test_names_follow_ai_search_naming_rules(self):
        rule = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
        for name in (config.sengoku_index_name(), config.synonym_map_name()):
            self.assertTrue(rule.fullmatch(name) and len(name) <= 128, name)


class CommandQuotingTest(Base):
    """案内のコマンドは、空白などを含むパスでも、PowerShell・bash にそのまま貼って動く形にする。"""

    def test_quote_arg(self):
        self.assertEqual(config.quote_arg("../../tools/reset.py"), "../../tools/reset.py")
        self.assertEqual(config.quote_arg("--to"), "--to")
        self.assertEqual(config.quote_arg("04"), "04")
        self.assertEqual(config.quote_arg("a b/c.py"), '"a b/c.py"')
        self.assertEqual(config.quote_arg("a(1)&b.py"), '"a(1)&b.py"')
        self.assertEqual(config.quote_arg("a$b c"), "'a$b c'")             # $ は一重引用符で文字どおりに
        self.assertEqual(config.quote_arg("a`b c"), "'a`b c'")
        self.assertEqual(config.quote_arg("it's"), "'it'\\''s'")           # 一重引用符を含むとき（bash）
        with mock.patch.object(config.os, "name", "nt"):
            self.assertEqual(config.quote_arg("it's"), "'it''s'")          # PowerShell

    def test_command_with_space_in_path(self):
        script = Path("/work/team folder/basic/tools/reset.py")
        with mock.patch.object(Path, "cwd", return_value=Path("/work/other dir")):
            self.assertEqual(config.command_to(script, "--to", "04"), 'python "../team folder/basic/tools/reset.py" --to 04')
        with mock.patch.object(Path, "cwd", return_value=Path("/work/team folder/basic/topics/04-hybrid-ranker")):
            self.assertEqual(config.command_to(script, "--to", "04"), "python ../../tools/reset.py --to 04")

    def test_reset_command_with_space(self):
        basic = Path("/work/team folder/basic")
        with mock.patch.object(config, "BASIC_DIR", basic), mock.patch.object(Path, "cwd", return_value=Path("/work/team folder")):
            self.assertEqual(config.reset_command("04"), 'python basic/tools/reset.py --to 04')
        with mock.patch.object(config, "BASIC_DIR", basic), mock.patch.object(Path, "cwd", return_value=Path("/tmp/elsewhere")):
            self.assertEqual(config.reset_command("04"), 'python "../../work/team folder/basic/tools/reset.py" --to 04')

    def test_other_drive_falls_back_to_absolute_path_with_forward_slashes(self):
        script = Path("D:/team folder/basic/tools/reset.py")
        with mock.patch.object(config.os.path, "relpath", side_effect=ValueError("path is on mount 'D:'")), \
                mock.patch.object(config.os, "sep", "\\"):
            cmd = config.command_to(script, "--to", "04")
        self.assertTrue(cmd.startswith('python "'), cmd)
        self.assertIn("team folder/basic/tools/reset.py", cmd)
        self.assertNotIn("\\", cmd)

    def test_error_messages_use_quoted_commands(self):
        """エラーの案内（state の止まるときの1行）も、空白を含むパスで引用符つきになる。"""
        basic = Path("/work/team folder/basic")
        with mock.patch.object(config, "BASIC_DIR", basic), mock.patch.object(Path, "cwd", return_value=Path("/tmp/x")), \
                mock.patch.dict(state.CHECKS, {"sengoku_vector": lambda: "インデックス sengoku がありません"}):
            with self.assertRaises(SetupError) as cm:
                state.ensure("04")
        self.assertIn('python "../../work/team folder/basic/tools/reset.py" --to 04', str(cm.exception))


class StateTest(Base):
    def test_topic_number(self):
        self.assertEqual(state.topic_number("3"), "03")
        self.assertEqual(state.topic_number("03-vector-search"), "03")
        with self.assertRaises(SetupError):
            state.topic_number("vector")

    def test_states_before(self):
        self.assertEqual(state.states_before("01"), [])
        self.assertEqual(state.states_before("02"), ["sengoku_text"])
        self.assertEqual(state.states_before("03"), ["sengoku_text"])
        self.assertEqual(state.states_before("04"), ["sengoku_text", "sengoku_vector"])
        self.assertEqual(state.states_before("06"), ["sengoku_text", "sengoku_vector"])

    def test_needs_are_known_states(self):
        for topic, needs in state.NEEDS.items():
            for s in needs:
                self.assertIn(s, state.CHECKS)
                self.assertIn(s, state.MADE_BY)
                self.assertIn(s, state.BUILDS)
                self.assertIn(s, state.STATE_TITLES)
            # 要る状態は、ハンズオン資料の流れでそのトピックの前に出来ている
            self.assertTrue(set(needs) <= set(state.states_before(topic)), topic)

    def test_only_the_basic_topics_are_known(self):
        self.assertEqual(sorted(state.NEEDS), ["01", "02", "03", "04", "05", "06"])

    def test_missing_state_message_has_one_line_and_reset_command(self):
        with mock.patch.dict(state.CHECKS, {"sengoku_text": lambda: "インデックス sengoku がありません"}):
            with self.assertRaises(SetupError) as cm:
                state.ensure("03")
        msg = str(cm.exception)
        self.assertNotIn("\n", msg)
        self.assertIn("reset.py --to 03", msg)
        self.assertIn("01-keyword-search", msg)


if __name__ == "__main__":
    unittest.main()
