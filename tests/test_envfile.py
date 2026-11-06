"""tools/teamlib/envfile.py と、team.py env の試験。

通信しない。az は、本物の Az を継いで _call だけ差し替えた偽物（FakeAz）を使う。
そのため、env が許可リスト（READ_ONLY）の外のコマンドを呼べば、試験の中でも CheckError になる。
キーの見本は文字列をつないで作る（公開前の検査に、鍵らしい文字列として引っかからないように）。
.env.local は一時フォルダーに書く。Repo 直下の .env.local は触らない。
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))

import team  # noqa: E402
from teamlib.az import Az, CheckError  # noqa: E402
from teamlib.envfile import ENV_FILE, env_text, write_env  # noqa: E402
from teamlib.names import make_names  # noqa: E402

SUB = "sub-for-test"
TENANT = "tenant-for-test"
CONFIG_TEXT = (
    f"AZURE_SUBSCRIPTION_ID={SUB}\n"
    "AZURE_LOCATION=japaneast\n"
    "WORKSHOP_ORG=acme\n"
    f"AZURE_TENANT={TENANT}\n"
)
NAMES = make_names("acme", "suika")

# どれも、ほかの見本の一部になっていない
ADMIN = "ADMIN" + "PRIMARY" + "0001"
ADMIN2 = "ADMIN" + "SECOND" + "0002"
QUERY = "QUERY" + "FIRST" + "0003"
QUERY2 = "QUERY" + "NEXT" + "0004"
AI = "FOUNDRY" + "ONE" + "0005"
AI2 = "FOUNDRY" + "TWO" + "0006"
ALL_KEYS = (ADMIN, ADMIN2, QUERY, QUERY2, AI, AI2)

ADMIN_CALL = ("search", "admin-key", "show")
QUERY_CALL = ("search", "query-key", "list")
AI_CALL = ("cognitiveservices", "account", "keys", "list")
BAD = "az の答えの形が想定外です"


class FakeAz(Az):
    """az を呼ぶところ（_call）だけ差し替える。run の許可の確認は本物のまま通る。

    responses は (呼び出しの先頭, 答え) の並び。答えが CheckError なら投げる。サインインの確認（account show）は、書かなければ通る。
    当てはまるものがなければ、予想外の呼び出しとして試験を落とす。
    """

    def __init__(self, responses):
        super().__init__(exe="fake-az", subscription=SUB)
        self.responses = [*responses, (("account", "show"), {"id": SUB})]
        self.calls = []

    def _call(self, args, scoped=True):
        args = tuple(args)
        self.calls.append(args)
        for prefix, answer in self.responses:
            if args[: len(prefix)] == prefix:
                if isinstance(answer, CheckError):
                    raise answer
                return answer
        raise AssertionError(f"予想外の az の呼び出し：{args}")


def answers(**changes):
    """キーを読む3つの答え。changes（admin、query、ai）で差し替える。"""
    base = {
        "admin": {"primaryKey": ADMIN, "secondaryKey": ADMIN2},
        "query": [{"name": "", "key": QUERY}, {"name": "second", "key": QUERY2}],
        "ai": {"key1": AI, "key2": AI2},
    }
    base.update(changes)
    return FakeAz([(ADMIN_CALL, base["admin"]), (QUERY_CALL, base["query"]), (AI_CALL, base["ai"])])


class TempCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / ".env.local"

    def read(self):
        return self.path.read_text(encoding="utf-8")

    def items(self):
        """書かれた KEY=VALUE を dict にする（# の行と空行は除く）。"""
        pairs = (line.split("=", 1) for line in self.read().splitlines() if line.strip() and not line.startswith("#"))
        return {key: value for key, value in pairs}


# ------------------------------------------------------------------ env_text

