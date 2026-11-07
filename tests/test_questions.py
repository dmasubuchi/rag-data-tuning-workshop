"""tools/evallib/questions.py（質問の形と確かめ）と tools/check_questions.py の試験。

通信しない。武将の既存の60問と bushou.json は本物を読む。人事・ホテルの質問は、試験の中で作った見本を使う
（本物の質問のファイルは、別の試験で確かめる）。一時のファイルは一時フォルダーに書く。
"""

import collections
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))

import check_questions  # noqa: E402
from evallib import questions as ev  # noqa: E402

DOCS = {"D1", "D2", "D3"}


def with_evidence(q):
    """answer_ids と hidden_ids の文書ごとに、見本の語句（evidence）を足した質問を返す（人事の質問に要る）。"""
    ids = list(dict.fromkeys(list(q.get("answer_ids", [])) + list(q.get("hidden_ids", []))))
    return {**q, "evidence": {doc_id: "見本の語句" for doc_id in ids}}


def sample(dataset):
    """TYPE_TARGETS どおりの、合格する質問の並び（人事は evidence つき。ホテルは condition の質問に condition、ほかに evidence）。"""
    out = []
    for kind, count in ev.TYPE_TARGETS[dataset].items():
        for _ in range(count):
            q = {"qid": f"{dataset}-{len(out) + 1:02d}", "question": "見本の質問", "type": kind,
                 "answer_ids": ["D1", "D2"] if kind == "multi-doc" else ["D1"]}
            if kind == "permission":
                q.update(answer_ids=[], as_role="role:employee", hidden_ids=["D2", "D3"])
            if dataset == "hr":
                q = with_evidence(q)
            elif dataset == "hotel":
                q = {**q, "condition": {"Rating": {"ge": 4.0}}} if kind == "condition" else with_evidence(q)
            out.append(q)
    return out


def valid(dataset, questions):
    return ev.validate(dataset, questions, known_ids=DOCS)


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = check_questions.main(list(args))
        except SystemExit as exit_:   # argparse の誤り
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class SengokuTest(unittest.TestCase):
    def setUp(self):
        self.questions = ev.load_questions(ev.QUESTION_FILES["sengoku"])
        self.ids = ev.ids_of("sengoku", ev.load_data("sengoku"))

    def test_sengoku_questions_pass(self):
        self.assertEqual(len(self.questions), 60)
        self.assertEqual(len(self.ids), 150)
        self.assertEqual(ev.validate("sengoku", self.questions, known_ids=self.ids), [])

    def test_intent_is_read_as_type(self):
        self.assertTrue(all(q["type"] == q["intent"] for q in self.questions))
        self.assertEqual({q["type"] for q in self.questions}, set(ev.SENGOKU_TYPES))

    def test_sengoku_counts_are_not_enforced(self):
        self.assertNotIn("sengoku", ev.TYPE_TARGETS)
        self.assertEqual(ev.validate("sengoku", self.questions[:7], known_ids=self.ids), [])

    def test_sengoku_unknown_type_is_reported(self):
        bad = [{**self.questions[0], "type": "paraphrase"}]
        problems = ev.validate("sengoku", bad, known_ids=self.ids)
        self.assertEqual(len(problems), 1)
        self.assertIn("q01", problems[0])
        self.assertIn("paraphrase", problems[0])


class ValidateTest(unittest.TestCase):
    def test_targets_match_the_brief(self):
        self.assertEqual(ev.TYPE_TARGETS["hr"], {"paraphrase": 12, "proper-noun": 10, "numeric": 10,
                                                 "multi-doc": 10, "scan": 6, "permission": 12})
        self.assertEqual(ev.TYPE_TARGETS["hotel"], {"paraphrase": 10, "proper-noun": 6, "condition": 10,
                                                    "ja-en": 6, "amenity": 8})
        self.assertEqual(sum(ev.TYPE_TARGETS["hr"].values()), 60)
        self.assertEqual(sum(ev.TYPE_TARGETS["hotel"].values()), 40)
        self.assertEqual(ev.DATASETS, ("sengoku", "hr", "hotel"))

    def test_samples_pass(self):
        for dataset in ("hr", "hotel"):
            with self.subTest(dataset):
                self.assertEqual(valid(dataset, sample(dataset)), [])

    def test_duplicate_qid_is_reported(self):
        questions = sample("hr")
        questions[4]["qid"] = questions[1]["qid"]
        problems = valid("hr", questions)
        self.assertEqual(len(problems), 1)
        self.assertIn("hr-02", problems[0])
        self.assertIn("重複", problems[0])
        self.assertIn("2・5 番目", problems[0])

    def test_unknown_answer_id_is_reported(self):
        questions = sample("hr")
        questions[0]["answer_ids"] = ["D1", "NOPE-1"]
        problems = valid("hr", questions)
        self.assertEqual(len(problems), 1)
        self.assertIn("hr-01", problems[0])
        self.assertIn("NOPE-1", problems[0])

    def test_unknown_hidden_id_is_reported(self):
        questions = sample("hr")
        questions[-1] = with_evidence({**questions[-1], "hidden_ids": ["D2", "NOPE-2"]})
        problems = valid("hr", questions)
        self.assertEqual(len(problems), 1)
        self.assertIn("hidden_ids", problems[0])
        self.assertIn("NOPE-2", problems[0])

    def test_type_counts_are_checked_against_targets(self):
        questions = sample("hr")
        questions[0]["type"] = "numeric"   # paraphrase が 11、numeric が 11
        problems = valid("hr", questions)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("paraphrase" in p and "11 問" in p and "目標 12 問" in p for p in problems))
        self.assertTrue(any("numeric" in p and "11 問" in p and "目標 10 問" in p for p in problems))
        # 足りないだけ・多いだけも
        problems = valid("hotel", sample("hotel")[:-1])
        self.assertEqual(len(problems), 1)
        self.assertIn("amenity は 7 問です（目標 8 問）", problems[0])
        problems = valid("hotel", sample("hotel") + [{**sample("hotel")[0], "qid": "extra"}])
        self.assertEqual(len(problems), 1)
        self.assertIn("paraphrase は 11 問です（目標 10 問）", problems[0])

    def test_type_not_in_targets_is_reported(self):
        questions = sample("hotel")
        questions[0]["type"] = "keyword-wins"
        problems = valid("hotel", questions)
        self.assertTrue(any("hotel-01" in p and "keyword-wins" in p and "使えません" in p for p in problems))

    def test_permission_needs_as_role_and_hidden_ids(self):
        base = {"qid": "p1", "question": "見えない文書を聞く", "type": "permission", "answer_ids": []}
        for name, extra, word in (
            ("as_role がない", {"hidden_ids": ["D2"]}, "as_role"),
            ("as_role が空", {"as_role": " ", "hidden_ids": ["D2"]}, "as_role"),
            ("hidden_ids がない", {"as_role": "role:employee"}, "hidden_ids"),
            ("hidden_ids が空", {"as_role": "role:employee", "hidden_ids": []}, "hidden_ids"),
        ):
            with self.subTest(name):
                problems = ev.validate("hr", [{**base, **extra}], known_ids=DOCS)
                self.assertTrue(any("p1" in p and "permission" in p and word in p for p in problems), problems)
        ok = with_evidence({**base, "as_role": "role:employee", "hidden_ids": ["D2"]})
        problems = ev.validate("hr", [ok], known_ids=DOCS)
        self.assertFalse([p for p in problems if "p1" in p], problems)   # 種類の数だけが残る

    def test_empty_answer_ids_are_allowed(self):
        questions = sample("hr")
        self.assertEqual([q for q in questions if q["type"] == "permission"][0]["answer_ids"], [])
        self.assertEqual(valid("hr", questions), [])

    def test_empty_answer_ids_only_for_permission(self):
        for dataset, kind in (("hr", "numeric"), ("hotel", "amenity"), ("sengoku", "climax")):
            with self.subTest(kind):
                bad = {"qid": "e1", "question": "答えがない", "type": kind, "answer_ids": [], "evidence": {}}
                problems = ev.validate(dataset, [bad], known_ids=DOCS)
                hits = [p for p in problems if p.startswith("e1：")]
                self.assertEqual(len(hits), 1, problems)
                self.assertIn("answer_ids", hits[0])
                self.assertIn(kind, hits[0])
                self.assertIn("permission だけ", hits[0])
        ok = with_evidence({"qid": "e2", "question": "見えない文書を聞く", "type": "permission", "answer_ids": [],
                            "as_role": "role:employee", "hidden_ids": ["D2"]})
        self.assertFalse([p for p in ev.validate("hr", [ok], known_ids=DOCS) if p.startswith("e2：")])

    def test_field_type_errors_say_how_to_write_them(self):
        cases = {
            "qid が数": ({"qid": 5, "question": "q", "type": "climax", "answer_ids": ["D1"]}, "qid は文字列で書きます"),
            "qid が並び": ({"qid": ["a"], "question": "q", "type": "climax", "answer_ids": ["D1"]},
                         "qid は文字列で書きます"),
            "question が数": ({"qid": "x", "question": 3, "type": "climax", "answer_ids": ["D1"]},
                            "question は文字列で書きます"),
            "type が並び": ({"qid": "x", "question": "q", "type": ["climax"], "answer_ids": ["D1"]},
                          "type は文字列で書きます"),
            "type が数": ({"qid": "x", "question": "q", "type": 1, "answer_ids": ["D1"]}, "type は文字列で書きます"),
        }
        for name, (q, word) in cases.items():
            with self.subTest(name):
                problems = ev.validate("sengoku", [q], known_ids=DOCS)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(word, problems[0])
                self.assertNotIn("がありません", problems[0])   # 「ない」のではなく「型が違う」と言う
        # 本当にないときは今までどおり「ありません」
        problems = ev.validate("sengoku", [{"question": "q", "type": "climax", "answer_ids": ["D1"]}], known_ids=DOCS)
        self.assertIn("qid がありません", problems[0])

    def test_answer_and_hidden_ids_must_not_overlap(self):
        questions = sample("hr")
        questions[-1]["answer_ids"] = ["D2"]
        problems = valid("hr", questions)
        self.assertEqual(len(problems), 1)
        self.assertIn("同じ ID", problems[0])
        self.assertIn("D2", problems[0])

    def test_missing_and_bad_fields_are_reported(self):
        cases = {
            "qid がない": ({"question": "q", "type": "climax", "answer_ids": ["D1"]}, "1 番目：qid"),
            "qid の空白": ({"qid": "a b", "question": "q", "type": "climax", "answer_ids": ["D1"]}, "空白"),
            "question がない": ({"qid": "x", "type": "climax", "answer_ids": ["D1"]}, "x：question"),
            "type がない": ({"qid": "x", "question": "q", "answer_ids": ["D1"]}, "x：type"),
            "answer_ids がない": ({"qid": "x", "question": "q", "type": "climax"}, "x：answer_ids"),
            "answer_ids が文字列": ({"qid": "x", "question": "q", "type": "climax", "answer_ids": "D1"},
                                  "ID の並び"),
            "answer_ids の重複": ({"qid": "x", "question": "q", "type": "climax", "answer_ids": ["D1", "D1"]},
                                "2 回"),
            "why が文字列でない": ({"qid": "x", "question": "q", "type": "climax", "answer_ids": ["D1"], "why": 1},
                                "why"),
        }
        for name, (q, word) in cases.items():
            with self.subTest(name):
                problems = ev.validate("sengoku", [q], known_ids=DOCS)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(word, problems[0])

    def test_non_question_item_is_reported(self):
        problems = ev.validate("sengoku", ["文字列"], known_ids=DOCS)
        self.assertEqual(len(problems), 1)
        self.assertIn("1 番目", problems[0])
        self.assertEqual(ev.validate("sengoku", {"qid": "x"}, known_ids=DOCS), ["質問は並び（[ ... ]）で書きます"])

    def test_unknown_dataset_raises(self):
        with self.assertRaises(ValueError):
            ev.validate("nope", [], known_ids=DOCS)

    def test_dataset_checks_plug_in(self):
        calls = []

        def extra(questions, *, known_ids, data):
            calls.append((questions, known_ids, data))
            return ["データ固有の問題"]

        questions = sample("hr") + ["質問でないもの"]
        with mock.patch.dict(ev.DATASET_CHECKS, {"hr": [extra]}):
            problems = ev.validate("hr", questions, known_ids=DOCS, data={"manifest": 1})
        self.assertIn("データ固有の問題", problems)
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(isinstance(q, dict) for q in calls[0][0]))   # 辞書だけが渡る
        self.assertEqual(len(calls[0][0]), 60)
        self.assertEqual(calls[0][1], DOCS)
        self.assertEqual(calls[0][2], {"manifest": 1})
        # 別のデータの確かめは呼ばれない
        calls.clear()
        with mock.patch.dict(ev.DATASET_CHECKS, {"hr": [extra]}):
            ev.validate("hotel", sample("hotel"), known_ids=DOCS)
        self.assertEqual(calls, [])

    def test_dataset_check_decorator_registers(self):
        with mock.patch.dict(ev.DATASET_CHECKS, {"hotel": []}):
            @ev.dataset_check("hotel")
            def mine(questions, *, known_ids, data):
                return ["足した確かめ"]

            self.assertEqual(ev.DATASET_CHECKS["hotel"], [mine])
            self.assertIn("足した確かめ", valid("hotel", sample("hotel")))


