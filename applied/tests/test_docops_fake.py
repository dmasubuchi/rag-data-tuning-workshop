"""17（更新と削除）の道具（lib/docops.py）と、トピックのスクリプトを、偽の Azure の上で最後まで動かす試験（通信なし）。

構築する人が build_hr_index.py で作った状態（manifest の 23 文書を置き、取り込み、見てよい人を付ける）を、偽の Azure
（fake_azure.FakeAzure）に作る。17 のスクリプトが、チームの本物の文書を直して、最後に元に戻すことを、
「どの blob・チャンクに、どんな要求を出したか」の記録（FakeAzure.log）と、前後の状態の比べ（snapshot）で確かめる。
applied フォルダで
    python -m unittest discover -s tests
"""
import contextlib
import io
import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
from lib import acl, clients, config, docops, pipeline  # noqa: E402
from envcase import BUILDER_MESSAGE, MEMBER, EnvCase  # noqa: E402
from fake_azure import FakeAzure  # noqa: E402

TOPICS = HERE.parent / "topics"
APP_FILES = docops.application_files("APP-0471")           # 経歴書・メール・スキャン
JOB = docops.JOB_REL
quiet = lambda s: None  # noqa: E731


def run_script(az, rel, argv=()):
    """トピックのスクリプトを、偽の Azure に向けて、最後まで動かす。標準出力を返す。"""
    path = TOPICS / rel
    out = io.StringIO()
    with az.patched(), mock.patch.object(sys, "argv", [str(path), *argv]), contextlib.redirect_stdout(out):
        runpy.run_path(str(path), run_name="__main__")
    return out.getvalue()


def changed_names(az):
    """blob を置いた・消した・メタデータを変えた、名前の集まり。"""
    return {e[1] for e in az.log if e[0] in ("upload_blob", "delete_blob", "set_blob_metadata")}


class Base(EnvCase):
    def setUp(self):
        super().setUp()
        self.az = FakeAzure(run_polls=1).build()
        self.base = self.az.snapshot()

    def reindex(self):
        with self.az.patched():
            return docops.reindex(say=quiet)


class BuiltStateTest(Base):
    def test_build_makes_every_document_available(self):
        self.assertEqual(len(self.az.blobs), 23)
        self.assertEqual(sorted(self.az.blobs), sorted(f["path"] for f in config.manifest_files()))     # shared/ や、チームごとのフォルダはない
        self.assertFalse([n for n in self.az.blobs if n.split("/")[0] in ("shared", "g1")])
        titles = {d["title"] for d in self.az.chunks.values()}
        self.assertEqual(titles, {Path(f["path"]).name for f in config.manifest_files()})
        self.assertTrue(all(d["allowed"] for d in self.az.chunks.values()))             # 見てよい人が付いている