class EnvTextTest(unittest.TestCase):
    def test_builder_items(self):
        text = env_text(NAMES, "builder", ADMIN, AI)
        lines = [line for line in text.splitlines() if line and not line.startswith("#")]
        self.assertEqual(lines, [
            "AZURE_SEARCH_ENDPOINT=https://srch-acme-suika.search.windows.net",
            f"AZURE_SEARCH_API_KEY={ADMIN}",
            "AZURE_SEARCH_KEY_ROLE=admin",
            "AZURE_OPENAI_ENDPOINT=https://ai-acme-suika.openai.azure.com/",
            f"AZURE_OPENAI_API_KEY={AI}",
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small",
            "AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-5-mini",
            "EMBEDDING_DIMENSIONS=1536",
        ])

    def test_member_items_differ_only_in_search_key_and_role(self):
        builder = env_text(NAMES, "builder", ADMIN, AI).replace(ADMIN, QUERY).replace("KEY_ROLE=admin", "KEY_ROLE=query")
        member = env_text(NAMES, "member", QUERY, AI)
        body = lambda text: [line for line in text.splitlines() if not line.startswith("#")]  # noqa: E731
        self.assertEqual(body(member), body(builder))
        self.assertIn("AZURE_SEARCH_KEY_ROLE=query", member)

    def test_text_ends_with_newline_and_names_the_team(self):
        text = env_text(NAMES, "member", QUERY, AI)
        self.assertTrue(text.endswith("\n"))
        self.assertIn("suika", text.splitlines()[0])
        self.assertTrue(text.startswith("#"))

    def test_unknown_role_is_refused(self):
        for role in ("admin", "query", "Member", "", None):
            with self.subTest(role=role), self.assertRaises(ValueError):
                env_text(NAMES, role, QUERY, AI)

    def test_example_lists_the_same_items(self):
        """config/env.example は、項目の名前だけ。env_text が書く項目と同じ並び。"""
        example = (REPO_DIR / "config" / "env.example").read_text(encoding="utf-8")
        names = [line.split("=", 1)[0] for line in example.splitlines() if line.strip() and not line.startswith("#")]
        written = [line.split("=", 1)[0] for line in env_text(NAMES, "builder", ADMIN, AI).splitlines() if line and not line.startswith("#")]
        self.assertEqual(names, written)
        for line in example.splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertTrue(line.endswith("="), f"値を書いてはいけない：{line.split('=')[0]}")


# ------------------------------------------------------------------ write_env

