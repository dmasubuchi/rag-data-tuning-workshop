"""応用編の通信しない試験（文書の読み取り、取り込みの設計図、見てよい人の決め方）。applied フォルダで  python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
from lib import acl, config, pipeline, readers  # noqa: E402
from envcase import EnvCase  # noqa: E402


class ReadersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = readers.read_all(config.manifest_files())

    def test_all_files_read(self):
        self.assertEqual(len(self.docs), 23)

    def test_scans_have_no_text(self):
        scans = [d for d in self.docs if d.kind == "scan"]
        self.assertEqual(len(scans), 3)
        self.assertTrue(all(d.chars == 0 for d in scans))

    def test_text_documents_have_text(self):
        others = [d for d in self.docs if d.kind != "scan"]
        self.assertTrue(all(d.chars > 0 for d in others))

    def test_excel_one_row_one_chunk(self):
        book = next(d for d in self.docs if d.format == "xlsx")
        rows = [c for c in book.chunks if c.label.startswith("面接評価 ")]
        self.assertEqual(len(rows), 12)
        self.assertIn("応募番号: APP-", rows[0].text)

    def test_word_split_by_headings(self):
        cv = next(d for d in self.docs if d.doc_id == "CV-APP-0391")
        labels = [c.label for c in cv.chunks]
        self.assertIn("職歴", labels)
        self.assertIn("自己PR", labels)

    def test_term_only_in_scan(self):
        hits = [d for d in self.docs for c in d.chunks if "入社予定日" in c.text]
        self.assertEqual(hits, [])


class PipelineTest(EnvCase):
    def test_metadata_never_empty(self):
        for f in config.manifest_files():
            md = pipeline.blob_metadata(f)
            self.assertTrue(all(v for v in md.values()), f["path"])
            self.assertTrue(all(v.isascii() for v in md.values()), f["path"])

    def test_metadata_fields_have_no_group(self):
        """組の欄はない。文書ごとの情報は、文書の番号・種類・求人・応募・人だけ。"""
        self.assertEqual(pipeline.META_FIELDS, ("doc_id", "kind", "req_id", "application_ids", "person_keys"))
        f = next(x for x in config.manifest_files() if x["path"] == "resumes/CV-APP-0471.docx")
        self.assertEqual(sorted(pipeline.blob_metadata(f)), sorted(pipeline.META_FIELDS))
        self.assertEqual(pipeline.blob_metadata(f)["application_ids"], "APP-0471")

    def test_blob_names_have_no_group_folder(self):
        """Storage の名前は、入れ物の直下に、manifest の相対パスのまま。shared/ や、チームごとのフォルダはない。"""
        self.assertEqual(pipeline.blob_name("jobs/JOB-REQ042-v3.pdf"), "jobs/JOB-REQ042-v3.pdf")
        for f in config.manifest_files():
            self.assertEqual(pipeline.blob_name(f["path"]), f["path"])
        top = {f["path"].split("/")[0] for f in config.manifest_files()}
        self.assertEqual(top, {"jobs", "resumes", "evaluations", "mail", "scans"})
        self.assertNotIn("shared", top)

    def test_blob_name_refuses_names_outside_the_container(self):
        for bad in ("", "/jobs/x.pdf", "../x.pdf", "jobs/../../x.pdf", "jobs\\..\\x.pdf"):
            with self.assertRaises(config.SetupError, msg=repr(bad)):
                pipeline.blob_name(bad)

    def test_index_has_no_group_field(self):
        names = [f.name for f in pipeline.index().fields]
        self.assertNotIn("group", names)
        for needed in ("chunk_id", "parent_id", "chunk", config.VECTOR_FIELD, "title", "doc_id", "kind", "req_id", "application_ids",
                       "person_keys", "allowed"):
            self.assertIn(needed, names)
        mapped = [m.name for m in pipeline.skillset().index_projection.selectors[0].mappings]
        self.assertNotIn("group", mapped)
        self.assertEqual(sorted(set(mapped) & set(pipeline.META_FIELDS)), sorted(pipeline.META_FIELDS))

    def test_delete_detection_is_on_from_the_start(self):
        """削除の検出は、最初のインデクサー実行から入れておく（17）。"""
        ds = pipeline.datasource()
        self.assertEqual(pipeline.DELETE_MARK, "IsDeleted")
        self.assertEqual(ds.data_deletion_detection_policy.soft_delete_column_name, "IsDeleted")
        self.assertEqual(ds.data_deletion_detection_policy.soft_delete_marker_value, "true")
        self.assertIsNone(ds.container.query)               # フォルダを指定しない＝入れ物の全体


class AclTest(unittest.TestCase):
    A = {"APP-0391": {"U-1006", "U-1007"}, "APP-0417": {"U-1006"}}

    def test_job_posting_is_public(self):
        got = acl.allowed_for({"kind": "job_posting", "chunk": "年収 500万円〜"}, self.A)
        self.assertIn(acl.ROLE_EMPLOYEE, got)

    def test_resume_for_assigned_interviewers(self):
        got = acl.allowed_for({"kind": "resume", "application_ids": "APP-0391", "chunk": "職歴"}, self.A)
        self.assertEqual(got, ["role:recruiter", "user:U-1006", "user:U-1007"])

    def test_current_salary_recruiter_only(self):
        got = acl.allowed_for({"kind": "resume", "application_ids": "APP-0417", "chunk": "現年収は700万円です。"}, self.A)
        self.assertEqual(got, ["role:recruiter"])

    def test_evaluation_by_apps_in_chunk(self):
        got = acl.allowed_for({"kind": "interview_evaluations", "application_ids": "APP-0391 APP-0417",
                               "chunk": "EV-005 APP-0417 一次面接"}, self.A)
        self.assertEqual(got, ["role:recruiter", "user:U-1006"])

    def test_evaluation_without_apps(self):
        got = acl.allowed_for({"kind": "interview_evaluations", "chunk": "点数 5 期待を大きく上回る"}, self.A)
        self.assertEqual(got, ["role:interviewer", "role:recruiter"])

    def test_unassigned_application_recruiter_only(self):
        got = acl.allowed_for({"kind": "resume", "application_ids": "APP-0471", "chunk": "職歴"}, self.A)
        self.assertEqual(got, ["role:recruiter"])

    def test_assignments_from_book(self):
        a = acl.interviewer_assignments()
        self.assertEqual(a["APP-0391"], {"U-1006", "U-1007"})
        self.assertNotIn("APP-0471", a)


if __name__ == "__main__":
    unittest.main()