class RestoreTest(Base):
    def withdraw_by_hand(self):
        """取り下げの途中の状態を作る：メールの blob は消しただけ、ほかは印を付けて取り込み、blob も消した。"""
        with self.az.patched():
            for rel in APP_FILES:
                if rel.startswith("mail/"):
                    docops.delete_blob(rel)
                else:
                    docops.mark_deleted(rel)
            docops.reindex(say=quiet)
            for rel in APP_FILES:
                if not rel.startswith("mail/"):
                    docops.delete_blob(rel)

    def test_restore_puts_documents_back(self):
        """取り下げの印を付けて消したあと、元に戻す（cleanup）と、manifest どおり（data/ のとおり）になる。"""
        self.withdraw_by_hand()
        self.assertNotEqual(self.az.snapshot(), self.base)
        self.assertEqual(len(self.az.blobs), 20)
        self.assertTrue(any(d["title"] == "MAIL-08_REQ-042_APP-0471.eml" for d in self.az.chunks.values()))     # 取り残し
        with self.az.patched():
            out = docops.restore(say=quiet)
        self.assertEqual(sorted(out["put"]), sorted(APP_FILES))                          # 違うものだけを置き直した
        self.assertEqual(out["removed"], [])
        self.assertEqual(self.az.snapshot(), self.base)
        self.assertTrue(all(d["allowed"] for d in self.az.chunks.values()))

    def test_restore_after_a_job_posting_was_overwritten(self):
        with self.az.patched():
            file_v1, entry_v1 = docops.job_version("v1")
            docops.put_blob(JOB, file_v1, entry_v1)
            docops.reindex(say=quiet)
        self.assertEqual(len([d for d in self.az.chunks.values() if d["title"] == "JOB-REQ042-v3.pdf"]), 3)       # v1 は 3 件
        self.assertEqual({d["doc_id"] for d in self.az.chunks.values() if d["title"] == "JOB-REQ042-v3.pdf"}, {"JOB-REQ042-v1"})
        with self.az.patched():
            out = docops.restore(say=quiet)
        self.assertEqual(out["put"], [JOB])
        self.assertEqual(self.az.snapshot(), self.base)

    def test_restore_is_repeatable_and_leaves_unchanged_documents_alone(self):
        for _ in range(2):
            self.az.log.clear()
            with self.az.patched():
                out = docops.restore(say=quiet)
            self.assertEqual((out["put"], out["removed"]), ([], []))
            self.assertFalse([e for e in self.az.log if e[0] in ("upload_blob", "delete_blob", "set_blob_metadata", "delete_documents")])
            self.assertEqual(self.az.snapshot(), self.base)
            self.assertIn(("run_indexer", "hr-docs-ixr"), self.az.log)                  # インデクサーは動かす（変わっていなければ、軽い）

    def test_restore_re_attaches_allowed(self):
        """取り込み直されて allowed が空に戻ったチャンクにも、元に戻すとき、付け直す。"""
        for d in self.az.chunks.values():
            d["allowed"] = []
        with self.az.patched():
            docops.restore(say=quiet)
        self.assertEqual(self.az.snapshot(), self.base)

    def test_restore_replaces_a_document_whose_metadata_still_has_the_delete_mark(self):
        rel = "resumes/CV-APP-0471.docx"
        with self.az.patched():
            docops.mark_deleted(rel)                                              # 印だけ付いて、blob は残っている
            self.assertEqual(self.az.blobs[rel]["metadata"]["IsDeleted"], "true")
            out = docops.restore(say=quiet)
        self.assertEqual(out["put"], [rel])
        self.assertNotIn("IsDeleted", self.az.blobs[rel]["metadata"])
        self.assertEqual(self.az.snapshot(), self.base)

    def test_restore_removes_blobs_not_in_the_manifest_and_their_chunks(self):
        extra = "extra/NOTE.pdf"
        with self.az.patched():
            source, entry = docops.job_version("v1")
            self.az.container.upload_blob(extra, source.read_bytes(), overwrite=True, metadata=pipeline.blob_metadata(entry))
            docops.reindex(say=quiet)
        self.assertTrue([d for d in self.az.chunks.values() if d["title"] == "NOTE.pdf"])
        self.az.log.clear()
        with self.az.patched():
            out = docops.restore(say=quiet)
        self.assertEqual(out["removed"], [extra])
        self.assertNotIn(extra, self.az.blobs)
        self.assertEqual(self.az.snapshot(), self.base)
        names = [e for e in self.az.log if e[0] in ("set_blob_metadata", "delete_blob") and e[1] == extra]
        self.assertEqual([e[0] for e in names], ["set_blob_metadata", "delete_blob"])      # 先に印、そのあとで blob を消す
        self.assertEqual(self.az.log.index(names[0]) < self.az.log.index(("run_indexer", "hr-docs-ixr")) < self.az.log.index(names[1]), True)

    def test_restore_keeps_an_extra_blob_when_its_chunks_do_not_go_away(self):
        az = FakeAzure(ignore_deleted=True).build()                               # 削除の印を読まない（読めなかった状態）
        extra = "extra/NOTE.pdf"
        with az.patched():
            source, entry = docops.job_version("v1")
            az.container.upload_blob(extra, source.read_bytes(), overwrite=True, metadata=pipeline.blob_metadata(entry))
            docops.reindex(say=quiet)
        with az.patched(), mock.patch.object(docops, "GONE_WAIT_SECONDS", 0):
            with self.assertRaises(config.SetupError) as cm:
                docops.restore(say=quiet)
        self.assertIn("残っています", str(cm.exception))
        self.assertIn("消さずに残しました", str(cm.exception))
        self.assertIn(extra, az.blobs)

    def test_restore_stops_when_the_chunks_do_not_come_back(self):
        with self.az.patched(), mock.patch.object(docops, "GONE_WAIT_SECONDS", 0), \
                mock.patch.object(docops, "chunks_missing", return_value=["CV-APP-0471.docx"]):
            with self.assertRaises(config.SetupError) as cm:
                docops.restore(say=quiet)
        self.assertIn("チャンクが、索引にありません", str(cm.exception))
        self.assertIn("CV-APP-0471.docx", str(cm.exception))

    def test_restore_waits_for_a_running_indexer_before_changing_anything(self):
        self.withdraw_by_hand()
        self.az.log.clear()
        self.az.hold_running = 3                                                  # ほかの実行が走っている
        with self.az.patched():
            docops.restore(say=quiet)
        kinds = [e[0] for e in self.az.log]
        first_change = min(i for i, k in enumerate(kinds) if k in ("upload_blob", "delete_blob", "set_blob_metadata"))
        running_before = [e for e in self.az.log[:first_change] if e == ("status", "inProgress")]
        self.assertEqual(len(running_before), 3, "実行中のあいだ、待っていない")        # ほかの実行が終わってから、変え始めた
        self.assertEqual(self.az.snapshot(), self.base)

    def test_restore_touches_only_the_documents_that_differ(self):
        self.withdraw_by_hand()
        self.az.log.clear()
        with self.az.patched():
            docops.restore(say=quiet)
        self.assertEqual({e[1] for e in self.az.log if e[0] == "upload_blob"}, set(APP_FILES))


