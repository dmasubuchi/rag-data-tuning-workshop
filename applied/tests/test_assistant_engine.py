"""採用アシスタントの、候補を絞り込む中心の処理（assistant/engine.py）の試験。Azure も LLM も使わない。"""
import sys
import unittest
from pathlib import Path

APPLIED = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APPLIED))
from assistant import engine  # noqa: E402


def hit(doc_id: str, app_id: str, kind: str = "resume") -> dict:
    return {"chunk_id": f"{doc_id}-c0", "doc_id": doc_id, "kind": kind, "req_id": "REQ-042",
            "application_ids": app_id, "title": f"{doc_id}.docx", "chunk": f"{app_id} の書類"}


EVAL_ROWS = ("\tEV-002\tAPP-0391\tC-120\t市川 浩二\tREQ-042\t二次面接\t月1回の夜間当番\n"
             "\tAPP-0386\tC-115\t石田 裕太\tREQ-043\t二次面接\t面接実施\n"
             "\tAPP-0439\tC-039\t大西 明日香\tREQ-042\t一次面接\t結果待ち\n")


class ApplicantsOfTest(unittest.TestCase):
    def test_evaluation_uses_text_not_field(self):
        h = {"kind": "interview_evaluations", "application_ids": "APP-0391 APP-0392 APP-0417 APP-0439 APP-0386 APP-0603",
             "chunk": "APP-0417 一次面接 …\nAPP-0439 …"}
        self.assertEqual(engine.applicants_of(h), {"APP-0417", "APP-0439"})

    def test_evaluation_without_ids_in_text_is_empty(self):
        h = {"kind": "interview_evaluations", "application_ids": "APP-0391 APP-0392", "chunk": "評価基準"}
        self.assertEqual(engine.applicants_of(h), set())

    def test_resume_falls_back_to_field(self):
        h = {"kind": "resume", "application_ids": "APP-0471", "chunk": "職務経歴"}
        self.assertEqual(engine.applicants_of(h), {"APP-0471"})

    def test_terms_keep_only_matching_rows(self):
        h = {"kind": "interview_evaluations", "application_ids": "APP-0391 APP-0386 APP-0439", "chunk": EVAL_ROWS}
        self.assertEqual(engine.applicants_of(h, ("REQ-042",)), {"APP-0391", "APP-0439"})
        self.assertEqual(engine.applicants_of(h, ("夜間",)), {"APP-0391"})

    def test_terms_without_matching_row_fall_back_to_all_rows(self):
        h = {"kind": "interview_evaluations", "application_ids": "APP-0391 APP-0386 APP-0439", "chunk": EVAL_ROWS}
        self.assertEqual(engine.applicants_of(h, ("オンコール",)), {"APP-0391", "APP-0386", "APP-0439"})


class NamesOfTest(unittest.TestCase):
    def test_evaluation_rows_give_the_name_after_the_person_key(self):
        h = {"kind": "interview_evaluations", "chunk": "\tEV-001\tAPP-0391\tC-120\t市川 浩二\tREQ-042\t一次面接\t吉田 誠\t推奨\n"}
        self.assertEqual(engine.names_of([h]), {"市川 浩二": {"APP-0391"}})

    def test_resume_gives_the_name_before_the_application_number(self):
        h = {"kind": "resume", "chunk": "職務経歴書\n氏名\n大西　明日香\n応募番号\nAPP-0439\n応募求人\nREQ-042"}
        self.assertEqual(engine.names_of([h]), {"大西 明日香": {"APP-0439"}})

    def test_mail_gives_the_name_before_sama(self):
        h = {"kind": "mail", "chunk": "山本 花子です。\n市川 浩二様（応募番号 APP-0391、求人番号 REQ-042）につきまして、ご連絡いたします。"}
        self.assertEqual(engine.names_of([h]), {"市川 浩二": {"APP-0391"}})

    def test_real_mail_lines_do_not_pull_in_the_words_before_the_name(self):
        lines = {
            "求人番号 REQ-042 にてご応募いただいた岩崎 俊介様（応募番号 APP-0417）につきまして、ご連絡いたします。": {"岩崎 俊介": {"APP-0417"}},
            "本日14時に行いました岩崎 俊介様（応募番号 APP-0417、求人番号 REQ-042）の一次面接につきまして": {"岩崎 俊介": {"APP-0417"}},
            "求人番号 REQ-047（SRE エンジニア）にてご応募いただきました中島 美和様（応募番号 APP-0603）につきまして": {"中島 美和": {"APP-0603"}},
            "石田 裕太様（応募番号 APP-0386、求人番号 REQ-043 バックエンドエンジニア（決済基盤））につきまして": {"石田 裕太": {"APP-0386"}},
        }
        for line, expected in lines.items():
            self.assertEqual(engine.names_of([{"chunk": line}]), expected, line)

    def test_interviewers_and_other_names_are_not_taken(self):
        h = {"kind": "mail", "chunk": "面接官は開発部の吉田 誠と松本 里奈の2名です。"}
        self.assertEqual(engine.names_of([h]), {})

    def test_documents_are_merged(self):
        a = {"chunk": "\tEV-001\tAPP-0391\tC-120\t市川 浩二\tREQ-042\n"}
        b = {"chunk": "氏名 市川 浩二 応募番号 APP-0391"}
        c = {"chunk": None}
        self.assertEqual(engine.names_of([a, b, c]), {"市川 浩二": {"APP-0391"}})


