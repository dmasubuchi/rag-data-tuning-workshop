"""19（エージェント型検索）と 20（答えの評価）の通信しない試験。applied フォルダで  python -m unittest discover -s tests

Azure には接続しない。要求の本文の形、activity・references・response の読み取り、答えの保存、採点の返事の読み取り、ぶれの計算を確かめる。
サンプルの返事は、実際の返事（2026-08-01-preview）の形に合わせた作り物。
"""
import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
from lib import agentic, clients, config, evaluation  # noqa: E402
from envcase import EnvCase  # noqa: E402

# 値は、公開前の検査（check_public）が「キーらしい文字列」と見ないように、20 文字より短くしてある
FAKE_SETTINGS = config.Settings(
    search_endpoint="https://search.example.net/", search_key="dummy-srch-0001",
    openai_endpoint="https://aoai.example.net/", openai_key="dummy-oai-0002",
    embedding_deployment="emb", chat_deployment="chat-deploy", dimensions=1536, env_file="dummy.env.local",
    storage_connection_string="dummy-storage", storage_container="hr-docs")

# 実際の返事の形（知識ベースの retrieve。low で3つに分解された例）
ACTIVITY = [
    {"type": "modelQueryPlanning", "id": 0, "inputTokens": 937, "outputTokens": 62, "elapsedMs": 684,
     "model": {"modelName": "gpt-5-mini", "deploymentId": "chat-deploy"}},
    {"type": "searchIndex", "id": 1, "knowledgeSourceName": "hr-docs-ks", "count": 32, "elapsedMs": 233,
     "searchIndexArguments": {"search": "REQ-043 最終面接 評価", "filter": "allowed/any(a: search.in(a, 'role:recruiter'))"}},
    {"type": "searchIndex", "id": 2, "knowledgeSourceName": "hr-docs-ks", "count": 29, "elapsedMs": 103,
     "searchIndexArguments": {"search": "REQ-043 内定 連絡 日付"}},
    {"type": "searchIndex", "id": 3, "knowledgeSourceName": "hr-docs-ks", "count": 20, "elapsedMs": 81,
     "searchIndexArguments": {"search": "REQ-043 最終面接 進んだ 人"}},
    {"type": "agenticReasoning", "id": 4, "reasoningTokens": 34156, "retrievalReasoningEffort": {"kind": "low"}},
]
REFERENCES = [
    {"type": "searchIndex", "id": "0", "activitySource": 2, "rerankerScore": 3.63, "docKey": "abc_pages_7",
     "title": "EVAL-INTERVIEWS-2026-10.xlsx", "sourceData": {"chunk": "EV-010 APP-0386", "kind": "interview_evaluations"}},
    {"type": "searchIndex", "id": "1", "activitySource": 3, "rerankerScore": 3.45, "docKey": "def_pages_0",
     "title": "MAIL-09_REQ-043_APP-0386.eml", "sourceData": {"chunk": "内定が決まりました", "kind": "mail"}},
    {"type": "searchIndex", "id": "2", "activitySource": 1, "rerankerScore": 2.99, "docKey": "abc_pages_7",
     "title": "EVAL-INTERVIEWS-2026-10.xlsx", "sourceData": {"chunk": "EV-010 APP-0386", "kind": "interview_evaluations"}},
]
RESPONSE = [{"content": [{"type": "text", "text": json.dumps([
    {"ref_id": 0, "title": "EVAL-INTERVIEWS-2026-10.xlsx", "content": "EV-010 APP-0386 最終面接"},
    {"ref_id": 1, "title": "MAIL-09_REQ-043_APP-0386.eml", "content": "内定が決まりました"},
    {"ref_id": 2, "title": "EVAL-INTERVIEWS-2026-10.xlsx", "content": "EV-010 APP-0386 最終面接"},
], ensure_ascii=False)}]}]