class IsAsInDataTest(Base):
    """docops.is_as_in_data：Storage の blob が、data/ の文書とメタデータのとおりか。分かれ目ごとに確かめる。"""

    REL = "resumes/CV-APP-0471.docx"

    def check(self, blob=True):
        """いまの偽の入れ物の blob（blob=False なら None）を、data/ の文書と比べる。答えと、比べる間に中身を読んだかを返す。"""
        entry = next(f for f in config.manifest_files() if f["path"] == self.REL)
        with self.az.patched():
            cc = clients.container_client()
            existing = {b.name: b for b in cc.list_blobs(include=["metadata"])}
            self.az.log.clear()
            answer = docops.is_as_in_data(cc, existing.get(self.REL) if blob else None, docops.DATA_DIR / self.REL, entry)
        return answer, ("download_blob", self.REL) in self.az.log

    def test_same_blob_is_as_in_data_and_its_content_was_compared(self):
        self.assertEqual(self.check(), (True, True))

    def test_no_blob_is_not_as_in_data(self):
        self.assertEqual(self.check(blob=False), (False, False))

    def test_different_metadata_is_decided_without_reading_the_content(self):
        self.az.blobs[self.REL]["metadata"]["doc_id"] = "CV-APP-9999"
        self.assertEqual(self.check(), (False, False))

    def test_same_metadata_and_size_but_different_content_is_not_as_in_data(self):
        body = self.az.blobs[self.REL]["data"]
        self.az.blobs[self.REL]["data"] = body[:-1] + bytes([body[-1] ^ 0xFF])      # 大きさは同じ、最後の1バイトだけ違う
        self.assertEqual(len(self.az.blobs[self.REL]["data"]), len(body))
        self.assertEqual(self.check(), (False, True))                                # 中身を読んで比べた

    def test_same_metadata_but_different_size_is_decided_without_reading_the_content(self):
        self.az.blobs[self.REL]["data"] += b"\x00"                                    # メタデータは同じ、大きさだけ違う
        self.assertEqual(self.check(), (False, False))

    def test_restore_puts_back_only_the_document_whose_content_differs(self):
        body = self.az.blobs[self.REL]["data"]
        self.az.blobs[self.REL]["data"] = body[:-1] + bytes([body[-1] ^ 0xFF])
        with self.az.patched():
            out = docops.restore(say=quiet)
        self.assertEqual(out["put"], [self.REL])
        self.assertEqual(self.az.snapshot(), self.base)