class WriteEnvTest(TempCase):
    def test_member_has_query_key_only(self):
        """メンバーの .env.local に、AI Search の管理者キーは入らない。管理者キーを読みにも行かない。"""
        az = answers()
        write_env(az, NAMES, "member", self.path)
        text = self.read()
        self.assertEqual(self.items()["AZURE_SEARCH_KEY_ROLE"], "query")
        self.assertEqual(self.items()["AZURE_SEARCH_API_KEY"], QUERY)
        for admin in (ADMIN, ADMIN2):
            self.assertNotIn(admin, text)
        self.assertNotIn(ADMIN_CALL, [call[:3] for call in az.calls], "メンバーのために、管理者キーを読んではいけない")

    def test_builder_has_admin_key(self):
        az = answers()
        write_env(az, NAMES, "builder", self.path)
        self.assertEqual(self.items()["AZURE_SEARCH_KEY_ROLE"], "admin")
        self.assertEqual(self.items()["AZURE_SEARCH_API_KEY"], ADMIN)
        self.assertNotIn(QUERY_CALL, [call[:3] for call in az.calls])

    def test_only_the_expected_keys_are_written(self):
        """管理者は primaryKey、検索用は先頭の key、Foundry は key1。ほかのキーは書かない。"""
        for role, wanted in (("builder", (ADMIN, AI)), ("member", (QUERY, AI))):
            with self.subTest(role=role):
                write_env(answers(), NAMES, role, self.path)
                text = self.read()
                for key in ALL_KEYS:
                    self.assertEqual(key in text, key in wanted, key)

    def test_foundry_key_is_the_same_for_both_roles(self):
        for role in ("builder", "member"):
            with self.subTest(role=role):
                write_env(answers(), NAMES, role, self.path)
                self.assertEqual(self.items()["AZURE_OPENAI_API_KEY"], AI)

    def test_write_env_does_not_print_keys(self):
        for role in ("builder", "member"):
            with self.subTest(role=role):
                shown = write_env(answers(), NAMES, role, self.path)
                for key in ALL_KEYS:
                    self.assertNotIn(key, shown)
                self.assertIn(".env.local", shown)
                self.assertIn("suika", shown)

    def test_keys_are_not_in_az_arguments(self):
        """az に渡す引数にも、キーは出ない（読む側の引数にあるのは、名前だけ）。"""
        az = answers()
        write_env(az, NAMES, "member", self.path)
        for call in az.calls:
            for key in ALL_KEYS:
                self.assertFalse(any(key in part for part in call), call)

    def test_az_is_asked_for_this_teams_resources(self):
        az = answers()
        write_env(az, NAMES, "builder", self.path)
        admin = next(call for call in az.calls if call[:3] == ADMIN_CALL)
        self.assertEqual(admin[3:], ("--service-name", "srch-acme-suika", "-g", "rg-acme-suika"))
        foundry = next(call for call in az.calls if call[:4] == AI_CALL)
        self.assertEqual(foundry[4:], ("-n", "ai-acme-suika", "-g", "rg-acme-suika"))

    def test_existing_file_is_replaced(self):
        self.path.write_text("OLD_SETTING=1\nAZURE_SEARCH_API_KEY=" + ADMIN2 + "\n", encoding="utf-8")
        write_env(answers(), NAMES, "member", self.path)
        text = self.read()
        self.assertNotIn("OLD_SETTING", text)
        self.assertNotIn(ADMIN2, text)

    def test_unknown_role_reads_and_writes_nothing(self):
        az = answers()
        with self.assertRaises(ValueError):
            write_env(az, NAMES, "owner", self.path)
        self.assertEqual(az.calls, [])
        self.assertFalse(self.path.exists())

    def test_no_query_key_stops_without_creating_one(self):
        """検索用のキーが0件なら、メンバーの設定を作らない。管理者キーで代わりにもしない。作る操作もしない。"""
        az = answers(query=[])
        with self.assertRaises(CheckError) as caught:
            write_env(az, NAMES, "member", self.path)
        self.assertIn("検索用のキーがありません", caught.exception.detail)
        self.assertFalse(self.path.exists())
        self.assertNotIn(ADMIN_CALL, [call[:3] for call in az.calls])
        self.assertFalse(any("create" in call or "renew" in call for call in az.calls))

    def test_no_query_key_does_not_stop_the_builder(self):
        write_env(answers(query=[]), NAMES, "builder", self.path)
        self.assertEqual(self.items()["AZURE_SEARCH_API_KEY"], ADMIN)

    def test_unexpected_search_answer_writes_nothing(self):
        cases = {
            "admin": (None, {}, [], "x", 3, {"primaryKey": ""}, {"primaryKey": None}, {"primaryKey": 3},
                      {"primaryKey": ["a"]}, {"secondaryKey": ADMIN2}),
            "query": (None, {}, "x", 3, [None], ["x"], [{}], [{"name": "a"}], [{"key": ""}], [{"key": None}], [{"key": 3}],
                      [{"key": ["a"]}]),
        }
        for which, role in (("admin", "builder"), ("query", "member")):
            for bad in cases[which]:
                with self.subTest(role=role, answer=bad):
                    with self.assertRaises(CheckError) as caught:
                        write_env(answers(**{which: bad}), NAMES, role, self.path)
                    self.assertEqual(caught.exception.detail, BAD)
                    self.assertFalse(self.path.exists())

    def test_unexpected_foundry_answer_writes_nothing(self):
        for role in ("builder", "member"):
            for bad in (None, {}, [], "x", 3, {"key1": ""}, {"key1": None}, {"key1": 3}, {"key2": AI2}, {"key1": ["a"]}):
                with self.subTest(role=role, answer=bad):
                    with self.assertRaises(CheckError) as caught:
                        write_env(answers(ai=bad), NAMES, role, self.path)
                    self.assertEqual(caught.exception.detail, BAD)
                    self.assertFalse(self.path.exists())

    def test_key_that_could_inject_a_line_is_refused(self):
        """キーに改行や空白があれば、別の行を書き込めてしまう。書かずに止める。"""
        bad_keys = (QUERY + "\nAZURE_SEARCH_KEY_ROLE=admin", QUERY + " x", QUERY + "\r", "\t" + QUERY)
        for bad in bad_keys:
            with self.subTest(key=bad):
                with self.assertRaises(CheckError) as caught:
                    write_env(answers(query=[{"key": bad}]), NAMES, "member", self.path)
                self.assertEqual(caught.exception.detail, BAD)
                self.assertNotIn(QUERY, caught.exception.detail)
                self.assertFalse(self.path.exists())

    def test_az_errors_become_plain_messages_and_write_nothing(self):
        cases = (
            ("notfound", "builder", ADMIN_CALL, "がまだありません"),
            ("denied", "builder", ADMIN_CALL, "キーを読む権限がありません"),
            ("notfound", "member", QUERY_CALL, "がまだありません"),
            ("denied", "member", QUERY_CALL, "キーを読む権限がありません"),
            ("notfound", "member", AI_CALL, "がまだありません"),
            ("denied", "member", AI_CALL, "キーを読む権限がありません"),
        )
        for kind, role, call, message in cases:
            with self.subTest(kind=kind, role=role, call=call[:3]):
                az = FakeAz([(call, CheckError(kind, "ERROR: raw az text")),
                             (ADMIN_CALL, {"primaryKey": ADMIN}), (QUERY_CALL, [{"key": QUERY}]), (AI_CALL, {"key1": AI})])
                with self.assertRaises(CheckError) as caught:
                    write_env(az, NAMES, role, self.path)
                self.assertEqual(caught.exception.kind, "other")
                self.assertIn(message, caught.exception.detail)
                self.assertNotIn("raw az text", caught.exception.detail)
                self.assertFalse(self.path.exists())

    def test_login_error_passes_through(self):
        """サインイン切れは、main が az login の案内にできるよう、そのまま上へ。"""
        az = FakeAz([(AI_CALL, CheckError("login", "")), (ADMIN_CALL, {"primaryKey": ADMIN})])
        with self.assertRaises(CheckError) as caught:
            write_env(az, NAMES, "builder", self.path)
        self.assertEqual(caught.exception.kind, "login")
        self.assertFalse(self.path.exists())

    def test_unwritable_path_is_a_plain_error(self):
        with self.assertRaises(CheckError) as caught:
            write_env(answers(), NAMES, "member", self.dir / "no-such-dir" / ".env.local")
        self.assertIn(".env.local", caught.exception.detail)
        for key in ALL_KEYS:
            self.assertNotIn(key, caught.exception.detail)

    def test_written_as_utf8(self):
        write_env(answers(), NAMES, "member", self.path)
        self.assertIn("チーム suika", self.path.read_bytes().decode("utf-8"))

    def test_default_path_is_repo_env_local(self):
        self.assertEqual(ENV_FILE, REPO_DIR / ".env.local")


