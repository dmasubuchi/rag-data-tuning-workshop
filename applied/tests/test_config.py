"""設定（.env.local）、Storage の扱い、メンバーのキー（検索だけ）の扱い、固定の名前を確かめる（通信なし）。applied フォルダで
    python -m unittest discover -s tests
"""
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
from lib import agentic, clients, config, pipeline  # noqa: E402
from lib.config import SetupError  # noqa: E402
from envcase import BUILDER, BUILDER_MESSAGE, ENV, MEMBER, STORAGE, EnvCase  # noqa: E402

# 以前の設定ファイルの名前。この試験自身が禁止語の検査（test_layout）に当たらないように、2つに分けて書く
OLD_ENV_NAME = "workshop" + ".env"


class Base(EnvCase):
    ENV_TEXT = ENV          # 必須の7項目だけ（役割も Storage もない）


class EnvLocalTest(Base):
    def test_env_local_is_the_only_source(self):
        """設定は Repo 直下の .env.local だけから読む。以前の名前のファイルが隣にあっても読まない。"""
        (self.dir / OLD_ENV_NAME).write_text(ENV.replace("a.search", "old.search"), encoding="utf-8")
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
        self.assertEqual(config.ENV_LOCAL, config.APPLIED_DIR.parent / ".env.local")
        self.assertEqual(config.REPO_DIR, config.APPLIED_DIR.parent)
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
            "AZURE_OPENAI_CHAT_MODEL": "stray-model",
            "EMBEDDING_DIMENSIONS": "3072",
            "AZURE_OPENAI_REASONING_EFFORT": "high",
            "AZURE_SEARCH_KEY_ROLE": "query",
            "AZURE_STORAGE_CONTAINER": "stray-container",
        }
        with mock.patch.dict(os.environ, stray):
            config.get_settings.cache_clear()
            s = config.get_settings()
            self.assertEqual(s.search_endpoint, "https://a.search.windows.net")
            self.assertEqual(s.search_key, "FAKE-SRCH-d4e5f6")
            self.assertEqual(s.openai_endpoint, "https://b.azure.com")
            self.assertEqual((s.embedding_deployment, s.chat_deployment, s.dimensions), ("e", "c", 1536))
            self.assertEqual(s.chat_model, "gpt-5-mini")        # ファイルにない項目は、端末の値で埋めない
            self.assertEqual((s.reasoning_effort, s.key_role, s.storage_container), ("", "", ""))
            self.assertEqual(os.environ["AZURE_SEARCH_API_KEY"], "STRAY-SRCH-0000")     # 環境変数には触らない

    def test_keys_are_not_in_repr(self):
        self.write_env(BUILDER)
        s = config.get_settings(need_storage=True)
        for text in (repr(s), str(s), f"{s!r}", repr([s])):
            for secret in ("FAKE-SRCH-d4e5f6", "FAKE-OAI-a1b2c3", "FAKE-ACCT-g7h8"):
                self.assertNotIn(secret, text)
        self.assertIn("https://a.search.windows.net", repr(s))
        self.assertEqual(s.search_key, "FAKE-SRCH-d4e5f6")     # 値そのものは使える
        self.assertEqual(s.storage_container, "hr-docs")

    def test_bad_dimensions_stop(self):
        self.write_env(ENV.replace("EMBEDDING_DIMENSIONS=1536", "EMBEDDING_DIMENSIONS=abc"))
        with self.assertRaises(SetupError) as cm:
            config.get_settings()
        self.assertIn("EMBEDDING_DIMENSIONS", str(cm.exception))