class RequestBodyTest(unittest.TestCase):
    def test_low_uses_messages(self):
        b = agentic.retrieve_body("質問です", "low", "kind eq 'resume'", 7)
        self.assertEqual(b["messages"][0]["role"], "user")
        self.assertEqual(b["messages"][0]["content"][0], {"type": "text", "text": "質問です"})
        self.assertNotIn("intents", b)
        self.assertEqual(b["retrievalReasoningEffort"], {"kind": "low"})
        self.assertEqual(b["maxOutputDocuments"], 7)
        self.assertTrue(b["includeActivity"])

    def test_minimal_uses_intents_not_messages(self):
        b = agentic.retrieve_body("質問です", "minimal")
        self.assertEqual(b["intents"], [{"type": "semantic", "search": "質問です"}])
        self.assertNotIn("messages", b)          # minimal に messages を付けると 400 になる
        self.assertEqual(b["retrievalReasoningEffort"], {"kind": "minimal"})

    def test_filter_add_on_and_references(self):
        b = agentic.retrieve_body("q", "medium")
        p = b["knowledgeSourceParams"][0]
        self.assertEqual(p["kind"], "searchIndex")
        self.assertEqual(p["knowledgeSourceName"], agentic.KNOWLEDGE_SOURCE)
        self.assertEqual(p["filterAddOn"], agentic.search_filter())
        self.assertTrue(p["includeReferences"] and p["includeReferenceSourceData"])
        self.assertEqual(b["outputMode"], "extractiveData")

    def test_auto_is_accepted_and_unknown_effort_is_not(self):
        self.assertEqual(agentic.retrieve_body("q", "auto")["retrievalReasoningEffort"], {"kind": "auto"})
        with self.assertRaises(config.SetupError):
            agentic.retrieve_body("q", "high")

    def test_filter_text(self):
        self.assertEqual(agentic.search_filter(), "allowed/any(a: search.in(a, 'role:recruiter'))")
        self.assertEqual(agentic.allowed_filter("role:interviewer", "user:U-1006"),
                         "allowed/any(a: search.in(a, 'role:interviewer,user:U-1006'))")
        with self.assertRaises(config.SetupError):
            agentic.allowed_filter("role:x') or true or ('a")

    def test_preview_version_is_in_one_place(self):
        self.assertEqual(agentic.API_VERSION, "2026-08-01-preview")
        self.assertIn(agentic.API_VERSION, agentic.PREVIEW_NOTICE)
        self.assertEqual(agentic.GA_API_VERSION, "2026-04-01")


class DefinitionTest(unittest.TestCase):
    def test_names_are_fixed(self):
        self.assertEqual((agentic.KNOWLEDGE_SOURCE, agentic.KNOWLEDGE_BASE), ("hr-docs-ks", "hr-docs-kb"))

    def test_knowledge_source_points_to_the_index(self):
        d = agentic.knowledge_source_definition()
        self.assertEqual(d["kind"], "searchIndex")
        self.assertEqual(d["searchIndexParameters"]["searchIndexName"], config.HR_INDEX)
        self.assertEqual(d["searchIndexParameters"]["semanticConfigurationName"], config.SEMANTIC_CONFIG)
        names = [f["name"] for f in d["searchIndexParameters"]["sourceDataFields"]]
        self.assertIn("chunk", names)
        self.assertIn("chunk_id", names)

    def test_knowledge_base_uses_key_not_identity(self):
        with mock.patch.object(config, "get_settings", return_value=FAKE_SETTINGS):
            d = agentic.knowledge_base_definition()
        self.assertEqual(d["knowledgeSources"], [{"name": agentic.KNOWLEDGE_SOURCE}])
        p = d["models"][0]["azureOpenAIParameters"]
        self.assertEqual(p["apiKey"], "dummy-oai-0002")
        self.assertEqual(p["deploymentId"], "chat-deploy")
        self.assertEqual(p["modelName"], "gpt-5-mini")                       # AZURE_OPENAI_CHAT_MODEL の既定（デプロイ名とは別）
        self.assertEqual(p["resourceUri"], "https://aoai.example.net")      # 末尾の / を除く
        self.assertNotIn("authIdentity", p)                                  # マネージド ID は使わない
        self.assertNotIn("identity", json.dumps(d).lower())


class ParseTest(unittest.TestCase):
    def test_activity_decomposition_and_counts(self):
        a = agentic.parse_activity(ACTIVITY)
        self.assertEqual(a["planning_calls"], 1)
        self.assertEqual(a["search_count"], 3)                       # searchIndex の記録の数が検索の回数
        self.assertEqual(a["queries"], ["REQ-043 最終面接 評価", "REQ-043 内定 連絡 日付", "REQ-043 最終面接 進んだ 人"])
        self.assertEqual((a["input_tokens"], a["output_tokens"]), (937, 62))
        self.assertEqual(a["planning_ms"], 684)
        self.assertEqual(a["search_tokens"], 34156)                  # reasoningTokens は検索側のトークン
        self.assertEqual(a["errors"], [])

    def test_activity_minimal_has_no_planning(self):
        a = agentic.parse_activity([ACTIVITY[1], ACTIVITY[4]])
        self.assertEqual((a["planning_calls"], a["search_count"]), (0, 1))

    def test_activity_medium_has_two_plannings_and_dedupes_queries(self):
        act = ACTIVITY[:3] + [dict(ACTIVITY[0], id=5, inputTokens=4000, outputTokens=200), dict(ACTIVITY[2], id=6)]
        a = agentic.parse_activity(act)
        self.assertEqual(a["planning_calls"], 2)
        self.assertEqual(a["input_tokens"], 4937)
        self.assertEqual(a["search_count"], 3)
        self.assertEqual(len(a["distinct_queries"]), 2)

    def test_activity_error_is_reported(self):
        a = agentic.parse_activity([{"type": "searchIndex", "id": 1, "error": {"message": "boom"}}])
        self.assertEqual(len(a["errors"]), 1)

    def test_activity_empty_or_none(self):
        self.assertEqual(agentic.parse_activity(None)["search_count"], 0)

    def test_references(self):
        refs = agentic.parse_references(REFERENCES)
        self.assertEqual(refs[0]["doc_key"], "abc_pages_7")
        self.assertEqual(refs[0]["ref_id"], "0")
        self.assertEqual(refs[0]["activity_source"], 2)
        self.assertEqual(refs[1]["kind"], "mail")
        self.assertAlmostEqual(refs[1]["score"], 3.45)

    def test_response_items(self):
        items = agentic.parse_response_items(RESPONSE)
        self.assertEqual([i["ref_id"] for i in items], [0, 1, 2])
        self.assertEqual(agentic.parse_response_items([{"content": [{"text": "not json"}]}]), [])
        self.assertEqual(agentic.parse_response_items(None), [])

    def test_evidence_maps_ref_to_doc_key_and_dedupes(self):
        refs = agentic.parse_references(REFERENCES)
        ev = agentic.evidence_from_retrieval(agentic.parse_response_items(RESPONSE), refs, 10)
        self.assertEqual([e["chunk_id"] for e in ev], ["abc_pages_7", "def_pages_0"])      # 同じチャンクは1件
        self.assertEqual(ev[1]["text"], "内定が決まりました")
        self.assertEqual(len(agentic.evidence_from_retrieval(agentic.parse_response_items(RESPONSE), refs, 1)), 1)

    def test_short_id(self):
        self.assertEqual(agentic.short_id("xx_pages_12", "EVAL.xlsx"), "EVAL.xlsx#12")


