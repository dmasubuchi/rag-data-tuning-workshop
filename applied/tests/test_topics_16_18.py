"""応用編 16（見せてよい人で絞る）・17（更新と削除）・18（関係で探す）の部品の通信しない試験。

Azure には接続しない（Storage・AI Search の呼び出しは、作り物に差し替える）。applied フォルダで
    python -m unittest discover -s tests
スクリプトを偽の Azure の上で最後まで動かす試験は test_docops_fake.py。
"""
import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
APPLIED = HERE.parent
sys.path.insert(0, str(APPLIED))
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
from lib import acl, config, docops, pipeline  # noqa: E402
from envcase import EnvCase  # noqa: E402

TOPICS = APPLIED / "topics"
SCRIPTS_16_18 = sorted(list((TOPICS / "16-security-filter").glob("*.py")) + list((TOPICS / "17-update-delete").glob("*.py"))
                       + list((TOPICS / "18-relations").glob("*.py")))


def visible(allowed, principals) -> bool:
    """絞り込みの式 allowed/any(a: search.in(a, '…')) と同じ意味：重なる印が1つでもあれば見える。"""
    return bool(set(allowed) & set(principals))


class FilterExpressionTest(unittest.TestCase):
    def test_allowed_filter_shape(self):
        self.assertEqual(acl.allowed_filter(["role:interviewer", "user:U-1006"]),
                         "allowed/any(a: search.in(a, 'role:interviewer,user:U-1006'))")
        self.assertEqual(acl.allowed_filter("role:recruiter"), "allowed/any(a: search.in(a, 'role:recruiter'))")

    def test_allowed_filter_refuses_bad_principals(self):
        for bad in ([], [""], ["recruiter"], ["role:a'b"], ["role:a,user:b"], ["role:a b"], ["role:x') or true or ('a"]):
            with self.assertRaises(config.SetupError, msg=repr(bad)):
                acl.allowed_filter(bad)

    def test_scope_filter(self):
        """見てよい人（allowed）だけで絞る。組の欄では絞らない。"""
        self.assertEqual(acl.scope_filter(acl.viewer_interviewer("U-1006")),
                         "allowed/any(a: search.in(a, 'role:interviewer,user:U-1006'))")
        self.assertNotIn("group", acl.scope_filter(acl.VIEWER_EMPLOYEE))

    def test_viewers(self):
        self.assertEqual(acl.VIEWER_RECRUITER, ("role:recruiter",))
        self.assertEqual(acl.VIEWER_EMPLOYEE, ("role:employee",))
        self.assertEqual(acl.viewer_interviewer("U-1007"), ("role:interviewer", "user:U-1007"))


class ThreeViewersTest(unittest.TestCase):
    """acl.allowed_for の結果を、3つの立場の印で見たときに、見え方が設計どおりになる。"""
    A = {"APP-0391": {"U-1006", "U-1007"}, "APP-0417": {"U-1006"}}

    def views(self, doc):
        allowed = acl.allowed_for(doc, self.A)
        return {"採用担当": visible(allowed, acl.VIEWER_RECRUITER),
                "面接官U-1006": visible(allowed, acl.viewer_interviewer("U-1006")),
                "面接官U-1007": visible(allowed, acl.viewer_interviewer("U-1007")),
                "一般社員": visible(allowed, acl.VIEWER_EMPLOYEE)}

    def test_job_posting_everyone(self):
        self.assertTrue(all(self.views({"kind": "job_posting", "chunk": "年収"}).values()))

    def test_resume_only_assigned_interviewer(self):
        v = self.views({"kind": "resume", "application_ids": "APP-0417", "chunk": "職歴"})
        self.assertEqual(v, {"採用担当": True, "面接官U-1006": True, "面接官U-1007": False, "一般社員": False})

    def test_current_salary_only_recruiter(self):
        v = self.views({"kind": "resume", "application_ids": "APP-0417", "chunk": "現年収は700万円です。"})
        self.assertEqual(v, {"採用担当": True, "面接官U-1006": False, "面接官U-1007": False, "一般社員": False})

    def test_unassigned_application_only_recruiter(self):
        v = self.views({"kind": "mail", "application_ids": "APP-0471", "chunk": "面接"})
        self.assertEqual([k for k, x in v.items() if x], ["採用担当"])