def hr_data():
    """人事の確かめの試験用の、小さな manifest（求人票・経歴書・スキャン）。"""
    return {"files": [
        {"doc_id": "JOB-1", "kind": "job_posting", "ocr_required": False},
        {"doc_id": "JOB-2", "kind": "job_posting", "ocr_required": False},
        {"doc_id": "CV-1", "kind": "resume", "ocr_required": False},
        {"doc_id": "MAIL-1", "kind": "mail", "ocr_required": False},
        {"doc_id": "SCAN-1", "kind": "scan", "ocr_required": True},
    ]}


def hr_check(questions):
    """evidence のない質問には、見本の語句を足してから、人事の確かめにかける（evidence 以外の確かめを 1 つずつ見るため）。"""
    data = hr_data()
    questions = [q if "evidence" in q else with_evidence(q) for q in questions]
    return ev.check_hr(questions, known_ids=ev.ids_of("hr", data), data=data)


class HrCheckTest(unittest.TestCase):
    """人事に固有の確かめ（@dataset_check("hr")）。小さな manifest で、1 つずつ。"""

    def setUp(self):
        # 本物の文書の本文のもとは見ない（ここの文書は試験用の名前）。語句を探す確かめは HrEvidenceTest が見る
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(ev, "HR_CONTENT_DIR", Path(self.tmp.name) / "none")
        patch.start()
        self.addCleanup(patch.stop)

    def perm(self, **extra):
        q = {"qid": "p1", "question": "見えない文書を聞く", "type": "permission", "answer_ids": [],
             "as_role": "role:employee", "hidden_ids": ["CV-1"]}
        q.update(extra)
        return q

    def test_check_is_registered_for_hr_only(self):
        self.assertIn(ev.check_hr, ev.DATASET_CHECKS["hr"])
        self.assertNotIn(ev.check_hr, ev.DATASET_CHECKS["hotel"])
        self.assertNotIn(ev.check_hr, ev.DATASET_CHECKS["sengoku"])

    def test_valid_permission_passes(self):
        self.assertEqual(hr_check([self.perm()]), [])
        self.assertEqual(hr_check([self.perm(answer_ids=["JOB-1"], hidden_ids=["CV-1", "MAIL-1", "SCAN-1"])]), [])

    def test_permission_role_must_be_employee(self):
        for role in ("role:recruiter", "role:interviewer", "user:U-1006"):
            with self.subTest(role):
                problems = hr_check([self.perm(as_role=role)])
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("p1", problems[0])
                self.assertIn("role:employee", problems[0])
                self.assertIn(role, problems[0])

    def test_permission_hidden_ids_must_not_be_job_postings(self):
        problems = hr_check([self.perm(hidden_ids=["CV-1", "JOB-2"])])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("hidden_ids", problems[0])
        self.assertIn("JOB-2", problems[0])
        self.assertIn("求人票", problems[0])

    def test_permission_answer_ids_must_be_job_postings(self):
        problems = hr_check([self.perm(answer_ids=["JOB-1", "MAIL-1"])])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("answer_ids", problems[0])
        self.assertIn("MAIL-1", problems[0])
        self.assertNotIn("JOB-1", problems[0])

    def test_scan_needs_an_ocr_document_in_answer_ids(self):
        scan = {"qid": "s1", "question": "スキャンにだけ書いてある", "type": "scan", "answer_ids": ["SCAN-1"]}
        self.assertEqual(hr_check([scan]), [])
        self.assertEqual(hr_check([{**scan, "answer_ids": ["MAIL-1", "SCAN-1"]}]), [])   # ほかの文書が混ざってよい
        for ids in (["MAIL-1"], ["JOB-1", "CV-1"]):
            with self.subTest(ids):
                problems = hr_check([{**scan, "answer_ids": ids}])
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("s1", problems[0])
                self.assertIn("OCR", problems[0])

    def test_multi_doc_needs_two_or_more_answers(self):
        multi = {"qid": "m1", "question": "2つの文書にまたがる", "type": "multi-doc", "answer_ids": ["JOB-1", "CV-1"]}
        self.assertEqual(hr_check([multi]), [])
        for ids in (["JOB-1"], ["JOB-1", "JOB-1"]):
            with self.subTest(ids):
                problems = hr_check([{**multi, "answer_ids": ids}])
                self.assertTrue(any("m1" in p and "2 件以上" in p for p in problems), problems)

    def test_other_types_are_not_restricted(self):
        questions = [{"qid": f"o{i}", "question": "q", "type": kind, "answer_ids": ["MAIL-1"]}
                     for i, kind in enumerate(("paraphrase", "proper-noun", "numeric"))]
        self.assertEqual(hr_check(questions), [])

    def test_without_manifest_only_manifest_free_checks_run(self):
        # data が None：文書の種類・OCR は分からないので飛ばす。multi-doc の数は、データがなくても確かめる
        questions = [with_evidence(q) for q in (
            self.perm(as_role="role:recruiter", hidden_ids=["JOB-2"]),
            {"qid": "s1", "question": "q", "type": "scan", "answer_ids": ["MAIL-1"]},
            {"qid": "m1", "question": "q", "type": "multi-doc", "answer_ids": ["JOB-1"]})]
        problems = ev.check_hr(questions, known_ids={"JOB-1", "JOB-2", "MAIL-1"}, data=None)
        self.assertTrue(any("m1" in p for p in problems), problems)
        self.assertTrue(any("p1" in p and "role:employee" in p for p in problems), problems)   # 役割は manifest なしでも
        self.assertFalse(any("s1" in p for p in problems), problems)
        self.assertFalse(any("hidden_ids" in p for p in problems), problems)   # 求人票かどうかは manifest がないと見ない

    def test_validate_runs_the_hr_check_through_the_cli_data(self):
        # validate に manifest（data）を渡すと、人事の確かめが走る
        questions = sample("hr")
        data = hr_data()
        known = ev.ids_of("hr", data)
        for q in questions:
            q["answer_ids"] = ["JOB-1", "CV-1"] if q["type"] == "multi-doc" else \
                ["SCAN-1"] if q["type"] == "scan" else q["answer_ids"]
            if q["type"] == "permission":
                q["answer_ids"], q["hidden_ids"] = [], ["CV-1", "MAIL-1"]
            elif q["type"] not in ("multi-doc", "scan"):
                q["answer_ids"] = ["MAIL-1"]
        questions = [with_evidence(q) for q in questions]
        with mock.patch.object(ev, "HR_CONTENT_DIR", Path(self.tmp.name) / "none"):
            self.assertEqual(ev.validate("hr", questions, known_ids=known, data=data), [])
            questions[-1] = with_evidence({**questions[-1], "hidden_ids": ["JOB-1"]})   # permission の hidden_ids に求人票
            problems = ev.validate("hr", questions, known_ids=known, data=data)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("JOB-1", problems[0])


