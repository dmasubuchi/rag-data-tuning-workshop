"""tools/evallib/questions.py（質問の形と確かめ）と tools/check_questions.py の試験。

通信しない。武将の既存の60問と bushou.json は本物を読む。人事・ホテルの質問は、試験の中で作った見本を使う
（本物の質問のファイルは、別の試験で確かめる）。一時のファイルは一時フォルダーに書く。
"""

import collections
import contextlib
import io
import json
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


def sample(dataset):
    """TYPE_TARGETS どおりの、合格する質問の並び。"""
    out = []
    for kind, count in ev.TYPE_TARGETS[dataset].items():
        for _ in range(count):
            q = {"qid": f"{dataset}-{len(out) + 1:02d}", "question": "見本の質問", "type": kind,
                 "answer_ids": ["D1", "D2"] if kind == "multi-doc" else ["D1"]}
            if kind == "permission":
                q.update(answer_ids=[], as_role="role:employee", hidden_ids=["D2", "D3"])
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
        questions[-1]["hidden_ids"] = ["D2", "NOPE-2"]
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
        ok = {**base, "as_role": "role:employee", "hidden_ids": ["D2"]}
        problems = ev.validate("hr", [ok], known_ids=DOCS)
        self.assertFalse([p for p in problems if "p1" in p], problems)   # 種類の数だけが残る

    def test_empty_answer_ids_are_allowed(self):
        questions = sample("hr")
        self.assertEqual([q for q in questions if q["type"] == "permission"][0]["answer_ids"], [])
        self.assertEqual(valid("hr", questions), [])

    def test_empty_answer_ids_only_for_permission(self):
        for dataset, kind in (("hr", "numeric"), ("hotel", "amenity"), ("sengoku", "climax")):
            with self.subTest(kind):
                bad = {"qid": "e1", "question": "答えがない", "type": kind, "answer_ids": []}
                problems = ev.validate(dataset, [bad], known_ids=DOCS)
                hits = [p for p in problems if p.startswith("e1：")]
                self.assertEqual(len(hits), 1, problems)
                self.assertIn("answer_ids", hits[0])
                self.assertIn(kind, hits[0])
                self.assertIn("permission だけ", hits[0])
        ok = {"qid": "e2", "question": "見えない文書を聞く", "type": "permission", "answer_ids": [],
              "as_role": "role:employee", "hidden_ids": ["D2"]}
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
    data = hr_data()
    return ev.check_hr(questions, known_ids=ev.ids_of("hr", data), data=data)


class HrCheckTest(unittest.TestCase):
    """人事に固有の確かめ（@dataset_check("hr")）。小さな manifest で、1 つずつ。"""

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
        questions = [self.perm(as_role="role:recruiter", hidden_ids=["JOB-2"]),
                     {"qid": "s1", "question": "q", "type": "scan", "answer_ids": ["MAIL-1"]},
                     {"qid": "m1", "question": "q", "type": "multi-doc", "answer_ids": ["JOB-1"]}]
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
        self.assertEqual(ev.validate("hr", questions, known_ids=known, data=data), [])
        questions[-1]["hidden_ids"] = ["JOB-1"]   # permission の hidden_ids に求人票
        problems = ev.validate("hr", questions, known_ids=known, data=data)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("JOB-1", problems[0])


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

    def test_hr_scan_questions_include_an_ocr_document(self):
        scan = [q for q in self.questions if q["type"] == "scan"]
        self.assertEqual(len(scan), 6)
        used = collections.Counter(doc_id for q in scan for doc_id in q["answer_ids"])
        self.assertEqual(set(used), {"SCAN-01", "SCAN-02", "SCAN-03"})
        self.assertTrue(all(count == 2 for count in used.values()), used)   # 3 つのスキャンを 2 回ずつ
        for q in scan:
            self.assertTrue(any(self.files[d]["ocr_required"] for d in q["answer_ids"]), q["qid"])

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
