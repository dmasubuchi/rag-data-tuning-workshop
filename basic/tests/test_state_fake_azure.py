"""状態の確認と作り直し（lib/state.py）、reset、メンバー用のキー（検索だけ）の扱いを、呼び出し元から確かめる。
AI Search は偽物（tests/fake_azure.py）で、通信しない。Azure OpenAI は呼ばない（同梱の埋め込み済みファイルを使う）。

  ・武将の部分登録（1人だけ欠ける、ベクトルが一部だけない）で ensure("04") が止まる
  ・作り直しの順序：武将のインデックスを消す → 武将の文字 → 武将のベクトル
  ・消すのは武将のインデックス sengoku だけ（同じ AI Search の、ほかの名前は残る）
  ・--dry-run は何も変えない
  ・メンバー用のキー（検索だけ）では、作る・変える・消す・登録するが、AI Search に届く前に日本語で止まる。検索と状態の確認はできる

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import importlib.util
import io
import os
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib  # noqa: E402,F401
from lib import clients, config, state, worklog  # noqa: E402
from lib.config import SetupError  # noqa: E402
from fake_azure import FakeService, fake_search, have_azure  # noqa: E402

BASIC = Path(__file__).resolve().parent.parent
ENV = """AZURE_SEARCH_ENDPOINT=https://a.search.windows.net
AZURE_SEARCH_API_KEY=FAKE-SRCH-d4e5f6
AZURE_SEARCH_KEY_ROLE={role}
AZURE_OPENAI_ENDPOINT=https://b.azure.com
AZURE_OPENAI_API_KEY=FAKE-OAI-a1b2c3
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=e
AZURE_OPENAI_CHAT_DEPLOYMENT=c
EMBEDDING_DIMENSIONS=1536
"""
BUILDER_MESSAGE = "この手順は構築する人の設定（--role builder）で実行します"


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def quiet(fn, *args, **kw):
    with redirect_stdout(io.StringIO()) as out:
        result = fn(*args, **kw)
    return result, out.getvalue()


@unittest.skipUnless(have_azure(), "azure-search-documents が入っていないので飛ばす")
class FakeAzureBase(unittest.TestCase):
    ROLE = "admin"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env.local"
        self.p = mock.patch.dict(os.environ, {"WORKSHOP_ENV_FILE": str(self.env)})
        self.p.start()
        self.set_role(self.ROLE)
        self.work = tempfile.TemporaryDirectory()
        self.p_work = mock.patch.object(worklog, "WORK_DIR", Path(self.work.name))
        self.p_work.start()
        self.svc = FakeService()
        self.fake = fake_search(self.svc)
        self.fake.__enter__()
        # 埋め込みは同梱のファイルから。Azure OpenAI に聞きにいったら失敗させる
        self.m1 = mock.patch("lib.llm.embedding_model_name", return_value="text-embedding-3-small")
        self.m2 = mock.patch("lib.llm.embed_texts", side_effect=AssertionError("Azure OpenAI は呼ばない"))
        self.m1.start()
        self.m2.start()

    def tearDown(self):
        self.m2.stop()
        self.m1.stop()
        self.fake.__exit__(None, None, None)
        self.p_work.stop()
        self.work.cleanup()
        self.p.stop()
        config.get_settings.cache_clear()
        self.tmp.cleanup()

    def set_role(self, role):
        """.env.local の代わりのファイルを、構築する人（admin）かメンバー（query）の設定にする。"""
        self.env.write_text(ENV.format(role=role), encoding="utf-8")
        config.get_settings.cache_clear()
        clients.index_client.cache_clear()

    def preload_others(self):
        """前から入っている、武将以外のインデックス（同じ AI Search の、ほかの用途のもの）。"""
        for name in ("other-index", "hr-docs", "hr-docs-ds"):
            self.svc.add_index(name, {"x": {"id": "x"}})

    def build_all(self):
        quiet(state.ensure, "06", rebuild=True)
        self.svc.log.clear()


class PartialStateTest(FakeAzureBase):
    def test_full_state_passes(self):
        quiet(state.ensure, "06", rebuild=True)
        for topic in ("02", "03", "04", "05", "06"):
            self.assertEqual(state.problems(topic), [], topic)
            state.ensure(topic)

    def test_no_index_stops_with_reset_command(self):
        with self.assertRaises(SetupError) as cm:
            state.ensure("03")
        msg = str(cm.exception)
        self.assertIn("インデックス sengoku がありません", msg)
        self.assertIn("reset.py --to 03", msg)
        self.assertNotIn("\n", msg)

    def test_sengoku_missing_person_or_vector_stops(self):
        self.build_all()
        docs = self.svc.docs["sengoku"]
        victim = next(iter(docs))
        saved = docs.pop(victim)
        with self.assertRaises(SetupError) as cm:
            state.ensure("03")
        self.assertIn("149/150", str(cm.exception))
        docs[victim] = saved
        state.ensure("03")
        docs[victim].pop("profile_vector")
        with self.assertRaises(SetupError) as cm:
            state.ensure("04")
        self.assertIn("149/150", str(cm.exception))


class RebuildTest(FakeAzureBase):
    def test_order_and_scope(self):
        self.preload_others()
        self.svc.add_index("sengoku", {"old": {"id": "old"}})
        before_others = {n: dict(d) for n, d in self.svc.docs.items() if n != "sengoku"}

        quiet(state.ensure, "06", rebuild=True)

        log = self.svc.log
        # 1. 最初の操作は、武将のインデックスの削除だけ
        self.assertEqual(log[:1], [("delete", "sengoku")])
        self.assertEqual([e for e in log if e[0] == "delete"], log[:1], "削除は武将のインデックスだけ")

        def at(event):
            return log.index(event)
        # 2. 武将の文字 → 武将のベクトル
        self.assertLess(at(("create", "sengoku")), at(("upload", "sengoku", 50)))
        self.assertLess(at(("upload", "sengoku", 50)), at(("update", "sengoku")))
        self.assertLess(at(("update", "sengoku")), at(("merge", "sengoku", 50)))
        # 3. ほかのインデックスには、読む以外の操作が1回もない
        self.assertEqual({e[1] for e in log}, {"sengoku"})
        self.assertEqual({n: d for n, d in self.svc.docs.items() if n != "sengoku"}, before_others)
        self.assertEqual(set(self.svc.indexes), {"sengoku", "other-index", "hr-docs", "hr-docs-ds"})
        # 4. できた状態は、確認を通る
        self.assertEqual(state.problems("06"), [])
        self.assertEqual(len(self.svc.docs["sengoku"]), 150)

    def test_stages_by_topic(self):
        quiet(state.ensure, "03", rebuild=True)
        self.assertEqual(set(self.svc.indexes), {"sengoku"})
        self.assertIsNone(self.svc.indexes["sengoku"].vector_search)       # 03 の開始は、文字の項目だけ
        quiet(state.ensure, "04", rebuild=True)
        self.assertIsNotNone(self.svc.indexes["sengoku"].vector_search)    # 04 の開始は、ベクトルまで

    def test_topic_01_start_only_deletes(self):
        self.svc.add_index("sengoku")
        quiet(state.ensure, "01", rebuild=True)
        self.assertEqual(self.svc.log, [("delete", "sengoku")])
        self.assertEqual(set(self.svc.indexes), set())


class ResetToolTest(FakeAzureBase):
    def run_reset(self, *argv):
        mod = load_script(BASIC / "tools" / "reset.py", "reset_tool")
        with mock.patch.object(sys, "argv", ["reset.py", *argv]):
            return quiet(mod.main)

    def test_dry_run_changes_nothing(self):
        self.preload_others()
        self.svc.add_index("sengoku", {"a": {"id": "a"}})
        before = ({n: dict(d) for n, d in self.svc.docs.items()}, set(self.svc.indexes))
        _, out = self.run_reset("--to", "04", "--dry-run")
        self.assertEqual(self.svc.log, [])
        self.assertEqual(({n: dict(d) for n, d in self.svc.docs.items()}, set(self.svc.indexes)), before)
        self.assertIn("何も消さず", out)
        self.assertIn("sengoku：あり", out)

    def test_reset_to_01_deletes_only_sengoku(self):
        self.preload_others()
        self.svc.add_index("sengoku")
        self.run_reset("--to", "01")
        self.assertEqual(self.svc.log, [("delete", "sengoku")])
        self.assertEqual(set(self.svc.indexes), {"other-index", "hr-docs", "hr-docs-ds"})

    def test_reset_accepts_number_and_folder_name(self):
        self.run_reset("--to", "3")
        self.assertEqual(set(self.svc.indexes), {"sengoku"})
        self.svc.log.clear()
        self.run_reset("--to", "03-vector-search")
        self.assertEqual(self.svc.log[0], ("delete", "sengoku"))

    def test_unknown_topic(self):
        for topic in ("99", "09"):          # 基礎編にあるのは 01〜06 だけ
            with self.assertRaises(SetupError):
                self.run_reset("--to", topic)
        self.assertEqual(self.svc.log, [])


class WaitForVectorsTest(FakeAzureBase):
    """embed.py の登録のあと、ベクトルが検索に出てくるまで待つ（lib/sengoku.py の wait_for_vectors）。"""

    def ids(self):
        from lib.data import load_bushou
        return [p["id"] for p in load_bushou()]

    def test_returns_at_once_when_all_vectors_are_searchable(self):
        from lib import sengoku
        from lib.clients import search_client
        self.build_all()
        with mock.patch("time.sleep") as sleep:
            out, text = quiet(sengoku.wait_for_vectors, search_client("sengoku"), self.ids())
        sleep.assert_not_called()
        self.assertEqual(text, "")

    def test_waits_then_stops_with_a_participant_message(self):
        from lib import sengoku
        from lib.clients import search_client
        self.build_all()
        victim = next(iter(self.svc.docs["sengoku"]))
        self.svc.docs["sengoku"][victim].pop("profile_vector")
        with mock.patch("time.sleep") as sleep:
            with self.assertRaises(SetupError) as cm:
                quiet(sengoku.wait_for_vectors, search_client("sengoku"), self.ids(), tries=3)
        self.assertEqual(sleep.call_count, 3)
        self.assertIn("149 件", str(cm.exception))
        self.assertIn("embed.py", str(cm.exception))

    def test_wait_ends_when_the_vectors_appear(self):
        from lib import sengoku
        from lib.clients import search_client
        self.build_all()
        victim = next(iter(self.svc.docs["sengoku"]))
        saved = self.svc.docs["sengoku"][victim].pop("profile_vector")

        def appear(_):
            self.svc.docs["sengoku"][victim]["profile_vector"] = saved
        with mock.patch("time.sleep", side_effect=appear) as sleep:
            _, text = quiet(sengoku.wait_for_vectors, search_client("sengoku"), self.ids())
        self.assertEqual(sleep.call_count, 1)
        self.assertIn("149/150", text)


class QueryKeyTest(FakeAzureBase):
    """メンバーの設定（AZURE_SEARCH_KEY_ROLE=query。検索だけのキー）。

    作る・変える・消す・登録するは、不透明な 403 の前に、日本語で止まる。検索と、状態の確認（文書の検索と件数だけ）はできる。
    """

    def setUp(self):
        super().setUp()
        quiet(state.ensure, "06", rebuild=True)       # 構築する人が作った状態
        self.svc.log.clear()
        self.set_role("query")                        # ここから、メンバーの設定

    def run_topic_script(self, folder, name):
        """トピックのスクリプトを上から実行する（偽の AI Search。止まったときの例外を返す）。"""
        patches = [mock.patch("lib.cells.start", lambda: None), mock.patch("lib.cells.at_exit", lambda f: None),
                   mock.patch.object(sys, "argv", [name])]
        for p in patches:
            p.start()
        error = None
        try:
            with redirect_stdout(io.StringIO()):
                runpy.run_path(str(BASIC / "topics" / folder / name), run_name="__main__")
        except Exception as e:  # noqa: BLE001  止まったときの例外を受け取って調べる
            error = e
        finally:
            for p in reversed(patches):
                p.stop()
        return error

    def test_every_index_client_method_is_refused(self):
        """index_client() は、メンバー用のキーでは、どのメソッドも本物に届く前に止まる（インデックスや辞書の定義は管理者キーだけ）。"""
        real = mock.MagicMock()
        guarded = clients._AdminOnly(real)
        for name in ("create_or_update_index", "create_index", "delete_index", "get_index", "list_index_names", "get_synonym_map",
                     "get_synonym_map_names", "create_or_update_synonym_map", "delete_synonym_map", "get_service_statistics",
                     "analyze_text"):
            with self.assertRaises(SetupError, msg=name) as cm:
                getattr(guarded, name)("x")
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
            self.assertNotIn("403", str(cm.exception))
        self.assertEqual(real.method_calls, [])

    def test_document_writes_are_refused_but_reads_pass(self):
        real = mock.MagicMock()
        guarded = clients._AdminOnly(real, blocked=clients._DOCUMENT_WRITES)
        for name in ("upload_documents", "merge_documents", "merge_or_upload_documents", "delete_documents", "index_documents"):
            with self.assertRaises(SetupError, msg=name) as cm:
                getattr(guarded, name)(documents=[])
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        guarded.search(search_text="*")
        guarded.get_document_count()
        self.assertEqual([c[0] for c in real.method_calls], ["search", "get_document_count"])

    def test_writes_through_the_real_client_path_are_refused(self):
        """偽の AI Search を、本物のクライアントの置き場所（lib/clients.py の包み）の下に置いても、書く操作は届かない。"""
        from azure.search.documents.indexes.models import SearchIndex
        ic, sc = clients.index_client(), clients.search_client("sengoku")
        for call in (lambda: ic.create_or_update_index(SearchIndex(name="sengoku", fields=[])), lambda: ic.delete_index("sengoku"),
                     lambda: ic.get_index("sengoku"), lambda: ic.list_index_names(),
                     lambda: sc.upload_documents(documents=[{"id": "x"}]), lambda: sc.merge_or_upload_documents(documents=[]),
                     lambda: sc.delete_documents(documents=[])):
            with self.assertRaises(SetupError) as cm:
                call()
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        self.assertEqual(self.svc.log, [])
        self.assertEqual(len(self.svc.docs["sengoku"]), 150)

    def test_searching_and_counting_still_work(self):
        sc = clients.search_client("sengoku")
        self.assertEqual(sc.get_document_count(), 150)
        self.assertEqual(len(list(sc.search(search_text="*", top=3))), 3)

    def test_index_exists_does_not_list_indexes(self):
        self.assertTrue(clients.index_exists("sengoku"))
        self.assertFalse(clients.index_exists("nothing-here"))

    def test_state_checks_work_with_documents_only(self):
        for topic in ("02", "03", "04", "05", "06"):
            self.assertEqual(state.problems(topic), [], topic)
            state.ensure(topic)

    def test_missing_state_tells_the_member_to_ask_the_builder(self):
        self.svc.docs["sengoku"].pop(next(iter(self.svc.docs["sengoku"])))
        with self.assertRaises(SetupError) as cm:
            state.ensure("03")
        msg = str(cm.exception)
        self.assertIn("149/150", msg)
        self.assertIn("構築する人に", msg)
        self.assertNotIn("reset.py", msg)           # メンバーは作り直せない
        self.svc.indexes.pop("sengoku")
        with self.assertRaises(SetupError) as cm:
            state.ensure("03")
        self.assertIn("インデックス sengoku がありません", str(cm.exception))

    def test_missing_vectors_are_found_without_reading_the_index_definition(self):
        victim = next(iter(self.svc.docs["sengoku"]))
        self.svc.docs["sengoku"][victim].pop("profile_vector")
        with self.assertRaises(SetupError) as cm:
            state.ensure("04")
        self.assertIn("149/150", str(cm.exception))

    def test_rebuild_and_reset_stop_before_deleting(self):
        with self.assertRaises(SetupError) as cm:
            quiet(state.ensure, "04", rebuild=True)
        self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        mod = load_script(BASIC / "tools" / "reset.py", "reset_tool_query")
        for argv in (["--to", "01"], ["--to", "04", "--embed", "live"]):
            with mock.patch.object(sys, "argv", ["reset.py", *argv]):
                with self.assertRaises(SetupError) as cm:
                    quiet(mod.main)
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        self.assertEqual(self.svc.log, [])
        self.assertIn("sengoku", self.svc.indexes)

    def test_reset_dry_run_is_read_only_so_it_works(self):
        mod = load_script(BASIC / "tools" / "reset.py", "reset_tool_query_dry")
        with mock.patch.object(sys, "argv", ["reset.py", "--to", "04", "--dry-run"]):
            _, out = quiet(mod.main)
        self.assertIn("sengoku：あり", out)
        self.assertEqual(self.svc.log, [])

    def test_scripts_that_create_or_change_stop_first(self):
        for folder, name in (("01-keyword-search", "create_index.py"), ("01-keyword-search", "upload.py"),
                             ("01-keyword-search", "analyze.py"), ("03-vector-search", "embed.py")):
            error = self.run_topic_script(folder, name)
            self.assertIsInstance(error, SetupError, name)
            self.assertIn(BUILDER_MESSAGE, str(error), name)
        self.assertEqual(self.svc.log, [])
        self.assertEqual(len(self.svc.docs["sengoku"]), 150)

    def test_search_scripts_run_with_the_member_key(self):
        for folder, name in (("01-keyword-search", "keyword_search.py"), ("01-keyword-search", "search_paraphrase.py")):
            error = self.run_topic_script(folder, name)
            self.assertIsNone(error, f"{name}: {error!r}")
        self.assertEqual(self.svc.log, [])


class RunnerHintTest(FakeAzureBase):
    """403 のとき、いまの設定が検索だけのキー（メンバー用）なら、そのことを先に案内する。"""

    def tips(self, role):
        from lib import runner

        class Forbidden(Exception):
            status_code = 403
        self.set_role(role)
        return runner.explain(Forbidden("Forbidden"))

    def test_member_key_hint_comes_first(self):
        tips = self.tips("query")
        self.assertIn("検索だけのキー", tips[0])
        self.assertIn("--role builder", tips[0])
        self.assertTrue(any("tools/team.py env" in t for t in tips))

    def test_builder_key_has_no_member_hint(self):
        tips = self.tips("admin")
        self.assertFalse(any("検索だけのキー" in t for t in tips))
        self.assertTrue(any("tools/team.py env" in t for t in tips))


if __name__ == "__main__":
    unittest.main()
