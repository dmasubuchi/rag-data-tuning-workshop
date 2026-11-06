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
import time
import unittest
import zipfile
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
API_KEY_LINE = "api" + "_key: " + "1" + "b" * 23
PRIVATE_KEY_HEAD = "-----BEGIN " + "RSA PRIVATE KEY-----"
SAS_WORD = "SharedAccess" + "Signature=x"
HOME_PATH = "/Us" + "ers/" + "someone" + "/docs"

# Azure のキーの形の見本（名前と値を、つないで作る）
ADMIN_KEY_LINE = "AZURE_SEARCH_ADMIN" + "_KEY=" + "1" + "c" * 31
OPENAI_KEY_LINE = "AZURE_OPENAI" + "_KEY=" + "2" + "d" * 31
ADMIN_KEY_QUOTED = "ADMIN" + "_KEY = " + '"' + "3" + "e" * 31 + '"'
PRIMARY_KEY_JSON = '"primary' + 'Key": "' + "4" + "f" * 31 + '"'
KEY1_JSON = '"key' + '1": "' + "5" + "g" * 31 + '"'
CONNECTION_LINE = "connection" + "_string = " + "6" + "j" * 29
APIM_HEADER = "Ocp-Apim-Subscription" + "-Key: " + "7" + "h" * 31
BEARER_HEADER = "Authorization: " + "Bear" + "er " + "i" * 40
# GUID（テナント・サブスクリプションの ID の形）の見本
GUID = "0123abcd" + "-4567-" + "89ab-cdef-" + "0123456789ab"
ARM_ID = "/subscrip" + "tions/" + GUID + "/resourceGroups/rg-x"


def kinds(findings):
    return [f.kind for f in findings]


