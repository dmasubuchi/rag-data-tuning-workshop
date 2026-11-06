"""tools/check_public.py の試験。

秘密の型や /Users/名前/ の見本は、このファイルにそのまま書かず、文字列をつないで作る。
そのまま書くと、Repo 全体への検査が、この試験自身に引っかかるため。
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import check_public  # noqa: E402
from check_public import BannedListError, Finding, load_banned, main, scan_text  # noqa: E402

HAS_GIT = shutil.which("git") is not None

# 秘密の型の見本（つないで作る）
AWS_KEY = "AK" + "IA" + "A" * 16
GITHUB_TOKEN = "gh" + "p_" + "a" * 36
OPENAI_KEY = "sk" + "-" + "a" * 32
ACCOUNT_KEY = "Account" + "Key=" + "A" * 24
SAS_URL = "https://x.test/f?" + "sig=" + "A" * 24
API_KEY_LINE = "api" + "_key: " + "b" * 24
PRIVATE_KEY_HEAD = "-----BEGIN " + "RSA PRIVATE KEY-----"
SAS_WORD = "SharedAccess" + "Signature=x"
HOME_PATH = "/Us" + "ers/" + "someone" + "/docs"


def kinds(findings):
    return [f.kind for f in findings]


class ScanTextTests(unittest.TestCase):
    def test_secret_is_found_and_redacted(self):
        secret = "A" * 52
        findings = scan_text("a.txt", "AZURE_SEARCH_API_KEY=" + secret, [])
        self.assertEqual(kinds(findings), ["secret"])
        self.assertIsInstance(findings[0], Finding)
        self.assertEqual(findings[0].path, "a.txt")
        self.assertEqual(findings[0].line, 1)
        self.assertNotIn(secret, findings[0].excerpt)
        self.assertIn("…", findings[0].excerpt)

    def test_known_patterns(self):
        cases = [
            ("秘密鍵の先頭", PRIVATE_KEY_HEAD, "secret"),
            ("AWS のキー", "id " + AWS_KEY, "secret"),
            ("GitHub のトークン", "token は " + GITHUB_TOKEN, "secret"),
            ("sk- のキー", "OPENAI " + OPENAI_KEY, "secret"),
            ("AccountKey", "接続文字列 " + ACCOUNT_KEY, "secret"),
            ("sig=", "URL " + SAS_URL, "secret"),
            ("SharedAccessSignature", SAS_WORD, "secret"),
            ("api_key の代入", API_KEY_LINE, "secret"),
            ("自分の Mac の絶対パス", "保存先は " + HOME_PATH, "abs-path"),
        ]
        for label, text, kind in cases:
            with self.subTest(label):
                findings = scan_text("a.txt", text, [])
                self.assertIn(kind, kinds(findings))
                for f in findings:
                    # 値の本体は、どの型でも出さない
                    self.assertNotIn("A" * 12, f.excerpt)
                    self.assertNotIn("a" * 12, f.excerpt)
                    self.assertNotIn("b" * 12, f.excerpt)

    def test_short_values_are_not_secrets(self):
        # 24 文字に満たない値は、api_key の代入として扱わない
        self.assertEqual(scan_text("a.txt", "api_key: " + "b" * 23, []), [])

    def test_banned_terms_case_insensitive(self):
        findings = scan_text("a.txt", "ACME 社", ["acme"])
        self.assertEqual(kinds(findings), ["banned"])

    def test_banned_term_excerpt_is_masked(self):
        findings = scan_text("a.txt", "ここに Acme とある", ["acme"])
        self.assertEqual(kinds(findings), ["banned"])
        self.assertNotIn("Acme", findings[0].excerpt)

    def test_line_numbers_start_at_one(self):
        findings = scan_text("a.txt", "ふつうの行\nACME\nふつうの行\n", ["acme"])
        self.assertEqual([f.line for f in findings], [2])

    def test_email_other_than_example_is_found(self):
        text = "連絡先 someone@" + "corp.test まで"
        findings = scan_text("a.txt", text, [])
        self.assertEqual(kinds(findings), ["email"])
        self.assertNotIn("someone", findings[0].excerpt)

    def test_example_emails_pass(self):
        text = "a@example.com と b@example.jp と C@EXAMPLE.COM"
        self.assertEqual(scan_text("a.txt", text, []), [])

    def test_clean_text_passes(self):
        text = "# はじめに\n\nこの研修では、データを整えると検索の結果がどう変わるかを体験します。\n"
        self.assertEqual(scan_text("a.txt", text, ["acme"]), [])


class LoadBannedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_reads_words_and_skips_blank_lines(self):
        p = self.tmp / "banned.txt"
        p.write_text("acme\n\n  試験語  \n", encoding="utf-8")
        self.assertEqual(load_banned(p), ["acme", "試験語"])

    def test_missing_file_raises(self):
        with self.assertRaises(BannedListError):
            load_banned(self.tmp / "nothing.txt")

    def test_empty_file_raises(self):
        p = self.tmp / "banned.txt"
        p.write_text("\n  \n", encoding="utf-8")
        with self.assertRaises(BannedListError):
            load_banned(p)


class MainTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.banned = self.tmp / "banned.txt"
        self.banned.write_text("acme\n", encoding="utf-8")
        self.target = self.tmp / "target"
        self.target.mkdir()

    def write(self, name, text, base=None):
        p = (base or self.target) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def git(self, *args, cwd=None):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
             "-c", "commit.gpgsign=false", *args],
            cwd=cwd or self.target, check=True, capture_output=True,
        )

    # --- 禁止語のリスト ---

    def test_missing_banned_list_fails(self):
        code, out, err = self.run_main("--banned", str(self.tmp / "nothing.txt"), str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("禁止語のリストがない", out + err)

    def test_empty_banned_list_fails(self):
        self.banned.write_text("\n", encoding="utf-8")
        code, out, err = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("禁止語のリスト", out + err)

    def test_banned_list_default_comes_from_environment(self):
        self.write("a.md", "ACME 社\n")
        with mock.patch.dict(os.environ, {"PUBLIC_CHECK_BANNED": str(self.banned)}):
            self.assertEqual(check_public.default_banned_path(), self.banned)
            code, _, _ = self.run_main(str(self.target))
        self.assertEqual(code, 1)

    def test_nonexistent_scan_path_fails(self):
        code, out, err = self.run_main("--banned", str(self.banned), str(self.tmp / "nothing"))
        self.assertEqual(code, 2)
        self.assertTrue(out + err)

    # --- 見つかる・見つからない ---

    def test_clean_directory_returns_0(self):
        self.write("a.md", "ふつうの文章です。\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_finding_returns_1_and_output_is_redacted(self):
        secret = "A" * 52
        self.write("sub/a.md", "1行目\nAZURE_SEARCH_API_KEY=" + secret + "\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("a.md:2", out)
        self.assertIn("secret", out)
        self.assertNotIn(secret, out)

    def test_single_file_can_be_given(self):
        p = self.write("a.md", "ACME 社\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(p))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)

    def test_binary_and_non_utf8_files_are_skipped(self):
        (self.target / "a.bin").write_bytes(b"\x00\x01ACME\x02")
        (self.target / "b.txt").write_bytes("ACME".encode("utf-16"))
        (self.target / "c.txt").write_bytes(b"\xff\xfe\xfa ACME")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("飛ばした", out)

    def test_outside_git_every_file_is_checked(self):
        self.write(".hidden/a.md", "ACME 社\n")
        self.write(".env.local", "x\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn(".hidden/a.md", out)

    def make_symlink(self, name, to):
        link = self.target / name
        try:
            link.symlink_to(to)
        except (OSError, NotImplementedError):
            self.skipTest("シンボリックリンクを作れない環境")
        return link

    def test_symlink_is_not_followed(self):
        outside = self.write("outside.md", "ACME 社\n", base=self.tmp)
        self.make_symlink("link.md", outside)
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0, out)

    def test_symlink_target_text_is_checked(self):
        self.make_symlink("link.md", HOME_PATH)
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("abs-path", out)

    # --- Git の Repo の中 ---

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_in_git_only_tracked_and_untracked_unignored_files_are_checked(self):
        secret_line = "ACME 社\n"
        self.git("init", "-q")
        self.write(".gitignore", "ignored.md\n_work/\n")
        self.write("tracked.md", "ふつう\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "first")
        self.write("ignored.md", secret_line)
        self.write("_work/x.md", secret_line)
        self.write("new.md", secret_line)
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("new.md", out)
        self.assertNotIn("ignored.md", out)
        self.assertNotIn("_work", out)
        self.assertNotIn(".git/", out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_in_git_subdirectory_only_that_subtree_is_checked(self):
        self.git("init", "-q")
        self.write("a/x.md", "ふつう\n")
        self.write("b/y.md", "ACME 社\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target / "a"))
        self.assertEqual(code, 0, out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_finds_a_secret_that_was_removed(self):
        self.git("init", "-q")
        self.write("a.md", "AZURE_SEARCH_API_KEY=" + "A" * 52 + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add")
        self.write("a.md", "消した\n")
        self.git("commit", "-q", "-am", "remove")

        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0, out)

        code, out, _ = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("a.md", out)
        self.assertIn("secret", out)
        self.assertNotIn("A" * 52, out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_of_clean_repo_returns_0(self):
        self.git("init", "-q")
        self.write("a.md", "ふつう\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add")
        code, out, _ = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        self.assertEqual(code, 0, out)

    def test_history_outside_git_fails(self):
        self.write("a.md", "ふつう\n")
        code, out, err = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("Git", out + err)


if __name__ == "__main__":
    unittest.main()