class MetadataTest(EnvCase):
    def test_merge_keeps_existing(self):
        existing = {"doc_id": "CV-APP-0471", "kind": "resume", "req_id": "REQ-042"}
        merged = docops.merge_metadata(existing, {"IsDeleted": "true"})
        self.assertEqual(merged, {"doc_id": "CV-APP-0471", "kind": "resume", "req_id": "REQ-042", "IsDeleted": "true"})
        self.assertNotIn("IsDeleted", existing)            # 元は変えない

    def test_merge_extra_wins(self):
        self.assertEqual(docops.merge_metadata({"IsDeleted": "false", "a": "1"}, {"IsDeleted": "true"}),
                         {"IsDeleted": "true", "a": "1"})

    def test_merge_none(self):
        self.assertEqual(docops.merge_metadata(None, {"IsDeleted": "true"}), {"IsDeleted": "true"})

    def test_add_metadata_reads_then_sets_everything(self):
        """set_blob_metadata は全部を置き換えるので、既存を読んで足したものを渡していること。"""
        class FakeBlob:
            sets = []

            def get_blob_properties(self):
                return SimpleNamespace(metadata={"doc_id": "SCAN-03", "kind": "scan", "req_id": "REQ-042"})

            def set_blob_metadata(self, md):
                self.sets.append(dict(md))

        blob = FakeBlob()
        out = docops.add_metadata(blob, IsDeleted="true")
        self.assertEqual(blob.sets, [{"doc_id": "SCAN-03", "kind": "scan", "req_id": "REQ-042", "IsDeleted": "true"}])
        self.assertEqual(out, blob.sets[0])

    def test_delete_mark_name_matches_datasource(self):
        ds = pipeline.datasource()
        self.assertEqual(pipeline.DELETE_MARK, "IsDeleted")
        self.assertEqual(ds.data_deletion_detection_policy.soft_delete_column_name, pipeline.DELETE_MARK)
        self.assertEqual(ds.data_deletion_detection_policy.soft_delete_marker_value, "true")


class BlobNamesTest(unittest.TestCase):
    def test_names_are_the_manifest_paths(self):
        self.assertEqual(pipeline.blob_name("jobs/JOB-REQ042.pdf"), "jobs/JOB-REQ042.pdf")
        self.assertEqual(pipeline.blob_name(docops.JOB_REL), "jobs/JOB-REQ042-v3.pdf")
        self.assertIn(docops.JOB_REL, [f["path"] for f in config.manifest_files()])      # 求人票は、manifest の名前のまま上書きする

    def test_name_cannot_leave_the_container(self):
        for bad in ("../x/jobs/x.pdf", "/x.pdf", "jobs/../../x.pdf", ""):
            with self.assertRaises(config.SetupError, msg=repr(bad)):
                pipeline.blob_name(bad)
            with self.assertRaises(config.SetupError, msg=repr(bad)):
                docops.mark_deleted(bad)

    def test_title_filter(self):
        self.assertEqual(docops._titles_filter(["mail/MAIL-08_REQ-042_APP-0471.eml", "resumes/CV-APP-0471.docx"]),
                         "search.in(title, 'CV-APP-0471.docx,MAIL-08_REQ-042_APP-0471.eml')")
        for bad in ("a b.pdf", "a,b.pdf", "a'b.pdf", ""):
            with self.assertRaises(config.SetupError, msg=repr(bad)):
                docops._titles_filter([bad])