class ScriptsTest(Base):
    def test_withdraw_script_removes_then_restores(self):
        out = run_script(self.az, "17-update-delete/withdraw_application.py")
        self.assertIn("取り残し", out)                                            # 失敗の例が見える
        self.assertIn("索引から消えたのを確かめてから、blob を消しました", out)
        self.assertIn("元に戻しました", out)
        self.assertEqual(self.az.snapshot(), self.base)                           # 最後は元と同じ
        self.assertTrue(changed_names(self.az) <= set(APP_FILES), changed_names(self.az))      # 取り下げる応募の書類だけに触る

    def test_withdraw_script_with_keep_leaves_it_withdrawn_until_cleanup(self):
        out = run_script(self.az, "17-update-delete/withdraw_application.py", ["--keep"])
        self.assertIn("--keep が付いているので、元に戻しません", out)
        self.assertEqual(sorted(self.az.blobs), sorted(set(self.base[0]) - set(APP_FILES)))
        self.assertFalse([d for d in self.az.chunks.values() if d["title"] in {Path(f).name for f in APP_FILES}])
        out = run_script(self.az, "17-update-delete/cleanup.py")
        self.assertIn("元に戻しました", out)
        self.assertEqual(self.az.snapshot(), self.base)

    def test_withdraw_script_other_application(self):
        files = docops.application_files("APP-0391")
        out = run_script(self.az, "17-update-delete/withdraw_application.py", ["--application", "APP-0391"])
        self.assertIn("APP-0391", out)
        self.assertEqual(self.az.snapshot(), self.base)
        self.assertTrue(changed_names(self.az) <= set(files))

    def test_revise_script_v1_then_v3_and_ends_as_it_began(self):
        out = run_script(self.az, "17-update-delete/revise_job_posting.py")
        self.assertIn("チャンク 3 件", out)          # v1
        self.assertIn("チャンク 2 件", out)          # v3
        self.assertIn("v1 にしかない語", out)
        self.assertIn("を含むチャンク：0 件", out)
        self.assertEqual(self.az.snapshot(), self.base)                           # 最後は元と同じ（v3）
        self.assertEqual(changed_names(self.az), {JOB})                           # 求人票だけに触る（manifest の名前のまま）
        self.assertNotIn("--keep", out)

    def test_scripts_are_repeatable(self):
        """2回続けて動かしても、同じ結果。途中で止まった状態（求人票が v1 のまま）からでも、同じ。"""
        skipped = ("最終更新日時", "元に戻しました", "見てよい人を付け直しました")        # 実行のたびに数が変わる行
        norm = lambda s: "\n".join(line for line in s.splitlines() if not any(w in line for w in skipped))  # noqa: E731
        first = run_script(self.az, "17-update-delete/revise_job_posting.py")
        with self.az.patched():                                                  # 途中で止まった状態を作る
            docops.put_blob(JOB, *docops.job_version("v1"))
            docops.reindex(say=quiet)
        second = run_script(self.az, "17-update-delete/revise_job_posting.py")
        self.assertEqual(norm(first), norm(second))
        self.assertEqual(self.az.snapshot(), self.base)
        out1 = run_script(self.az, "17-update-delete/withdraw_application.py")
        out2 = run_script(self.az, "17-update-delete/withdraw_application.py")
        self.assertEqual(norm(out1), norm(out2))
        self.assertEqual(self.az.snapshot(), self.base)

    def test_cleanup_script_after_an_interrupted_withdraw(self):
        with self.az.patched():
            docops.delete_blob("mail/MAIL-08_REQ-042_APP-0471.eml")
            docops.mark_deleted("resumes/CV-APP-0471.docx")
            docops.reindex(say=quiet)
        self.assertNotEqual(self.az.snapshot(), self.base)
        out = run_script(self.az, "17-update-delete/cleanup.py")
        self.assertIn("元に戻しました", out)
        self.assertEqual(self.az.snapshot(), self.base)
        run_script(self.az, "17-update-delete/cleanup.py")                       # 何度実行しても同じ
        self.assertEqual(self.az.snapshot(), self.base)

    def test_withdraw_keeps_blobs_when_chunks_are_not_removed(self):
        """印を付けて取り込んでも、チャンクが索引から消えなかったら、blob は消さずに残して、止まる。"""
        az = FakeAzure(ignore_deleted=True).build()                               # 削除の印を読まない（読めなかった状態）
        with mock.patch.object(docops, "GONE_WAIT_SECONDS", 0):
            with self.assertRaises(config.SetupError) as cm:
                run_script(az, "17-update-delete/withdraw_application.py")
        self.assertIn("残っています", str(cm.exception))
        self.assertIn("消さずに残しました", str(cm.exception))
        self.assertIn("resumes/CV-APP-0471.docx", az.blobs)                       # 印のついた経歴書とスキャンの blob は、残っている
        self.assertIn("scans/SCAN-COVER-APP-0471.png", az.blobs)
        self.assertFalse([e for e in az.log if e[0] == "delete_blob" and e[1].startswith(("resumes", "scans"))])

    def test_wait_until_removed(self):
        rel = "resumes/CV-APP-0471.docx"
        with self.az.patched():
            self.assertEqual(docops.wait_until_removed([rel], wait_seconds=0), {"CV-APP-0471.docx": len(
                [d for d in self.az.chunks.values() if d["title"] == "CV-APP-0471.docx"])})
            docops.mark_deleted(rel)
            docops.reindex(say=quiet)
            self.assertEqual(docops.wait_until_removed([rel], wait_seconds=0), {})

    def test_member_key_stops_every_17_script_before_touching_azure(self):
        """メンバーの設定（検索だけのキー、Storage なし）では、17 の3本は、始めに止まり、Azure には何もしない。"""
        self.write_env(MEMBER)
        self.az.log.clear()
        for rel in ("withdraw_application.py", "revise_job_posting.py", "cleanup.py"):
            with self.assertRaises(config.SetupError, msg=rel) as cm:
                run_script(self.az, f"17-update-delete/{rel}")
            self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        self.assertEqual(self.az.log, [])
        self.assertEqual(self.az.snapshot(), self.base)

    def test_builder_without_storage_stops_with_a_japanese_message(self):
        no_storage = "\n".join(line for line in self.ENV_TEXT.splitlines() if "AZURE_STORAGE" not in line) + "\n"
        self.write_env(no_storage)
        with self.assertRaises(config.SetupError) as cm:
            run_script(self.az, "17-update-delete/cleanup.py")
        self.assertIn("AZURE_STORAGE_CONNECTION_STRING", str(cm.exception))
        self.assertIn("python tools/team.py env --team <チーム> --role builder", str(cm.exception))
        self.assertEqual(self.az.log, [])