class ApplyStepTest(unittest.TestCase):
    def test_narrowing_never_grows(self):
        run = engine.Run("q")
        engine.apply_step(run, "fields", {"req_id": "REQ-042"}, [hit("CV-APP-0391", "APP-0391"), hit("CV-APP-0392", "APP-0392")], True)
        step = engine.apply_step(run, "keyword", {"query": "夜間"}, [hit("CV-APP-0391", "APP-0391"), hit("CV-APP-0603", "APP-0603")], True)
        self.assertEqual(run.candidates, {"APP-0391"})
        self.assertEqual((step.people_before, step.people_after), (2, 1))

    def test_first_step_counts_from_everyone(self):
        run = engine.Run("q")
        step = engine.apply_step(run, "fields", {"req_id": "REQ-042"}, [hit("CV-APP-0391", "APP-0391")], True)
        self.assertIsNone(step.people_before)
        self.assertEqual(step.people_after, 1)
        self.assertEqual((step.no, step.method), (1, "欄で絞る"))

    def test_zero_keeps_previous(self):
        run = engine.Run("q", candidates={"APP-0391", "APP-0392"})
        step = engine.apply_step(run, "keyword", {"query": "なし"}, [], True)
        self.assertEqual(run.candidates, {"APP-0391", "APP-0392"})
        self.assertIn("絞らなかった", step.note)
        self.assertEqual(step.people_after, 2)

    def test_follow_keeps_candidates_and_adds_evidence(self):
        run = engine.Run("q", candidates={"APP-0391"})
        engine.apply_step(run, "follow", {}, [hit("MAIL-05", "APP-0391"), hit("SCAN-01", "APP-0391")], False)
        self.assertEqual(run.candidates, {"APP-0391"})
        self.assertEqual(len(run.evidence), 2)

    def test_evidence_keeps_order_without_duplicates(self):
        run = engine.Run("q")
        engine.apply_step(run, "keyword", {"query": "a"}, [hit("A", "APP-0001"), hit("B", "APP-0002")], True)
        engine.apply_step(run, "follow", {}, [hit("B", "APP-0002"), hit("C", "APP-0001")], False)
        self.assertEqual(list(run.evidence), ["A-c0", "B-c0", "C-c0"])

    def test_step_lists_top_titles(self):
        run = engine.Run("q")
        step = engine.apply_step(run, "keyword", {"query": "a"}, [hit("A", "APP-0001"), hit("B", "APP-0002"),
                                                                  hit("C", "APP-0003"), hit("D", "APP-0004")], True)
        self.assertEqual(step.top_titles, ["A.docx", "B.docx", "C.docx"])
        self.assertEqual(step.docs_found, 4)

    def test_fields_with_applicant_ids_counts_only_those_people(self):
        run = engine.Run("q")
        evaluation = {"chunk_id": "E1-c0", "doc_id": "EVAL", "kind": "interview_evaluations", "req_id": "-",
                      "application_ids": "APP-0391 APP-0417 APP-0439", "title": "EVAL.xlsx",
                      "chunk": "\tAPP-0391\t市川 浩二\tREQ-042\n\tAPP-0417\t岩崎 俊介\tREQ-042\n\tAPP-0439\t大西 明日香\tREQ-042\n"}
        step = engine.apply_step(run, "fields", {"applicant_ids": ["APP-0417"]}, [evaluation, hit("CV-APP-0417", "APP-0417")], True)
        self.assertEqual(run.candidates, {"APP-0417"})
        self.assertEqual(step.people_after, 1)

    def test_candidate_filter(self):
        self.assertIsNone(engine.candidate_filter(None))
        self.assertEqual(engine.candidate_filter({"APP-0392", "APP-0391"}),
                         "search.ismatch('APP-0391 APP-0392', 'application_ids', 'simple', 'any')")


if __name__ == "__main__":
    unittest.main()