class StorageTest(Base):
    def test_member_settings_without_storage_work_for_read_topics(self):
        """メンバーの設定（Storage の項目なし）で、14〜16・18〜20 のスクリプトが使う get_settings() は通る。"""
        self.write_env(MEMBER)
        s = config.get_settings()
        self.assertEqual((s.key_role, s.storage_connection_string, s.storage_container), ("query", "", ""))
        self.assertEqual(config.get_settings(need_storage=False), s)
        self.assertEqual(s.chat_deployment, "c")
        agentic.knowledge_base_definition()         # 知識ベースの定義（19 が使う）も、Storage なしで組み立てられる
        pipeline.skillset()
        pipeline.index()

    def test_storage_required_only_for_ingest(self):
        """Storage の2項目は、Storage を使う段（build_hr_index、17、container_client）でだけ必須。"""
        self.write_env(MEMBER)
        with self.assertRaises(SetupError) as cm:
            config.get_settings(need_storage=True)
        msg = str(cm.exception)
        self.assertIn("AZURE_STORAGE_CONNECTION_STRING", msg)
        self.assertIn("AZURE_STORAGE_CONTAINER", msg)
        self.assertIn("--role builder", msg)
        # Storage を使うもの：データソースの定義、Storage の接続（メンバーの設定では、管理者でないので、その前に止まる）
        with self.assertRaises(SetupError):
            pipeline.datasource()
        with self.assertRaises(SetupError):
            clients.container_client()
        # 片方だけでも止まる
        self.write_env(ENV + "AZURE_STORAGE_CONTAINER=hr-docs\n")
        with self.assertRaises(SetupError) as cm:
            config.get_settings(need_storage=True)
        self.assertIn("AZURE_STORAGE_CONNECTION_STRING", str(cm.exception))
        self.assertNotIn("AZURE_STORAGE_CONTAINER,", str(cm.exception))
        # builder の設定なら通る
        self.write_env(BUILDER)
        s = config.get_settings(need_storage=True)
        self.assertEqual((s.storage_container, s.key_role), ("hr-docs", "admin"))
        ds = pipeline.datasource()
        self.assertEqual((ds.name, ds.container.name), ("hr-docs-ds", "hr-docs"))

    def test_cache_is_per_argument(self):
        self.write_env(BUILDER)
        a, b = config.get_settings(), config.get_settings(need_storage=True)
        self.assertIs(a, config.get_settings())
        self.assertIs(b, config.get_settings(need_storage=True))

    def test_storage_placeholder_is_refused(self):
        self.write_env(ENV + "AZURE_STORAGE_CONNECTION_STRING=<接続文字列>\nAZURE_STORAGE_CONTAINER=hr-docs\n")
        with self.assertRaises(SetupError) as cm:
            config.get_settings(need_storage=True)
        self.assertIn("AZURE_STORAGE_CONNECTION_STRING", str(cm.exception))