class ScanTextTests(unittest.TestCase):
    def test_secret_is_found_and_redacted(self):
        secret = "1" + "A" * 51
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
            ("AI Search の管理者キー", ADMIN_KEY_LINE, "secret"),
            ("Azure OpenAI のキー", OPENAI_KEY_LINE, "secret"),
            ("引用符つきの ADMIN_KEY", ADMIN_KEY_QUOTED, "secret"),
            ("JSON の primaryKey", PRIMARY_KEY_JSON, "secret"),
            ("JSON の key1", KEY1_JSON, "secret"),
            ("接続文字列の代入", CONNECTION_LINE, "secret"),
            ("Ocp-Apim-Subscription-Key", APIM_HEADER, "secret"),
            ("Authorization: Bearer", BEARER_HEADER, "secret"),
            ("GUID", "テナント " + GUID, "guid"),
            ("ARM のリソース ID", "id: " + ARM_ID, "guid"),
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
                    for letter in "cdefghij":
                        self.assertNotIn(letter * 12, f.excerpt)
                    self.assertNotIn("4567", f.excerpt)

    def test_short_values_are_not_secrets(self):
        # 20 文字に満たない値は、キーの代入として扱わない
        self.assertEqual(scan_text("a.txt", "api_key: " + "1" + "b" * 18, []), [])
        self.assertEqual(scan_text("a.txt", ADMIN_KEY_LINE[:-13], []), [])
        self.assertEqual(scan_text("a.txt", "Authorization: Bearer " + "i" * 19, []), [])

    def test_key_name_rule_is_case_insensitive_and_wide(self):
        for name in ("admin_key", "ADMIN_KEY", "AdminKey", "client_secret", "access_token", "db_password",
                     "storage_connectionstring", "myPasswd"):
            with self.subTest(name=name):
                findings = scan_text("a.txt", name + ' = "' + "1" + "k" * 23 + '"', [])
                self.assertEqual(kinds(findings), ["secret"])

    def test_empty_placeholder_and_code_lines_are_not_secrets(self):
        clean = [
            "AZURE_SEARCH_ADMIN_KEY=",
            "AZURE_SEARCH_API_KEY={search_key}",
            'f"AZURE_OPENAI_API_KEY={ai_key}"',
            "AZURE_SEARCH_API_KEY=<ここにキー>",
            '"key": "short"',
            "key_role, short, _ = ROLES[role]",
            "text = env_text(names, role, search_key, ai_key)",
            "キーは表示しません",
        ]
        for text in clean:
            with self.subTest(text=text):
                self.assertEqual(scan_text("a.txt", text, []), [])

    def test_code_without_digits_is_not_a_secret(self):
        # 値に数字がない（x = a.b.c のような）コードは、キーの代入として扱わない
        for text in ("          const key = window.localStorage.key(i);",
                     "token = response.headers.authorization_value"):
            with self.subTest(text=text):
                self.assertEqual(scan_text("a.js", text, []), [])

    def test_name_rule_still_finds_values_with_digits(self):
        line = "AZURE_SEARCH_API" + "_KEY=" + "Abc1defghijklmnopqrstuvwxyz0123"
        findings = scan_text("a.txt", line, [])
        self.assertEqual(kinds(findings), ["secret"])
        self.assertNotIn("defghijklmnopqrstuvwxyz", findings[0].excerpt)

    def test_all_zero_guid_is_not_reported(self):
        zero = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(scan_text("a.txt", zero, []), [])
        self.assertEqual(kinds(scan_text("a.txt", zero + " と " + GUID, [])), ["guid"])

    def test_guid_is_masked_and_needs_full_shape(self):
        findings = scan_text("a.txt", GUID.upper(), [])
        self.assertEqual(kinds(findings), ["guid"])
        self.assertNotIn(GUID[:12].upper(), findings[0].excerpt)
        self.assertIn("…", findings[0].excerpt)
        for short in (GUID[:-1], GUID[1:], "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"):
            with self.subTest(short=short):
                self.assertEqual(scan_text("a.txt", short, []), [])

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
        text = "連絡先 someone@" + "corp.net まで"
        findings = scan_text("a.txt", text, [])
        self.assertEqual(kinds(findings), ["email"])
        self.assertNotIn("someone", findings[0].excerpt)

    def test_example_emails_pass(self):
        text = "a@example.com と b@example.jp と C@EXAMPLE.COM"
        self.assertEqual(scan_text("a.txt", text, []), [])

    def test_jprs_reserved_example_domains_pass(self):
        # JPRS の予約名：example.jp と example.{ac,ad,co,ed,go,gr,lg,ne,or}.jp
        text = " と ".join(f"a@example.{kind}.jp" if kind else "a@example.jp"
                           for kind in ("", "ac", "ad", "co", "ed", "go", "gr", "lg", "ne", "or"))
        text += " と C@EXAMPLE.CO.JP"
        self.assertEqual(scan_text("a.txt", text, []), [])

    def test_reserved_example_domains_are_allowed(self):
        # 予約済みの例用のドメイン（.example .test .invalid .localhost と example.com .net .org）は、個人のメールではない
        text = ("a@" + "sampletech.example と b@" + "x.test と c@" + "host.invalid と d@" + "app.localhost と "
                "e@" + "example.net と F@" + "EXAMPLE.ORG と g@" + "deep.sub.test と h@" + "X.TEST")
        self.assertEqual(scan_text("a.txt", text, []), [])
        # 実在しそうなドメインは、予約名のアドレスが同じ行にあっても拾う
        self.assertEqual(kinds(scan_text("a.txt", text + " と someone@" + "corp.net", [])), ["email"])

    def test_real_looking_domains_are_still_found_next_to_reserved_ones(self):
        # 実在しそうなドメインは拾う。予約名に似ているだけのドメイン（予約名で終わらないもの）も拾う
        cases = {
            "ふつうのドメイン": "someone@" + "corp.net",
            "test を含むだけ": "a@" + "test.com",
            "test で始まる": "a@" + "testing.org",
            "example を含むだけ": "a@" + "myexample.com",
            "example.net の後ろに続く": "a@" + "example.net.corp.net",
            "test の後ろに続く": "a@" + "x.test.corp.net",
            "invalid の後ろに続く": "a@" + "x.invalid.com",
            "example の別の TLD": "a@" + "sampletech.company",
            "JPRS の予約名にない example.pref.jp": "c@" + "example.pref.jp",
            "example.co.jp の下のサブドメイン": "c@" + "mail.example.co.jp",
            "example.co.jp の後ろに続く": "c@" + "example.co.jp.corp.net",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertEqual(kinds(scan_text("a.txt", text, [])), ["email"])

    def test_github_and_ai_noreply_emails_pass(self):
        # GitHub の noreply アドレスと、AI の共著者の noreply アドレスは、個人のメールではないので除く
        text = ("3191973+someone@" + "users.noreply.github.com と " + "noreply@" + "anthropic.com と "
                + "NoReply@" + "GitHub.com と " + "Co-Authored-By: Claude Sonnet 5.5 <noreply@" + "anthropic.com>")
        self.assertEqual(scan_text("a.txt", text, []), [])

    def test_lookalike_noreply_emails_are_still_found(self):
        # 似た形のアドレスは除かない（アドレス全体・ドメイン全体が一致するものだけ除く）
        cases = {
            "別のローカル部": "xnoreply@" + "anthropic.com",
            "別のドメイン": "noreply@" + "anthropic.co.jp",
            "noreply@github の別の形": "noreply@" + "mail.github.com",
            "ドメインの後ろに続く": "someone@" + "users.noreply.github.com.corp.net",
            "別のサブドメイン": "someone@" + "x.users.noreply.github.com",
            "github.com の個人": "someone@" + "github.com",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertEqual(kinds(scan_text("a.txt", text, [])), ["email"])

    def test_full_width_and_half_width_forms_match_banned_terms(self):
        # 全角の英字・半角のカナも、禁止語に当てる（NFKC でそろえる）
        self.assertEqual(kinds(scan_text("a.txt", "ＡＣＭＥ 社", ["acme"])), ["banned"])
        self.assertEqual(kinds(scan_text("a.txt", "ｱｲｳ 社", ["アイウ"])), ["banned"])
        self.assertEqual(kinds(scan_text("a.txt", "acme 社", ["ＡＣＭＥ"])), ["banned"])
        self.assertEqual(kinds(scan_text("a.txt", "アイウ 社", ["ｱｲｳ"])), ["banned"])

    def test_full_width_forms_of_other_kinds_are_found_too(self):
        full = "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in "someone@" + "corp.net")
        self.assertEqual(kinds(scan_text("a.txt", full, [])), ["email"])

    def test_long_lines_are_scanned_in_linear_time(self):
        """base64 の塊や、1行にまとめた文書でも、検査が終わらなくならない（正規表現が二乗の時間にならない）。"""
        for label, line in (("英数字の長い連なり", "a" * 300_000), ("key の連なり", "key" * 100_000),
                            ("メール風の連なり", "a.b" * 100_000)):
            with self.subTest(label):
                started = time.monotonic()
                scan_text("a.txt", line, ["acme"])
                self.assertLess(time.monotonic() - started, 3.0)

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

    def scrub(self, out):
        """出力から、調べる場所の絶対パス（一時フォルダーのでたらめな名前）を除く。"""
        return out.replace(str(self.target), "").replace(self.target.as_posix(), "")

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

    def test_banned_list_is_required_there_is_no_personal_default(self):
        self.write("a.md", "ふつう\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(check_public.default_banned_path())
            code, out, err = self.run_main(str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("禁止語のリストの場所を --banned か PUBLIC_CHECK_BANNED で渡す", out + err)
        self.assertNotIn("OK", out)
        # 個人の置き場所を、コードにも説明にも書かない
        self.assertFalse(hasattr(check_public, "BANNED_DEFAULT"))
        self.assertNotIn("public-check", check_public.__doc__ or "")
        self.assertNotIn("runtime", check_public.__doc__ or "")

    def test_empty_environment_variable_counts_as_not_given(self):
        with mock.patch.dict(os.environ, {"PUBLIC_CHECK_BANNED": "  "}):
            self.assertIsNone(check_public.default_banned_path())

    def test_tilde_in_banned_path_is_expanded(self):
        self.write("a.md", "ACME 社\n")
        home = {"HOME": str(self.tmp), "USERPROFILE": str(self.tmp)}
        with mock.patch.dict(os.environ, {**home, "PUBLIC_CHECK_BANNED": "~/banned.txt"}):
            self.assertEqual(check_public.default_banned_path(), self.banned)
            code, _, _ = self.run_main(str(self.target))
            self.assertEqual(code, 1)
            code, _, _ = self.run_main("--banned", "~/banned.txt", str(self.target))
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
        secret = "1" + "A" * 51
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

    # --- 読めずに飛ばしたファイル ---

    def write_unreadable(self):
        (self.target / "a.bin").write_bytes(b"\x00\x01ACME\x02")
        (self.target / "b.txt").write_bytes("ACME".encode("utf-16"))
        (self.target / "sub").mkdir(exist_ok=True)
        (self.target / "sub" / "c.txt").write_bytes(b"\xff\xfe\xfa ACME")

    def test_skipped_files_fail_and_are_listed_one_by_one(self):
        self.write("ok.md", "ふつうの文章です。\n")
        self.write_unreadable()
        code, out, err = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        for name in ("a.bin", "b.txt", "sub/c.txt"):
            self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("飛ばした") and line.endswith(name)), 1, out)
        self.assertNotIn("ok.md", "".join(line for line in out.splitlines() if line.startswith("飛ばした")))
        self.assertIn("--allow-skipped", out + err)

    def test_allow_skipped_lets_them_pass_but_still_lists_them(self):
        self.write("ok.md", "ふつうの文章です。\n")
        self.write_unreadable()
        code, out, _ = self.run_main("--banned", str(self.banned), "--allow-skipped", str(self.target))
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("飛ばした")), 3, out)

    def test_allow_skipped_does_not_hide_findings(self):
        self.write("bad.md", "ACME 社\n")
        self.write_unreadable()
        code, out, _ = self.run_main("--banned", str(self.banned), "--allow-skipped", str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)

    # --- 検査したファイルが 0 件 ---

    def test_empty_directory_is_not_ok(self):
        code, out, err = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("0 件", out + err)
        self.assertNotIn("OK", out)

    def test_nothing_scanned_even_with_allow_skipped_is_not_ok(self):
        self.write_unreadable()
        code, out, err = self.run_main("--banned", str(self.banned), "--allow-skipped", str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("0 件", out + err)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_git_repo_without_files_is_not_ok(self):
        self.git("init", "-q")
        code, out, err = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        self.assertEqual(code, 2)
        self.assertNotIn("OK", out)

    # --- ファイルとフォルダのパス ---

    def test_banned_word_in_a_file_name_is_found(self):
        self.write("ACME-notes.md", "ふつうの文章です。\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)
        self.assertNotIn("ACME", self.scrub(out))   # 禁止語そのものは、出力にも出さない
        self.assertIn("notes.md", out)

    def test_banned_word_in_a_folder_name_is_found(self):
        self.write("docs/acme/readme.md", "ふつうの文章です。\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)
        self.assertNotIn("acme", self.scrub(out).lower())
        self.assertIn("readme.md", out)   # どのファイルかは分かる

    def test_full_width_banned_word_in_a_name_is_found(self):
        self.write("ＡＣＭＥ.md", "ふつうの文章です。\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)

    def test_guid_and_secret_in_a_name_are_found(self):
        self.write(GUID + ".md", "ふつうの文章です。\n")
        self.write(ADMIN_KEY_LINE.replace("=", "-") + ".md", "ふつうの文章です。\n")   # = は名前に使いにくいので - にする
        self.write("subscrip" + "tions-" + GUID + "/a.md", "ふつうの文章です。\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("guid", out)
        self.assertNotIn(GUID, out)

    def test_the_scanned_places_own_name_is_not_checked(self):
        """調べる場所の名前（自分で指定した絶対パスなど）は、中のファイルのパスではない。"""
        place = self.tmp / "acme-place"
        place.mkdir()
        self.write("a.md", "ふつうの文章です。\n", base=place)
        code, out, _ = self.run_main("--banned", str(self.banned), str(place))
        self.assertEqual(code, 0, out)
        code, out, _ = self.run_main("--banned", str(self.banned), str(place / "a.md"))
        self.assertEqual(code, 0, out)

    def test_single_file_name_is_checked(self):
        p = self.write("acme.md", "ふつうの文章です。\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(p))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_file_name_in_git_repo_is_found(self):
        self.git("init", "-q")
        self.write("ACME-notes.md", "ふつうの文章です。\n")
        self.git("add", "-A")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_finds_a_removed_file_name(self):
        self.git("init", "-q")
        self.write("acme-plan.md", "ふつうの文章です。\n")
        self.write("keep.md", "ふつうの文章です。\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add")
        self.git("rm", "-q", "acme-plan.md")
        self.git("commit", "-q", "-m", "remove")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0, out)
        code, out, _ = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("banned", out)
        self.assertNotIn("acme", self.scrub(out).lower())

    # --- Office の文書 ---

    def make_office(self, name, parts):
        path = self.target / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for member, body in parts.items():
                z.writestr(member, body)
        return path

    WORD = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://example.invalid/w"><w:body><w:p>'
            '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{}</w:t></w:r></w:p></w:body></w:document>')

    def test_office_documents_are_read_as_text(self):
        cases = {
            "a.docx": {"word/document.xml": self.WORD.format("これは ACME 社の資料")},
            "b.xlsx": {"xl/sharedStrings.xml": "<sst><si><t>ACME</t></si></sst>"},
            "c.pptx": {"ppt/slides/slide1.xml": "<p:sld><a:p><a:r><a:t>ACME</a:t></a:r></a:p></p:sld>"},
        }
        for name, parts in cases.items():
            with self.subTest(name=name):
                for old in self.target.iterdir():
                    old.unlink()
                self.make_office(name, parts)
                code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
                self.assertEqual(code, 1, out)
                self.assertIn("banned", out)
                self.assertNotIn("飛ばした", out)

    def test_word_that_is_split_across_runs_is_still_found(self):
        split = ('<w:p><w:r><w:t>AC</w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>ME</w:t></w:r></w:p>')
        self.make_office("a.docx", {"word/document.xml": split})
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1, out)
        self.assertIn("banned", out)

    def test_document_properties_and_alt_text_are_read(self):
        core = "<cp:coreProperties><dc:creator>ACME Person</dc:creator></cp:coreProperties>"
        alt = '<p:pic><p:cNvPr id="2" name="Picture 1" descr="ACME logo"/></p:pic>'
        for member, body in (("docProps/core.xml", core), ("ppt/slides/slide1.xml", alt)):
            with self.subTest(member=member):
                for old in self.target.iterdir():
                    old.unlink()
                self.make_office("a.pptx", {member: body})
                code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
                self.assertEqual(code, 1, out)

    def test_markup_alone_is_not_a_finding(self):
        # タグの名前や属性（キーのような長い名前、GUID のような ID）は、文字ではない
        xml = ('<w:document w:rsidR="00A1B2C3" mc:Ignorable="w14 w15" w15:docId="{' + GUID + '}">'
               '<w:p><w:r><w:t>ふつうの文章です。</w:t></w:r></w:p></w:document>')
        self.make_office("a.docx", {"word/document.xml": xml})
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0, out)
        self.assertNotIn("飛ばした", out)

    def test_clean_office_document_counts_as_scanned(self):
        self.make_office("a.docx", {"word/document.xml": self.WORD.format("ふつうの文章です。")})
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0, out)
        self.assertIn("1 ファイルを検査", out)

    def test_office_entities_are_decoded(self):
        self.make_office("a.docx", {"word/document.xml": self.WORD.format("A&#67;ME")})
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1, out)

    def test_broken_office_file_is_skipped_and_fails(self):
        (self.target / "broken.docx").write_bytes(b"PK\x03\x04 this is not a zip file")
        self.write("ok.md", "ふつうの文章です。\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("broken.docx", out)

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
        self.write("a.md", "AZURE_SEARCH_API_KEY=" + "1" + "A" * 51 + "\n")
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
        self.assertNotIn("1" + "A" * 51, out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_of_clean_repo_returns_0(self):
        self.git("init", "-q")
        self.write("a.md", "ふつう\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add")
        code, out, _ = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        self.assertEqual(code, 0, out)

    # --- 履歴の作成者・メッセージ・ブランチ・タグ ---

    def git_as(self, name, email, *args):
        subprocess.run(
            ["git", "-c", f"user.name={name}", "-c", f"user.email={email}", "-c", "commit.gpgsign=false",
             "-c", "tag.gpgsign=false", *args],
            cwd=self.target, check=True, capture_output=True,
        )

    def history_repo(self, name="t", email="t@example.com", message="add", tag=None, branch=None, tag_message=None):
        self.git("init", "-q")
        self.write("a.md", "ふつうの文章です。\n")
        self.git("add", "-A")
        self.git_as(name, email, "commit", "-q", "-m", message)
        if branch:
            self.git("branch", branch)
        if tag and tag_message:
            self.git_as(name, email, "tag", "-a", tag, "-m", tag_message)
        elif tag:
            self.git("tag", tag)

    def history_codes(self):
        _, plain, _ = self.run_main("--banned", str(self.banned), str(self.target))
        code, out, _ = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        return code, plain, out

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_checks_author_name_and_email(self):
        cases = {
            "作成者の名前": dict(name="Acme Person"),
            "作成者のメール": dict(email="someone@" + "corp.net"),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                shutil.rmtree(self.target / ".git", ignore_errors=True)
                self.history_repo(**kwargs)
                code, plain, out = self.history_codes()
                self.assertIn("OK", plain)
                self.assertEqual(code, 1, out)
                self.assertNotIn("Acme", self.scrub(out))
                self.assertNotIn("someone", self.scrub(out))

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_ignores_noreply_emails_in_author_committer_tagger_and_message(self):
        # 作成者・コミッター・タグの作成者のメールが noreply でも、メッセージに共著者の noreply があっても 0 件
        email = "3191973+someone@" + "users.noreply.github.com"
        message = "追加\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@" + "anthropic.com>"
        self.history_repo(email=email, message=message, tag="v1", tag_message="最初の版\n\nnoreply@" + "github.com")
        code, _, out = self.history_codes()
        self.assertEqual(code, 0, out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_still_finds_lookalike_noreply_in_message(self):
        self.history_repo(message="追加\n\nCo-Authored-By: Someone <xnoreply@" + "anthropic.com>")
        code, _, out = self.history_codes()
        self.assertEqual(code, 1, out)
        self.assertIn("email", out)

    def test_noreply_email_in_file_path_and_text_passes(self):
        self.write("noreply@" + "anthropic.com", "連絡先 3191973+someone@" + "users.noreply.github.com\n")
        code, out, _ = self.run_main("--banned", str(self.banned), str(self.target))
        self.assertEqual(code, 0, out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_checks_committer_name_and_email(self):
        self.git("init", "-q")
        self.write("a.md", "ふつうの文章です。\n")
        self.git("add", "-A")
        env = {**os.environ, "GIT_COMMITTER_NAME": "Acme Person", "GIT_COMMITTER_EMAIL": "t@example.com"}
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                        "commit", "-q", "-m", "add"], cwd=self.target, check=True, capture_output=True, env=env)
        code, plain, out = self.history_codes()
        self.assertEqual(code, 1, out)
        self.assertIn("banned", out)

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_checks_commit_message(self):
        self.history_repo(message="ACME 向けの追加\n\n2行目にも ACME")
        code, plain, out = self.history_codes()
        self.assertIn("OK", plain)
        self.assertEqual(code, 1, out)
        self.assertIn("banned", out)
        self.assertNotIn("ACME", self.scrub(out))

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_checks_tag_message_and_names_of_branches_and_tags(self):
        cases = {
            "注釈つきタグのメッセージ": dict(tag="v1", tag_message="ACME 向け"),
            "ブランチの名前": dict(branch="acme-work"),
            "タグの名前": dict(tag="acme-1"),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                shutil.rmtree(self.target / ".git", ignore_errors=True)
                self.history_repo(**kwargs)
                code, plain, out = self.history_codes()
                self.assertIn("OK", plain)
                self.assertEqual(code, 1, out)
                self.assertNotIn("acme", self.scrub(out).lower())

    @unittest.skipUnless(HAS_GIT, "git がない環境")
    def test_history_ignores_clean_commit_info(self):
        self.history_repo(message="はじめの追加", tag="v1", tag_message="最初の版", branch="work")
        code, _, out = self.history_codes()
        self.assertEqual(code, 0, out)

    def test_history_outside_git_fails(self):
        self.write("a.md", "ふつう\n")
        code, out, err = self.run_main("--banned", str(self.banned), "--history", str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("Git", out + err)


if __name__ == "__main__":
    unittest.main()