class PromptTest(unittest.TestCase):
    EV = [{"chunk_id": "a_pages_0", "title": "MAIL-09.eml", "text": "内定が決まりました。\n\n\n期限は10月30日です。"},
          {"chunk_id": "b_pages_1", "title": "CV.docx", "text": "職務経歴書"}]

    def test_same_prompt_for_both_methods(self):
        m = agentic.answer_messages("いつですか", self.EV)
        self.assertEqual(m[0]["role"], "system")
        self.assertIn("[1] MAIL-09.eml", m[1]["content"])
        self.assertIn("[2] CV.docx", m[1]["content"])
        self.assertNotIn("\n\n\n", m[1]["content"])          # 空行のかたまりは詰める
        self.assertIn("質問：いつですか", m[1]["content"])

    def test_no_evidence_is_said(self):
        self.assertIn("資料はありません", agentic.answer_messages("q", [])[1]["content"])

    def test_coverage_counts_by_application(self):
        ev = [{"title": "CV-APP-0391.docx", "text": "応募番号 APP-0391"},
              {"title": "EVAL-INTERVIEWS-2026-10.xlsx", "text": "APP-0391 APP-0417 EV-001"},
              {"title": "MAIL-05.eml", "text": "APP-0391"}]
        c = agentic.application_coverage(ev)
        self.assertEqual(c["APP-0391"], {"経歴書": 1, "評価一覧": 1, "メール": 1})
        self.assertEqual(c["APP-0417"], {"評価一覧": 1})
        self.assertEqual(agentic.coverage_text(c["APP-0417"]), "評価一覧1")
        self.assertEqual(agentic.coverage_text(None), "（なし）")

    def test_coverage_rows_cover_all_applications(self):
        rows = agentic.coverage_rows([], [])
        self.assertEqual(len(rows), len(config.load_manifest()["applications"]))
        no_eval = next(r for r in rows if r[0].startswith("APP-0471"))
        self.assertIn("評価の行0", no_eval[2])                  # 面接の評価がない人は、データでも 0


class QuestionsTest(unittest.TestCase):
    def test_ten_questions_with_expectations(self):
        qs = agentic.load_questions()
        self.assertEqual([q["id"] for q in qs], [f"q{i:02d}" for i in range(1, 11)])
        self.assertTrue(all(q["question"] and q["expect"] for q in qs))
        self.assertIn("REQ-043 の最終面接に進んだ人の評価と、内定の連絡の日付は？", [q["question"] for q in qs])

    def test_resolve_question(self):
        self.assertEqual(agentic.resolve_question("自分の質問", None), ("自分の質問", "自分の質問"))
        self.assertEqual(agentic.resolve_question(None, "q02")[0], "q02")
        self.assertEqual(agentic.resolve_question()[0], "q01")
        with self.assertRaises(config.SetupError):
            agentic.resolve_question(None, "q99")