class ChatModelTest(Base):
    def test_kb_model_name_from_env(self):
        """知識ベースの modelName は AZURE_OPENAI_CHAT_MODEL から、deploymentId はデプロイ名から読む。"""
        self.write_env(ENV.replace("AZURE_OPENAI_CHAT_DEPLOYMENT=c", "AZURE_OPENAI_CHAT_DEPLOYMENT=my-deploy")
                       + "AZURE_OPENAI_CHAT_MODEL=some-model-name\n")
        p = agentic.knowledge_base_definition()["models"][0]["azureOpenAIParameters"]
        self.assertEqual((p["modelName"], p["deploymentId"]), ("some-model-name", "my-deploy"))
        self.assertEqual(config.get_settings().chat_model, "some-model-name")
        # 書いてなければ、既定の gpt-5-mini
        self.write_env(ENV)
        p = agentic.knowledge_base_definition()["models"][0]["azureOpenAIParameters"]
        self.assertEqual((p["modelName"], p["deploymentId"]), ("gpt-5-mini", "c"))
        self.assertFalse(hasattr(agentic, "CHAT_MODEL_NAME"))       # 固定のモデル名の定数は、もうない

    def test_kb_definition_has_no_fixed_model_text(self):
        text = (Path(agentic.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("gpt-5" + ".4", text)


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
        self.assertIn(BUILDER_MESSAGE, msg)
        self.assertIn("python tools/team.py env --role builder", msg)
        self.assertNotIn("403", msg)


class NamesTest(Base):
    def test_names_are_fixed(self):
        """チームごとに自分の AI Search を持つので、名前は固定。組や共有の名前はない。"""
        self.assertEqual((config.HR_INDEX, config.HR_DATASOURCE, config.HR_SKILLSET, config.HR_INDEXER),
                         ("hr-docs", "hr-docs-ds", "hr-docs-ss", "hr-docs-ixr"))
        self.assertEqual((agentic.KNOWLEDGE_SOURCE, agentic.KNOWLEDGE_BASE), ("hr-docs-ks", "hr-docs-kb"))
        for removed in ("SHARED_INDEX", "SHARED_DATASOURCE", "SHARED_SKILLSET", "SHARED_INDEXER", "SHARED_PREFIX", "SHARED_FOLDER",
                        "refuse_unshared", "get_group", "check_group", "group_file_path", "GROUP_FILE", "WORKSHOP_ENV"):
            self.assertFalse(hasattr(config, removed), removed)

    def test_names_do_not_depend_on_environment(self):
        with mock.patch.dict(os.environ, {"WORKSHOP_GROUP": "g1"}):
            self.assertEqual(config.HR_INDEX, "hr-docs")
            self.assertEqual(pipeline.index().name, "hr-docs")

    def test_names_follow_ai_search_naming_rules(self):
        rule = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
        for name in (config.HR_INDEX, config.HR_DATASOURCE, config.HR_SKILLSET, config.HR_INDEXER,
                     agentic.KNOWLEDGE_SOURCE, agentic.KNOWLEDGE_BASE):
            self.assertTrue(rule.fullmatch(name) and len(name) <= 128, name)

    def test_definitions_use_the_fixed_names(self):
        self.write_env(BUILDER)
        ds, ix, ss, idxr = pipeline.datasource(), pipeline.index(), pipeline.skillset(), pipeline.indexer()
        self.assertEqual((ds.name, ix.name, ss.name, idxr.name), ("hr-docs-ds", "hr-docs", "hr-docs-ss", "hr-docs-ixr"))
        self.assertEqual((idxr.data_source_name, idxr.target_index_name, idxr.skillset_name), ("hr-docs-ds", "hr-docs", "hr-docs-ss"))
        self.assertEqual(ss.index_projection.selectors[0].target_index_name, "hr-docs")
        self.assertEqual(agentic.knowledge_source_definition()["searchIndexParameters"]["searchIndexName"], "hr-docs")


class MemberKeyTest(Base):
    """メンバーの設定（検索だけのキー）。作る・変える・動かす・文書を直すは、不透明な 403 の前に、日本語で止まる。"""

    def setUp(self):
        super().setUp()
        self.write_env(MEMBER)

    def test_member_key_refuses_admin_steps(self):
        real = mock.MagicMock()
        for name in ("create_or_update_index", "delete_index", "get_index", "list_index_names", "get_service_statistics"):
            with self.assertRaises(SetupError, msg=name) as cm:
                getattr(clients._AdminOnly(real), name)("x")
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
            self.assertNotIn("403", str(cm.exception))
        # インデクサー・データソース・スキルセットも、全部（動かす・読む・作る・消す）
        for name in ("run_indexer", "get_indexer_status", "create_or_update_indexer", "create_or_update_skillset",
                     "create_or_update_data_source_connection", "delete_indexer", "get_indexers"):
            with self.assertRaises(SetupError, msg=name) as cm:
                getattr(clients._AdminOnly(real), name)("x")
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        # 文書の登録・削除・付け直しは止まり、検索と件数は通る
        guarded = clients._AdminOnly(real, blocked=clients._DOCUMENT_WRITES)
        for name in ("upload_documents", "merge_documents", "merge_or_upload_documents", "delete_documents", "index_documents"):
            with self.assertRaises(SetupError, msg=name):
                getattr(guarded, name)(documents=[])
        guarded.search(search_text="*")
        guarded.get_document_count()
        self.assertEqual([c[0] for c in real.method_calls], ["search", "get_document_count"])

    def test_clients_from_the_real_factories_are_guarded(self):
        """本物のクライアントの作り口（lib/clients.py）の下でも、書く操作は、通信の前に止まる。"""
        ic, rc, sc = clients.index_client(), clients.indexer_client(), clients.search_client(config.HR_INDEX)
        for call in (lambda: ic.list_index_names(), lambda: ic.delete_index("hr-docs"),
                     lambda: rc.run_indexer("hr-docs-ixr"), lambda: rc.get_indexer_status("hr-docs-ixr"),
                     lambda: sc.upload_documents(documents=[]), lambda: sc.merge_documents(documents=[]),
                     lambda: sc.delete_documents(documents=[])):
            with self.assertRaises(SetupError) as cm:
                call()
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))

    def test_storage_is_not_reachable_for_member(self):
        with self.assertRaises(SetupError) as cm:
            clients.container_client()
        self.assertIn(BUILDER_MESSAGE, str(cm.exception))

    def test_rest_writes_are_refused_but_retrieve_and_reads_are_not(self):
        """知識ソース・知識ベースを作る・消す（PUT・DELETE）は止まる。retrieve（POST）と読み取り（GET）は、通信まで進む。"""
        for method in ("PUT", "DELETE"):
            with self.assertRaises(SetupError) as cm:
                agentic.call(method, "/knowledgebases/hr-docs-kb", {})
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        response = mock.Mock(status_code=200, content=b"{}", headers={})
        response.json.return_value = {}
        with mock.patch("requests.request", return_value=response) as req:
            agentic.call("POST", "/knowledgebases/hr-docs-kb/retrieve", {})
            agentic.call("GET", "/knowledgebases/hr-docs-kb")
        self.assertEqual([c.args[0] for c in req.call_args_list], ["POST", "GET"])

    def test_require_knowledge_base_does_not_stop_member_on_403(self):
        """検索だけのキーは、知識ベースの定義を読めないかもしれない（403）。そのときは確かめずに進む（retrieve が答える）。"""
        forbidden = agentic.SearchApiError("forbidden", 403)
        with mock.patch.object(agentic, "call", side_effect=forbidden):
            agentic.require_knowledge_base()
        with mock.patch.object(agentic, "call", return_value=None):         # 読めて、なかったときは、構築する人への案内で止まる
            with self.assertRaises(SetupError) as cm:
                agentic.require_knowledge_base()
        self.assertIn("構築する人", str(cm.exception))
        self.write_env(BUILDER)                                             # 構築する人の 403 は、そのまま出す
        with mock.patch.object(agentic, "call", side_effect=forbidden):
            with self.assertRaises(agentic.SearchApiError):
                agentic.require_knowledge_base()

    def test_builder_tools_stop_before_any_azure_call(self):
        sys.path.insert(0, str(HERE.parent / "tools"))
        import importlib

        for name in ("build_hr_index", "build_hr_kb"):
            mod = importlib.import_module(name)
            with mock.patch.object(sys, "argv", [name]), mock.patch.object(clients, "index_client", side_effect=AssertionError("Azure に触った")), \
                    mock.patch.object(clients, "indexer_client", side_effect=AssertionError("Azure に触った")), \
                    mock.patch.object(clients, "container_client", side_effect=AssertionError("Azure に触った")), \
                    mock.patch("requests.request", side_effect=AssertionError("Azure に触った")):
                with self.assertRaises(SetupError, msg=name) as cm:
                    mod.main()
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))

    def test_403_explanation_for_member(self):
        err = Exception("forbidden")
        err.status_code = 403
        text = "\n".join(lib.errors.explain(err))
        self.assertIn("検索だけのキー", text)
        self.assertIn(BUILDER_MESSAGE, text)
        self.write_env(BUILDER)
        self.assertNotIn("検索だけのキー", "\n".join(lib.errors.explain(err)))


if __name__ == "__main__":
    unittest.main()
