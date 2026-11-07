"""tools/evallib/questions.py（質問の形と確かめ）と tools/check_questions.py の試験。

通信しない。武将の既存の60問と bushou.json は本物を読む。人事・ホテルの質問は、試験の中で作った見本を使う
（本物の質問のファイルは、別の試験で確かめる）。一時のファイルは一時フォルダーに書く。
"""

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
                 "answer_ids": ["D1"]}
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

    def test_answer_and_hidden_ids_must_not_overlap(self):
        questions = sample("hr")
        questions[-1]["answer_ids"] = ["D2"]
        problems = valid("hr", questions)
        self.assertEqual(len(problems), 1)
        self.assertIn("同じ ID", problems[0])
        self.assertIn("D2", problems[0])

    def test_missing_and_bad_fields_are_reported(self):
        cases = {
            "qid がない": ({"question": "q", "type": "climax", "answer_ids": []}, "1 番目：qid"),
            "qid の空白": ({"qid": "a b", "question": "q", "type": "climax", "answer_ids": []}, "空白"),
            "question がない": ({"qid": "x", "type": "climax", "answer_ids": []}, "x：question"),
            "type がない": ({"qid": "x", "question": "q", "answer_ids": []}, "x：type"),
            "answer_ids がない": ({"qid": "x", "question": "q", "type": "climax"}, "x：answer_ids"),
            "answer_ids が文字列": ({"qid": "x", "question": "q", "type": "climax", "answer_ids": "D1"},
                                  "ID の並び"),
            "answer_ids の重複": ({"qid": "x", "question": "q", "type": "climax", "answer_ids": ["D1", "D1"]},
                                "2 回"),
            "why が文字列でない": ({"qid": "x", "question": "q", "type": "climax", "answer_ids": [], "why": 1},
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