class RedactTest(unittest.TestCase):
    def test_error_text_hides_key(self):
        class Res:
            text = '{"error": {"message": "bad key dummy-oai-0002 given"}}'

            def json(self):
                return json.loads(self.text)

        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / "w.env"
            env.write_text("AZURE_OPENAI_API_KEY=dummy-oai-0002\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {"WORKSHOP_ENV_FILE": str(env)}):
                got = agentic._error_text(Res())
        self.assertNotIn("dummy-oai-0002", got)
        self.assertIn("***", got)


class SaveTest(unittest.TestCase):
    """答えの保存：できていない分だけ足す。設定が違う保存は断る。"""

    QS = [{"id": "q01", "question": "質問1", "expect": ["a"]}, {"id": "q02", "question": "質問2", "expect": ["b"]}]

    @staticmethod
    def fake_run(method, question, effort, top_n, filter_expr=None):
        return {"answer": f"{method}:{question}", "context": [{"chunk_id": "k_pages_0", "title": "T", "text": "本文"}],
                "queries": ["検索文"], "search_count": 3 if method == "agentic" else 1,
                "planning_calls": 1 if method == "agentic" else 0, "total_seconds": 1.5,
                "tokens": {"planning_input": 1, "planning_output": 1, "answer_input": 2, "answer_output": 2, "search_side": 0}}

    def test_make_answers_resumes(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "get_settings", return_value=FAKE_SETTINGS), \
                mock.patch.object(agentic, "run_method", side_effect=self.fake_run) as run:
            path = Path(d) / "19.json"
            data = agentic.make_answers(self.QS, runs=2, path=path, progress=lambda *a: None)
            self.assertEqual(len(data["items"]), 2 * 2 * 2)                      # 質問2 × 方式2 × 2回
            self.assertEqual(run.call_count, 8)
            run.reset_mock()
            data = agentic.make_answers(self.QS, runs=3, path=path, progress=lambda *a: None)
            self.assertEqual(run.call_count, 4)                                  # 3回目の分だけ足す
            self.assertEqual(len(data["items"]), 12)
            keys = {agentic.answer_key(i) for i in data["items"]}
            self.assertEqual(len(keys), 12)
            item = data["items"][0]
            self.assertEqual(set(item) >= {"question_id", "question", "method", "run", "answer", "context"}, True)
            self.assertEqual(item["context"][0], {"chunk_id": "k_pages_0", "title": "T", "text": "本文"})
            self.assertEqual(agentic.load_answers(path)["meta"]["top_n"], agentic.TOP_N)

    def test_different_settings_are_refused(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "get_settings", return_value=FAKE_SETTINGS), \
                mock.patch.object(agentic, "run_method", side_effect=self.fake_run):
            path = Path(d) / "19.json"
            agentic.make_answers(self.QS, runs=1, path=path, progress=lambda *a: None)
            with self.assertRaises(config.SetupError):
                agentic.make_answers(self.QS, runs=1, effort="medium", path=path, progress=lambda *a: None)
            agentic.make_answers(self.QS, runs=1, effort="medium", path=path, fresh=True, progress=lambda *a: None)

    def test_load_answers_missing(self):
        self.assertIsNone(agentic.load_answers(Path(tempfile.gettempdir()) / "no-such-19-answers.json"))


class OwnScoreTest(unittest.TestCase):
    GOOD = {"faithfulness": {"score": 5, "reason": "資料のとおり"}, "answers_question": {"score": 4, "reason": "ほぼ"},
            "coverage": {"score": 3, "reason": "1つ欠ける"}}

    def test_parse(self):
        got = evaluation.parse_own_score(json.dumps(self.GOOD, ensure_ascii=False))
        self.assertEqual([got[k]["score"] for k, _ in evaluation.OWN_METRICS], [5, 4, 3])
        self.assertEqual(got["coverage"]["reason"], "1つ欠ける")

    def test_parse_inside_code_fence_and_string_score(self):
        text = "```json\n" + json.dumps({**self.GOOD, "coverage": {"score": "2", "reason": "x"}}, ensure_ascii=False) + "\n```"
        self.assertEqual(evaluation.parse_own_score(text)["coverage"]["score"], 2)

    def test_parse_rejects_bad_scores(self):
        for bad in (6, 0, 3.5, None, True):
            data = {**self.GOOD, "coverage": {"score": bad, "reason": "x"}}
            with self.assertRaises(ValueError, msg=repr(bad)):
                evaluation.parse_own_score(json.dumps(data))
        with self.assertRaises(ValueError):
            evaluation.parse_own_score("点は 5 です")
        with self.assertRaises(ValueError):
            evaluation.parse_own_score(json.dumps({"faithfulness": self.GOOD["faithfulness"]}))

    def test_messages_carry_numbered_context_and_expectations(self):
        m = evaluation.own_messages("質問", [{"title": "T.eml", "text": "本文"}], ["要点A", "要点B"], "答え")
        self.assertIn("1〜5", m[0]["content"])
        self.assertIn("[1] T.eml", m[1]["content"])
        self.assertIn("- 要点A", m[1]["content"])
        self.assertIn("システムの答え：\n答え", m[1]["content"])

    def test_score_own_retries_once_on_bad_reply(self):
        replies = iter([("これは JSON ではない", {"input_tokens": 10, "output_tokens": 1}),
                        (json.dumps(self.GOOD), {"input_tokens": 20, "output_tokens": 2})])
        with mock.patch.object(agentic, "chat", side_effect=lambda *a, **k: next(replies)):
            got = evaluation.score_own("q", [], ["e"], "a")
        self.assertEqual(got["coverage"]["score"], 3)
        self.assertEqual((got["input_tokens"], got["output_tokens"]), (30, 3))

    def test_score_own_gives_up_after_two_bad_replies(self):
        with mock.patch.object(agentic, "chat", return_value=("だめ", {"input_tokens": 1, "output_tokens": 1})):
            with self.assertRaises(config.SetupError):
                evaluation.score_own("q", [], ["e"], "a")


class FakeOpenAI:
    """openai.OpenAI の代わり。chat.completions.create に実際に渡された引数を記録して、決まった返事を返す（通信しない）。"""
    calls = []
    reply = "答えです"

    def __init__(self, base_url=None, api_key=None, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        FakeOpenAI.calls.append(kwargs)
        message = SimpleNamespace(content=FakeOpenAI.reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))


class OutputLimitSentTest(EnvCase):
    """自前の採点（score_own）と 16 の漏れの実演（leak_demo の ask_llm）は、出力の上限 4000 を、実際の送信に載せる。

    推論モデルは考える分も上限に数える。800・1200 に戻ると、返事が途中で切れて空になる。
    ソースの文字列ではなく、偽のクライアントが受け取った引数（max_completion_tokens）を見る。
    """

    def setUp(self):
        super().setUp()
        FakeOpenAI.calls = []
        patcher = mock.patch("openai.OpenAI", FakeOpenAI)      # agentic.openai_client も leak_demo も、ここから作る
        patcher.start()
        self.addCleanup(patcher.stop)
        usage = mock.patch.object(agentic, "USAGE", agentic.Usage())    # 使った量の記録を、ほかの試験に持ち越さない
        usage.start()
        self.addCleanup(usage.stop)

    def test_score_own_sends_4000(self):
        FakeOpenAI.reply = json.dumps(OwnScoreTest.GOOD, ensure_ascii=False)
        got = evaluation.score_own("q", [{"title": "T.eml", "text": "本文"}], ["e"], "a")
        self.assertEqual(got["coverage"]["score"], 3)
        self.assertEqual(len(FakeOpenAI.calls), 1)
        sent = FakeOpenAI.calls[0]
        self.assertEqual(sent["max_completion_tokens"], 4000)
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertEqual(sent["model"], "c")

    def test_score_own_retry_also_sends_4000(self):
        replies = iter(["これは JSON ではない", json.dumps(OwnScoreTest.GOOD, ensure_ascii=False)])

        def create(**kwargs):
            FakeOpenAI.calls.append(kwargs)
            message = SimpleNamespace(content=next(replies))
            return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                                   usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))

        with mock.patch.object(FakeOpenAI, "create", side_effect=create):
            evaluation.score_own("q", [], ["e"], "a")
        self.assertEqual([c["max_completion_tokens"] for c in FakeOpenAI.calls], [4000, 4000])

    def test_make_answer_default_sends_4000(self):
        FakeOpenAI.reply = "資料のとおりです [1]"
        agentic.make_answer("質問", [{"title": "T.eml", "text": "本文"}])
        self.assertEqual([c["max_completion_tokens"] for c in FakeOpenAI.calls], [4000])

    def test_leak_demo_ask_llm_sends_4000(self):
        """スクリプトを最後まで動かす（検索だけ偽）。悪い例・良い例の 2 回とも、4000 を送る。"""
        FakeOpenAI.reply = "資料にありません。"
        hits = [{"title": "JOB-REQ042-v3.pdf", "kind": "job_posting", "chunk": "求人票の本文"}]
        search = SimpleNamespace(search=lambda *a, **k: list(hits))
        path = HERE.parent / "topics" / "16-security-filter" / "leak_demo.py"
        out = io.StringIO()
        with mock.patch.object(clients, "search_client", return_value=search), \
                mock.patch.object(sys, "argv", [str(path), "--question", "石田さんの評価は？"]), \
                contextlib.redirect_stdout(out):
            runpy.run_path(str(path), run_name="__main__")
        self.assertEqual(len(FakeOpenAI.calls), 2, out.getvalue())
        self.assertEqual([c["max_completion_tokens"] for c in FakeOpenAI.calls], [4000, 4000])
        self.assertEqual(FakeOpenAI.calls[0]["reasoning_effort"], "low")        # .env.local の考える量もそのまま渡る
        self.assertIn("石田さんの評価は？", FakeOpenAI.calls[0]["messages"][1]["content"])


