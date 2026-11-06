"""採用アシスタントの、LLM が道具を選んで検索する流れ（assistant/azure_io.py）の試験。偽の LLM と偽の検索を使う。"""
import json
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

APPLIED = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APPLIED))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from assistant import azure_io, engine  # noqa: E402
from lib import config  # noqa: E402
from envcase import MEMBER, EnvCase  # noqa: E402


def call(name: str, args: dict) -> dict:
    return {"tool": name, "args": args}


def final(text: str) -> dict:
    return {"final": text}


RATE_LIMIT = "rate-limit"


class FakeLLM:
    """決まった順に返事をする LLM。tool_choice="none" のときは、次の final まで読み飛ばす。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, messages, tools, tool_choice):
        self.calls += 1
        if tool_choice == "none":
            while self.script and "final" not in self.script[0]:
                self.script.pop(0)
        item = self.script.pop(0)
        if item == RATE_LIMIT:
            raise azure_io.RateLimited()
        usage = {"input_tokens": 10, "output_tokens": 2}
        if "final" in item:
            return {"content": item["final"], "tool_calls": [], "usage": usage}
        return {"content": "", "tool_calls": [{"id": f"c{self.calls}", "name": item["tool"],
                                               "arguments": json.dumps(item["args"], ensure_ascii=False)}], "usage": usage}


def doc(doc_id: str, app_id: str, req_id: str = "REQ-042", kind: str = "resume") -> dict:
    return {"chunk_id": f"{doc_id}-c0", "doc_id": doc_id, "kind": kind, "req_id": req_id,
            "application_ids": app_id, "title": f"{doc_id}.docx", "chunk": f"{app_id} 夜間の障害対応"}


ALL = [doc("CV-APP-0391", "APP-0391"), doc("CV-APP-0392", "APP-0392"), doc("CV-APP-0603", "APP-0603", "REQ-047"),
       doc("JOB-REQ042-v3", "-", kind="job_posting")]


def fake_search(text, vector_text, extra_filter, top):
    """REQ-042 の欄の絞り込みと、候補の絞り込み（search.ismatch）だけを真似る。キーワードは APP-0391 だけに当たる。"""
    rows = list(ALL)
    f = extra_filter or ""
    if "req_id eq 'REQ-042'" in f:
        rows = [r for r in rows if r["req_id"] == "REQ-042"]
    m = re.search(r"search\.ismatch\('([^']*)', 'application_ids'", f)
    if m:
        ids = m.group(1).split()
        rows = [r for r in rows if r["application_ids"] in ids or r["kind"] == "job_posting"]
    if text and text != "*":
        rows = [r for r in rows if r["doc_id"] == "CV-APP-0391"]
    return rows[:top]


class LoopTest(unittest.TestCase):
    def test_loop_runs_tools_in_order_and_reports_steps(self):
        llm = FakeLLM([call("filter_fields", {"req_id": "REQ-042"}), call("keyword_search", {"query": "夜間"}),
                       call("follow_ids", {}), final("市川さん [1]")])
        seen = []
        out = azure_io.ask("REQ-042 で夜間対応の経験は？", seen.append, llm=llm, searcher=fake_search)
        self.assertEqual([s.method for s in seen], ["欄で絞る", "キーワード", "ID でたどる"])
        self.assertEqual((seen[0].people_after, seen[1].people_after), (2, 1))
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["answer"], "市川さん [1]")
        self.assertEqual(out["sources"][0]["no"], 1)

    def test_stops_at_max_steps(self):
        llm = FakeLLM([call("keyword_search", {"query": "a"})] * 10 + [final("答え [1]")])
        seen = []
        out = azure_io.ask("q", seen.append, llm=llm, searcher=fake_search)
        self.assertEqual(len(seen), engine.MAX_STEPS)
        self.assertEqual(out["answer"], "答え [1]")

    def test_rate_limit_is_retried(self):
        llm = FakeLLM([RATE_LIMIT, call("keyword_search", {"query": "a"}), final("答え [1]")])
        with mock.patch.object(azure_io.time, "sleep") as slept:
            out = azure_io.ask("q", lambda s: None, llm=llm, searcher=fake_search)
        self.assertIn("[1]", out["answer"])
        slept.assert_called()

    def test_rate_limit_after_all_retries_is_explained_as_busy(self):
        from lib.errors import explain

        llm = FakeLLM([RATE_LIMIT] * (azure_io.RETRIES + 1))
        with mock.patch.object(azure_io.time, "sleep"):
            with self.assertRaises(azure_io.RateLimited) as cm:
                azure_io.ask("q", lambda s: None, llm=llm, searcher=fake_search)
        self.assertIn("混んでいます", " ".join(explain(cm.exception)))
        self.assertNotIn("思わぬエラー", " ".join(explain(cm.exception)))

    def test_unknown_tool_is_reported_not_crash(self):
        seen = []
        llm = FakeLLM([call("delete_all", {}), final("資料にありません")])
        out = azure_io.ask("q", seen.append, llm=llm, searcher=fake_search)
        self.assertTrue(out["warnings"])
        self.assertEqual(seen, [])

    def test_bad_field_values_are_not_put_in_the_filter(self):
        seen_filters = []

        def spy(text, vector_text, extra_filter, top):
            seen_filters.append(extra_filter or "")
            return fake_search(text, vector_text, extra_filter, top)

        llm = FakeLLM([call("filter_fields", {"req_id": "REQ-042' or true or '"}), final("資料にありません")])
        out = azure_io.ask("q", lambda s: None, llm=llm, searcher=spy)
        self.assertFalse(any("or true" in f for f in seen_filters))
        self.assertTrue(out["warnings"])

    def test_sources_are_renumbered_from_one(self):
        llm = FakeLLM([call("filter_fields", {"req_id": "REQ-042"}), final("A [3] B [1] C [3]")])
        out = azure_io.ask("q", lambda s: None, llm=llm, searcher=fake_search)
        self.assertEqual(out["answer"], "A [1] B [2] C [1]")
        self.assertEqual([s["no"] for s in out["sources"]], [1, 2])


class RobustnessTest(unittest.TestCase):
    def test_applicant_ids_not_a_list_is_a_warning_not_a_crash(self):
        llm = FakeLLM([call("filter_fields", {"applicant_ids": 5}), final("資料にありません")])
        out = azure_io.ask("q", lambda s: None, llm=llm, searcher=fake_search)
        self.assertTrue(out["warnings"])

    def test_llm_uses_a_short_timeout_and_reports_it(self):
        import httpx2 as httpx   # openai 3.x の通信の部品
        from openai import APITimeoutError

        seen = {}

        class Completions:
            def create(self, **kwargs):
                raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))

        class Client:
            def with_options(self, **kwargs):
                seen.update(kwargs)
                return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

        settings = SimpleNamespace(chat_deployment="d", reasoning_effort="")
        with mock.patch("lib.agentic.openai_client", return_value=Client()), \
                mock.patch("lib.config.get_settings", return_value=settings):
            with self.assertRaises(azure_io.config.SetupError) as cm:
                azure_io.openai_llm([], [], "auto")
        self.assertEqual(seen["timeout"], azure_io.LLM_TIMEOUT)
        self.assertIn("秒", str(cm.exception))

    def test_search_uses_a_short_timeout_and_reports_it(self):
        from azure.core.exceptions import ServiceResponseError

        seen = {}

        class Client:
            def search(self, text, **kwargs):
                seen.update(kwargs)
                raise ServiceResponseError("timed out")

        with mock.patch("lib.clients.search_client", return_value=Client()):
            with self.assertRaises(azure_io.config.SetupError):
                azure_io.search("夜間", None, None, 5)
        self.assertEqual(seen["read_timeout"], azure_io.SEARCH_TIMEOUT)


class SummaryTest(unittest.TestCase):
    def test_follow_summary_lists_every_document_with_its_applicant(self):
        run = engine.Run("q", candidates={"APP-0391"})
        hits = [doc(f"D{i:02d}", "APP-0391") for i in range(30)]
        step = engine.apply_step(run, "follow", {}, hits, False)
        text = azure_io.summary(run, step, [h["chunk_id"] for h in hits], "follow")
        self.assertIn("[30]", text)
        self.assertIn("APP-0391", text.splitlines()[-1])
        self.assertIn("夜間の障害対応", text.splitlines()[-1])

    def test_fields_summary_has_titles_without_body(self):
        run = engine.Run("q")
        hits = [doc("CV-APP-0391", "APP-0391"), doc("CV-APP-0392", "APP-0392")]
        step = engine.apply_step(run, "fields", {"req_id": "REQ-042"}, hits, True)
        text = azure_io.summary(run, step, [h["chunk_id"] for h in hits], "fields")
        self.assertIn("CV-APP-0392.docx", text)
        self.assertNotIn("夜間の障害対応", text)


class SummaryNamesTest(unittest.TestCase):
    """LLM に返す要約で、候補を「名前（応募番号）」の形に。名前が応募番号だけだと、答えに名前が出ないことがあった。"""

    def run_with(self, hits, candidates=None):
        run = engine.Run("q", candidates=candidates)
        step = engine.apply_step(run, "keyword", {"query": "x"}, hits, True)
        return azure_io.summary(run, step, [h["chunk_id"] for h in hits], "keyword")

    def test_candidates_are_listed_with_names(self):
        text = self.run_with([RESUME_0471, RESUME_0417])
        first = text.splitlines()[0]
        self.assertIn("2 人", first)
        self.assertIn("岩崎 俊介（APP-0417）", first)
        self.assertIn("岩崎 俊樹（APP-0471）", first)

    def test_a_person_without_a_known_name_is_just_the_number(self):
        text = self.run_with([RESUME_0471, doc("CV-APP-0603", "APP-0603", "REQ-047")])
        first = text.splitlines()[0]
        self.assertIn("岩崎 俊樹（APP-0471）", first)
        self.assertIn("APP-0603", first)
        self.assertNotIn("（APP-0603）", first)

    def test_each_document_line_names_its_people(self):
        text = self.run_with([RESUME_0471, doc("CV-APP-0603", "APP-0603", "REQ-047")])
        lines = text.splitlines()
        self.assertIn("岩崎 俊樹（APP-0471）", lines[1])
        self.assertIn("APP-0603", lines[2])
        self.assertNotIn("（APP-0603）", lines[2])

    def test_names_come_from_the_documents_collected_so_far(self):
        run = engine.Run("q", candidates={"APP-0471"})
        engine.apply_step(run, "keyword", {"query": "x"}, [RESUME_0471], True)
        step = engine.apply_step(run, "follow", {}, [doc("MAIL-1", "APP-0471", kind="mail")], False)
        text = azure_io.summary(run, step, ["MAIL-1-c0"], "follow")
        self.assertIn("岩崎 俊樹（APP-0471）", text.splitlines()[0])
        self.assertIn("岩崎 俊樹（APP-0471）", text.splitlines()[1])

    def test_nobody_yet_says_everyone(self):
        run = engine.Run("q")
        step = engine.apply_step(run, "fields", {"req_id": "REQ-042"}, [], False)
        self.assertIn("全員", azure_io.summary(run, step, [], "fields").splitlines()[0])


class SummaryContinuationTest(unittest.TestCase):
    """評価一覧のチャンクが前の行の途中から始まるとき、LLM が次の行の人の所見と読み違えないよう、要約に添え書きを入れる。"""

    CONT = "（ここから前の行の続き。だれの評価かは、この資料からは分からない）"
    NEXT = "（ここから次の行）"

    def line_of(self, hit, tool="keyword"):
        run = engine.Run("q")
        step = engine.apply_step(run, tool, {"query": "x"}, [hit], True)
        return azure_io.summary(run, step, [hit["chunk_id"]], tool).splitlines()[1]

    def test_a_chunk_that_starts_in_the_middle_of_a_row_is_marked_before_and_after_the_continuation(self):
        line = self.line_of(EVAL_PAGES_4)
        self.assertIn(self.CONT, line)
        self.assertIn(self.NEXT, line)
        self.assertLess(line.index(self.CONT), line.index("見送りとする"))
        self.assertLess(line.index("見送りとする"), line.index(self.NEXT))
        self.assertLess(line.index(self.NEXT), line.index("EV-006"))

    def test_the_marks_are_in_the_follow_summary_too(self):
        line = self.line_of(EVAL_PAGES_5, "follow")
        self.assertIn(self.CONT, line)
        self.assertLess(line.index(self.NEXT), line.index("EV-007"))

    def test_a_chunk_that_starts_with_a_row_has_no_marks(self):
        line = self.line_of(ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0391 APP-0439", EVAL_CHUNK))
        self.assertNotIn("ここから", line)

    def test_the_sheet_head_chunk_has_no_marks(self):
        self.assertNotIn("ここから", self.line_of(sheet_head("52250c6dea2f_aHR0cHM6Ly9z_pages_0")))

    def test_other_kinds_have_no_marks(self):
        self.assertNotIn("ここから", self.line_of(ev("CV-APP-0391", "resume", "APP-0391", "資格と研修\n基本情報技術者")))


class EffortTest(unittest.TestCase):
    def test_default_is_low(self):
        self.assertEqual(azure_io.reasoning_effort({}), "low")

    def test_env_overrides(self):
        self.assertEqual(azure_io.reasoning_effort({"ASSISTANT_REASONING_EFFORT": "medium"}), "medium")

    def test_unknown_value_falls_back_to_low(self):
        self.assertEqual(azure_io.reasoning_effort({"ASSISTANT_REASONING_EFFORT": "max"}), "low")


class CitationTest(unittest.TestCase):
    def test_bad_citations_are_removed(self):
        text, warns = azure_io.check_citations("A [1] B [7]", 3)
        self.assertNotIn("[7]", text)
        self.assertTrue(warns)

    def test_no_citation_warns(self):
        self.assertTrue(azure_io.check_citations("出典なし", 3)[1])

    def test_good_citations_pass(self):
        self.assertEqual(azure_io.check_citations("A [1] B [3]", 3), ("A [1] B [3]", []))

    def test_comma_list_is_split(self):
        self.assertEqual(azure_io.check_citations("A [1, 2]、B [2、3]", 3), ("A [1][2]、B [2][3]", []))

    def test_an_answer_of_only_not_in_the_documents_sentences_needs_no_citation(self):
        for text in ("資料にありません。", "鈴木さんの経歴書は資料から確認できませんでした。", "日付は資料では見つかりませんでした。",
                     "資料には見当たりません。", "REQ-042・APP-0439 の職務経歴書資料を確認できませんでした。",
                     "経歴書は資料にありません。\n評価は資料からは確認できません。"):
            self.assertEqual(azure_io.check_citations(text, 3), (text, []), text)

    def test_a_content_sentence_next_to_a_not_in_the_documents_one_still_warns(self):
        _, warns = azure_io.check_citations("田中さんは5年担当しました。鈴木さんは資料にありません。", 3)
        self.assertEqual(warns, ["答えに出典の番号がありません"])

    def test_markdown_marks_and_other_endings_do_not_hide_the_type(self):
        for text in ("**資料にありません**。", "_資料にありません_。", "`資料`にありません。", "鈴木さんの経歴書は資料にありませんでした。",
                     "鈴木さんの経歴書は資料に存在しません。", "鈴木さんの経歴書は資料に記載されていません。",
                     "資料には、鈴木さんの職務経歴書に関する記述が見つかりませんでした。"):
            self.assertEqual(azure_io.check_citations(text, 3), (text, []), text)

    def test_a_long_not_in_the_documents_sentence_is_still_the_type(self):
        text = "資料には、REQ-042 の応募者で夜間の障害対応の経験がある人を示す記述はありません。"
        self.assertEqual(azure_io.check_citations(text, 3), (text, []))
        edge = "資料に" + "い" * 40 + "ありません。"
        self.assertEqual(azure_io.check_citations(edge, 3), (edge, []))

    def test_too_long_a_gap_is_a_content_sentence(self):
        text = "資料に" + "い" * 41 + "ありません。"
        self.assertEqual(azure_io.check_citations(text, 3)[1], ["答えに出典の番号がありません"])

    def test_based_on_the_documents_it_cannot_be_confirmed_is_a_content_sentence(self):
        for text in ("資料に基づくと、鈴木さんの職務経歴は確認できません。", "資料によると、鈴木さんの経験は確認できません。"):
            self.assertEqual(azure_io.check_citations(text, 3)[1], ["答えに出典の番号がありません"], text)

    def test_cannot_confirm_without_the_word_documents_is_a_content_sentence(self):
        self.assertTrue(azure_io.check_citations("本人が担当した経験とは確認できません。", 3)[1])

    def test_empty_answer_still_warns(self):
        self.assertTrue(azure_io.check_citations("", 3)[1])

    def test_bad_numbers_are_still_reported_next_to_not_in_the_documents_sentences(self):
        text, warns = azure_io.check_citations("経験があります [7]。資料にありません。", 3)
        self.assertNotIn("[7]", text)
        self.assertTrue(any("見つけていない資料の番号" in w for w in warns))


def ev(doc_id: str, kind: str, application_ids: str, chunk: str) -> dict:
    return {"chunk_id": f"{doc_id}-c0", "doc_id": doc_id, "kind": kind, "req_id": "REQ-042", "application_ids": application_ids,
            "title": doc_id, "chunk": chunk}


EVAL_CHUNK = ("\tEV-005\tAPP-0439\tC-039\t大西 明日香\tREQ-042\t一次面接\t吉田 誠\t結果待ち\n"
              "\tEV-001\tAPP-0391\tC-120\t市川 浩二\tREQ-042\t一次面接\t吉田 誠\t推奨\n")
RESUME_0391 = ev("CV-APP-0391", "resume", "APP-0391", "職務経歴書 氏名 市川 浩二 応募番号 APP-0391 応募求人 REQ-042 夜間の障害対応")
RESUME_0392 = ev("CV-APP-0392", "resume", "APP-0392", "職務経歴書 氏名 田村 朋美 応募番号 APP-0392 応募求人 REQ-042 監視の設定")
RESUME_0417 = ev("CV-APP-0417", "resume", "APP-0417", "職務経歴書 氏名 岩崎 俊介 応募番号 APP-0417 応募求人 REQ-042")
RESUME_0471 = ev("CV-APP-0471", "resume", "APP-0471", "職務経歴書 氏名 岩崎 俊樹 応募番号 APP-0471 応募求人 REQ-042")
EVAL = ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0391 APP-0439 APP-0392", EVAL_CHUNK)
JOB = ev("JOB-REQ042-v3", "job_posting", "-", "求人票 REQ-042 バックエンドエンジニア")


PAGES_4 = '実装と運用の経験は確かだが、設計の判断と根拠の説明が弱く、プロダクト開発の中核を任せるには不安がある。見送りとする。\n\tEV-006\tAPP-0417\tC-017\t岩崎 俊介\tREQ-042\tバックエンドエンジニア（プロダクト開発）\t一次面接\t2026-10-21 14:00\tU-1006\t吉田 誠\t4\t3\t4\t4\t推奨\t提出済み\t2026-10-21 17:30\tPython での API の設計と実装: みらいシステムでの具体的な案件を挙げて説明でき、テストの書き方も確認できた。Azure 上の本番運用: 監視の設定とデプロイの手順を説明でき、運用の実務を担当していると確認できた。\t障害対応: 一次切り分けを自分で担当した経験を確認する時間がなかった。AWS の本番運用: 経歴書にある AWS の利用はテスト環境までで、本番の運用経験は確認できていない。\t'    # 本物の評価一覧のチャンク。前の行（田村 APP-0392 の EV-005）の所見の後半で始まる
PAGES_5 = '説明は具体的で、質問の意図を取り違えない。要件との対応は二次面接で確かめる。\n\tEV-007\tAPP-0439\tC-039\t大西 明日香\tREQ-042\tバックエンドエンジニア（プロダクト開発）\t一次面接\t2026-10-22 16:00\tU-1007\t松本 里奈\t\t\t\t\t\t下書き（未提出）\t\t\t\t下書き（未提出）。保存日時 2026-10-22 18:10。経験年数の確認が中心。評価の言葉は提出前に見直す。\n\tEV-008\tAPP-0386\tC-115\t石田 裕太\tREQ-043\tバックエンドエンジニア（決済基盤）\t一次面接\t2026-09-29 14:00\tU-1006\t吉田 誠\t4\t4\t4\t4\t推奨\t提出済み\t2026-09-29 16:45\tAPI の設計と実装: Java と Go で決済 API を説明できた。データベース: PostgreSQL の設計を説明できた。'    # 同じ形。EV-006（APP-0417）の所見の後半で始まる
EVAL_PAGES_4 = ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0391 APP-0392 APP-0417 APP-0439 APP-0386 APP-0603", PAGES_4)
EVAL_PAGES_5 = ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0391 APP-0392 APP-0417 APP-0439 APP-0386 APP-0603", PAGES_5)


class MismatchedCitationTest(unittest.TestCase):
    """文に書いた人と、出典の資料の人が合わない番号を外す。言い方（資料にありません など）は見ない。"""

    def drop(self, text, evidence):
        return azure_io.drop_mismatched_citations(text, evidence)

    def test_q03_resume_of_another_person_is_dropped(self):
        evidence = [EVAL, RESUME_0391]
        self.assertEqual(self.drop("REQ-042・APP-0439 の職務経歴書資料を確認できませんでした。[2]", evidence),
                         ("REQ-042・APP-0439 の職務経歴書資料を確認できませんでした。", 1))

    def test_the_evaluation_row_of_the_same_person_stays(self):
        text = "REQ-042・APP-0439 の職務経歴書資料を確認できませんでした。[1]"
        self.assertEqual(self.drop(text, [EVAL, RESUME_0391]), (text, 0))

    def test_job_posting_stays(self):
        text = "APP-0439 は REQ-042 に応募しています。[3]"
        self.assertEqual(self.drop(text, [EVAL, RESUME_0391, JOB]), (text, 0))

    def test_sentence_without_a_person_stays(self):
        text = "夜間の障害対応の経験があります。[2]"
        self.assertEqual(self.drop(text, [EVAL, RESUME_0392]), (text, 0))

    def test_name_only_sentence_is_matched_to_the_person_through_the_names_in_the_documents(self):
        evidence = [RESUME_0392, EVAL]
        self.assertEqual(self.drop("市川 浩二さんは夜間の当番を担当しています [1]。", evidence),
                         ("市川 浩二さんは夜間の当番を担当しています。", 1))
        text = "市川 浩二さんは夜間の当番を担当しています [2]。"
        self.assertEqual(self.drop(text, evidence), (text, 0))

    def test_name_without_space_and_surname_only_are_matched_too(self):
        evidence = [RESUME_0392, EVAL]
        self.assertEqual(self.drop("市川浩二さんは担当しています [1]。", evidence)[1], 1)
        self.assertEqual(self.drop("大西さんの経歴書は資料にありません。[1]", evidence), ("大西さんの経歴書は資料にありません。", 1))

    def test_names_that_the_documents_do_not_give_are_not_looked_at(self):
        text = "市川 浩二さんは担当しています [1]。"
        self.assertEqual(self.drop(text, [RESUME_0392]), (text, 0))

    def test_interviewer_names_are_not_taken_as_applicants(self):
        text = "吉田 誠が面接しました。[2]"
        self.assertEqual(self.drop(text, [EVAL, RESUME_0392]), (text, 0))

    def test_two_people_with_the_same_surname(self):
        evidence = [RESUME_0417, RESUME_0471]
        self.assertEqual(self.drop("岩崎 俊樹さんは書類選考中です [1]。", evidence)[1], 1)
        self.assertEqual(self.drop("岩崎 俊樹さんは書類選考中です [2]。", evidence)[1], 0)
        self.assertEqual(self.drop("岩崎さんは応募しています [1][2]。", evidence)[1], 0)

    def test_application_number_wins_over_names(self):
        evidence = [RESUME_0417, RESUME_0471]
        text = "APP-0471 の岩崎 俊介さんは書類選考中です [2]。"
        self.assertEqual(self.drop(text, evidence), (text, 0))
        self.assertEqual(self.drop("APP-0471 の岩崎 俊介さんは書類選考中です [1]。", evidence),
                         ("APP-0471 の岩崎 俊介さんは書類選考中です。", 1))

    def test_one_character_surname_is_not_looked_up(self):
        hayashi = ev("CV-APP-0999", "resume", "APP-0999", "職務経歴書 氏名 林 太郎 応募番号 APP-0999 応募求人 REQ-042")
        text = "林業の経験があります [1]。"
        self.assertEqual(self.drop(text, [RESUME_0392, hayashi]), (text, 0))
        self.assertEqual(self.drop("林 太郎さんは経験があります [1]。", [RESUME_0392, hayashi])[1], 1)

    def test_surname_followed_by_another_given_name_is_not_the_known_person(self):
        """名字の直後に名前が続くなら、名字だけで引かない（資料にない「岩崎 太郎」を、資料の岩崎の誰かとは見ない）。"""
        evidence = [RESUME_0392, RESUME_0417]
        text = "岩崎 太郎さんは経験があります [1]。"
        self.assertEqual(self.drop(text, evidence), (text, 0))
        self.assertEqual(self.drop("岩崎さんは経験があります [1]。", evidence)[1], 1)

    def test_only_the_sentence_that_does_not_match_loses_its_numbers(self):
        evidence = [RESUME_0391, RESUME_0392]
        text = "APP-0391 は担当しています [1]。APP-0391 の別の経験は資料にありません。[2] APP-0392 は監視を担当しています [2]。"
        self.assertEqual(self.drop(text, evidence),
                         ("APP-0391 は担当しています [1]。APP-0391 の別の経験は資料にありません。 APP-0392 は監視を担当しています [2]。", 1))

    def test_a_list_is_split_and_only_the_mismatched_number_goes(self):
        self.assertEqual(self.drop("APP-0439 は結果待ちです。[1, 2]", [EVAL, RESUME_0391]), ("APP-0439 は結果待ちです。[1]", 1))

    def test_a_sentence_with_several_people_keeps_a_document_of_any_of_them(self):
        text = "APP-0391 と APP-0392 は応募しています [1][2]。"
        self.assertEqual(self.drop(text, [RESUME_0391, RESUME_0392]), (text, 0))

    def test_numbers_outside_the_found_documents_are_left_for_check_citations(self):
        text = "APP-0391 は担当しています [9]。"
        self.assertEqual(self.drop(text, [RESUME_0391]), (text, 0))

    def test_a_line_break_ends_a_sentence(self):
        evidence = [RESUME_0391, RESUME_0392]
        text = "- APP-0391：担当しています [1]\n- APP-0392：監視を担当しています [1]"
        self.assertEqual(self.drop(text, evidence), ("- APP-0391：担当しています [1]\n- APP-0392：監視を担当しています", 1))

    def test_chunk_that_starts_in_the_middle_of_a_row_has_no_known_person(self):
        """本物の評価一覧のチャンクは、前の行の所見の途中で始まる。先頭の行に応募番号がないので、その人は分からない（外さない）。"""
        text = "APP-0392 の所見は「見送りとする」です [1]。"
        self.assertEqual(self.drop(text, [EVAL_PAGES_4, RESUME_0392]), (text, 0))
        by_name = "田村 朋美さんの所見は「見送りとする」です [2]。"
        self.assertEqual(self.drop(by_name, [RESUME_0392, EVAL_PAGES_4]), (by_name, 0))

    def test_second_real_chunk_of_the_same_shape(self):
        text = "APP-0417 の所見は「説明は具体的」です [1]。"
        self.assertEqual(self.drop(text, [EVAL_PAGES_5, RESUME_0417]), (text, 0))

    def test_a_chunk_that_starts_with_a_row_is_still_checked(self):
        self.assertEqual(self.drop("APP-0392 は監視を担当しています [1]。", [EVAL, RESUME_0392])[1], 1)

    def test_blank_lines_before_the_first_row_do_not_hide_it(self):
        chunk = ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "", "\n\n" + EVAL_CHUNK)
        self.assertEqual(self.drop("APP-0392 は監視を担当しています [1]。", [chunk, RESUME_0392])[1], 1)

    def test_nothing_to_drop(self):
        self.assertEqual(self.drop("", []), ("", 0))
        self.assertEqual(self.drop("経験があります [1]。", [RESUME_0391]), ("経験があります [1]。", 0))


EVAL_ONISHI_ISHIDA = ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0439 APP-0386",
                        "\tEV-007\tAPP-0439\tC-039\t大西 明日香\tREQ-042\t一次面接\t松本 里奈\n"
                        "\tEV-008\tAPP-0386\tC-115\t石田 裕太\tREQ-043\t一次面接\t吉田 誠\n")
EVAL_ICHIKAWA = ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0391",
                   "\tEV-001\tAPP-0391\tC-120\t市川 浩二\tREQ-042\t一次面接\t吉田 誠\n"
                   "\tEV-002\tAPP-0391\tC-120\t市川 浩二\tREQ-042\t二次面接\t吉田 誠\n")
EVAL_IWASAKI_ONISHI = ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0417 APP-0439",
                         "\tEV-006\tAPP-0417\tC-017\t岩崎 俊介\tREQ-042\t一次面接\t吉田 誠\n"
                         "\tEV-007\tAPP-0439\tC-039\t大西 明日香\tREQ-042\t一次面接\t松本 里奈\n")
Q03 = "REQ-042 の大西 明日香さんの一次面接の評価と、職務経歴書の内容を教えてください。"


class QuestionPersonTest(unittest.TestCase):
    """文に人がいないときは、質問に出てくる人をその文の人とする。"""

    EVIDENCE = [EVAL_ONISHI_ISHIDA, EVAL_ICHIKAWA, EVAL_IWASAKI_ONISHI]

    def drop(self, text, question, evidence=None):
        return azure_io.drop_mismatched_citations(text, self.EVIDENCE if evidence is None else evidence, question)

    def test_q03_the_row_of_another_person_goes_and_the_rows_with_the_person_stay(self):
        # [1]=大西と石田の行、[2]=市川の行、[3]=岩崎 俊介と大西の行
        self.assertEqual(self.drop("職務経歴書の内容は、資料にありません。[2][1][3]", Q03), ("職務経歴書の内容は、資料にありません。[1][3]", 1))

    def test_application_number_in_the_question_counts(self):
        self.assertEqual(self.drop("職務経歴書は、資料にありません。[2][1]", "APP-0439 の職務経歴書を教えてください。")[1], 1)

    def test_a_question_without_a_person_changes_nothing(self):
        text = "夜間の障害対応の経験がある人は、資料にありません。[2][1][3]"
        self.assertEqual(self.drop(text, "REQ-042 の応募者のうち、夜間の障害対応の経験がある人はだれですか。"), (text, 0))
        self.assertEqual(self.drop(text, ""), (text, 0))

    def test_a_person_in_the_sentence_wins_over_the_question(self):
        text = "APP-0391 の評価は高いです [2]。"
        self.assertEqual(self.drop(text, Q03), (text, 0))

    def test_the_person_of_the_previous_paragraph_is_not_carried_over(self):
        text = "市川 浩二さんは夜間の当番を担当しています [2]。\n\n経験は資料にありません。[1]"
        self.assertEqual(self.drop(text, "REQ-042 の応募者のうち、夜間の障害対応の経験がある人はだれですか。"), (text, 0))

    def test_documents_without_a_person_stay(self):
        text = "職務経歴書の内容は、資料にありません。[3]"
        self.assertEqual(self.drop(text, Q03, [EVAL_ONISHI_ISHIDA, EVAL_ICHIKAWA, JOB]), (text, 0))

    def test_names_in_the_question_that_the_documents_do_not_give_are_not_looked_at(self):
        text = "職務経歴書の内容は、資料にありません。[1]"
        self.assertEqual(self.drop(text, Q03, [EVAL_ICHIKAWA]), (text, 0))


SCAN_0391 = ev("SCAN-MEMO-APP-0391-2ND.pdf", "scan", "APP-0391", "二次面接メモ 総合評価 5 強く推奨")
Q04 = "REQ-042 の二次面接を受けた人のうち、評価が高かった人と見送りになった人で、評価の中身はどう違いましたか。"


class ParagraphPersonTest(unittest.TestCase):
    """文に人がいないときは、同じ段落（空行まで。箇条書きの行は続き）の、前の文に出てきた人を全部まとめて、その文の人とする。"""

    EVIDENCE = [EVAL_ICHIKAWA, RESUME_0392, JOB, SCAN_0391]    # [1]=市川の評価の行、[2]=田村の経歴書、[3]=求人票、[4]=市川の二次面接メモ

    def drop(self, text, question=Q04, evidence=None):
        return azure_io.drop_mismatched_citations(text, self.EVIDENCE if evidence is None else evidence, question)

    def test_q04_bullet_under_a_line_about_one_person_loses_the_memo_of_another(self):
        text = "一方、田村 朋美（APP-0392）は、\n- 二次面接メモでも総合評価は 2 で「見送り」でした。[2][4]"
        self.assertEqual(self.drop(text), ("一方、田村 朋美（APP-0392）は、\n- 二次面接メモでも総合評価は 2 で「見送り」でした。[2]", 1))

    def test_two_people_in_one_paragraph_keep_the_documents_of_both(self):
        text = "市川 浩二（APP-0391）と田村 朋美（APP-0392）は二次面接を受けました。\n- 二次面接メモの評価は分かれました。[1][2][4]"
        self.assertEqual(self.drop(text), (text, 0))

    def test_a_person_mentioned_later_does_not_count_for_an_earlier_sentence(self):
        text = "二次面接メモの評価は分かれました。[4]\n田村 朋美（APP-0392）は見送りでした。[2]"
        self.assertEqual(self.drop(text), (text, 0))

    def test_a_blank_line_starts_a_new_paragraph_that_falls_back_to_the_question(self):
        text = "田村 朋美（APP-0392）は見送りでした。[2]\n\n- 二次面接メモの評価は高いです。[4]"
        self.assertEqual(self.drop(text), (text, 0))
        self.assertEqual(self.drop(text, "APP-0392 の評価を教えてください。")[1], 1)

    def test_a_sentence_with_its_own_person_does_not_use_the_paragraph(self):
        text = "田村 朋美（APP-0392）は見送りでした。[2]\nAPP-0391 の二次面接メモは高評価です。[4]"
        self.assertEqual(self.drop(text), (text, 0))

    def test_q03_plain_3_the_sentences_after_the_one_naming_the_person_keep_her_resume(self):
        text = ("## 職務経歴書の内容\n"
                "- 資料にある職務経歴書は、**CV-APP-0392**で、**田村 朋美さん**のものです。[2]\n"
                "- 内容は、バックエンド開発6年の経験があります。[2]\n"
                "- 職歴として、API の開発を3年担当しています。[2]")
        evidence = [EVAL_ONISHI_ISHIDA, RESUME_0392]
        self.assertEqual(self.drop(text, Q03, evidence), (text, 0))

    def test_q03_plain_3_the_next_paragraph_about_the_asked_person_still_loses_the_other_resume(self):
        text = ("- 資料にある職務経歴書は、**CV-APP-0392**で、**田村 朋美さん**のものです。[2]\n\n"
                "## 分からないこと\n"
                "- 大西 明日香さん本人の**職務経歴書の内容は資料にありません**。[1][2]\n"
                "- 具体的な職歴は資料にありません。[1][2]")
        fixed, n = self.drop(text, Q03, [EVAL_ONISHI_ISHIDA, RESUME_0392])
        self.assertEqual(n, 2)
        self.assertIn("資料にありません**。[1]\n- 具体的な職歴は資料にありません。[1]", fixed)


class UnmappedNameTest(unittest.TestCase):
    """「姓 名さん／様」の形の名前があるのに、資料の名前の対応から引けないときは、質問や前の文の人に切り替えず、外さない。"""

    EVIDENCE = [RESUME_0392, EVAL_ONISHI_ISHIDA]

    def drop(self, text, question=Q03, evidence=None):
        return azure_io.drop_mismatched_citations(text, self.EVIDENCE if evidence is None else evidence, question)

    def test_unknown_person_does_not_fall_back_to_the_question(self):
        for text in ("山田 太郎さんの職務経歴書は資料にありません。[1]", "山田 太郎様の職務経歴書は資料にありません。[1]"):
            self.assertEqual(self.drop(text), (text, 0), text)

    def test_unknown_person_does_not_fall_back_to_the_paragraph(self):
        text = "田村 朋美（APP-0392）は見送りでした。[1]\n- 面接官の吉田 誠さんが担当しました。[2]"
        self.assertEqual(self.drop(text), (text, 0))

    def test_a_sentence_without_a_name_like_word_still_falls_back(self):
        self.assertEqual(self.drop("職務経歴書の内容は、資料にありません。[1]")[1], 1)

    def test_a_known_person_is_still_matched(self):
        self.assertEqual(self.drop("大西 明日香さんの職務経歴書は資料にありません。[1]")[1], 1)


class OwnersOnlyForEvaluationsTest(unittest.TestCase):
    """前の行の途中から始まるチャンクの扱いは、評価一覧だけ。経歴書の 2 つ目のチャンクやメールは、本文に番号がなくても欄の人で照らす。"""

    def drop(self, text, evidence):
        return azure_io.drop_mismatched_citations(text, evidence)

    def test_second_chunk_of_a_resume_is_checked_by_the_field(self):
        second = ev("CV-APP-0391", "resume", "APP-0391", "資格と研修\n基本情報技術者")
        self.assertEqual(self.drop("APP-0392 は監視を担当しています [1]。", [second]), ("APP-0392 は監視を担当しています。", 1))
        text = "APP-0391 は資格を持っています [1]。"
        self.assertEqual(self.drop(text, [second]), (text, 0))

    def test_mail_without_a_number_in_the_text_is_checked_by_the_field(self):
        mail = ev("MAIL-05_REQ-042_APP-0391", "mail", "APP-0391", "亀井様\n\nサンプルテックの採用担当です。")
        self.assertEqual(self.drop("APP-0392 は二次面接の連絡を受けました [1]。", [mail]), ("APP-0392 は二次面接の連絡を受けました。", 1))


SHEET_HEAD = ("面接評価\n\t評価ID\t応募番号\t人物キー\t候補者名\t求人番号\n"
              "\tEV-001\tAPP-0391\tC-120\t市川 浩二\tREQ-042\t一次面接\t吉田 誠\t推奨\n")


def sheet_head(chunk_id: str) -> dict:
    """評価一覧の、シートの見出しで始まるチャンク。chunk_id の終わりだけを変えて試す。"""
    return {**ev("EVAL-INTERVIEWS-2026-10.xlsx", "interview_evaluations", "APP-0391", SHEET_HEAD), "chunk_id": chunk_id}


class SheetHeadChunkTest(unittest.TestCase):
    """チャンク ID が _pages_0 で終わる評価一覧は、シートの見出しで始まる。続きのチャンクの扱い（人不明）にせず、本文の行の人で照らす。"""

    def test_the_first_chunk_is_checked_by_its_rows(self):
        hit = sheet_head("52250c6dea2f_aHR0cHM6Ly9z_pages_0")
        self.assertEqual(azure_io.drop_mismatched_citations("APP-0392 は監視を担当しています [1]。", [hit])[1], 1)
        text = "APP-0391 は一次面接で推奨されました [1]。"
        self.assertEqual(azure_io.drop_mismatched_citations(text, [hit]), (text, 0))

    def test_a_later_chunk_with_the_same_start_is_still_a_continuation(self):
        for chunk_id in ("52250c6dea2f_aHR0cHM6Ly9z_pages_1", "52250c6dea2f_aHR0cHM6Ly9z_pages_10", "x_pages_20"):
            hit = sheet_head(chunk_id)
            text = "APP-0392 は監視を担当しています [1]。"
            self.assertEqual(azure_io.drop_mismatched_citations(text, [hit]), (text, 0), chunk_id)


class AskMismatchTest(unittest.TestCase):
    def ask(self, final_text):
        llm = FakeLLM([call("filter_fields", {"req_id": "REQ-042"}), final(final_text)])
        return azure_io.ask("q", lambda s: None, llm=llm, searcher=fake_search)

    def test_q03_the_resume_of_another_person_is_not_listed_as_a_source(self):
        # filter_fields REQ-042 の資料は、[1]=CV-APP-0391、[2]=CV-APP-0392、[3]=求人票
        out = self.ask("APP-0391 は夜間の障害対応の経験があります [1]。APP-0392 の職務経歴書は資料にありません。[1]")
        self.assertEqual(out["answer"], "APP-0391 は夜間の障害対応の経験があります [1]。APP-0392 の職務経歴書は資料にありません。")
        self.assertEqual([s["doc_id"] for s in out["sources"]], ["CV-APP-0391"])
        self.assertEqual(out["warnings"], [])

    def test_removed_numbers_are_not_reported_on_the_screen(self):
        out = self.ask("APP-0392 の職務経歴書は資料を確認できませんでした。[1]")
        self.assertEqual(out["sources"], [])
        self.assertEqual(out["warnings"], [])

    def test_numbers_are_renumbered_after_the_drop(self):
        out = self.ask("APP-0392 の職務経歴書は資料にありません。[1] APP-0392 は監視を担当しています [2]。")
        self.assertEqual(out["answer"], "APP-0392 の職務経歴書は資料にありません。 APP-0392 は監視を担当しています [1]。")
        self.assertEqual(out["sources"][0]["doc_id"], "CV-APP-0392")

    def test_the_question_gives_the_person_of_a_sentence_without_one(self):
        llm = FakeLLM([call("filter_fields", {"req_id": "REQ-042"}), final("職務経歴書の内容は、資料にありません。[1]")])
        out = azure_io.ask("APP-0392 の職務経歴書の内容を教えてください。", lambda s: None, llm=llm, searcher=fake_search)
        self.assertEqual(out["answer"], "職務経歴書の内容は、資料にありません。")
        self.assertEqual(out["sources"], [])
        self.assertEqual(out["warnings"], [])

    def test_matching_numbers_stay(self):
        out = self.ask("APP-0391 は夜間の障害対応の経験があります [1]。")
        self.assertEqual(out["answer"], "APP-0391 は夜間の障害対応の経験があります [1]。")

    def test_content_without_any_number_after_the_drop_still_warns(self):
        out = self.ask("APP-0392 は監視を担当しています [1]。")
        self.assertEqual(out["answer"], "APP-0392 は監視を担当しています。")
        self.assertIn("答えに出典の番号がありません", out["warnings"])


class FakeSearchClient:
    """lib.clients.search_client が作る本物の SearchClient の代わり。何に向けて何を頼まれたかを記録する。"""
    seen = {}

    def __init__(self, endpoint, index_name, credential):
        FakeSearchClient.seen = {"endpoint": endpoint, "index": index_name, "key": credential.key}

    def search(self, text, **kwargs):
        FakeSearchClient.seen.update(text=text, **kwargs)
        return [{"chunk_id": "CV-APP-0391-c0", "doc_id": "CV-APP-0391", "kind": "resume", "req_id": "REQ-042",
                 "application_ids": "APP-0391", "title": "CV-APP-0391.docx", "chunk": "夜間の障害対応"}]


class FakeOpenAI:
    """openai.OpenAI の代わり。chat.completions.create に渡された引数を記録して、script の返事を順に返す。
    script が空なら、道具を使わずに「答えです [1]」と答える。"""
    seen = {}
    script = []

    def __init__(self, base_url, api_key):
        FakeOpenAI.seen = {"base_url": base_url, "api_key": api_key}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        FakeOpenAI.seen["options"] = kwargs
        return self

    def create(self, **kwargs):
        FakeOpenAI.seen["create"] = kwargs
        message = FakeOpenAI.script.pop(0) if FakeOpenAI.script else SimpleNamespace(content="答えです [1]", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))


class MemberSettingsTest(EnvCase):
    """メンバーの .env.local（検索だけのキー、Storage の項目なし）で、アシスタントが動く。Azure には接続しない。"""
    ENV_TEXT = MEMBER

    def setUp(self):
        super().setUp()
        FakeOpenAI.seen, FakeOpenAI.script = {}, []

    def test_assistant_uses_hr_index_and_no_storage(self):
        self.assertEqual(azure_io.INDEX, "hr-docs")
        self.assertNotIn("STORAGE", MEMBER)
        s = config.get_settings()            # need_storage なしで読める（Storage の項目がなくても止まらない）
        self.assertEqual((s.key_role, s.storage_connection_string, s.storage_container), ("query", "", ""))
        with mock.patch("azure.search.documents.SearchClient", FakeSearchClient):
            hits = azure_io.search("夜間", None, "kind eq 'resume'", 5)
        seen = FakeSearchClient.seen
        self.assertEqual((seen["endpoint"], seen["index"], seen["key"]), ("https://a.search.windows.net", "hr-docs", "FAKE-SRCH-d4e5f6"))
        self.assertEqual(seen["filter"], "allowed/any(a: search.in(a, 'role:recruiter')) and (kind eq 'resume')")
        self.assertEqual((seen["top"], seen["text"]), (5, "夜間"))
        self.assertEqual([h["chunk_id"] for h in hits], ["CV-APP-0391-c0"])

    def test_vector_search_uses_the_vector_field_of_the_index(self):
        with mock.patch("azure.search.documents.SearchClient", FakeSearchClient):
            azure_io.search(None, "夜間の対応", None, 8)
        seen = FakeSearchClient.seen
        self.assertEqual(seen["filter"], "allowed/any(a: search.in(a, 'role:recruiter'))")
        self.assertIsNone(seen["text"])
        self.assertEqual([q.fields for q in seen["vector_queries"]], [config.VECTOR_FIELD])

    def call_llm(self, process_env=None):
        """偽の OpenAI に 1 回頼み、(返事, 渡された引数) を返す。process_env は ASSISTANT_REASONING_EFFORT の値（なければ未設定）。"""
        with mock.patch.dict(os.environ):
            os.environ.pop("ASSISTANT_REASONING_EFFORT", None)
            if process_env is not None:
                os.environ["ASSISTANT_REASONING_EFFORT"] = process_env
            with mock.patch("openai.OpenAI", FakeOpenAI):
                out = azure_io.openai_llm([{"role": "user", "content": "q"}], azure_io.TOOLS, "auto")
        return out, FakeOpenAI.seen

    def test_llm_uses_the_chat_deployment(self):
        out, seen = self.call_llm()
        self.assertEqual(seen["base_url"], "https://b.azure.com/openai/v1/")
        self.assertEqual(seen["create"]["model"], "c")                 # .env.local のチャットのデプロイ
        self.assertEqual(seen["options"]["timeout"], azure_io.LLM_TIMEOUT)
        self.assertEqual(out, {"content": "答えです [1]", "tool_calls": [], "usage": {"input_tokens": 7, "output_tokens": 3}})

    def test_reasoning_effort_reads_env_local_then_default(self):
        """考える量：環境変数 → .env.local（一時のファイル）→ 既定 low。使えない値は、書いていないものとして次へ。"""
        line = "AZURE_OPENAI_REASONING_EFFORT=low\n"
        self.assertIn(line, MEMBER)

        def sent(env_line, process_env=None):
            self.write_env(MEMBER.replace(line, env_line))
            return self.call_llm(process_env)[1]["create"]["reasoning_effort"]

        # .env.local の値に従う（none も、medium も）
        self.assertEqual(sent("AZURE_OPENAI_REASONING_EFFORT=medium\n"), "medium")
        self.assertEqual(sent("AZURE_OPENAI_REASONING_EFFORT=none\n"), "none")
        # .env.local に書いていない・空・使えない値なら、既定の low
        self.assertEqual(sent(""), "low")
        self.assertEqual(sent("AZURE_OPENAI_REASONING_EFFORT=\n"), "low")
        self.assertEqual(sent("AZURE_OPENAI_REASONING_EFFORT=max\n"), "low")
        # 環境変数があれば、.env.local より先
        self.assertEqual(sent("AZURE_OPENAI_REASONING_EFFORT=none\n", process_env="high"), "high")
        self.assertEqual(sent("", process_env="medium"), "medium")
        # 環境変数が使えない値なら、.env.local の値へ
        self.assertEqual(sent("AZURE_OPENAI_REASONING_EFFORT=medium\n", process_env="max"), "medium")
        self.assertEqual(sent("", process_env="max"), "low")
        # 関数そのものの順番
        self.assertEqual(azure_io.reasoning_effort({}, "high"), "high")
        self.assertEqual(azure_io.reasoning_effort({"ASSISTANT_REASONING_EFFORT": "none"}, "high"), "none")
        self.assertEqual(azure_io.reasoning_effort({}, "max"), "low")

    def test_the_whole_loop_runs_with_member_settings(self):
        """通信する部品（Azure の検索と OpenAI の接続）は偽、設定の読み取り（lib.config）と道具の実行は本物。メンバーの設定で最後まで通る。"""
        tool_call = SimpleNamespace(id="t1", function=SimpleNamespace(name="filter_fields", arguments='{"req_id": "REQ-042"}'))
        FakeOpenAI.script = [SimpleNamespace(content="", tool_calls=[tool_call])]
        steps = []
        with mock.patch("azure.search.documents.SearchClient", FakeSearchClient), mock.patch("openai.OpenAI", FakeOpenAI):
            out = azure_io.ask("REQ-042 の夜間対応は？", steps.append)
        self.assertEqual(FakeSearchClient.seen["index"], "hr-docs")
        self.assertEqual([(s.no, s.people_after) for s in steps], [(1, 1)])
        self.assertEqual(out["answer"], "答えです [1]")
        self.assertEqual([s["title"] for s in out["sources"]], ["CV-APP-0391.docx"])
        self.assertEqual((out["warnings"], out["tokens"]), ([], {"input_tokens": 14, "output_tokens": 6}))


if __name__ == "__main__":
    unittest.main()