class DocumentFilesTest(EnvCase):
    def test_application_files(self):
        self.assertEqual(docops.application_files("APP-0471"),
                         ["resumes/CV-APP-0471.docx", "mail/MAIL-08_REQ-042_APP-0471.eml", "scans/SCAN-COVER-APP-0471.png"])
        self.assertEqual(docops.application_files("APP-0439"), [])        # 面接の評価の Excel にしか出てこない
        with self.assertRaises(config.SetupError):
            docops.application_files("APP-9999")

    def test_job_versions(self):
        f1, e1 = docops.job_version("v1")
        f3, e3 = docops.job_version("v3")
        self.assertTrue(f1.is_file() and f3.is_file())
        self.assertEqual((e1["doc_id"], e3["doc_id"]), ("JOB-REQ042-v1", "JOB-REQ042-v3"))
        self.assertEqual((e1["kind"], e1["req_id"]), ("job_posting", "REQ-042"))
        self.assertEqual(f3, config.DATA_DIR / "jobs" / "JOB-REQ042-v3.pdf")     # v3 は、manifest にある元の版
        for e in (e1, e3):
            md = pipeline.blob_metadata(e)
            self.assertTrue(all(v and v.isascii() for v in md.values()))
        with self.assertRaises(config.SetupError):
            docops.job_version("v2")

    def test_v1_is_not_in_the_manifest(self):
        """v1 は 17 だけで使う。manifest（build_hr_index.py が Storage に置くもの）に入っていない。"""
        paths = [f["path"] for f in config.manifest_files()]
        self.assertEqual(len(paths), 23)
        self.assertFalse([p for p in paths if "v1" in p and "REQ042" in p])
        self.assertFalse([p for p in paths if p.startswith("updates/")])
        self.assertEqual(docops.UPDATES_DIR, config.DATA_DIR / "updates")

    def test_v1_and_v3_differ_in_searchable_ways(self):
        from pypdf import PdfReader

        def text(path):
            return "".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)

        t1, t3 = text(docops.job_version("v1")[0]), text(docops.job_version("v3")[0])
        self.assertIn("REQ-042", t1)
        self.assertIn("500万円から700万円", t1)
        self.assertIn("600万円から800万円", t3)
        self.assertIn("試用期間", t1)
        self.assertNotIn("試用期間", t3)
        self.assertNotIn("500万円", t3)
        self.assertGreater(len(t1), len(t3))             # v1 のほうが長い（取り込むとチャンクが多い）

    def test_v1_matches_ledger(self):
        ledger = json.loads((config.DATA_DIR / "_build" / "content" / "source_ats.json").read_text(encoding="utf-8"))
        req = next(r for r in ledger["requisitions"] if r["req_id"] == "REQ-042")
        v1 = next(v for v in req["versions"] if v["version"] == "v1")
        self.assertEqual(v1["doc_id"], "JOB-REQ042-v1")
        self.assertEqual(docops.job_version("v1")[1]["doc_id"], v1["doc_id"])


class DatasourceTest(EnvCase):
    def test_reads_whole_container(self):
        ds = pipeline.datasource()
        self.assertEqual(ds.name, config.HR_DATASOURCE)
        self.assertIsNone(ds.container.query)               # フォルダを指定しない＝入れ物の全体
        self.assertEqual(ds.container.name, "hr-docs")


class StateRowsTest(EnvCase):
    def test_orphan_is_marked(self):
        blobs = [SimpleNamespace(name="resumes/CV-APP-0471.docx", metadata={})]
        files = ["resumes/CV-APP-0471.docx", "mail/MAIL-08_REQ-042_APP-0471.eml"]
        with mock.patch.object(docops, "list_blobs", return_value=blobs), \
                mock.patch.object(docops, "chunk_counts", return_value={"CV-APP-0471.docx": 2, "MAIL-08_REQ-042_APP-0471.eml": 1}):
            rows = docops.state_rows(files)
        self.assertEqual(rows[0][:3], ["CV-APP-0471.docx", "ある", 2])
        self.assertEqual(rows[0][3], "")
        self.assertEqual(rows[1][:3], ["MAIL-08_REQ-042_APP-0471.eml", "ない", 1])
        self.assertIn("取り残し", rows[1][3])

    def test_only_the_given_files_are_listed(self):
        blobs = [SimpleNamespace(name="resumes/CV-APP-0471.docx", metadata={}), SimpleNamespace(name="jobs/JOB-REQ042-v3.pdf", metadata={})]
        with mock.patch.object(docops, "list_blobs", return_value=blobs), mock.patch.object(docops, "chunk_counts", return_value={}):
            rows = docops.state_rows(["resumes/CV-APP-0471.docx"])
        self.assertEqual([r[0] for r in rows], ["CV-APP-0471.docx"])


class FakeIndexer:
    """run_indexer を、最初の n 回は「実行中」（409）で断り、そのあと動かす。状態は、実行中 → 成功と進む。"""

    def __init__(self, busy_times=1, end_status="success", errors=()):
        self.busy_times, self.run_calls, self.polls, self.started = busy_times, 0, 0, False
        self.end_status, self.errors = end_status, list(errors)
        self.last = SimpleNamespace(start_time="t0", status="success", item_count=0, failed_item_count=0, warnings=[], errors=[])

    def run_indexer(self, name):
        self.run_calls += 1
        if self.busy_times > 0:
            self.busy_times -= 1
            e = Exception("Another indexer invocation is currently in progress; concurrent invocations are not allowed.")
            e.status_code = 409
            raise e
        self.started = True

    def get_indexer_status(self, name):
        if self.started:
            self.polls += 1
            if self.polls == 1:
                self.last = SimpleNamespace(start_time="t1", status="inProgress", item_count=0, failed_item_count=0,
                                            warnings=[], errors=[])
            else:
                self.last = SimpleNamespace(start_time="t1", status=self.end_status, item_count=3, failed_item_count=0,
                                            warnings=[1], errors=self.errors)
        return SimpleNamespace(last_result=self.last)