class BuiltinParseTest(unittest.TestCase):
    NEW = {"groundedness": 3.0, "groundedness_score": 3.0, "groundedness_passed": True, "groundedness_result": "pass",
           "groundedness_reason": "Let's think step by step: ...", "groundedness_status": "completed", "groundedness_threshold": 3,
           "groundedness_properties": {"prompt_tokens": 3254, "completion_tokens": 121, "total_tokens": 3375}}

    def test_new_field_names(self):
        got = evaluation.parse_builtin(self.NEW, "groundedness")
        self.assertEqual(got["score"], 3.0)
        self.assertTrue(got["passed"])                                   # 3 点でも pass（しきい値 3）
        self.assertEqual(got["result"], "pass")
        self.assertEqual((got["input_tokens"], got["output_tokens"]), (3254, 121))
        self.assertEqual(got["threshold"], 3)
        self.assertIn("groundedness_reason", got["fields"])
        self.assertFalse(any(f.startswith("gpt_") for f in got["fields"]))

    def test_old_gpt_prefixed_names(self):
        got = evaluation.parse_builtin({"gpt_groundedness": 4.0, "groundedness_reason": "理由"}, "groundedness")
        self.assertEqual(got["score"], 4.0)
        self.assertEqual(got["reason"], "理由")
        self.assertIsNone(got["passed"])

    def test_passed_from_result_text(self):
        got = evaluation.parse_builtin({"relevance": 2.0, "relevance_result": "fail"}, "relevance")
        self.assertFalse(got["passed"])

    def test_skipped_has_no_score(self):
        got = evaluation.parse_builtin({"relevance_status": "skipped", "relevance_passed": None}, "relevance")
        self.assertIsNone(got["score"])

    def test_score_builtin_uses_both_evaluators_and_counts_tokens(self):
        calls = {}

        def fake(name):
            def ev(**kw):
                calls[name] = kw
                return {name: 4.0, f"{name}_result": "pass", f"{name}_properties": {"prompt_tokens": 100, "completion_tokens": 10}}
            return ev

        before = agentic.USAGE.snapshot().get("score_builtin", {"calls": 0, "input_tokens": 0})
        got = evaluation.score_builtin({"groundedness": fake("groundedness"), "relevance": fake("relevance")}, "質問",
                                       [{"text": "A"}, {"text": "B"}], "答え")
        self.assertEqual(calls["groundedness"], {"query": "質問", "response": "答え", "context": "A\n\nB"})
        self.assertEqual(calls["relevance"], {"query": "質問", "response": "答え"})          # relevance に context は要らない
        self.assertEqual((got["groundedness"]["score"], got["relevance"]["score"]), (4.0, 4.0))
        after = agentic.USAGE.snapshot()["score_builtin"]
        self.assertEqual(after["calls"] - before["calls"], 2)
        self.assertEqual(after["input_tokens"] - before["input_tokens"], 200)