class HrEvidenceTest(unittest.TestCase):
    """人事の evidence（答えの文書ごとの、本文にそのまま出る語句）。小さな「本文のもと」のフォルダーで確かめる。"""

    DATA = {"files": [
        {"doc_id": "JOB-1", "kind": "job_posting", "ocr_required": False},
        {"doc_id": "CV-1", "kind": "resume", "ocr_required": False},
        {"doc_id": "MAIL-1", "kind": "mail", "ocr_required": False},
        {"doc_id": "EVAL-1", "kind": "interview_evaluations", "ocr_required": False},
        {"doc_id": "SCAN-1", "kind": "scan", "ocr_required": True},
        {"doc_id": "SCAN-2", "kind": "scan", "ocr_required": True},
    ]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.content = root / "content"
        for name in ("jobs", "resumes"):
            (self.content / name).mkdir(parents=True)
        (self.content / "jobs" / "JOB-1.md").write_text("# 求人票\n\n## 年収\n\n600万円から\n800万円。経験により決定します。\n", encoding="utf-8")
        (self.content / "resumes" / "CV-1.md").write_text("氏名: 山田 太郎\n自己PR: 現年収は700万円です。\n", encoding="utf-8")
        self.write("mail.json", {"mails": [{"id": "MAIL-1", "subject": "【REQ-1】面接のご案内", "body": "二次面接は東京本社で行います。"}]})
        self.write("evaluations.json", {"rows": [{"evaluation_id": "EV-1", "comment": "必須条件を満たす。推奨する。"}]})
        self.write("source_ats.json", {"persons": [{"display_name": "鈴木 花子"}]})
        self.write("scans.json", {"scans": [{"id": "SCAN-1", "kind": "memo", "what": "手書きの面接メモ（2026-10-22）"},
                                            {"id": "SCAN-2", "kind": "offer", "what": "内定承諾書"}]})
        (root / "make_scans.py").write_text(
            'def make_memo():\n    items = ["・懸念：特になし。入社時期は要確認"]\n    label = "確認印"\n\n\n'
            'def make_offer():\n    items = [("入社予定日", "2026年12月1日")]\n\n\ndef main():\n    pass\n\n\n'
            'def scan_facts():\n    return {"SCAN-1": {"stamp": "2026.10.26", "application_id": "APP-0001"},\n'
            '            "SCAN-2": {"sent_header": "2026-10-28 10:52　FAX　P.1/3"}}\n', encoding="utf-8")
        patch = mock.patch.object(ev, "HR_CONTENT_DIR", self.content)
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, name, content):
        (self.content / name).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    def check(self, question):
        known = ev.ids_of("hr", self.DATA)
        return ev.check_hr([question], known_ids=known, data=self.DATA)

    def question(self, **extra):
        q = {"qid": "q1", "question": "年収は", "type": "numeric", "answer_ids": ["JOB-1"],
             "evidence": {"JOB-1": "600万円から800万円"}}
        q.update(extra)
        return q

    def test_phrases_found_in_each_kind_of_source_pass(self):
        q = {"qid": "m1", "question": "いくつもの文書", "type": "multi-doc",
             "answer_ids": ["JOB-1", "CV-1", "MAIL-1", "EVAL-1", "SCAN-1", "SCAN-2"],
             "evidence": {"JOB-1": "600万円から800万円",        # 折り返しの空白があっても探せる
                          "CV-1": "現年収は700万円です",
                          "MAIL-1": "二次面接は東京本社で行います",
                          "EVAL-1": "必須条件を満たす。推奨する",    # evaluations.json
                          "SCAN-1": "確認印",                       # make_scans.py の make_memo の中
                          "SCAN-2": "2026年12月1日"}}               # make_offer の中
        self.assertEqual(self.check(q), [])
        # 件名、台帳（source_ats.json）、scans.json の記述にある語句でもよい
        q["evidence"].update({"MAIL-1": "面接のご案内", "EVAL-1": "鈴木 花子", "SCAN-1": "手書きの面接メモ（2026-10-22）"})
        self.assertEqual(self.check(q), [])

    def test_wrong_phrase_is_reported(self):
        problems = self.check(self.question(evidence={"JOB-1": "650万円から950万円"}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("q1", problems[0])
        self.assertIn("JOB-1", problems[0])
        self.assertIn("650万円から950万円", problems[0])
        self.assertIn("jobs/JOB-1.md", problems[0])
        # 別の文書の語句は、その文書にないので問題
        problems = self.check(self.question(evidence={"JOB-1": "現年収は700万円です"}))
        self.assertEqual(len(problems), 1, problems)

    def test_scan_phrase_must_come_from_that_scans_own_function(self):
        base = {"qid": "s1", "question": "スキャン", "type": "scan", "answer_ids": ["SCAN-1"]}
        self.assertEqual(self.check({**base, "evidence": {"SCAN-1": "入社時期は要確認"}}), [])
        problems = self.check({**base, "evidence": {"SCAN-1": "2026年12月1日"}})   # SCAN-2（make_offer）の文字
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("SCAN-1", problems[0])
        self.assertIn("2026年12月1日", problems[0])

    def test_missing_evidence_is_reported(self):
        # 項目がない
        q = self.question()
        del q["evidence"]
        problems = self.check(q)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("evidence がありません", problems[0])
        # 形が違う
        problems = self.check(self.question(evidence=["600万円から800万円"]))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("evidence は", problems[0])
        # 文書の分が足りない
        q = self.question(type="multi-doc", answer_ids=["JOB-1", "CV-1"])
        problems = self.check(q)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("CV-1", problems[0])
        self.assertIn("語句がありません", problems[0])
        # 語句が空
        problems = self.check(self.question(evidence={"JOB-1": " "}))
        self.assertTrue(any("JOB-1" in p and "語句がありません" in p for p in problems), problems)
        # permission は hidden_ids の文書にも要る
        perm = {"qid": "p1", "question": "見えない", "type": "permission", "answer_ids": [], "as_role": "role:employee",
                "hidden_ids": ["CV-1", "MAIL-1"], "evidence": {"CV-1": "現年収は700万円です"}}
        problems = self.check(perm)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("MAIL-1", problems[0])

    def test_evidence_for_a_document_not_in_the_question_is_reported(self):
        problems = self.check(self.question(evidence={"JOB-1": "600万円から800万円", "CV-1": "現年収は700万円です"}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("CV-1", problems[0])
        self.assertIn("answer_ids にも hidden_ids にもありません", problems[0])

    def test_unreadable_source_is_reported_not_crashed(self):
        (self.content / "jobs" / "JOB-1.md").unlink()
        problems = self.check(self.question())
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("語句を探せません", problems[0])
        (self.content / "mail.json").write_text("{", encoding="utf-8")
        q = {"qid": "q2", "question": "メール", "type": "numeric", "answer_ids": ["MAIL-1"], "evidence": {"MAIL-1": "x"}}
        problems = self.check(q)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("mail.json", problems[0])

    def test_phrase_search_is_skipped_when_the_content_folder_is_missing(self):
        with mock.patch.object(ev, "HR_CONTENT_DIR", Path(self.tmp.name) / "no-such-folder"):
            self.assertEqual(self.check(self.question(evidence={"JOB-1": "どこにもない語句"})), [])
            # 語句がそろっているかは、フォルダーがなくても見る
            q = self.question()
            del q["evidence"]
            self.assertEqual(len(self.check(q)), 1)

    def test_phrase_search_is_skipped_without_manifest(self):
        questions = [self.question(evidence={"JOB-1": "どこにもない語句"})]
        self.assertEqual(ev.check_hr(questions, known_ids={"JOB-1"}, data=None), [])

    def test_evidence_for_unknown_ids_is_not_demanded_twice(self):
        # 文書にない ID は共通の確かめが言う。evidence には求めない
        q = self.question(answer_ids=["JOB-1", "NOPE-1"])
        self.assertEqual(self.check(q), [])

    def scan_question(self, doc_id, phrase):
        return {"qid": "s1", "question": "スキャン", "type": "scan", "answer_ids": [doc_id], "evidence": {doc_id: phrase}}

    def test_scan_phrase_may_come_from_scan_facts_of_that_scan(self):
        # 画像に見える文字（受付印の日付・FAX の上部の日時）は、scan_facts() の、そのスキャンの分から探す
        self.assertEqual(self.check(self.scan_question("SCAN-1", "2026.10.26")), [])
        self.assertEqual(self.check(self.scan_question("SCAN-1", "APP-0001")), [])
        self.assertEqual(self.check(self.scan_question("SCAN-2", "10:52")), [])
        problems = self.check(self.scan_question("SCAN-2", "2026.10.26"))   # SCAN-1 の受付印の日付
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("scans.json・make_scans.py・scan_facts()", problems[0])
        self.assertNotIn("※", problems[0])

    def test_scan_facts_that_cannot_be_read_are_named_in_the_problem(self):
        script = self.content.parent / "make_scans.py"
        script.write_text("import no_such_module_for_this_test\n\n\ndef scan_facts():\n    return {}\n", encoding="utf-8")
        problems = self.check(self.scan_question("SCAN-1", "2026.10.26"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("scan_facts() は読めませんでした", problems[0])
        self.assertIn("ModuleNotFoundError", problems[0])
        # 読めなくても、これまでの探し方で見つかる語句は通る
        self.assertEqual(self.check(self.scan_question("SCAN-1", "手書きの面接メモ")), [])
        # scan_facts() がない make_scans.py も同じ
        script.write_text("def make_memo():\n    pass\n", encoding="utf-8")
        problems = self.check(self.scan_question("SCAN-1", "2026.10.26"))
        self.assertIn("make_scans.py に scan_facts() がありません", problems[0])

    def test_reading_scan_facts_leaves_no_trace_in_the_process(self):
        script = self.content.parent / "make_scans.py"
        (self.content.parent / "helper_for_this_test.py").write_text("STAMP = '2026.10.26'\n", encoding="utf-8")
        script.write_text("from helper_for_this_test import STAMP\n\n\ndef scan_facts():\n    return {'SCAN-1': {'stamp': STAMP}}\n",
                          encoding="utf-8")
        self.assertEqual(self.check(self.scan_question("SCAN-1", "2026.10.26")), [])
        self.assertNotIn("helper_for_this_test", sys.modules)
        self.assertNotIn("_evallib_make_scans", sys.modules)
        self.assertNotIn(str(self.content.parent), sys.path)

    def test_unknown_scan_kind_is_named_in_the_problem(self):
        self.write("scans.json", {"scans": [{"id": "SCAN-1", "kind": "receipt", "what": "領収書"}]})
        problems = self.check(self.scan_question("SCAN-1", "どこにもない語句"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("スキャンの種類「receipt」", problems[0])
        self.assertIn("make_receipt", problems[0])
        # 種類が分からなくても、scans.json の記述にある語句は通る
        self.assertEqual(self.check(self.scan_question("SCAN-1", "領収書")), [])

    def test_wrong_top_level_shape_is_a_data_error_not_a_crash(self):
        for name, doc_id, key in (("mail.json", "MAIL-1", "mails"), ("scans.json", "SCAN-1", "scans")):
            for wrong in ([], "文字列", {key: "並びではない"}, {"other": []}):
                with self.subTest(name=name, wrong=wrong):
                    self.write(name, wrong)
                    kind = "mail" if key == "mails" else "scan"
                    with self.assertRaisesRegex(ev.DataError, rf"{name} の一番上の形が違います（.*{key}"):
                        ev.hr_source_text(doc_id, {"kind": kind}, self.content)
                    q = {**self.scan_question(doc_id, "x"), "type": "scan" if kind == "scan" else "numeric"}
                    problems = self.check(q)
                    self.assertEqual(len(problems), 1, problems)
                    self.assertIn(f"{name} の一番上の形が違います", problems[0])


class HrQuestionsTest(unittest.TestCase):
    """本物の evaluation/hr_questions.json（人事の 60 問）を、本物の manifest で確かめる。"""

    @classmethod
    def setUpClass(cls):
        cls.questions = ev.load_questions(ev.QUESTION_FILES["hr"])
        cls.data = ev.load_data("hr")
        cls.ids = ev.ids_of("hr", cls.data)
        cls.files = {f["doc_id"]: f for f in cls.data["files"]}

    def test_hr_questions_pass(self):
        self.assertEqual(len(self.questions), 60)
        self.assertEqual(ev.validate("hr", self.questions, known_ids=self.ids, data=self.data), [])
        # 種類の数（報告どおり。目標と同じ）
        counts = collections.Counter(q["type"] for q in self.questions)
        self.assertEqual(dict(counts), {"paraphrase": 12, "proper-noun": 10, "numeric": 10, "multi-doc": 10,
                                        "scan": 6, "permission": 12})
        self.assertEqual(dict(counts), ev.TYPE_TARGETS["hr"])
        # ID はすべて manifest にある
        for q in self.questions:
            for name in ("answer_ids", "hidden_ids"):
                for doc_id in q.get(name, []):
                    self.assertIn(doc_id, self.ids, f"{q['qid']} の {name}")
        # qid は hr-01〜hr-60 で、1 問ずつ why がある
        self.assertEqual([q["qid"] for q in self.questions], [f"hr-{n:02d}" for n in range(1, 61)])
        for q in self.questions:
            self.assertTrue(q.get("why", "").strip(), f"{q['qid']} に why がありません")

    def test_hr_permission_hidden_ids_are_not_job_postings(self):
        permission = [q for q in self.questions if q["type"] == "permission"]
        self.assertEqual(len(permission), 12)
        for q in permission:
            self.assertEqual(q["as_role"], "role:employee", q["qid"])
            self.assertTrue(q["hidden_ids"], q["qid"])
            for doc_id in q["hidden_ids"]:
                self.assertNotEqual(self.files[doc_id]["kind"], "job_posting", f"{q['qid']} の hidden_ids {doc_id}")
            for doc_id in q["answer_ids"]:
                self.assertEqual(self.files[doc_id]["kind"], "job_posting", f"{q['qid']} の answer_ids {doc_id}")
        # 答えが空の質問（漏れだけを数える）と、求人票で答えられる部分がある質問の両方がある
        self.assertTrue(any(not q["answer_ids"] for q in permission))
        self.assertTrue(any(q["answer_ids"] for q in permission))

    def test_hr_evidence_is_complete_and_found_in_the_source_texts(self):
        self.assertTrue(ev.HR_CONTENT_DIR.is_dir(), "本文のもと（applied/data/_build/content）がないと、語句の確かめが飛ばされる")
        for q in self.questions:
            ids = set(q["answer_ids"]) | set(q.get("hidden_ids", []))
            self.assertEqual(set(q["evidence"]), ids, q["qid"])   # 文書ごとに 1 つ。余りもない
            for doc_id, phrase in q["evidence"].items():
                text, _ = ev.hr_source_text(doc_id, self.files[doc_id], ev.HR_CONTENT_DIR)
                self.assertIn(ev._squash(phrase), ev._squash(text), f"{q['qid']} の evidence {doc_id}")

    def test_hr_order_mixes_the_types(self):
        types = [q["type"] for q in self.questions]
        order = list(ev.TYPE_TARGETS["hr"])
        # hr-01〜hr-36 は、6 問ごとに 6 つの種類が 1 回ずつ。hr-37 以降は scan がなく、最後の 4 問は paraphrase と permission
        for start in range(0, 36, 6):
            self.assertEqual(sorted(types[start:start + 6]), sorted(order), f"hr-{start + 1:02d} から 6 問")
        self.assertNotIn("scan", types[36:])
        self.assertEqual(set(types[56:]), {"paraphrase", "permission"})

    def test_hr_scan_questions_include_an_ocr_document(self):
        scan = [q for q in self.questions if q["type"] == "scan"]
        self.assertEqual(len(scan), 6)
        used = collections.Counter(doc_id for q in scan for doc_id in q["answer_ids"])
        self.assertEqual(set(used), {"SCAN-01", "SCAN-02", "SCAN-03"})
        self.assertTrue(all(count == 2 for count in used.values()), used)   # 3 つのスキャンを 2 回ずつ
        for q in scan:
            self.assertTrue(any(self.files[d]["ocr_required"] for d in q["answer_ids"]), q["qid"])

    def test_hr_scan_evidence_is_text_you_can_see_in_the_image(self):
        by_qid = {q["qid"]: q for q in self.questions}
        self.assertEqual(by_qid["hr-55"]["evidence"]["SCAN-03"], "10:52")        # FAX の上部に印字された日時
        self.assertEqual(by_qid["hr-23"]["evidence"]["SCAN-03"], "APP-0471")     # 手書きの応募番号
        self.assertEqual(by_qid["hr-11"]["evidence"]["SCAN-02"], "2026.10.26")   # 受付印の日付
        self.assertEqual(by_qid["hr-16"]["evidence"]["SCAN-02"], "2026.10.26")
        # 受付 11:00（評価一覧）と取り違えない聞き方
        self.assertIn("FAX の上部に印字された日時", by_qid["hr-55"]["question"])
        self.assertNotIn("何時何分に届き", by_qid["hr-55"]["question"])
        # 台帳・PDF の表示にないコロン付きの書き方をしない（PDF ではコロンが消える）
        self.assertEqual(by_qid["hr-49"]["evidence"], {"JOB-REQ043-v1": "2026年9月2日", "JOB-REQ047-v2": "2026年9月29日"})

    def test_hr_multi_doc_questions_need_two_documents(self):
        multi = [q for q in self.questions if q["type"] == "multi-doc"]
        self.assertEqual(len(multi), 10)
        self.assertTrue(all(len(set(q["answer_ids"])) >= 2 for q in multi))

    def test_hr_question_set_is_varied(self):
        texts = [q["question"] for q in self.questions]
        self.assertEqual(len(set(texts)), 60)   # 同じ文の質問がない
        # どの文書も、どれかの質問の正解になっている（23 件。旧版の求人票 JOB-REQ042-v1 は索引に入らないので正解にしない）
        answers = {d for q in self.questions for d in q["answer_ids"]}
        self.assertEqual(answers, self.ids)
        self.assertNotIn("JOB-REQ042-v1", answers)
        # 先頭の 6 問に 6 つの種類がそろう（--limit で先頭から取っても、種類がかたよらない）
        self.assertEqual(len({q["type"] for q in self.questions[:6]}), 6)


MINI_HOTELS = REPO_DIR / "tests" / "fixtures" / "hotels_mini.json"   # 試験用の、架空のホテル 3 件（項目の形だけ本物に合わせた）


def mini_hotels():
    return json.loads(MINI_HOTELS.read_text(encoding="utf-8"))


def hotel_check(questions, hotels=None):
    hotels = mini_hotels() if hotels is None else hotels
    return ev.check_hotel(questions, known_ids=ev.ids_of("hotel", hotels), data=hotels)


def real_hotel_data_path():
    """本物のホテルのデータ（Repo に写していない）の場所。環境変数 HOTEL_DATA か、_work/hotel-vectors/ の中。なければ None。"""
    for candidate in (os.environ.get("HOTEL_DATA"), ev.DATA_FILES["hotel"]):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


class HotelConditionTest(unittest.TestCase):
    """condition（条件）を、検索の $filter の文字にする・データと照らす。"""

    def setUp(self):
        self.hotels = {h["HotelId"]: h for h in mini_hotels()}

    def ids(self, condition):
        return [i for i, hotel in self.hotels.items() if ev.matches(hotel, condition)]

    def test_condition_to_filter(self):
        cases = [
            ({"Rating": {"ge": 4.5}, "ParkingIncluded": True}, "Rating ge 4.5 and ParkingIncluded eq true"),
            ({"Category_ja": "ブティック"}, "Category_ja eq 'ブティック'"),
            ({"Rooms/BaseRate": {"le": 100}}, "Rooms/any(r: r/BaseRate le 100)"),
            ({"Address/City": "New York"}, "Address/City eq 'New York'"),
            ({"ParkingIncluded": False}, "ParkingIncluded eq false"),
            ({"Rating": 4}, "Rating eq 4"),
            ({"Rating": {"gt": 4, "lt": 4.5}}, "Rating gt 4 and Rating lt 4.5"),
            ({"Rooms/BaseRate": {"lt": 59.5}}, "Rooms/any(r: r/BaseRate lt 59.5)"),
        ]
        for condition, expected in cases:
            with self.subTest(expected):
                self.assertEqual(ev.condition_to_filter(condition), expected)

    def test_condition_to_filter_quotes_text_and_leaves_dates_bare(self):
        self.assertEqual(ev.condition_to_filter({"Address/City": "Lion's Den"}), "Address/City eq 'Lion''s Den'")
        self.assertEqual(ev.condition_to_filter({"LastRenovationDate": {"ge": "2015-01-01T00:00:00Z"}}),
                         "LastRenovationDate ge 2015-01-01T00:00:00Z")   # OData の日時は引用符なし
        self.assertEqual(ev.condition_to_filter({"Category_ja": "リゾート＆スパ", "LastRenovationDate": {"lt": "2005-01-01T00:00:00Z"}}),
                         "Category_ja eq 'リゾート＆スパ' and LastRenovationDate lt 2005-01-01T00:00:00Z")

    def test_condition_to_filter_keeps_key_order_and_groups_rooms_into_one_any(self):
        # 客室の条件は、いくつあっても 1 つの any に（同じ客室が全部を満たす）。位置は最初の Rooms/… の位置
        self.assertEqual(ev.condition_to_filter({"Rooms/BaseRate": {"le": 100}, "Rating": {"ge": 4}, "Rooms/SmokingAllowed": False}),
                         "Rooms/any(r: r/BaseRate le 100 and r/SmokingAllowed eq false) and Rating ge 4")
        self.assertEqual(ev.condition_to_filter({"Rating": {"ge": 4}, "Rooms/SmokingAllowed": False, "Rooms/BaseRate": {"le": 100}}),
                         "Rating ge 4 and Rooms/any(r: r/SmokingAllowed eq false and r/BaseRate le 100)")
        self.assertEqual(ev.condition_to_filter({"Rooms/BaseRate": {"ge": 50, "le": 100}}),
                         "Rooms/any(r: r/BaseRate ge 50 and r/BaseRate le 100)")

    def test_bad_conditions_are_value_errors_in_japanese(self):
        cases = [
            ({}, "1 つ以上の条件"),
            ("Rating ge 4", "1 つ以上の条件"),
            ({"Description": "x"}, "「Description」は condition に使えません"),
            ({"Rooms/Foo": 1}, "「Rooms/Foo」は condition に使えません"),
            ({"Rating": {"ne": 4}}, "演算「ne」は使えません"),
            ({"Rating": {}}, "条件が空です"),
            ({"Rating": "high"}, "「Rating」の eq は 数 で書きます"),
            ({"Rating": True}, "数 で書きます"),
            ({"ParkingIncluded": {"ge": True}}, "true か false"),
            ({"ParkingIncluded": "yes"}, "true か false"),
            ({"Category_ja": {"ge": "ブ"}}, "文字列（演算は eq だけ）"),
            ({"Category_ja": 5}, "文字列"),
            ({"LastRenovationDate": {"ge": "2015"}}, "日時の文字"),
            ({"LastRenovationDate": {"ge": 2015}}, "日時の文字"),
        ]
        for condition, word in cases:
            with self.subTest(condition):
                for function in (ev.condition_to_filter, lambda c: ev.matches(self.hotels["1"], c)):
                    with self.assertRaises(ValueError) as caught:
                        function(condition)
                    self.assertIn(word, str(caught.exception))

    def test_matches_top_level_and_address(self):
        self.assertEqual(self.ids({"Rating": {"ge": 4.5}, "ParkingIncluded": True}), ["1"])
        self.assertEqual(self.ids({"Rating": {"ge": 4}}), ["1", "3"])          # 評価が整数 4 のホテルも比べられる
        self.assertEqual(self.ids({"Rating": {"gt": 4}}), ["1"])
        self.assertEqual(self.ids({"Rating": 4}), ["3"])
        self.assertEqual(self.ids({"Category_ja": "ブティック"}), ["1"])
        self.assertEqual(self.ids({"Category_ja": "ブティック", "Rating": {"lt": 4}}), [])
        self.assertEqual(self.ids({"Address/City": "Lakeview"}), ["1", "2"])
        self.assertEqual(self.ids({"Address/City": "lakeview"}), [])           # 大文字・小文字は区別する（OData の eq と同じ）
        self.assertEqual(self.ids({"ParkingIncluded": False}), ["2"])
        self.assertEqual(self.ids({"LastRenovationDate": {"ge": "2015-01-01T00:00:00Z"}}), ["1", "3"])
        self.assertEqual(self.ids({"LastRenovationDate": {"lt": "2015-01-01T00:00:00Z"}}), ["2"])
        self.assertEqual(self.ids({"LastRenovationDate": {"ge": "2019-05-01T09:00:00+09:00"}}), ["1", "3"])   # 時差つきも日時として比べる

    def test_matches_missing_values_never_match(self):
        # ホテル 2 は StateProvince がない（本物のデータにもある）。null との比べは、どれも偽
        self.assertEqual(self.ids({"Address/StateProvince": "XX"}), ["1"])
        self.assertEqual(self.ids({"Address/StateProvince": "ZZ"}), [])
        self.assertFalse(ev.matches({"HotelId": "9"}, {"Rating": {"ge": 0}}))
        self.assertFalse(ev.matches({"HotelId": "9", "Rooms": None}, {"Rooms/BaseRate": {"le": 100}}))
        self.assertFalse(ev.matches({"HotelId": "9", "Rating": "4.5"}, {"Rating": {"ge": 4}}))   # 数でない値は偽

    def test_matches_rooms_any(self):
        # どれかの客室が満たせばよい（ホテル 1 は 95.5 と 240、ホテル 2 は 59 と 80、ホテル 3 は 150 と 240）
        self.assertEqual(self.ids({"Rooms/BaseRate": {"le": 100}}), ["1", "2"])
        self.assertEqual(self.ids({"Rooms/BaseRate": {"le": 60}}), ["2"])
        self.assertEqual(self.ids({"Rooms/BaseRate": {"lt": 59}}), [])
        self.assertEqual(self.ids({"Rooms/BaseRate": {"ge": 240}}), ["1", "3"])
        self.assertEqual(self.ids({"Rooms/Type_ja": "スイート"}), ["1", "3"])
        self.assertEqual(self.ids({"Rooms/BaseRate": {"ge": 100, "le": 200}}), ["3"])   # 1 つの客室が両方を満たす
        self.assertEqual(self.ids({"Category_ja": "バジェット", "Rooms/BaseRate": {"le": 60}}), ["2"])

    def test_matches_rooms_conditions_are_met_by_the_same_room(self):
        # 100 ドル以下の部屋と、禁煙の部屋が別々にあるだけでは合わない（ホテル 1：安い部屋は喫煙可、禁煙の部屋は 240 ドル）
        condition = {"Rooms/BaseRate": {"le": 100}, "Rooms/SmokingAllowed": False}
        self.assertEqual(self.ids(condition), ["2"])
        self.assertEqual(self.ids({"Rooms/BaseRate": {"le": 100}}), ["1", "2"])
        self.assertEqual(self.ids({"Rooms/SmokingAllowed": False}), ["1", "2", "3"])

    def test_every_allowed_field_converts_and_matches(self):
        for key in ev.CONDITION_FIELDS:
            kind = ev.CONDITION_FIELDS[key]
            value = {"bool": True, "text": "x", "number": 1, "datetime": "2020-01-01T00:00:00Z"}[kind]
            self.assertIn(key.split("/")[-1], ev.condition_to_filter({key: value}))
            ev.matches(self.hotels["1"], {key: value})   # 形が正しい条件は、例外なく真偽を返す


class HotelCheckTest(unittest.TestCase):
    """ホテルに固有の確かめ（@dataset_check("hotel")）：condition・答えの数・evidence。架空の 3 件で。"""

    def cond(self, answers, condition, **extra):
        return {"qid": "c1", "question": "条件で絞る", "type": "condition", "answer_ids": answers, "condition": condition, **extra}

    def other(self, kind="paraphrase", answers=("1",), evidence=None, **extra):
        q = {"qid": "q1", "question": "湾の見える宿は", "type": kind, "answer_ids": list(answers),
             "evidence": {"1": "湾を見下ろす静かな宿"} if evidence is None else evidence}
        q.update(extra)
        return q

    def test_check_is_registered_for_hotel_only(self):
        self.assertIn(ev.check_hotel, ev.DATASET_CHECKS["hotel"])
        self.assertNotIn(ev.check_hotel, ev.DATASET_CHECKS["hr"])
        self.assertNotIn(ev.check_hotel, ev.DATASET_CHECKS["sengoku"])

    def test_condition_answers_must_equal_data_matches(self):
        self.assertEqual(hotel_check([self.cond(["1"], {"Rating": {"ge": 4.5}})]), [])
        self.assertEqual(hotel_check([self.cond(["1", "3"], {"ParkingIncluded": True})]), [])
        self.assertEqual(hotel_check([self.cond(["3", "1"], {"ParkingIncluded": True})]), [])   # 順番は関係ない
        # 条件に合わないホテルが入っている
        problems = hotel_check([self.cond(["1", "3"], {"Rating": {"ge": 4.5}})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("c1", problems[0])
        self.assertIn("条件に合わない：3", problems[0])
        self.assertIn("条件に合うホテル全部", problems[0])
        # 条件に合うホテルが足りない
        problems = hotel_check([self.cond(["1"], {"ParkingIncluded": True})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("足りない：3", problems[0])
        self.assertIn("2 件：1・3", problems[0])
        # 足りないのと余計なのが両方
        problems = hotel_check([self.cond(["2"], {"ParkingIncluded": True})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("足りない：1・3", problems[0])
        self.assertIn("条件に合わない：2", problems[0])

    def test_condition_must_match_between_one_and_the_limit(self):
        problems = hotel_check([self.cond(["1"], {"Rating": {"ge": 5}})])
        self.assertEqual(len(problems), 1, problems)   # 0 件の条件では、answer_ids の食い違いを重ねて言わない
        self.assertIn("0 件です", problems[0])
        with mock.patch.object(ev, "HOTEL_MAX_CONDITION_ANSWERS", 2):
            self.assertEqual(hotel_check([self.cond(["1", "3"], {"ParkingIncluded": True})]), [])
            problems = hotel_check([self.cond(["1", "2", "3"], {"Rating": {"ge": 3}})])
            self.assertTrue(any("3 件です" in p and "1〜2 件" in p for p in problems), problems)

    def test_condition_type_needs_a_condition(self):
        q = self.cond(["1"], {"Rating": {"ge": 4.5}})
        del q["condition"]
        problems = hotel_check([q])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("c1", problems[0])
        self.assertIn("condition（答えの条件）が要ります", problems[0])

    def test_a_condition_on_another_type_is_checked_the_same_way(self):
        q = self.other(answers=("1", "2"), condition={"Rating": {"ge": 4.5}})
        problems = hotel_check([q])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("条件に合わない：2", problems[0])

    def test_bad_condition_shape_is_a_problem_not_a_crash(self):
        for bad in ({}, "Rating ge 4", {"Description": "x"}, {"Rating": {"ne": 4}}, {"Rating": "high"}):
            with self.subTest(bad):
                problems = hotel_check([self.cond(["1"], bad)])
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("condition の形が違います", problems[0])

    def test_data_checks_are_skipped_without_the_data(self):
        known = {"1", "2", "3"}
        wrong = [self.cond(["2"], {"Rating": {"ge": 4.5}}), self.other(evidence={"1": "どこにもない語句"})]
        self.assertEqual(ev.check_hotel(wrong, known_ids=known, data=None), [])
        self.assertEqual(ev.check_hotel(wrong, known_ids=known, data={"not": "a list"}), [])
        # 形は、データがなくても確かめる
        problems = ev.check_hotel([self.cond(["1"], {"Rating": "high"})], known_ids=known, data=None)
        self.assertIn("condition の形が違います", problems[0])

    def test_non_condition_answers_are_limited(self):
        known = {str(n) for n in range(1, 30)}
        ids = [str(n) for n in range(1, 7)]
        q = self.other(answers=ids, evidence={i: "x" for i in ids})
        problems = ev.check_hotel([q], known_ids=known, data=None)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("q1", problems[0])
        self.assertIn("5 件までです（今は 6 件", problems[0])
        ok = self.other(answers=ids[:5], evidence={i: "x" for i in ids[:5]})
        self.assertEqual(ev.check_hotel([ok], known_ids=known, data=None), [])
        # condition の質問は、20 件まで（数はデータがあるとき、条件の結果で確かめる）
        many = [str(n) for n in range(1, 21)]
        self.assertEqual(ev.check_hotel([self.cond(many, {"Rating": {"ge": 4}})], known_ids=known, data=None), [])

    def test_evidence_is_required_for_questions_without_a_condition(self):
        q = self.other()
        del q["evidence"]
        problems = hotel_check([q])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("evidence がありません", problems[0])
        problems = hotel_check([self.other(evidence=["湾を見下ろす静かな宿"])])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("evidence は {HotelId: 語句} の形", problems[0])
        # ホテルごとに 1 つ
        problems = hotel_check([self.other(answers=("1", "3"))])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("evidence に「3」の語句がありません", problems[0])
        # answer_ids にないホテル
        problems = hotel_check([self.other(evidence={"1": "湾を見下ろす静かな宿", "3": "スパと温水プール"})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("evidence の「3」は answer_ids にありません", problems[0])
        # 語句が空・文字列でない
        for bad in ("  ", [], [""], ["湾を見下ろす静かな宿", 5], 5):
            with self.subTest(bad):
                problems = hotel_check([self.other(evidence={"1": bad})])
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("語句か、語句の並び", problems[0])
        # condition の質問には要らない（あれば同じ確かめ）
        self.assertEqual(hotel_check([self.cond(["1"], {"Rating": {"ge": 4.5}})]), [])
        problems = hotel_check([self.cond(["1"], {"Rating": {"ge": 4.5}}, evidence={"1": "どこにもない語句"})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("どこにもない語句", problems[0])

    def test_evidence_phrases_must_be_in_that_hotels_data(self):
        self.assertEqual(hotel_check([self.other()]), [])
        self.assertEqual(hotel_check([self.other(evidence={"1": "Free parking and an evening wine hour"})]), [])   # 英語の説明
        self.assertEqual(hotel_check([self.other(evidence={"1": "Free  parking"})]), [])                            # 空白は無視
        self.assertEqual(hotel_check([self.other(evidence={"1": ["眺め", "コンシェルジュ"]})]), [])                # タグ
        self.assertEqual(hotel_check([self.other(evidence={"1": "Suite, 1 King Bed (Bay View)"})]), [])           # 客室の説明
        self.assertEqual(hotel_check([self.other(evidence={"1": "jacuzzi tub"})]), [])                              # 客室のタグ
        self.assertEqual(hotel_check([self.other(evidence={"1": "10 Bay St"})]), [])                                # 住所
        problems = hotel_check([self.other(evidence={"1": "海を見下ろす静かな宿"})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("q1", problems[0])
        self.assertIn("「1」の語句「海を見下ろす静かな宿」", problems[0])
        # 並びのうち、見つからない語句だけを言う
        problems = hotel_check([self.other(evidence={"1": ["眺め", "プール"]})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("「プール」", problems[0])
        self.assertNotIn("「眺め」", problems[0])
        # 別のホテルの語句は、そのホテルになければ問題
        problems = hotel_check([self.other(evidence={"1": "スパと温水プールのある"})])
        self.assertEqual(len(problems), 1, problems)
        # フランス語の説明・HotelId は、根拠にしない
        for phrase in ("Une auberge calme au-dessus de la baie", "Chambre Économique"):
            self.assertEqual(len(hotel_check([self.other(evidence={"1": phrase})])), 1, phrase)

    def test_hotel_texts_split_english_and_japanese_items(self):
        hotel = mini_hotels()[0]
        texts = ev.hotel_texts(hotel)
        self.assertEqual(set(texts), {"en", "ja"})
        for word in ("Harbor Light Inn", "quiet inn above the bay", "Boutique", "concierge", "Budget Room", "1 Queen Bed",
                     "jacuzzi tub", "10 Bay St", "Lakeview", "USA"):
            self.assertIn(word, texts["en"])
            self.assertNotIn(word, texts["ja"])
        for word in ("ハーバーライト・イン", "湾を見下ろす静かな宿", "ブティック", "コンシェルジュ", "バジェットルーム", "スイート、キングベッド1台"):
            self.assertIn(word, texts["ja"])
            self.assertNotIn(word, texts["en"])
        both = texts["en"] + texts["ja"]
        for word in ("Une auberge", "Chambre", "2019-05-01", "coordinates"):
            self.assertNotIn(word, both)   # フランス語・日付・位置は含めない

    def test_question_language(self):
        self.assertEqual(ev.question_language("ホノルルのホテルは"), "ja")
        self.assertEqual(ev.question_language("Trails End Motel の朝食は無料ですか"), "ja")
        self.assertEqual(ev.question_language("Which hotel is in Pinecrest?"), "en")
        self.assertEqual(ev.question_language("条件"), "ja")
        self.assertEqual(ev.question_language(None), "en")

    def ja_en(self, question, evidence, answers=("3",)):
        return {"qid": "j1", "question": question, "type": "ja-en", "answer_ids": list(answers), "evidence": evidence}

    def test_ja_en_japanese_question_needs_a_clue_only_in_english_items(self):
        ok = self.ja_en("Pinecrest にあるホテルはどこですか。", {"3": "Pinecrest"})        # 住所は英語の項目だけ
        self.assertEqual(hotel_check([ok]), [])
        self.assertEqual(hotel_check([self.ja_en("Summit Resort の設備は？", {"3": "Summit Resort"})]), [])   # 英語の名前
        # 手がかりが 1 つあれば、ほかの語句は日本語の項目のものでもよい
        self.assertEqual(hotel_check([self.ja_en("Pinecrest のスパのあるホテルは？", {"3": ["Pinecrest", "スパと温水プール"]})]), [])
        # 日本語の項目にある語句だけ：日本語で聞いたら、ふつうに日本語で当たる
        problems = hotel_check([self.ja_en("サミット・リゾートはどこですか。", {"3": "サミット・リゾート"})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("j1", problems[0])
        self.assertIn("英語の項目にだけあって、日本語の項目にない語句がありません", problems[0])
        # 英語の項目にもあるが、日本語の項目にも同じ綴りがある語句：どちらでも当たる
        hotels = mini_hotels()
        hotels[2]["Description_ja"] += "Pinecrest 駅から徒歩5分です。"
        problems = hotel_check([ok], hotels)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("英語の項目にだけあって、日本語の項目にない語句がありません", problems[0])

    def test_ja_en_english_question_needs_a_clue_only_in_japanese_items(self):
        english = "Which hotel has a heated pool?"
        self.assertEqual(hotel_check([self.ja_en(english, {"3": "温水プール"})]), [])
        problems = hotel_check([self.ja_en(english, {"3": "A mountain resort"})])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("日本語の項目にだけあって、英語の項目にない語句がありません", problems[0])

    def test_language_of_the_clue_is_only_checked_for_ja_en_and_with_data(self):
        q = {**self.ja_en("Pinecrest にあるホテルは？", {"3": "サミット・リゾート"}), "type": "proper-noun"}
        self.assertEqual(hotel_check([q]), [])
        ja_en = self.ja_en("Pinecrest にあるホテルは？", {"3": "サミット・リゾート"})
        self.assertEqual(ev.check_hotel([ja_en], known_ids={"3"}, data=None), [])

    def test_valid_sample_passes_with_the_mini_data(self):
        questions = [self.cond(["1", "3"], {"ParkingIncluded": True}), self.other(),
                     self.ja_en("Pinecrest にあるホテルはどこですか。", {"3": "Pinecrest"})]
        self.assertEqual(hotel_check(questions), [])


class HotelQuestionsTest(unittest.TestCase):
    """本物の evaluation/hotel_questions.json（40 問）。ホテルのデータは Repo に写していないので、形は常に、中身はデータがあるときだけ確かめる。"""

    @classmethod
    def setUpClass(cls):
        cls.questions = ev.load_questions(ev.QUESTION_FILES["hotel"])
        cls.ids = {str(n) for n in range(1, 51)}   # 日本語版のホテルは 50 件（HotelId は "1"〜"50"）

    def test_shape_and_type_counts(self):
        self.assertEqual(len(self.questions), 40)
        self.assertEqual(ev.validate("hotel", self.questions, known_ids=self.ids), [])
        counts = collections.Counter(q["type"] for q in self.questions)
        self.assertEqual(dict(counts), {"paraphrase": 10, "proper-noun": 6, "condition": 10, "ja-en": 6, "amenity": 8})
        self.assertEqual(dict(counts), ev.TYPE_TARGETS["hotel"])
        self.assertEqual([q["qid"] for q in self.questions], [f"hotel-{n:02d}" for n in range(1, 41)])

    def test_each_question_has_a_why_of_one_or_two_sentences(self):
        for q in self.questions:
            why = q.get("why", "")
            self.assertTrue(why.strip(), f"{q['qid']} に why がありません")
            self.assertLessEqual(len(re.findall("。", why)), 2, f"{q['qid']} の why は 2 文までです")

    def test_condition_questions_carry_a_condition_and_the_others_carry_evidence(self):
        for q in self.questions:
            if q["type"] == "condition":
                self.assertIn("condition", q, q["qid"])
                self.assertTrue(ev.condition_to_filter(q["condition"]), q["qid"])
                self.assertLessEqual(len(q["answer_ids"]), ev.HOTEL_MAX_CONDITION_ANSWERS, q["qid"])
            else:
                self.assertEqual(set(q["evidence"]), set(q["answer_ids"]), q["qid"])   # ホテルごとに 1 つ。余りもない
                self.assertLessEqual(len(q["answer_ids"]), ev.HOTEL_MAX_ANSWERS, q["qid"])

    def test_condition_questions_use_every_operator_and_several_fields(self):
        conditions = [q["condition"] for q in self.questions if q["type"] == "condition"]
        ops = {op for c in conditions for spec in c.values() if isinstance(spec, dict) for op in spec}
        self.assertEqual(ops, {"ge", "le", "gt", "lt"})   # eq は値だけで書く
        fields = {key for c in conditions for key in c}
        self.assertGreaterEqual(len(fields), 6, fields)
        self.assertTrue({"Rating", "ParkingIncluded", "Category_ja", "LastRenovationDate", "Rooms/BaseRate", "Address/City"} <= fields)
        self.assertEqual(len({ev.condition_to_filter(c) for c in conditions}), 10)   # 同じ条件の質問がない

    def test_ja_en_questions_are_asked_in_japanese(self):
        # ホテルのデータの英語と日本語は、1 対 1 の翻訳で、日本語だけにある手がかりはない。逆向き（英語で聞く）の質問は作れない
        for q in self.questions:
            if q["type"] == "ja-en":
                self.assertEqual(ev.question_language(q["question"]), "ja", q["qid"])

    def test_hotel_order_mixes_the_types(self):
        types = [q["type"] for q in self.questions]
        order = ["paraphrase", "proper-noun", "condition", "ja-en", "amenity"]
        # hotel-01〜hotel-30 は、5 問ごとに 5 つの種類が 1 回ずつ。hotel-31 以降は、数の多い paraphrase・condition・amenity だけ
        for start in range(0, 30, 5):
            self.assertEqual(types[start:start + 5], order, f"hotel-{start + 1:02d} から 5 問")
        self.assertEqual(set(types[30:]), {"paraphrase", "condition", "amenity"})

    def test_question_set_is_varied(self):
        texts = [q["question"] for q in self.questions]
        self.assertEqual(len(set(texts)), 40)   # 同じ文の質問がない
        answers = collections.Counter(i for q in self.questions for i in q["answer_ids"])
        self.assertGreaterEqual(len(answers), 40)   # 40 件以上のホテルが、どれかの質問の正解になっている
        self.assertLessEqual(max(answers.values()), 4)   # 特定のホテルにかたよらない

    @unittest.skipUnless(real_hotel_data_path(), "ホテルのデータがありません（HOTEL_DATA か _work/hotel-vectors/ に置くと確かめます）")
    def test_questions_pass_against_the_real_hotel_data(self):
        data = ev.load_data("hotel", real_hotel_data_path())
        self.assertEqual(len(data), 50)
        self.assertEqual(ev.validate("hotel", self.questions, known_ids=ev.ids_of("hotel", data), data=data), [])
        # condition の質問の answer_ids は、データのうち条件に合うホテル全部
        for q in self.questions:
            if q["type"] == "condition":
                matched = {h["HotelId"] for h in data if ev.matches(h, q["condition"])}
                self.assertEqual(matched, set(q["answer_ids"]), q["qid"])
        # ja-en の手がかりは、日本語の質問なら、英語の項目にだけある（日本語の項目に同じ語句がない）
        for q in self.questions:
            if q["type"] == "ja-en":
                for hotel_id, value in q["evidence"].items():
                    texts = ev.hotel_texts(next(h for h in data if h["HotelId"] == hotel_id))
                    phrases = [value] if isinstance(value, str) else value
                    self.assertTrue(any(p in texts["en"] and p not in texts["ja"] for p in phrases), f"{q['qid']} {hotel_id}")

    @unittest.skipUnless(real_hotel_data_path(), "ホテルのデータがありません")
    def test_ja_en_clues_for_all_matching_hotels_are_listed(self):
        # 「ポートランド」「サンフランシスコ」のように都市名で聞く質問は、その都市のホテルを全部、正解にしている
        data = ev.load_data("hotel", real_hotel_data_path())
        for q in self.questions:
            if q["type"] != "ja-en":
                continue
            clue = next(iter(q["evidence"].values()))
            clue = clue if isinstance(clue, str) else clue[0]
            wanted = {h["HotelId"] for h in data if clue in ev.hotel_texts(h)["en"]}
            self.assertEqual(wanted, set(q["answer_ids"]), q["qid"])


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, content):
        path = self.dir / name
        path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def test_load_questions_reads_type_and_intent(self):
        path = self.write("q.json", [{"qid": "a", "intent": "climax"}, {"qid": "b", "type": "scan", "intent": "x"},
                                     "そのまま"])
        got = ev.load_questions(path)
        self.assertEqual(got[0]["type"], "climax")
        self.assertEqual(got[0]["intent"], "climax")
        self.assertEqual(got[1]["type"], "scan")
        self.assertEqual(got[2], "そのまま")

    def test_load_errors_are_in_japanese(self):
        with self.assertRaisesRegex(ev.DataError, "がありません"):
            ev.load_questions(self.dir / "none.json")
        with self.assertRaisesRegex(ev.DataError, "JSON として読めません"):
            ev.load_questions(self.write("bad.json", "[ {"))
        with self.assertRaisesRegex(ev.DataError, "質問の並び"):
            ev.load_questions(self.write("obj.json", {"qid": "x"}))
        (self.dir / "bin.json").write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaisesRegex(ev.DataError, "読めません"):
            ev.load_questions(self.dir / "bin.json")

    def test_ids_of_each_dataset(self):
        self.assertEqual(ev.ids_of("sengoku", [{"id": "b001"}, {"id": "b002"}]), {"b001", "b002"})
        self.assertEqual(ev.ids_of("hr", {"files": [{"doc_id": "JOB-1"}, {"doc_id": "MAIL-01"}]}),
                         {"JOB-1", "MAIL-01"})
        self.assertEqual(ev.ids_of("hotel", [{"HotelId": "1"}, {"HotelId": 2}]), {"1", "2"})
        for dataset, wrong in (("sengoku", {"id": "x"}), ("hr", [{"doc_id": "x"}]), ("hotel", [{"id": "1"}])):
            with self.subTest(dataset), self.assertRaises(ev.DataError):
                ev.ids_of(dataset, wrong)

    def test_real_hr_manifest_ids(self):
        ids = ev.ids_of("hr", ev.load_data("hr"))
        self.assertIn("JOB-REQ042-v3", ids)
        self.assertIn("SCAN-01", ids)

    def test_load_data_rejects_wrong_shape(self):
        with self.assertRaisesRegex(ev.DataError, "hotel のデータの形ではありません"):
            ev.load_data("hotel", self.write("h.json", {"value": []}))
        with self.assertRaisesRegex(ev.DataError, "がありません"):
            ev.load_data("hotel", self.dir / "none.json")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, content):
        path = self.dir / name
        path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_sengoku_passes_with_exit_0(self):
        code, out, err = run_cli("--dataset", "sengoku")
        self.assertEqual((code, out.strip(), err), (0, "問題なし（60 問）", ""))

    def test_problems_are_listed_with_exit_1(self):
        questions = ev.load_questions(ev.QUESTION_FILES["sengoku"])
        questions[1]["qid"] = questions[0]["qid"]
        questions[2]["answer_ids"] = ["b999"]
        code, out, err = run_cli("--dataset", "sengoku", "--file", self.write("q.json", questions))
        self.assertEqual(code, 1)
        self.assertIn("問題が 2 件あります（60 問を確認）", out)
        self.assertIn("  - qid「q01」が重複しています", out)
        self.assertIn("b999", out)
        self.assertEqual(err, "")

    def test_missing_question_file_is_exit_2(self):
        for dataset in ("sengoku", "hr", "hotel"):
            with self.subTest(dataset):
                code, out, err = run_cli("--dataset", dataset, "--file", str(self.dir / "none.json"))
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("none.json がありません", err)

    def test_missing_question_file_tells_the_next_step(self):
        code, out, err = run_cli("--dataset", "hr", "--file", str(self.dir / "none.json"))
        self.assertEqual(code, 2)
        self.assertIn("none.json がありません", err)
        self.assertIn("--file で渡すか、質問を作ります", err)
        # 既定の場所にも同じ案内（本物の hr_questions.json があるので、読めない場合を作る）
        with mock.patch.dict(ev.QUESTION_FILES, {"hr": self.dir / "default.json"}):
            code, out, err = run_cli("--dataset", "hr")
        self.assertEqual(code, 2)
        self.assertIn("default.json がありません", err)
        self.assertIn("--file で渡すか、質問を作ります", err)

    def test_hr_questions_pass_from_the_cli(self):
        code, out, err = run_cli("--dataset", "hr")
        self.assertEqual((code, out.strip(), err), (0, "問題なし（60 問）", ""))

    def test_hr_says_when_the_content_folder_is_missing(self):
        with mock.patch.object(ev, "HR_CONTENT_DIR", self.dir / "no-such-folder"):
            code, out, err = run_cli("--dataset", "hr")
        self.assertEqual((code, out.strip()), (0, "問題なし（60 問）"))
        self.assertEqual(err.strip().count("\n"), 0)   # 1 行
        self.assertIn("本文が見つからないので、evidence の照らし合わせを飛ばしました", err)
        # 本文のもとがあるときは、何も言わない
        self.assertEqual(run_cli("--dataset", "hr")[2], "")
        # 人事以外には関係ない
        with mock.patch.object(ev, "HR_CONTENT_DIR", self.dir / "no-such-folder"):
            self.assertEqual(run_cli("--dataset", "sengoku")[2], "")

    def test_a_data_error_that_escapes_validation_is_exit_2(self):
        with mock.patch.object(check_questions, "validate", side_effect=ev.DataError("形が違います")):
            code, out, err = run_cli("--dataset", "hr")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("NG    形が違います", err)

    def test_hr_runs_against_the_manifest(self):
        path = self.write("hr.json", [{"qid": "hr-01", "question": "求人票は？", "type": "numeric",
                                       "answer_ids": ["JOB-REQ042-v3"]}])
        code, out, err = run_cli("--dataset", "hr", "--file", path)
        self.assertEqual(code, 1)   # 種類の数が目標に足りない。ID は manifest にある
        self.assertIn("種類 numeric は 1 問です（目標 10 問）", out)
        self.assertNotIn("文書にありません", out)

    def test_hotel_needs_data_file(self):
        path = self.write("hotel.json", [])
        code, out, err = run_cli("--dataset", "hotel", "--file", path, "--hotel-data", str(self.dir / "none.json"))
        self.assertEqual(code, 2)
        self.assertIn("none.json がありません", err)
        hotels = self.write("hotels.json", [{"HotelId": "1"}, {"HotelId": "2"}])
        code, out, err = run_cli("--dataset", "hotel", "--file", path, "--hotel-data", hotels)
        self.assertEqual(code, 1)   # 質問が 0 問。ファイルは読めた
        self.assertIn("種類 amenity は 0 問です（目標 8 問）", out)

    def test_hotel_conditions_are_checked_against_the_data(self):
        good = {"qid": "hotel-01", "question": "評価が4.5以上のホテルは", "type": "condition", "answer_ids": ["1"],
                "condition": {"Rating": {"ge": 4.5}}}
        path = self.write("hotel.json", [good, {**good, "qid": "hotel-02", "answer_ids": ["1", "2"]}])
        code, out, err = run_cli("--dataset", "hotel", "--file", path, "--hotel-data", str(MINI_HOTELS))
        self.assertEqual(code, 1)
        self.assertIn("hotel-02：answer_ids が、condition に合うホテル（1 件：1）と違います（条件に合わない：2）", out)
        self.assertNotIn("hotel-01：", out)
        self.assertEqual(err, "")
        # 条件どおりなら、condition の確かめは通る（種類の数の違いだけが残る）
        code, out, err = run_cli("--dataset", "hotel", "--file", self.write("ok.json", [good]), "--hotel-data", str(MINI_HOTELS))
        self.assertEqual(code, 1)
        self.assertNotIn("hotel-01：", out)
        self.assertIn("種類 condition は 1 問です（目標 10 問）", out)

    @unittest.skipUnless(real_hotel_data_path(), "ホテルのデータがありません（HOTEL_DATA か _work/hotel-vectors/ に置くと確かめます）")
    def test_hotel_questions_pass_from_the_cli(self):
        code, out, err = run_cli("--dataset", "hotel", "--hotel-data", str(real_hotel_data_path()))
        self.assertEqual((code, out.strip(), err), (0, "問題なし（40 問）", ""))

    def test_hotel_data_option_only_for_hotel(self):
        code, out, err = run_cli("--dataset", "sengoku", "--hotel-data", str(self.dir / "h.json"))
        self.assertEqual(code, 2)
        self.assertIn("--hotel-data", err)

    def test_dataset_is_required_and_checked(self):
        self.assertEqual(run_cli()[0], 2)
        self.assertEqual(run_cli("--dataset", "nope")[0], 2)

    def test_runs_as_a_script(self):
        done = subprocess.run([sys.executable, str(REPO_DIR / "tools" / "check_questions.py"),
                               "--dataset", "sengoku"], capture_output=True, text=True, encoding="utf-8",
                              cwd=self.dir)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "問題なし（60 問）"), done.stderr)


if __name__ == "__main__":
    unittest.main()