class IndexerStatusTest(EnvCase):
    def test_status_failure_is_not_taken_as_no_run_record(self):
        """最初の状態の取得が通信の失敗でも、前回の成功を、今回の完了と取り違えない。"""
        az = FakeAzure()
        az.status_failures = 1
        with az.patched():
            rel = "resumes/CV-APP-0471.docx"
            docops.put_blob(rel, config.DATA_DIR / rel, docops.entry_of(rel))
            result = docops.run_indexer(say=quiet)
        self.assertEqual(az.runs, 1)                                    # 今回の実行が終わってから、戻った
        self.assertEqual(result["items"], 1)
        self.assertTrue(az.chunk_ids())
        self.assertIn(("status", "success"), az.log)

    def test_persistent_status_failure_stops(self):
        az = FakeAzure()
        az.status_failures = 100
        with az.patched():
            with self.assertRaises(config.SetupError) as cm:
                docops.run_indexer(say=quiet)
        self.assertIn("状態を取得できませんでした", str(cm.exception))
        self.assertFalse([e for e in az.log if e[0] == "run_indexer"])     # 状態が分からないまま、実行を頼まない

    def test_no_run_record_is_not_a_failure(self):
        az = FakeAzure()
        az.last = None                                                  # 実行の記録がまだない
        with az.patched():
            irc = lib.clients.indexer_client()
            self.assertIsNone(docops._last_start(irc))

    def test_client_errors_are_not_retried(self):
        irc = mock.Mock()
        err = Exception("not found")
        err.status_code = 404
        irc.get_indexer_status.side_effect = err
        with mock.patch("time.sleep"):
            with self.assertRaises(Exception) as cm:
                docops._indexer_status(irc)
        self.assertIs(cm.exception, err)
        self.assertEqual(irc.get_indexer_status.call_count, 1)

    def test_busy_message_does_not_mention_other_groups(self):
        az = FakeAzure()
        az.hold_running = 3                                              # ほかの実行が走っていて、run_indexer が 409 で断られる
        said = []
        with az.patched():
            docops.run_indexer(say=said.append)
        self.assertTrue([s for s in said if "インデクサーが実行中なので待ちます" in s])