class SpreadTest(unittest.TestCase):
    def rec(self, q, method, run, cov, ground=None):
        r = {"question_id": q, "method": method, "run": run, "own": {"coverage": {"score": cov}}}
        if ground is not None:
            r["builtin"] = {"groundedness": {"score": ground}}
        return r

    def test_spread(self):
        s = evaluation.spread([3, 5, 4])
        self.assertEqual((s["min"], s["max"], s["range"], s["n"]), (3, 5, 2, 3))
        self.assertAlmostEqual(s["mean"], 4.0)
        self.assertEqual(evaluation.spread([None, 4])["n"], 1)
        self.assertEqual(evaluation.spread([])["range"], None)

    def test_range_text(self):
        self.assertEqual(evaluation.range_text(evaluation.spread([3, 5, 4])), "3〜5")
        self.assertEqual(evaluation.range_text(evaluation.spread([4, 4, 4])), "4")
        self.assertEqual(evaluation.range_text(evaluation.spread([])), "-")
        self.assertEqual(evaluation.range_text(evaluation.spread([2.5, 3.0])), "2.5〜3")

    def test_group_spreads_and_means(self):
        recs = [self.rec("q01", "plain", 1, 3), self.rec("q01", "plain", 2, 5), self.rec("q01", "plain", 3, 4),
                self.rec("q01", "agentic", 1, 4), self.rec("q01", "agentic", 2, 4), self.rec("q01", "agentic", 3, 4),
                self.rec("q02", "plain", 1, 2), self.rec("q02", "agentic", 1, 5)]
        sp = evaluation.group_spreads(recs, "own.coverage")
        self.assertEqual(sp[("q01", "plain")]["range"], 2)
        self.assertEqual(sp[("q01", "agentic")]["range"], 0)
        self.assertEqual(sp[("q02", "plain")]["n"], 1)
        means = evaluation.method_means(recs, "own.coverage")
        self.assertAlmostEqual(means["plain"], (3 + 5 + 4 + 2) / 4)
        self.assertAlmostEqual(means["agentic"], (4 * 3 + 5) / 4)
        self.assertAlmostEqual(evaluation.mean_range(sp, "plain"), (2 + 0) / 2)

    def test_missing_builtin_is_none(self):
        self.assertIsNone(evaluation.metric_value(self.rec("q01", "plain", 1, 3), "builtin.groundedness"))
        self.assertEqual(evaluation.metric_value(self.rec("q01", "plain", 1, 3, 4.0), "builtin.groundedness"), 4.0)

    def test_agreement(self):
        recs = [{"own": {"faithfulness": {"score": s}}, "builtin": {"groundedness": {"score": g}}}
                for s, g in ((5, 5), (4, 5), (3, 5), (2, None))]
        a = evaluation.agreement(recs, "own.faithfulness", "builtin.groundedness")
        self.assertEqual(a["n"], 3)
        self.assertAlmostEqual(a["same"], 1 / 3)
        self.assertAlmostEqual(a["within1"], 2 / 3)
        self.assertAlmostEqual(a["mean_diff"], (0 - 1 - 2) / 3)
        self.assertEqual(evaluation.agreement([], "own.faithfulness", "builtin.groundedness")["n"], 0)


