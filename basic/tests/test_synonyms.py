"""lib/synonyms.py（同義語マップ）と、02 の synonym_map.py・tuning.py の後片付けの試験。通信なし（AI Search の偽物を使う）。

  ・操作する相手（インデックス・辞書の名前。固定）を始めに決め、固定の名前でないものを渡されたら何も変えずに止まる
  ・確認用の語は、入れ替えたルールが効き始めてから当たる
  ・スクリプトが途中で止まっても、後片付け（cells.at_exit）で辞書のつなぎとプロファイルが元に戻る
  ・検索だけのキー（メンバー用）では、辞書もインデックスも変える前に「構築する人の設定で実行します」と止まる

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import copy
import io
import os
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BASIC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASIC))
from lib import config, synonyms  # noqa: E402
from lib.config import SetupError  # noqa: E402

TOPIC_02 = BASIC / "topics" / "02-analyzers-synonyms"
ENV = """AZURE_SEARCH_ENDPOINT=https://a.search.windows.net
AZURE_SEARCH_API_KEY=FAKE-SRCH-d4e5f6
AZURE_SEARCH_KEY_ROLE={role}
AZURE_OPENAI_ENDPOINT=https://b.azure.com
AZURE_OPENAI_API_KEY=FAKE-OAI-a1b2c3
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=e
AZURE_OPENAI_CHAT_DEPLOYMENT=c
EMBEDDING_DIMENSIONS=1536
"""


class FakeService:
    """名前ごとに、同義語マップとインデックスの状態を持つ AI Search の偽物。

    ルールを入れ替えると、検索 delay 回のあいだは前のルールのまま（本物も、入れ替えた直後は古いルールで検索されることがある）。
    """

    def __init__(self, quota=3, delay=2):
        self.maps = {}           # 名前 → {"rules": 書いたルール, "old": 前のルール, "left": 効くまでの残りの検索回数}
        self.indexes = {}        # 名前 → SearchIndex（azure の本物のクラス）
        self.quota = quota
        self.delay = delay
        self.log = []            # 変更の記録：("map", 名前) ("delete_map", 名前) ("index", 名前)
        self.searches = 0        # 確認用の語以外の検索の回数
        self.fail_after = None   # 確認用の語以外の検索を、この回数のあとで失敗させる（途中で止まる試験）

    def add_index(self, name: str, profiles=None) -> None:
        from azure.search.documents.indexes.models import SearchField, SearchIndex

        self.indexes[name] = SearchIndex(name=name, fields=[
            SearchField(name="id", type="Edm.String", key=True),
            *[SearchField(name=n, type="Edm.String", searchable=True) for n in synonyms.SEARCH_FIELDS],
            SearchField(name="clan", type="Edm.String", searchable=False),
        ], scoring_profiles=list(profiles or []))

    def add_map(self, name: str, rules: list) -> None:
        self.maps[name] = {"rules": list(rules), "old": list(rules), "left": 0}

    def active_rules(self, name: str) -> list:
        m = self.maps[name]
        return m["rules"] if m["left"] <= 0 else m["old"]

    def fields(self, index_name: str) -> dict:
        return {f.name: list(f.synonym_map_names or []) for f in self.indexes[index_name].fields if f.name in synonyms.SEARCH_FIELDS}

    def profiles(self, index_name: str) -> dict:
        return {p.name: dict(p.text_weights.weights) for p in (self.indexes[index_name].scoring_profiles or [])}


class FakeIndexClient:
    def __init__(self, s: FakeService):
        self.s = s

    def get_synonym_map_names(self):
        return list(self.s.maps)

    def get_synonym_map(self, name):
        from azure.core.exceptions import ResourceNotFoundError

        if name not in self.s.maps:
            raise ResourceNotFoundError(f"synonym map {name} not found")
        return SimpleNamespace(name=name, synonyms=list(self.s.maps[name]["rules"]))

    def create_or_update_synonym_map(self, sm):
        old = self.s.active_rules(sm.name) if sm.name in self.s.maps else []
        self.s.maps[sm.name] = {"rules": list(sm.synonyms), "old": old, "left": self.s.delay}
        self.s.log.append(("map", sm.name))

    def delete_synonym_map(self, name):
        used = [i for i in self.s.indexes if any(name in v for v in self.s.fields(i).values())]
        assert not used, f"{name} はまだ {used} につながっている"
        self.s.maps.pop(name)
        self.s.log.append(("delete_map", name))

    def get_service_statistics(self):
        return {"counters": {"synonymMaps": {"usage": len(self.s.maps), "quota": self.s.quota}}}

    def get_index(self, name):
        from azure.core.exceptions import ResourceNotFoundError

        if name not in self.s.indexes:
            raise ResourceNotFoundError(f"index {name} not found")
        return copy.deepcopy(self.s.indexes[name])     # 本物と同じく、受け取った定義を書き換えても、保存するまでは変わらない

    def create_or_update_index(self, index):
        self.s.indexes[index.name] = copy.deepcopy(index)
        self.s.log.append(("index", index.name))


class FakeResults(list):
    def get_count(self):
        return len(self)


class FakeSearchClient:
    def __init__(self, s: FakeService, index_name: str):
        self.s, self.index_name = s, index_name

    def search(self, search_text=None, top=50, select=None, include_total_count=False, **kw):
        for m in self.s.maps.values():
            m["left"] -= 1
        if (search_text or "").startswith(synonyms.PROBE_PREFIX):
            maps = {n for names in self.s.fields(self.index_name).values() for n in names if n in self.s.maps}
            found = any(r.startswith(search_text + " ") for n in maps for r in self.s.active_rules(n))
            return FakeResults([{"id": "b001", "@search.score": 1.0}] if found else [])
        self.s.searches += 1
        if self.s.fail_after is not None and self.s.searches > self.s.fail_after:
            raise RuntimeError("検索に失敗しました（試験）")
        return FakeResults([{"id": "b001", "@search.score": 2.0}, {"id": "b002", "@search.score": 1.0}])


class SynonymsCase(unittest.TestCase):
    """偽の AI Search を使う（武将のインデックスは sengoku）。設定（.env.local の代わり）は構築する人（admin）のもの。"""

    ROLE = "admin"
    FAKE_CLIENTS = True      # False のときは lib.clients の本物の包み（検索だけのキーを止めるところ）を通す

    def setUp(self):
        self.s = FakeService()
        self.s.add_index("sengoku")
        self.s.add_index("other-index")        # 同じ AI Search にある、ほかのインデックス（触らない）
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / ".env.local").write_text(ENV.format(role=self.ROLE), encoding="utf-8")
        env = mock.patch.dict(os.environ, {"WORKSHOP_ENV_FILE": str(Path(tmp.name) / ".env.local")})
        env.start()
        self.addCleanup(env.stop)
        config.get_settings.cache_clear()
        self.addCleanup(config.get_settings.cache_clear)
        patches = [("lib.synonyms.time.sleep", lambda seconds: None)]
        if self.FAKE_CLIENTS:
            patches += [("lib.synonyms.index_client", lambda: FakeIndexClient(self.s)),
                        ("lib.synonyms.search_client", lambda name: FakeSearchClient(self.s, name))]
        else:
            from lib import clients
            clients.index_client.cache_clear()
            self.addCleanup(clients.index_client.cache_clear)
            patches += [("azure.search.documents.indexes.SearchIndexClient", lambda endpoint, credential: FakeIndexClient(self.s)),
                        ("azure.search.documents.SearchClient", lambda endpoint, index_name, credential: FakeSearchClient(self.s, index_name))]
        for target, value in patches:
            p = mock.patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def run_script(self, name: str) -> "tuple[BaseException | None, list]":
        """02 のスクリプトを、偽の AI Search で上から実行する。返すのは、止まったときの例外と、後片付け（cells.at_exit）に渡された関数。"""
        exits = []
        patches = [
            mock.patch("lib.clients.index_client", lambda: FakeIndexClient(self.s)),
            mock.patch("lib.clients.search_client", lambda name: FakeSearchClient(self.s, name)),
            mock.patch("lib.state.ensure", lambda *a, **kw: None),
            mock.patch("lib.cells.start", lambda: None),
            mock.patch("lib.cells.at_exit", exits.append),
            mock.patch.object(sys, "argv", [name]),
        ]
        for p in patches:
            p.start()
        error = None
        try:
            with redirect_stdout(io.StringIO()):
                runpy.run_path(str(TOPIC_02 / name), run_name="__main__")
        except Exception as e:  # noqa: BLE001  途中で止まったときの例外を受け取って調べる
            error = e
        finally:
            for p in reversed(patches):
                p.stop()
        return error, exits

    def call_exits(self, exits: list) -> None:
        with redirect_stdout(io.StringIO()):
            for func in exits:
                func()


class TargetTest(SynonymsCase):
    def test_target_names_are_fixed(self):
        t = synonyms.target()
        self.assertEqual((t.index_name, t.map_name), ("sengoku", "sengoku-synonyms"))

    def test_names_other_than_fixed_are_refused(self):
        self.s.add_map("other-synonyms", ["a, b"])
        for t in (synonyms.Target("sengoku", "other-synonyms"),
                  synonyms.Target("other-index", "sengoku-synonyms"),
                  synonyms.Target("other-index", "other-synonyms")):
            with self.assertRaises(SetupError) as cm:
                synonyms.save_rules(t, ["北海道, 蝦夷地"])
            self.assertIn("固定", str(cm.exception))
            for call in (lambda: synonyms.apply(t, ["北海道, 蝦夷地"]), lambda: synonyms.attach(t, True),
                         lambda: synonyms.attach(t, False), lambda: synonyms.delete_map(t),
                         lambda: synonyms.restore(t, {"exists": False, "rules": [], "attached": {}})):
                with self.assertRaises(SetupError):
                    call()
        self.assertEqual(self.s.log, [])
        self.assertEqual(self.s.maps["other-synonyms"]["rules"], ["a, b"])
        self.assertEqual(self.s.fields("other-index"), {f: [] for f in synonyms.SEARCH_FIELDS})

    def test_target_has_no_group(self):
        self.assertFalse(hasattr(synonyms.target(), "group"))


class RulesTest(SynonymsCase):
    def test_probe_is_hidden(self):
        word, rule = synonyms.make_probe()
        self.assertTrue(word.startswith(synonyms.PROBE_PREFIX) and word.isascii() and word.isalpha())
        self.assertEqual(rule, f"{word} => {synonyms.PROBE_TARGET}")
        self.assertEqual(synonyms.visible_rules(["北海道, 蝦夷地", rule, " "]), ["北海道, 蝦夷地"])

    def test_save_rules_adds_probe_and_current_rules_hides_it(self):
        t = synonyms.target()
        word = synonyms.save_rules(t, ["北海道, 蝦夷地"])
        self.assertEqual(self.s.maps["sengoku-synonyms"]["rules"], ["北海道, 蝦夷地", f"{word} => {synonyms.PROBE_TARGET}"])
        self.assertEqual(synonyms.current_rules(t), ["北海道, 蝦夷地"])

    def test_save_rules_refuses_empty(self):
        with self.assertRaises(SetupError):
            synonyms.save_rules(synonyms.target(), ["   "])

    def test_full_service_stops_with_guidance(self):
        for name in ("a", "b", "c"):
            self.s.add_map(f"{name}-synonyms", [])
        with self.assertRaises(SetupError) as cm:
            synonyms.save_rules(synonyms.target(), ["北海道, 蝦夷地"])
        self.assertIn("使っていない辞書を消して", str(cm.exception))
        self.assertNotIn("sengoku-synonyms", self.s.maps)

    def test_own_map_can_be_replaced_when_full(self):
        for name in ("sengoku", "b", "c"):
            self.s.add_map(f"{name}-synonyms", ["a, b"])
        t = synonyms.target()
        synonyms.save_rules(t, ["北海道, 蝦夷地"])
        self.assertEqual(synonyms.current_rules(t), ["北海道, 蝦夷地"])
        self.assertEqual(self.s.maps["b-synonyms"]["rules"], ["a, b"])

    def test_max_maps_falls_back(self):
        with mock.patch.object(FakeIndexClient, "get_service_statistics", side_effect=RuntimeError("no")):
            self.assertEqual(synonyms.max_maps(), synonyms.DEFAULT_MAX_MAPS)


class AttachTest(SynonymsCase):
    def test_attach_only_sengoku_index_and_search_fields(self):
        t = synonyms.target()
        synonyms.save_rules(t, ["北海道, 蝦夷地"])
        synonyms.attach(t, True)
        self.assertEqual(self.s.fields("sengoku"), {f: ["sengoku-synonyms"] for f in synonyms.SEARCH_FIELDS})
        self.assertEqual(self.s.fields("other-index"), {f: [] for f in synonyms.SEARCH_FIELDS})
        clan = next(f for f in self.s.indexes["sengoku"].fields if f.name == "clan")
        self.assertFalse(clan.synonym_map_names)
        synonyms.attach(t, False)
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})

    def test_detach_leaves_other_maps(self):
        index = self.s.indexes["sengoku"]
        for f in index.fields:
            if f.name == "aliases":
                f.synonym_map_names = ["other-synonyms"]
        synonyms.attach(synonyms.target(), False)
        self.assertEqual(self.s.fields("sengoku")["aliases"], ["other-synonyms"])


class WaitTest(SynonymsCase):
    def test_probe_hits_only_after_new_rules_are_active(self):
        self.s.delay = 3
        t = synonyms.target()
        synonyms.apply(t, ["北海道, 蝦夷地"])
        sc = FakeSearchClient(self.s, "sengoku")
        word = synonyms.save_rules(t, ["眼球, 目玉"])
        self.assertEqual(list(sc.search(search_text=word)), [])      # 入れ替えた直後は古いルールのまま
        self.assertEqual(synonyms.current_rules(t), ["眼球, 目玉"])
        synonyms.wait_until_active(t, word, limit=60, step=0)
        self.assertNotEqual(list(sc.search(search_text=word)), [])

    def test_old_probe_does_not_count(self):
        self.s.delay = 0
        t = synonyms.target()
        old = synonyms.save_rules(t, ["北海道, 蝦夷地"])
        synonyms.attach(t, True)
        synonyms.save_rules(t, ["眼球, 目玉"])
        self.assertEqual(list(FakeSearchClient(self.s, "sengoku").search(search_text=old)), [])

    def test_probe_does_not_hit_when_detached(self):
        self.s.delay = 0
        t = synonyms.target()
        word = synonyms.save_rules(t, ["北海道, 蝦夷地"])
        with self.assertRaises(SetupError):
            synonyms.wait_until_active(t, word, limit=-1, step=0)


class SnapshotTest(SynonymsCase):
    def test_restore_deletes_map_that_did_not_exist(self):
        t = synonyms.target()
        snap = synonyms.snapshot(t)
        synonyms.apply(t, ["関白 => 太閤"])
        synonyms.restore(t, snap)
        self.assertNotIn("sengoku-synonyms", self.s.maps)
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})

    def test_restore_puts_back_rules_and_attachment(self):
        t = synonyms.target()
        synonyms.apply(t, ["北海道, 蝦夷地"])
        snap = synonyms.snapshot(t)
        synonyms.attach(t, False)
        synonyms.apply(t, ["北海道, 蝦夷地", "関白 => 太閤"])
        synonyms.attach(t, False)
        synonyms.restore(t, snap)
        self.assertEqual(synonyms.current_rules(t), ["北海道, 蝦夷地"])
        self.assertEqual(self.s.fields("sengoku"), {f: ["sengoku-synonyms"] for f in synonyms.SEARCH_FIELDS})
        probe = next(r for r in self.s.maps["sengoku-synonyms"]["rules"] if synonyms.is_probe(r))
        self.assertEqual(self.s.active_rules("sengoku-synonyms")[-1], probe)    # 戻したルールが効き始めるまで待った

    def test_delete_map_detaches_first(self):
        t = synonyms.target()
        synonyms.apply(t, ["a, b"])
        self.assertTrue(synonyms.delete_map(t))
        self.assertNotIn("sengoku-synonyms", self.s.maps)
        self.assertFalse(synonyms.delete_map(t))


class ScriptCleanupTest(SynonymsCase):
    """02 のスクリプトを、偽の AI Search で上から実行する。途中で止めて、後片付けで元に戻るかを確かめる。"""

    def test_synonym_map_detaches_when_stopped(self):
        self.s.fail_after = 3          # 辞書なしの3問のあと、辞書をつないでからの検索で止まる
        error, exits = self.run_script("synonym_map.py")
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(self.s.fields("sengoku")["profile"], ["sengoku-synonyms"])   # 止まった時点ではつながったまま
        self.assertEqual(len(exits), 1)
        self.call_exits(exits)
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})

    def test_synonym_map_finishes_detached(self):
        error, exits = self.run_script("synonym_map.py")
        self.assertIsNone(error)
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})
        self.assertEqual(synonyms.current_rules(synonyms.target()), ["北海道, 蝦夷地"])
        self.call_exits(exits)          # スクリプトの終わりにもう一度呼ばれても、そのまま
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})

    def test_tuning_restores_profiles_and_map_when_stopped(self):
        from azure.search.documents.indexes.models import ScoringProfile, TextWeights

        self.s.add_index("sengoku", profiles=[ScoringProfile(name="name-first", text_weights=TextWeights(weights={"name": 2})),
                                                 ScoringProfile(name="mine", text_weights=TextWeights(weights={"aliases": 4}))])
        self.s.fail_after = 15         # 1〜3 と、4 の辞書なしの検索のあと、辞書をつないでからの検索で止まる
        error, exits = self.run_script("tuning.py")
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(self.s.profiles("sengoku")["name-first"], {"name": 5, "aliases": 3})
        self.assertIn("sengoku-synonyms", self.s.maps)
        self.call_exits(exits)
        self.assertEqual(self.s.profiles("sengoku"), {"name-first": {"name": 2}, "mine": {"aliases": 4}})
        self.assertNotIn("sengoku-synonyms", self.s.maps)
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})

    def test_tuning_finishes_with_previous_state(self):
        self.s.add_map("sengoku-synonyms", ["北海道, 蝦夷地"])
        error, exits = self.run_script("tuning.py")
        self.assertIsNone(error)
        self.assertEqual(self.s.profiles("sengoku"), {})
        self.assertEqual(synonyms.current_rules(synonyms.target()), ["北海道, 蝦夷地"])
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})
        writes = len(self.s.log)
        self.call_exits(exits)          # スクリプトの終わりに2回目は戻さない
        self.assertEqual(len(self.s.log), writes)


class QueryKeyTest(SynonymsCase):
    """メンバー用の検索だけのキー（AZURE_SEARCH_KEY_ROLE=query）では、辞書もインデックスも変える前に、日本語で止まる。"""

    ROLE = "query"
    FAKE_CLIENTS = False
    MESSAGE = "この手順は構築する人の設定（--role builder）で実行します"

    def assert_nothing_changed(self):
        self.assertEqual(self.s.log, [])
        self.assertEqual(self.s.maps, {})
        self.assertEqual(self.s.fields("sengoku"), {f: [] for f in synonyms.SEARCH_FIELDS})

    def test_synonyms_functions_stop_with_the_builder_message(self):
        t = synonyms.target()
        for call in (lambda: synonyms.apply(t, ["北海道, 蝦夷地"]), lambda: synonyms.save_rules(t, ["北海道, 蝦夷地"]),
                     lambda: synonyms.attach(t, True), lambda: synonyms.attach(t, False), lambda: synonyms.delete_map(t),
                     lambda: synonyms.snapshot(t), lambda: synonyms.current_rules(t)):
            with self.assertRaises(SetupError) as cm:
                call()
            self.assertIn(self.MESSAGE, str(cm.exception))
        self.assert_nothing_changed()

    def test_scripts_stop_before_anything_is_done(self):
        for name in ("synonym_map.py", "tuning.py", "compare_analyzers.py"):
            error, exits = self.run_script(name)
            self.assertIsInstance(error, SetupError, name)
            self.assertIn(self.MESSAGE, str(error), name)
            self.assertEqual(exits, [], name)           # 後片付け（辞書を外す）も登録されない
            self.assertEqual(self.s.searches, 0, name)  # 検索も始めていない
        self.assert_nothing_changed()


if __name__ == "__main__":
    unittest.main()