class GitignoreTest(unittest.TestCase):
    def test_env_file_is_gitignored(self):
        done = subprocess.run(["git", "check-ignore", "-q", ".env.local"], cwd=REPO_DIR, capture_output=True)
        self.assertEqual(done.returncode, 0, ".env.local が .gitignore に入っていない")


# ------------------------------------------------------------------ team.py env

class EnvCommandTest(TempCase):
    def setUp(self):
        super().setUp()
        self.config = self.dir / "workshop.config"
        self.config.write_text(CONFIG_TEXT, encoding="utf-8")

    def run_main(self, *extra, az=None, role="member"):
        argv = ["env", "--config", str(self.config), "--team", "suika"]
        if role is not None:
            argv += ["--role", role]
        argv += list(extra)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = team.main(argv, az=az, env_path=self.path)
        return code, out.getvalue(), err.getvalue()

    def test_member_writes_query_key_and_shows_no_key(self):
        az = answers()
        code, out, err = self.run_main(az=az, role="member")
        self.assertEqual(code, 0, out)
        self.assertEqual(err, "")
        self.assertEqual(self.items()["AZURE_SEARCH_KEY_ROLE"], "query")
        self.assertNotIn(ADMIN, self.read())
        self.assertIn("OK", out)
        for key in ALL_KEYS:
            self.assertNotIn(key, out)
        self.assertNotIn(ADMIN_CALL, [call[:3] for call in az.calls])

    def test_builder_writes_admin_key_and_shows_no_key(self):
        code, out, _ = self.run_main(az=answers(), role="builder")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.items()["AZURE_SEARCH_KEY_ROLE"], "admin")
        self.assertEqual(self.items()["AZURE_SEARCH_API_KEY"], ADMIN)
        for key in ALL_KEYS:
            self.assertNotIn(key, out)

    def test_role_is_required_and_checked(self):
        for role in (None, "owner", "admin"):
            with self.subTest(role=role), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.run_main(az=answers(), role=role)
        self.assertFalse(self.path.exists())

    def test_no_query_key_exits_1_with_reason(self):
        code, out, err = self.run_main(az=answers(query=[]), role="member")
        self.assertEqual(code, 1)
        self.assertIn("検索用のキーがありません", out)
        self.assertNotIn("Traceback", out + err)
        self.assertFalse(self.path.exists())

    def test_not_signed_in_points_to_az_login_and_writes_nothing(self):
        az = FakeAz([(("account", "show"), CheckError("login", "az login"))])
        code, out, _ = self.run_main(az=az)
        self.assertEqual(code, 1)
        self.assertIn(f"az login --tenant {TENANT}", out)
        self.assertFalse(self.path.exists())
        self.assertEqual({call[:2] for call in az.calls}, {("account", "show")})

    def test_sign_in_lost_while_reading_keys(self):
        az = FakeAz([(QUERY_CALL, CheckError("login", "")), (AI_CALL, {"key1": AI})])
        code, out, _ = self.run_main(az=az)
        self.assertEqual(code, 1)
        self.assertIn(f"az login --tenant {TENANT}", out)
        self.assertFalse(self.path.exists())

    def test_bad_team_stops_before_az(self):
        class NoAz:
            def __getattr__(self, name):
                raise AssertionError("チームの名前が違うとき、az を呼んではいけない")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = team.main(["env", "--config", str(self.config), "--team", "Suika", "--role", "member"], az=NoAz(), env_path=self.path)
        self.assertEqual(code, 2)
        self.assertIn("チームの名前", err.getvalue())
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