class ScoreSaveTest(unittest.TestCase):
    """採点の保存：入力が同じものだけ使い回す。足りない評価器の分だけ足す。"""

    QS = [{"id": "q01", "question": "質問", "expect": ["要点A"]}]

    def answers(self, texts=("答え1", "答え2")):
        return {"meta": {"api_version": "x"}, "items": [
            {"question_id": "q01", "question": "質問", "method": m, "run": 1, "answer": t,
             "context": [{"chunk_id": "k_pages_0", "title": "T", "text": "本文"}]}
            for m, t in zip(("plain", "agentic"), texts)]}

    @staticmethod
    def fake_own(*a, **k):
        r = {key: {"score": 4, "reason": "r"} for key, _ in evaluation.OWN_METRICS}
        r.update(input_tokens=5, output_tokens=1)
        return r

    @staticmethod
    def fake_builtin(evaluators, question, context, answer):
        return {n: {"score": 4.0, "passed": True, "result": "pass", "reason": "r", "status": "completed", "threshold": 3,
                    "input_tokens": 10, "output_tokens": 2, "fields": []} for n, _ in evaluation.BUILTIN_METRICS}

    def run_scoring(self, path, answers, builtin, so, sb):
        return evaluation.score_answers(answers, self.QS, builtin=builtin, path=path, progress=lambda *a: None)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "20.json"
        self.stack = [mock.patch.object(config, "get_settings", return_value=FAKE_SETTINGS),
                      mock.patch.object(evaluation, "score_own", side_effect=self.fake_own),
                      mock.patch.object(evaluation, "score_builtin", side_effect=self.fake_builtin),
                      mock.patch.object(evaluation, "builtin_evaluators", return_value={"groundedness": None, "relevance": None})]
        self.so, self.sb, self.be = self.stack[1].start(), self.stack[2].start(), self.stack[3].start()
        self.stack[0].start()

    def tearDown(self):
        for m in self.stack:
            m.stop()
        self.tmp.cleanup()

    def test_resumes_without_rescoring(self):
        data = self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        self.assertEqual((self.so.call_count, self.sb.call_count), (2, 2))
        self.assertEqual(len(data["records"]), 2)
        self.assertTrue(all(r["own_hash"] and r["builtin_hash"] for r in data["records"]))
        self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        self.assertEqual((self.so.call_count, self.sb.call_count), (2, 2))               # 入力が同じなので、もう採点しない
        self.assertEqual(evaluation.load_scores(self.path)["records"][0]["own_tokens"], {"input_tokens": 5, "output_tokens": 1})

    def test_changed_answer_is_rescored_only_for_that_item(self):
        self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        data = self.run_scoring(self.path, self.answers(("答え1", "作り直した答え2")), True, self.so, self.sb)
        self.assertEqual((self.so.call_count, self.sb.call_count), (3, 3))               # 変わった1件の自前・組み込みだけ
        self.assertEqual(len(data["records"]), 2)

    def test_changed_context_or_expectation_or_prompt_is_rescored(self):
        self.run_scoring(self.path, self.answers(), False, self.so, self.sb)
        changed = self.answers()
        changed["items"][0]["context"][0]["text"] = "別の本文"
        self.run_scoring(self.path, changed, False, self.so, self.sb)
        self.assertEqual(self.so.call_count, 3)                                           # 資料が変わった1件
        self.QS = [{"id": "q01", "question": "質問", "expect": ["要点A", "要点B"]}]
        self.run_scoring(self.path, changed, False, self.so, self.sb)
        self.assertEqual(self.so.call_count, 5)                                           # 想定の要点が変わったので2件
        with mock.patch.object(evaluation, "OWN_SYSTEM", evaluation.OWN_SYSTEM + "\n追加の基準"):
            self.run_scoring(self.path, changed, False, self.so, self.sb)
        self.assertEqual(self.so.call_count, 7)                                           # 採点の基準が変わったので2件

    def test_adds_only_missing_builtin_after_own_only(self):
        self.run_scoring(self.path, self.answers(), False, self.so, self.sb)
        self.assertEqual((self.so.call_count, self.sb.call_count), (2, 0))
        self.assertFalse(any(r.get("builtin") for r in evaluation.load_scores(self.path)["records"]))
        data = self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        self.assertEqual((self.so.call_count, self.sb.call_count), (2, 2))               # 自前はそのまま、組み込みだけ足す
        self.assertTrue(all(r.get("builtin") for r in data["records"]))

    def test_stale_builtin_is_dropped_when_builtin_is_off(self):
        self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        data = self.run_scoring(self.path, self.answers(("答え1", "作り直した答え2")), False, self.so, self.sb)
        by_method = {r["method"]: r for r in data["records"]}
        self.assertTrue(by_method["plain"].get("builtin"))                                # 入力が同じ組み込みの点は残る
        self.assertFalse(by_method["agentic"].get("builtin"))                             # 古い組み込みの点は残さない
        self.assertEqual(self.sb.call_count, 2)

    def test_legacy_records_without_hash_are_rescored(self):
        self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        data = evaluation.load_scores(self.path)
        for r in data["records"]:
            r.pop("own_hash"), r.pop("builtin_hash")
        agentic.write_json(self.path, data)
        self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        self.assertEqual((self.so.call_count, self.sb.call_count), (4, 4))

    def test_stale_records_for_summary(self):
        self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        scores = evaluation.load_scores(self.path)
        self.assertEqual(evaluation.stale_records(scores, self.answers(), self.QS), [])
        self.assertEqual(evaluation.stale_records(scores, self.answers(("答え1", "作り直した答え2")), self.QS), [("q01", "agentic", 1)])

    def test_fresh_scores_everything_again(self):
        self.run_scoring(self.path, self.answers(), True, self.so, self.sb)
        evaluation.score_answers(self.answers(), self.QS, builtin=True, path=self.path, fresh=True, progress=lambda *a: None)
        self.assertEqual(self.so.call_count, 4)