class RunIndexerTest(EnvCase):
    def run_with(self, fake, **kw):
        with mock.patch.object(docops.clients, "indexer_client", return_value=fake), \
                mock.patch.object(docops.time, "sleep"):
            return docops.run_indexer(say=lambda s: None, **kw)

    def test_waits_and_retries_when_busy(self):
        fake = FakeIndexer(busy_times=2)
        r = self.run_with(fake)
        self.assertEqual(fake.run_calls, 3)                 # 2回断られて、3回目で通った
        self.assertEqual((r["status"], r["items"], r["failed"]), ("success", 3, 0))

    def test_waits_for_run_started_after_ours(self):
        fake = FakeIndexer(busy_times=0)
        r = self.run_with(fake)
        self.assertEqual(fake.run_calls, 1)
        self.assertGreaterEqual(fake.polls, 2)              # 実行中のあいだは、終わったと見なさない
        self.assertEqual(r["items"], 3)

    def test_other_errors_are_not_retried(self):
        fake = FakeIndexer(busy_times=0)
        boom = Exception("forbidden")
        boom.status_code = 403
        fake.run_indexer = mock.Mock(side_effect=boom)
        with mock.patch.object(docops.clients, "indexer_client", return_value=fake), \
                mock.patch.object(docops.time, "sleep"):
            with self.assertRaises(Exception) as cm:
                docops.run_indexer(say=lambda s: None)
        self.assertIs(cm.exception, boom)
        self.assertEqual(fake.run_indexer.call_count, 1)

    def test_gives_up_when_always_busy(self):
        fake = FakeIndexer(busy_times=10 ** 6)
        times = iter(range(0, 10 ** 6, 400))               # 時計を進めて、待つ上限を超える
        with mock.patch.object(docops.clients, "indexer_client", return_value=fake), \
                mock.patch.object(docops.time, "sleep"), mock.patch.object(docops.time, "time", side_effect=lambda: next(times)):
            with self.assertRaises(config.SetupError):
                docops.run_indexer(say=lambda s: None, wait_seconds=900)

    def test_failed_run_raises_without_key(self):
        err = SimpleNamespace(error_message="something failed")
        fake = FakeIndexer(busy_times=0, end_status="transientFailure", errors=[err])
        with self.assertRaises(config.SetupError) as cm:
            self.run_with(fake)
        self.assertIn("something failed", str(cm.exception))

    def test_is_busy(self):
        e = Exception("x")
        e.status_code = 409
        self.assertTrue(docops.is_busy(e))
        self.assertTrue(docops.is_busy(Exception("An indexer is already running")))
        self.assertFalse(docops.is_busy(Exception("not found")))


class TopicScriptsTest(unittest.TestCase):
    def test_scripts_exist(self):
        names = {p.name for p in SCRIPTS_16_18}
        self.assertTrue({"search_by_role.py", "leak_demo.py", "withdraw_application.py", "revise_job_posting.py",
                         "cleanup.py", "trace_relations.py"} <= names)
        for d in ("16-security-filter", "17-update-delete", "18-relations"):
            self.assertTrue((TOPICS / d / "README.md").is_file(), d)

    def test_cell_format(self):
        """14・15 と同じ書き方：先頭は説明のセル、# %% のセルに分ける、main() は作らない。"""
        for p in SCRIPTS_16_18:
            text = p.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# %% [markdown]\n"), p.name)
            self.assertGreaterEqual(text.count("\n# %%\n"), 1, p.name)
            self.assertNotIn("def main(", text, p.name)
            ast.parse(text)

    def test_notebook_safe_init(self):
        """__file__ がない Notebook でも動く初期化（15 と同じ形）。"""
        for p in SCRIPTS_16_18:
            text = p.read_text(encoding="utf-8")
            self.assertIn('HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()', text, p.name)
            if "argparse" in text:
                self.assertIn("parse_known_args", text, p.name)

    def test_no_secret_printing(self):
        for p in SCRIPTS_16_18:
            text = p.read_text(encoding="utf-8")
            for word in ("search_key", "storage_connection_string", "AZURE_SEARCH_API_KEY", "AccountKey"):
                self.assertNotIn(word, text, f"{p.name} に {word}")


if __name__ == "__main__":
    unittest.main()
