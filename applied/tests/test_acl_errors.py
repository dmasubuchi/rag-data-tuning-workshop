"""見てよい人の付け方（acl.py）と、キーを伏せる処理（errors.py）の通信しない試験。applied フォルダで
    python -m unittest discover -s tests
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
from lib import acl, config, errors  # noqa: E402
from fake_azure import FakeAzure  # noqa: E402


class EvaluationBasisTest(unittest.TestCase):
    """応募の番号が出てこない評価のチャンクは、評価基準・注記と確かめられたものだけ、面接官全員に見せる。"""
    A = {"APP-0391": {"U-1006"}}

    def allowed(self, text, **kw):
        return acl.allowed_for({"kind": "interview_evaluations", "chunk": text}, self.A, **kw)

    def test_unknown_origin_is_recruiter_only(self):
        # 個別の評価の後半だけが、応募の番号なしで切れて入った場合（Azure の分割は行を保証しない）
        self.assertEqual(self.allowed("確認が弱い。見送り。"), ["role:recruiter"])
        self.assertEqual(self.allowed("設計の判断理由を自分の言葉で説明できなかった。見送りとする。"), ["role:recruiter"])

    def test_basis_chunk_is_for_all_interviewers(self):
        self.assertEqual(self.allowed("点数 5 期待を大きく上回る 点数 4 期待を上回る"), ["role:interviewer", "role:recruiter"])
        self.assertEqual(self.allowed("点数は 5 段階（5 が最も高い）。"), ["role:interviewer", "role:recruiter"])

    def test_basis_with_sheet_title_and_line_breaks(self):
        self.assertEqual(self.allowed("注記\n このファイルは研修用の架空データです。\n 実在の人物・企業とは関係ありません。"),
                         ["role:interviewer", "role:recruiter"])

    def test_basis_mixed_with_other_text_is_recruiter_only(self):
        self.assertEqual(self.allowed("点数 3 期待どおり 確認が弱い。見送り。"), ["role:recruiter"])

    def test_empty_chunk_is_recruiter_only(self):
        self.assertEqual(self.allowed(""), ["role:recruiter"])
        self.assertEqual(self.allowed("   \n "), ["role:recruiter"])

    def test_chunk_with_application_uses_assignments(self):
        self.assertEqual(self.allowed("EV-001 APP-0391 一次面接"), ["role:recruiter", "user:U-1006"])
        self.assertEqual(self.allowed("EV-009 APP-0471 一次面接"), ["role:recruiter"])

    def test_basis_can_be_given(self):
        self.assertEqual(self.allowed("確認が弱い。見送り。", basis="確認が弱い。見送り。"), ["role:interviewer", "role:recruiter"])
        self.assertEqual(self.allowed("点数 5 期待を大きく上回る", basis=""), ["role:recruiter"])

    def test_basis_text_comes_from_workbook(self):
        basis = acl.evaluation_basis_text()
        self.assertIn("期待どおり", basis)
        self.assertIn("注記", basis)
        self.assertNotIn("EV-001", basis)                  # 個別の評価の行は入っていない


class MergeResultTest(unittest.TestCase):
    """merge_documents は、要求が通っても、文書ごとに失敗を返すことがある。数えて、やり直し、残れば止まる。"""

    def setUp(self):
        self.az = FakeAzure()
        for i in range(3):
            self.az.chunks[f"c{i}"] = {"chunk_id": f"c{i}", "title": "x.pdf", "kind": "job_posting", "chunk": "求人", "allowed": [],
                                       "application_ids": "", "parent_id": "jobs/x.pdf"}

    def run_sync(self):
        with self.az.patched():
            return acl.sync()

    def test_all_succeed(self):
        st = self.run_sync()
        self.assertEqual((st["chunks"], st["changed"], st["gone"]), (3, 3, 0))
        self.assertTrue(all(d["allowed"] for d in self.az.chunks.values()))

    def test_one_failure_is_retried(self):
        self.az.merge_plan["c1"] = 1                        # 1回だけ 503
        st = self.run_sync()
        self.assertEqual(st["changed"], 3)
        merges = [e[1] for e in self.az.log if e[0] == "merge_documents"]
        self.assertEqual(merges, [["c0", "c1", "c2"], ["c1"]])           # 失敗した1件だけ、送り直した
        self.assertTrue(self.az.chunks["c1"]["allowed"])

    def test_persistent_failure_stops(self):
        self.az.merge_plan["c1"] = -1                       # 何回でも 503
        with self.assertRaises(config.SetupError) as cm:
            self.run_sync()
        self.assertIn("1 件", str(cm.exception))
        self.assertEqual(len([e for e in self.az.log if e[0] == "merge_documents"]), acl.MERGE_TRIES)

    def test_gone_chunk_is_counted_not_retried(self):
        with self.az.patched():
            out = acl._merge_all(self.az.search, [{"chunk_id": "c0", "allowed": ["role:recruiter"]},
                                                  {"chunk_id": "missing", "allowed": ["role:recruiter"]}])
        self.assertEqual(out, {"done": 1, "gone": 1})
        self.assertEqual(len([e for e in self.az.log if e[0] == "merge_documents"]), 1)


class SyncTest(unittest.TestCase):
    def test_syncs_every_chunk_in_the_index(self):
        """絞り込みなしで、インデックスの全部のチャンクに見てよい人を付ける（組や共有の区別はない）。"""
        az = FakeAzure()
        for i, kind in enumerate(("job_posting", "resume", "job_posting", "mail")):
            az.chunks[f"c{i}"] = {"chunk_id": f"c{i}", "title": f"{kind}-{i}", "kind": kind, "chunk": "求人", "allowed": [],
                                  "application_ids": "", "parent_id": f"x/{i}"}
        with az.patched():
            out = acl.sync()
        self.assertEqual((out["chunks"], out["changed"]), (4, 4))
        self.assertTrue(all(d["allowed"] for d in az.chunks.values()))
        self.assertEqual([e[1] for e in az.log if e[0] == "search"], [None])            # 絞り込みなし
        for removed in ("group_filter", "sync_all", "groups_in_index"):
            self.assertFalse(hasattr(acl, removed), removed)

    def test_second_sync_changes_nothing(self):
        az = FakeAzure()
        az.chunks["c0"] = {"chunk_id": "c0", "title": "a.pdf", "kind": "job_posting", "chunk": "求人", "allowed": [],
                           "application_ids": "", "parent_id": "jobs/a.pdf"}
        with az.patched():
            acl.sync()
            self.assertEqual(acl.sync()["changed"], 0)

    def test_scope_filter_uses_allowed_only(self):
        self.assertEqual(acl.scope_filter(acl.viewer_interviewer("U-1006")),
                         "allowed/any(a: search.in(a, 'role:interviewer,user:U-1006'))")
        self.assertEqual(acl.scope_filter(acl.VIEWER_RECRUITER), "allowed/any(a: search.in(a, 'role:recruiter'))")
        with self.assertRaises(config.SetupError):
            acl.scope_filter([])


# 値は、公開前の検査（check_public）が「キーらしい文字列」と見ないように、20 文字より短くしてある
DUMMY_ENV = (
    "AZURE_OPENAI_API_KEY=SENTINEL_OAI_12345 # team key\n"
    "AZURE_SEARCH_API_KEY=\"SENTINEL_SRCH_67890\"   # quoted, with a comment\n"
    "AZURE_STORAGE_CONNECTION_STRING=AccountName=x;AccountKey=SENTINEL_ACCT_abc==;EndpointSuffix=core.windows.net\n"
    "OTHER_TOKEN='SENTINEL_TOK_5555'\n"
    "PLAIN_NAME=not-a-secret-value\n"
)
SENTINELS = ["SENTINEL_OAI_12345", "SENTINEL_SRCH_67890", "SENTINEL_ACCT_abc==", "SENTINEL_TOK_5555"]


class RedactTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "dummy.env"
        path.write_text(DUMMY_ENV, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AZURE_")}
        env["WORKSHOP_ENV_FILE"] = str(path)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_values_without_trailing_comment(self):
        vals = errors._secret_values()
        for s in SENTINELS:
            self.assertIn(s, vals)
        self.assertFalse([v for v in vals if "team key" in v or "#" in v])        # コメントを、値に含めていない
        self.assertNotIn("not-a-secret-value", vals)

    def test_redact_hides_each_key_alone(self):
        for s in SENTINELS:
            self.assertEqual(errors.redact(f"failed with {s} here"), "failed with *** here")

    def test_matches_dotenv_parsing(self):
        parsed = config.read_env_file(config.env_file_path())
        self.assertEqual(parsed["AZURE_OPENAI_API_KEY"], "SENTINEL_OAI_12345")
        self.assertEqual(parsed["AZURE_SEARCH_API_KEY"], "SENTINEL_SRCH_67890")

    def report(self, exc):
        buf = io.StringIO()
        with redirect_stderr(buf):
            errors._report(type(exc), exc, None)
        return buf.getvalue()

    def test_setup_error_first_line_is_redacted(self):
        out = self.report(config.SetupError("設定が違います（SENTINEL_OAI_12345）。\n  2行目にも SENTINEL_SRCH_67890"))
        for s in SENTINELS:
            self.assertNotIn(s, out)
        self.assertIn("止まりました：設定が違います（***）", out)
        self.assertIn("2行目にも ***", out)

    def test_other_errors_are_redacted(self):
        out = self.report(RuntimeError("SENTINEL_ACCT_abc== が出た"))
        self.assertNotIn("SENTINEL_ACCT_abc==", out)


if __name__ == "__main__":
    unittest.main()