class ThresholdAndSkippedTest(unittest.TestCase):
    """合否はしきい値で判定し直す。評価器がスキップした（点がない）ときも落ちない。"""

    def rec(self, method, g, r):
        def part(score):
            return {"score": score, "passed": None if score is None else score >= 3, "result": None, "status": "completed" if score else "skipped",
                    "threshold": 3, "input_tokens": 1, "output_tokens": 1, "fields": []}
        return {"question_id": "q01", "method": method, "run": 1, "own": {"faithfulness": {"score": 4}, "answers_question": {"score": 4}},
                "builtin": {"groundedness": part(g), "relevance": part(r)}}

    def test_judge(self):
        self.assertTrue(evaluation.judge(3.0, 3))
        self.assertFalse(evaluation.judge(3.0, 4))
        self.assertTrue(evaluation.judge(4.0, 4))
        self.assertIsNone(evaluation.judge(None, 3))

    def test_pass_counts_use_chosen_threshold_not_saved_passed(self):
        recs = [self.rec("plain", 4.0, 5.0), self.rec("plain", 3.0, 3.0), self.rec("plain", 2.0, 4.0), self.rec("agentic", 5.0, 5.0)]
        self.assertEqual(evaluation.pass_counts(recs, "groundedness", "plain", 3), (2, 3))
        self.assertEqual(evaluation.pass_counts(recs, "groundedness", "plain", 4), (1, 3))       # 保存の passed は True のままでも、4 では不合格
        self.assertEqual(evaluation.pass_counts(recs, "groundedness", "plain", 5), (0, 3))
        self.assertEqual(evaluation.pass_counts(recs, "relevance", "agentic", 5), (1, 1))

    def test_pass_counts_skip_missing_scores(self):
        recs = [self.rec("plain", None, None), self.rec("plain", 4.0, 4.0)]
        self.assertEqual(evaluation.pass_counts(recs, "groundedness", "plain", 3), (1, 1))
        self.assertEqual(evaluation.pass_counts([self.rec("plain", None, None)], "groundedness", "plain", 3), (0, 0))

    def test_all_skipped_does_not_crash_agreement(self):
        recs = [self.rec("plain", None, None), self.rec("agentic", None, None)]
        ag = evaluation.agreement(recs, "own.faithfulness", "builtin.groundedness")
        self.assertEqual(ag["n"], 0)
        row = evaluation.agreement_row("根拠への忠実さ と groundedness", ag)
        self.assertEqual(row, ["根拠への忠実さ と groundedness", 0, "比べる相手なし", "-", "-"])
        self.assertEqual(evaluation.method_means(recs, "builtin.groundedness"), {"plain": None, "agentic": None})

    def test_agreement_row_with_data(self):
        recs = [self.rec("plain", 4.0, 4.0), self.rec("plain", 5.0, 3.0)]
        row = evaluation.agreement_row("x", evaluation.agreement(recs, "own.faithfulness", "builtin.groundedness"))
        self.assertEqual(row[:2], ["x", 2])
        self.assertEqual(row[2], "50%")
        self.assertEqual(row[3], "100%")


class DocsTest(unittest.TestCase):
    def test_preview_notice_mentions_auto_version(self):
        self.assertIn("auto", agentic.PREVIEW_NOTICE)
        self.assertIn(agentic.API_VERSION, agentic.PREVIEW_NOTICE)

    def test_readme_does_not_say_low_medium_are_latest_only(self):
        readme = (agentic.TOPIC_19_DIR / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("low・medium・auto）は、プレビューの API 版 `2026-08-01-preview` にしかありません", readme)
        self.assertIn("`low`・`medium` はそれより前のプレビューにもあり", readme)
        self.assertIn("足されたのが `auto`", readme)

    def test_completeness_evaluator_is_importable_when_package_is_installed(self):
        if not evaluation.builtin_available():
            self.skipTest("azure-ai-evaluation が入っていない")
        from azure.ai.evaluation import ResponseCompletenessEvaluator      # 1.18.10 にある（実験的なクラス）
        self.assertTrue(callable(ResponseCompletenessEvaluator))


if __name__ == "__main__":
    unittest.main()