class BuildContainerTest(EnvCase):
    """build_hr_index.py は、Storage の入れ物（AZURE_STORAGE_CONTAINER）がなければ作ってから、文書を置く。"""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(HERE.parent / "tools"))
        import importlib

        self.build = importlib.import_module("build_hr_index")
        self.az = FakeAzure()

    def upload(self):
        with self.az.patched(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.build.upload()
        return out.getvalue()

    def test_missing_container_is_created_before_the_documents_are_put(self):
        self.az.container.exists = False
        out = self.upload()
        names = [e[0] for e in self.az.log]
        self.assertEqual(names[0], "create_container")
        self.assertLess(names.index("create_container"), names.index("upload_blob"))
        self.assertEqual(len(self.az.blobs), 23)
        self.assertTrue(self.az.container.exists)
        self.assertIn("hr-docs を作りました", out)

    def test_existing_container_is_left_alone_and_running_again_gives_the_same_result(self):
        self.az.container.exists = False
        self.upload()
        first = self.az.snapshot()
        out = self.upload()                                     # 2回目：入れ物はもうある。何も変わらない
        self.assertEqual(self.az.snapshot(), first)
        self.assertNotIn("を作りました（非公開）", out)
        self.assertEqual([e for e in self.az.log if e[0] == "create_container"], [("create_container", False), ("create_container", True)])

    def test_ensure_container_reports_whether_it_created_one(self):
        self.az.container.exists = False
        with self.az.patched():
            self.assertTrue(docops.ensure_container())
            self.assertFalse(docops.ensure_container())

    def test_member_settings_cannot_create_the_container(self):
        self.write_env(MEMBER)
        self.az.container.exists = False
        with self.assertRaises(config.SetupError) as cm:
            docops.ensure_container()                           # clients.container_client を差し替えない：メンバーの設定は、本物の入口で止まる
        self.assertIn(BUILDER_MESSAGE, str(cm.exception))
        self.assertFalse(self.az.container.exists)


class ReadTopicsTest(EnvCase):
    """14〜16・18 は、メンバーの設定（検索だけのキー、Storage なし）で、最後まで動く。実際に出す検索の絞り込みも見る。"""
    ENV_TEXT = MEMBER

    def run_as_member(self, rel, argv=()):
        az = FakeAzure().build()                  # 構築する人が作った状態（検索だけの偽物。メンバーの設定には、Storage の項目がない）
        fake_llm = mock.Mock()
        fake_llm.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="資料にありません。"))])
        guard = AssertionError("メンバーの設定で、Storage・インデックス・インデクサーの管理には触らない")
        path = TOPICS / rel
        out = io.StringIO()
        with az.patched():                        # 検索だけは、偽の AI Search に向ける
            with mock.patch.object(clients, "container_client", side_effect=guard), \
                    mock.patch.object(clients, "indexer_client", side_effect=guard), \
                    mock.patch.object(clients, "index_client", side_effect=guard), \
                    mock.patch("openai.OpenAI", return_value=fake_llm), \
                    mock.patch.object(sys, "argv", [str(path), *argv]), contextlib.redirect_stdout(out):
                runpy.run_path(str(path), run_name="__main__")
        return az, out.getvalue()

    def filters(self, az):
        return [e[1] for e in az.log if e[0] == "search"]

    def test_14_reads_documents_without_azure(self):
        _, out = self.run_as_member("14-mixed-documents/read_documents.py")
        self.assertIn("23 ファイルを読む", out)

    def test_15_show_pipeline_reads_the_design_from_the_code(self):
        az, out = self.run_as_member("15-azure-indexer/show_pipeline.py")
        self.assertIn("1. データソース", out)
        self.assertIn("hr-docs-ds", out)
        self.assertIn("allowed", out)
        self.assertNotIn("group", out)
        self.assertEqual(set(self.filters(az)), {None})

    def test_15_search_documents_has_no_group_filter(self):
        az, out = self.run_as_member("15-azure-indexer/search_documents.py")
        self.assertIn("1. キーワード検索", out)
        fs = self.filters(az)
        self.assertTrue(fs)
        self.assertEqual(set(fs), {None})                      # 組もなく、見てよい人の絞り込みもない（15 は全部を探す）

    def test_16_search_by_role_filters_on_allowed_only(self):
        az, _ = self.run_as_member("16-security-filter/search_by_role.py")
        fs = [f for f in self.filters(az) if f]
        self.assertTrue(fs)
        for f in fs:
            self.assertTrue(f.startswith("allowed/any("), f)
            self.assertNotIn("group", f)
        self.assertIn("allowed/any(a: search.in(a, 'role:employee'))", fs)
        self.assertIn("allowed/any(a: search.in(a, 'role:interviewer,user:U-1006'))", fs)
        self.assertIn("allowed/any(a: search.in(a, 'role:recruiter'))", fs)

    def test_16_leak_demo_bad_example_has_no_filter_and_good_example_filters_for_employee(self):
        az, out = self.run_as_member("16-security-filter/leak_demo.py")
        fs = self.filters(az)
        self.assertIn(None, fs)                                                    # 悪い例：絞らない
        self.assertIn("allowed/any(a: search.in(a, 'role:employee'))", fs)         # 良い例
        self.assertIn("filter = なし（全部のチャンク）", out)

    def test_18_trace_relations_filters_as_recruiter(self):
        az, _ = self.run_as_member("18-relations/trace_relations.py")
        fs = self.filters(az)
        self.assertTrue(fs)
        for f in fs:
            self.assertTrue(f.startswith("allowed/any(a: search.in(a, 'role:recruiter'))"), f)
            self.assertNotIn("group", f)

    def test_read_topics_work_with_member_settings(self):
        """メンバーの設定は、Storage を持たない・管理者キーでない。それでも、上の5本が動いた（Storage・管理の道具に触れていない）。"""
        s = config.get_settings()
        self.assertEqual((s.key_role, s.storage_connection_string, s.storage_container), ("query", "", ""))


if __name__ == "__main__":
    unittest.main()
