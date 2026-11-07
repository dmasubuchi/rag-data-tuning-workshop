"""tools/team.py と tools/teamlib/az.py の試験。

通信しない。az は、本物の Az を継いで _call だけ差し替えた偽物（FakeAz）を使う。
AI Search の件数の取得（urllib.request.urlopen）は、偽物（FakeHttp）に差し替える（MainCase.run_main が、いつも差し替える）。
そのため、names・check-names・health が許可リスト（READ_ONLY）の外のコマンドを呼べば、試験の中でも CheckError になる。
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))

import team  # noqa: E402
from teamlib.az import READ_ONLY, Az, CheckError, find_az  # noqa: E402
from teamlib.names import make_names  # noqa: E402
PREFIX = team.PREFIX

SUB = "0123abcd" + "-4567-" + "89ab-cdef-" + "0123456789ab"   # サブスクリプション ID の形（つないで作る）
TENANT = "tenant-for-test"
CONFIG_TEXT = (
    f"AZURE_SUBSCRIPTION_ID={SUB}\n"
    "AZURE_LOCATION=japaneast\n"
    "WORKSHOP_ORG=acme\n"
    f"AZURE_TENANT={TENANT}\n"
)
NAMES = make_names("acme", "suika")
NOTFOUND = CheckError("notfound", "ResourceNotFound")


# ------------------------------------------------------------------ 偽物の az

class FakeAz(Az):
    """az を呼ぶところ（_call）だけ差し替える。run・get・post の許可の確認は本物のまま通る。

    responses は (呼び出しの先頭, 答え) の並び。答えが CheckError なら投げる。サインインの確認（account show）は、書かなければ通る。
    当てはまるものがなければ default を返す（None のままなら、予想外の呼び出しとして試験を落とす）。
    """

    def __init__(self, responses=(), default=None):
        super().__init__(exe="fake-az", subscription=SUB)
        self.responses = [*responses, (("account", "show"), {"id": SUB})]
        self.default = default
        self.calls = []

    @staticmethod
    def key(args):
        """az rest は (rest, 方法, 最後の道筋, 名前)、ほかは引数そのまま。"""
        if args[0] != "rest":
            return tuple(args)
        method, url = args[2], args[4]
        endpoint = url.split("?")[0].rsplit("/", 1)[-1]
        if method != "post":
            return ("rest", method, endpoint)
        body = json.loads(Path(args[6][1:]).read_text(encoding="utf-8"))
        return ("rest", method, endpoint, body.get("name") or body.get("subdomainName"))

    def _call(self, args, scoped=True):
        key = self.key(args)
        self.calls.append(key)
        for prefix, answer in self.responses:
            if key[: len(prefix)] == prefix:
                break
        else:
            answer = self.default
            if answer is None:
                raise AssertionError(f"予想外の az の呼び出し：{key}")
        if isinstance(answer, CheckError):
            raise answer
        return answer


FAKE_KEY = "fake-query-" + "key-" + "0123456789abcdef"      # 検索用のキーの形の偽物（つないで作る）
FAKE_ADMIN = "fake-admin-" + "key-" + "fedcba9876543210"     # 管理者キーの形の偽物。health は、これを読まない


def http_error(code, url="https://example.invalid/"):
    return urllib.error.HTTPError(url, code, f"error {code}", {}, io.BytesIO(b""))


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    """urllib.request.urlopen の代わり。インデックスごとの答えを返す。書いていないインデックスは 404（まだない）。

    答えは、数（int）・本文（bytes）・投げる例外のどれか。requests に、受け取った Request を残す。
    """

    URL = re.compile(r"https://([^/]+)/indexes/([^/]+)/docs/\$count\?api-version=(.+)")

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        found = self.URL.fullmatch(request.full_url)
        if not found:
            raise AssertionError(f"予想外の URL：{request.full_url}")
        answer = self.answers.get(found.group(2), http_error(404, request.full_url))
        if isinstance(answer, BaseException):
            raise answer
        return FakeResponse(str(answer).encode() if isinstance(answer, int) else answer)


def names_free():
    """5つの名前がどこにも使われていない。"""
    return [
        (("group", "exists"), False),
        (("storage", "account", "check-name"), {"nameAvailable": True}),
        (("cosmosdb", "check-name-exists"), False),
        (("rest", "post", "checkNameAvailability"), {"nameAvailable": True}),
        (("rest", "post", "checkDomainAvailability"), {"isSubdomainAvailable": True}),
    ]


def healthy():
    """リソースもデプロイも、そろって動いている。"""
    deployment = lambda name: {"name": name, "sku": {"name": "GlobalStandard", "capacity": 50}, "properties": {"provisioningState": "Succeeded"}}  # noqa: E731
    return [
        (("group", "show"), {"properties": {"provisioningState": "Succeeded"}}),
        (("storage", "account", "show"), {"provisioningState": "Succeeded", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}),
        (("search", "service", "show"), {"provisioningState": "succeeded", "status": "running", "sku": {"name": "basic"}, "semanticSearch": "free"}),
        (("search", "query-key", "list"), [{"name": "member", "key": FAKE_KEY}]),
        (("cognitiveservices", "account", "show"), {"kind": "AIServices", "properties": {"provisioningState": "Succeeded"}}),
        (("cognitiveservices", "account", "deployment", "list"), [deployment("text-embedding-3-small"), deployment("gpt-5-mini")]),
    ]


def override(base, *changes):
    """base の答えのうち、changes と同じ呼び出しの先頭のものを差し替える。"""
    prefixes = {prefix for prefix, _ in changes}
    return list(changes) + [(prefix, answer) for prefix, answer in base if prefix not in prefixes]


class MainCase(unittest.TestCase):
    """main を一時フォルダーの workshop.config で動かして、画面の文と終了コードを取る。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = self.write_config(CONFIG_TEXT)

    def write_config(self, text, name="workshop.config"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_main(self, command, *extra, team_name="suika", az=None, environ=None, http=None):
        """http は偽の urlopen（FakeHttp）。省略すると、どのインデックスも 404。本物の通信は、どの試験でもしない。"""
        argv = [command, "--config", str(self.config)]
        if team_name is not None:
            argv += ["--team", team_name]
        argv += list(extra)
        self.http = http or FakeHttp()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with mock.patch.dict(os.environ, environ or {}, clear=environ is not None):
                with mock.patch("urllib.request.urlopen", self.http):
                    code = team.main(argv, az=az)
        return code, out.getvalue(), err.getvalue()


# ------------------------------------------------------------------ az.py

class FindAzTest(unittest.TestCase):
    def which(self, found):
        return mock.patch("teamlib.az.shutil.which", side_effect=lambda name: found.get(name))

    def test_find_az_windows(self):
        with self.which({"az.cmd": r"C:\az\wbin\az.cmd"}):
            self.assertEqual(find_az(), r"C:\az\wbin\az.cmd")

    def test_find_az_prefers_az(self):
        with self.which({"az": "/usr/bin/az", "az.cmd": "/x/az.cmd"}):
            self.assertEqual(find_az(), "/usr/bin/az")

    def test_find_az_none(self):
        with self.which({}):
            self.assertIsNone(find_az())

    def test_az_without_subscription_is_refused(self):
        with self.assertRaises(CheckError):
            Az(exe="fake-az")

    def test_az_without_exe_is_noaz(self):
        with mock.patch("teamlib.az.shutil.which", return_value=None):
            with self.assertRaises(CheckError) as caught:
                Az(subscription=SUB)
        self.assertEqual(caught.exception.kind, "noaz")


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.az = Az(exe="fake-az", subscription=SUB)

    def test_run_rejects_write_commands(self):
        writes = [
            ("group", "delete", "-n", "rg-acme-suika"),
            ("group", "create", "-n", "rg-acme-suika", "-l", "japaneast"),
            ("storage", "account", "delete", "-n", "stacmesuika"),
            ("search", "service", "create", "-n", "x"),
            ("search", "query-key", "create", "--service-name", "x"),
            ("search", "admin-key", "renew"),
            ("cognitiveservices", "account", "keys", "regenerate"),
            ("role", "assignment", "create"),
            ("rest", "--method", "delete", "--url", "https://example.invalid"),
            (),
        ]
        with mock.patch("teamlib.az.subprocess.run", side_effect=AssertionError("az を実行してはいけない")) as run:
            for args in writes:
                with self.subTest(args=args), self.assertRaises(CheckError) as caught:
                    self.az.run(*args)
                self.assertEqual(caught.exception.kind, "other")
            run.assert_not_called()

    def test_allowlist_has_query_key_list_and_no_writes(self):
        self.assertIn(("search", "query-key", "list"), READ_ONLY)
        self.assertIn(("search", "admin-key", "show"), READ_ONLY)
        self.assertIn(("cognitiveservices", "account", "keys", "list"), READ_ONLY)
        verbs = {prefix[-1] for prefix in READ_ONLY}
        self.assertFalse(verbs & {"create", "delete", "update", "set", "renew", "regenerate", "remove"})

    def test_run_builds_command_and_parses_json(self):
        with mock.patch("teamlib.az.subprocess.run", return_value=completed('{"a": 1}')) as run:
            self.assertEqual(self.az.run("group", "show", "-n", "rg-acme-suika"), {"a": 1})
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:4], ["fake-az", "group", "show", "-n"])
        self.assertIn("--only-show-errors", cmd)
        self.assertEqual(cmd[cmd.index("-o") + 1], "json")
        self.assertEqual(cmd[cmd.index("--subscription") + 1], SUB)

    def test_az_never_reads_from_the_keyboard(self):
        """az が入力を待って止まらないよう、標準入力は空にする。"""
        with mock.patch("teamlib.az.subprocess.run", return_value=completed('{"a": 1}')) as run:
            self.az.run("group", "show", "-n", "rg-acme-suika")
        self.assertIs(run.call_args.kwargs.get("stdin"), subprocess.DEVNULL)

    def test_post_never_reads_from_the_keyboard_either(self):
        url = f"https://management.azure.com/subscriptions/{SUB}/providers/Microsoft.Search/checkNameAvailability?api-version=2023-11-01"
        with mock.patch("teamlib.az.subprocess.run", return_value=completed('{"nameAvailable": true}')) as run:
            self.az.post(url, {"name": "x", "type": "searchServices"})
        self.assertIs(run.call_args.kwargs.get("stdin"), subprocess.DEVNULL)

    def test_run_false_is_returned_not_none(self):
        with mock.patch("teamlib.az.subprocess.run", return_value=completed("false")):
            self.assertIs(self.az.run("group", "exists", "-n", "x"), False)

    def test_run_empty_output_is_none(self):
        with mock.patch("teamlib.az.subprocess.run", return_value=completed("")):
            self.assertIsNone(self.az.run("account", "show"))

    def test_run_bad_json_is_other(self):
        with mock.patch("teamlib.az.subprocess.run", return_value=completed("not json")):
            with self.assertRaises(CheckError) as caught:
                self.az.run("account", "show")
        self.assertEqual(caught.exception.kind, "other")

    def test_failure_kinds(self):
        cases = {
            "ERROR: Please run 'az login' to setup account.": "login",
            "ERROR: The subscription of 'x' doesn't exist in cloud 'AzureCloud'.": "login",
            "ERROR: (AuthorizationFailed) The client does not have authorization": "denied",
            "ERROR: (ResourceGroupNotFound) Resource group 'x' could not be found.": "notfound",
            "ERROR: something strange": "other",
        }
        for stderr, kind in cases.items():
            with self.subTest(kind=kind), mock.patch("teamlib.az.subprocess.run", return_value=completed("", stderr, 1)):
                with self.assertRaises(CheckError) as caught:
                    self.az.run("account", "show")
                self.assertEqual(caught.exception.kind, kind)

    def test_error_detail_hides_secret_values(self):
        stderr = "WARNING: old module\nERROR: bad request key=abc123secret more"
        with mock.patch("teamlib.az.subprocess.run", return_value=completed("", stderr, 1)):
            with self.assertRaises(CheckError) as caught:
                self.az.run("account", "show")
        self.assertNotIn("abc123secret", caught.exception.detail)
        self.assertNotIn("WARNING", caught.exception.detail)

    def test_timeout_and_oserror(self):
        for error in (subprocess.TimeoutExpired("az", 1), OSError("no")):
            with self.subTest(error=type(error).__name__), mock.patch("teamlib.az.subprocess.run", side_effect=error):
                with self.assertRaises(CheckError) as caught:
                    self.az.run("account", "show")
                self.assertEqual(caught.exception.kind, "other")


class GetPostTest(unittest.TestCase):
    ARM_SUB = f"https://management.azure.com/subscriptions/{SUB}"

    def setUp(self):
        self.az = Az(exe="fake-az", subscription=SUB)

    def test_get_only_own_subscription(self):
        url = f"{self.ARM_SUB}/resourceGroups/rg/providers/Microsoft.Foo/accounts/x/projects?api-version=1"
        with mock.patch("teamlib.az.subprocess.run", return_value=completed('{"value": []}')) as run:
            self.assertEqual(self.az.get(url), {"value": []})
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[1:6], ["rest", "--method", "get", "--url", url])
        self.assertNotIn("--subscription", cmd)
        with mock.patch("teamlib.az.subprocess.run", side_effect=AssertionError("実行してはいけない")):
            for bad in ("https://example.invalid/subscriptions/x", "https://management.azure.com/subscriptions/other-sub/resourceGroups",
                        "https://management.azure.com/tenants"):
                with self.subTest(url=bad), self.assertRaises(CheckError):
                    self.az.get(bad)

    def test_post_only_name_availability_with_temp_body(self):
        url = f"{self.ARM_SUB}/providers/Microsoft.Search/checkNameAvailability?api-version=2023-11-01"
        seen = {}

        def fake_run(cmd, **kwargs):
            body_path = Path(cmd[cmd.index("--body") + 1][1:])
            seen["path"] = body_path
            seen["body"] = json.loads(body_path.read_text(encoding="utf-8"))
            return completed('{"nameAvailable": true}')

        with mock.patch("teamlib.az.subprocess.run", side_effect=fake_run):
            self.assertEqual(self.az.post(url, {"name": "srch-acme-suika", "type": "searchServices"}), {"nameAvailable": True})
        self.assertEqual(seen["body"]["name"], "srch-acme-suika")
        self.assertFalse(seen["path"].exists(), "一時ファイルが残っている")

    def test_post_rejects_other_urls(self):
        with mock.patch("teamlib.az.subprocess.run", side_effect=AssertionError("実行してはいけない")):
            for bad in (f"{self.ARM_SUB}/resourcegroups/rg?api-version=1",
                        f"{self.ARM_SUB}/providers/Microsoft.Search/searchServices/x/listAdminKeys",
                        "https://example.invalid/subscriptions/x/checkNameAvailability"):
                with self.subTest(url=bad), self.assertRaises(CheckError):
                    self.az.post(bad, {})


# ------------------------------------------------------------------ check-names

class CheckNamesTest(MainCase):
    def test_check_names_states(self):
        # 使える
        az = FakeAz(names_free())
        code, out, _ = self.run_main("check-names", az=az)
        self.assertEqual(code, 0)
        for label, name in (("リソース グループ", "rg-acme-suika"), ("Storage", "stacmesuika"), ("AI Search", "srch-acme-suika"),
                            ("Cosmos DB", "cosmos-acme-suika"), ("Foundry", "ai-acme-suika")):
            self.assertIn(f"{label} {name}：使える", out)
        self.assertIn("すべて使えます", out)

        # ほかで使われている（名前は取られているが、このサブスクリプションにはない）
        taken = override(names_free(),
                         (("storage", "account", "check-name"), {"nameAvailable": False}),
                         (("rest", "post", "checkNameAvailability"), {"nameAvailable": False}),
                         (("resource", "list"), []))
        code, out, _ = self.run_main("check-names", az=FakeAz(taken))
        self.assertEqual(code, 1)
        self.assertIn("Storage stacmesuika：ほかで使われている", out)
        self.assertIn("AI Search srch-acme-suika：ほかで使われている", out)
        self.assertIn("リソース グループ rg-acme-suika：使える", out)
        self.assertIn("チームの名前を変えて", out)

        # 作成済み（このサブスクリプションにある）
        created = override(names_free(),
                           (("group", "exists"), True),
                           (("storage", "account", "check-name"), {"nameAvailable": False}),
                           (("resource", "list"), [{"name": "stacmesuika"}]))
        code, out, _ = self.run_main("check-names", az=FakeAz(created))
        self.assertEqual(code, 0)
        self.assertIn("リソース グループ rg-acme-suika：このサブスクリプションに作成済み", out)
        self.assertIn("Storage stacmesuika：このサブスクリプションに作成済み", out)
        self.assertIn("AI Search srch-acme-suika：使える", out)

    def test_check_names_reads_no_keys(self):
        az = FakeAz(names_free())
        self.run_main("check-names", az=az)
        self.assertTrue(az.calls)
        self.assertEqual([c for c in az.calls if c[0] in ("search", "cognitiveservices")], [], "キーを読む az を呼んではいけない")

    def test_check_names_unknown_state_is_error(self):
        denied = override(names_free(), (("storage", "account", "check-name"), CheckError("denied", "AuthorizationFailed")))
        code, out, _ = self.run_main("check-names", az=FakeAz(denied))
        self.assertEqual(code, 1)
        self.assertIn("Storage stacmesuika：確認できない（権限がありません）", out)
        self.assertIn("AI Search srch-acme-suika：使える", out)  # ほかの名前の確認は続く

    def test_check_names_posts_to_own_subscription(self):
        az = FakeAz(names_free())
        urls = []
        original = az.post

        def spy(url, body):
            urls.append((url, body))
            return original(url, body)

        az.post = spy
        self.run_main("check-names", az=az)
        self.assertEqual(len(urls), 2)
        for url, _ in urls:
            self.assertTrue(url.startswith(f"https://management.azure.com/subscriptions/{SUB}/providers/"))
        bodies = {tuple(sorted(b.items())) for _, b in urls}
        self.assertIn((("name", "srch-acme-suika"), ("type", "searchServices")), bodies)



# ------------------------------------------------------------------ 既存のリソース グループ（AZURE_RESOURCE_GROUP）

CUSTOM_RG = "day1-rg"


class CustomGroupTest(MainCase):
    """workshop.config に AZURE_RESOURCE_GROUP があるとき、names・check-names・health は、その名前（-n / -g）を使う。"""

    def setUp(self):
        super().setUp()
        self.config = self.write_config(CONFIG_TEXT + f"AZURE_RESOURCE_GROUP={CUSTOM_RG}\n")

    def test_names_shows_the_existing_group(self):
        code, out, _ = self.run_main("names")
        self.assertEqual(code, 0)
        self.assertIn(f"リソース グループ：{CUSTOM_RG}（既存のものを使う", out)
        self.assertNotIn("rg-acme-suika", out)
        self.assertIn("stacmesuika", out)   # ほかの名前は変わらない

    def test_names_without_the_key_shows_no_existing_note(self):
        self.config = self.write_config(CONFIG_TEXT)
        code, out, _ = self.run_main("names")
        self.assertIn("リソース グループ：rg-acme-suika\n", out)
        self.assertNotIn("既存のものを使う", out)

    def test_check_names_existing_group_row_and_no_rename_advice(self):
        az = FakeAz(override(names_free(), (("group", "exists"), True)))
        code, out, _ = self.run_main("check-names", az=az)
        self.assertEqual(code, 0, out)
        self.assertIn(("group", "exists", "-n", CUSTOM_RG), az.calls)
        self.assertNotIn(("group", "exists", "-n", "rg-acme-suika"), az.calls)
        self.assertIn(f"リソース グループ {CUSTOM_RG}：既存のものを使う（AZURE_RESOURCE_GROUP）", out)
        self.assertNotIn("作成済み", out)
        self.assertNotIn("チームの名前を変え", out)
        self.assertIn("Storage stacmesuika：使える", out)
        self.assertIn("ほかの名前はすべて使えます", out)

    def test_check_names_existing_group_with_taken_name_still_advises_rename(self):
        taken = override(names_free(), (("group", "exists"), True),
                         (("storage", "account", "check-name"), {"nameAvailable": False}), (("resource", "list"), []))
        code, out, _ = self.run_main("check-names", az=FakeAz(taken))
        self.assertEqual(code, 1)
        self.assertIn(f"リソース グループ {CUSTOM_RG}：既存のものを使う（AZURE_RESOURCE_GROUP）", out)
        self.assertIn("Storage stacmesuika：ほかで使われている", out)
        self.assertIn("チームの名前を変えて", out)

    def test_check_names_missing_existing_group_is_a_config_mistake(self):
        az = FakeAz(names_free())   # group exists は False
        code, out, _ = self.run_main("check-names", az=az)
        self.assertEqual(code, 1)
        self.assertIn(f"AZURE_RESOURCE_GROUP のリソース グループ {CUSTOM_RG} が見つかりません", out)
        self.assertIn(f"リソース グループ {CUSTOM_RG}：見つかりません", out)
        self.assertNotIn(f"リソース グループ {CUSTOM_RG}：使える", out)
        self.assertNotIn("すべて使えます", out)
        self.assertNotIn("チームの名前を変え", out)
        self.assertIn("Storage stacmesuika：使える", out)   # ほかの名前の確認は続く

    def test_check_names_without_the_key_still_treats_a_missing_group_as_free(self):
        self.config = self.write_config(CONFIG_TEXT)
        code, out, _ = self.run_main("check-names", az=FakeAz(names_free()))
        self.assertEqual(code, 0)
        self.assertIn("リソース グループ rg-acme-suika：使える", out)
        self.assertNotIn("AZURE_RESOURCE_GROUP", out)

    def test_health_uses_the_existing_group(self):
        az = FakeAz(healthy())
        code, out, _ = self.run_main("health", az=az)
        self.assertEqual(code, 0, out)
        self.assertIn(f"OK    リソース グループ {CUSTOM_RG}", out)
        self.assertNotIn("rg-acme-suika", out)
        self.assertIn(("group", "show", "-n", CUSTOM_RG), az.calls)
        self.assertIn(("storage", "account", "show", "-n", "stacmesuika", "-g", CUSTOM_RG), az.calls)
        self.assertIn(("search", "service", "show", "-n", "srch-acme-suika", "-g", CUSTOM_RG), az.calls)
        self.assertIn(("cognitiveservices", "account", "show", "-n", "ai-acme-suika", "-g", CUSTOM_RG), az.calls)

    def test_health_missing_existing_group_is_ng_and_points_to_the_config(self):
        """既存のグループを使う設定で見つからない＝名前の間違いの疑い。そのグループの行だけ NG にして、終了コードは 1。"""
        az = FakeAz(default=NOTFOUND)
        code, out, _ = self.run_main("health", az=az)
        self.assertEqual(code, 1, out)
        rows = [line for line in out.splitlines() if line.startswith(tuple(PREFIX.values()))]
        self.assertEqual(len(rows), 8)
        self.assertTrue(rows[0].startswith(PREFIX[team.NG] + f"リソース グループ {CUSTOM_RG}"), rows[0])
        for hint in ("見つかりません", "workshop.config", "AZURE_RESOURCE_GROUP"):
            self.assertIn(hint, rows[0])
        self.assertTrue(all(line.startswith(PREFIX[team.MADA]) for line in rows[1:]), out)
        self.assertIn("OK 0・まだ 7・NG 1", out)
        self.assertEqual(az.calls, [("account", "show"), ("group", "show", "-n", CUSTOM_RG)])   # グループがなければ、ほかは調べない

    def test_health_missing_default_group_is_still_not_yet(self):
        """設定に AZURE_RESOURCE_GROUP がなければ、グループがなくても、従来どおり「まだ」・終了コード 0（これから作る）。"""
        self.config = self.write_config(CONFIG_TEXT)
        code, out, _ = self.run_main("health", az=FakeAz(default=NOTFOUND))
        self.assertEqual(code, 0, out)
        self.assertIn(PREFIX[team.MADA] + "リソース グループ rg-acme-suika", out)
        self.assertIn("OK 0・まだ 8・NG 0", out)
        self.assertNotIn("AZURE_RESOURCE_GROUP", out)

# ------------------------------------------------------------------ health

class HealthTest(MainCase):
    def lines(self, out):
        return [line for line in out.splitlines() if line.startswith(("OK    ", "まだ  ", "NG    "))]

    def test_health_missing_is_not_error(self):
        az = FakeAz(default=NOTFOUND)
        code, out, _ = self.run_main("health", az=az)
        self.assertEqual(code, 0)
        rows = self.lines(out)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(line.startswith("まだ") for line in rows), out)
        self.assertIn("OK 0・まだ 8・NG 0", out)

    def test_health_all_ready(self):
        code, out, _ = self.run_main("health", az=FakeAz(healthy()))
        self.assertEqual(code, 0, out)
        self.assertIn("OK    リソース グループ rg-acme-suika", out)
        self.assertIn("OK    Storage stacmesuika", out)
        self.assertIn("OK    AI Search srch-acme-suika", out)
        self.assertIn("OK    AI Search 価格レベル（Basic）", out)
        self.assertIn("OK    AI Search セマンティック ランカー（Free）", out)
        self.assertIn("OK    Foundry ai-acme-suika", out)
        self.assertIn("OK    デプロイ text-embedding-3-small", out)
        self.assertIn("OK    デプロイ gpt-5-mini", out)
        self.assertIn("OK 8・まだ 0・NG 0", out)

    def test_health_resource_group_only(self):
        az = FakeAz([(("group", "show"), {"properties": {"provisioningState": "Succeeded"}})], default=NOTFOUND)
        code, out, _ = self.run_main("health", az=az)
        self.assertEqual(code, 0)
        self.assertIn("OK    リソース グループ rg-acme-suika（Succeeded）", out)
        self.assertIn("まだ  Storage stacmesuika", out)
        self.assertIn("OK 1・まだ 7・NG 0", out)

    def test_health_resource_group_that_is_not_succeeded_is_not_ok(self):
        """Deleting などは OK にしない。Failed・Canceled は NG（大文字小文字は問わない）。"""
        cases = (("Deleting", "まだ", 0), ("Creating", "まだ", 0), ("Failed", "NG", 1), ("Canceled", "NG", 1),
                 ("failed", "NG", 1), ("", "まだ", 0))
        for state, status, code_wanted in cases:
            with self.subTest(state=state):
                group = override(healthy(), (("group", "show"), {"properties": {"provisioningState": state}}))
                code, out, _ = self.run_main("health", az=FakeAz(group))
                row = next(line for line in self.lines(out) if "リソース グループ" in line)
                self.assertTrue(row.startswith(PREFIX[status]), row)
                self.assertNotIn("OK    リソース グループ", out)
                self.assertEqual(code, code_wanted, out)
                if state:
                    self.assertIn(state, row)

    def test_health_failed_or_canceled_resources_are_ng(self):
        failed = lambda state: [  # noqa: E731
            ("Storage stacmesuika", ("storage", "account", "show"), {"provisioningState": state, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}),
            ("AI Search srch-acme-suika", ("search", "service", "show"),
             {"provisioningState": state, "status": "running", "sku": {"name": "basic"}, "semanticSearch": "free"}),
            ("Foundry ai-acme-suika", ("cognitiveservices", "account", "show"), {"kind": "AIServices", "properties": {"provisioningState": state}}),
        ]
        for state in ("Failed", "Canceled", "failed", "canceled"):
            for label, prefix, answer in failed(state):
                with self.subTest(state=state, resource=label):
                    code, out, _ = self.run_main("health", az=FakeAz(override(healthy(), (prefix, answer))))
                    self.assertEqual(code, 1, out)
                    self.assertIn(f"NG    {label}（{state}）", out)
                    self.assertNotIn(f"OK    {label}", out)

    def test_health_resource_in_progress_is_mada_not_ng(self):
        for state in ("Creating", "Updating", "Accepted", "Deleting"):
            with self.subTest(state=state):
                busy = override(healthy(), (("storage", "account", "show"), {"provisioningState": state}),
                                (("cognitiveservices", "account", "show"), {"kind": "AIServices", "properties": {"provisioningState": state}}))
                code, out, _ = self.run_main("health", az=FakeAz(busy))
                self.assertEqual(code, 0, out)
                self.assertIn(f"まだ  Storage stacmesuika（{state}）", out)
                self.assertIn(f"まだ  Foundry ai-acme-suika（{state}）", out)

    def test_health_wrong_search_settings_are_ng(self):
        wrong = override(healthy(), (("search", "service", "show"),
                                     {"provisioningState": "succeeded", "status": "running", "sku": {"name": "standard"}, "semanticSearch": "disabled"}))
        code, out, _ = self.run_main("health", az=FakeAz(wrong))
        self.assertEqual(code, 1)
        self.assertIn("NG    AI Search 価格レベル（standard。Basic のはず）", out)
        self.assertIn("NG    AI Search セマンティック ランカー（無効。Free にする）", out)
        self.assertIn("NG 2", out)

    def test_health_still_creating_is_mada(self):
        creating = override(healthy(),
                            (("search", "service", "show"), {"provisioningState": "provisioning", "sku": {"name": "basic"}, "semanticSearch": "free"}),
                            (("storage", "account", "show"), {"provisioningState": "Creating"}))
        code, out, _ = self.run_main("health", az=FakeAz(creating))
        self.assertEqual(code, 0)
        self.assertIn("まだ  Storage stacmesuika（Creating）", out)
        self.assertIn("まだ  AI Search srch-acme-suika（provisioning）", out)

    def test_health_deployments(self):
        one = lambda name, state: {"name": name, "sku": {"name": "GlobalStandard", "capacity": 10}, "properties": {"provisioningState": state}}  # noqa: E731
        listing = [one("text-embedding-3-small", "Failed"), one("other-model", "Succeeded")]
        code, out, _ = self.run_main("health", az=FakeAz(override(healthy(), (("cognitiveservices", "account", "deployment", "list"), listing))))
        self.assertEqual(code, 1)
        self.assertIn("NG    デプロイ text-embedding-3-small", out)
        self.assertIn("まだ  デプロイ gpt-5-mini", out)

    def test_health_foundry_of_wrong_kind_is_ng(self):
        wrong = override(healthy(), (("cognitiveservices", "account", "show"), {"kind": "OpenAI", "properties": {"provisioningState": "Succeeded"}}))
        code, out, _ = self.run_main("health", az=FakeAz(wrong))
        self.assertEqual(code, 1)
        self.assertIn("NG    Foundry ai-acme-suika（種類 OpenAI。AIServices のはず）", out)

    def test_health_denied_one_section_keeps_going(self):
        denied = override(healthy(), (("storage", "account", "show"), CheckError("denied", "AuthorizationFailed")))
        code, out, _ = self.run_main("health", az=FakeAz(denied))
        self.assertEqual(code, 1)
        self.assertIn("NG    Storage stacmesuika（権限がありません）", out)
        self.assertIn("OK    AI Search srch-acme-suika", out)
        self.assertIn("OK    デプロイ gpt-5-mini", out)

    def test_health_reads_only_the_query_key(self):
        """文書の数を数えるために、検索用（query）のキーを1回だけ読む。管理者キー・Foundry や Storage のキーは読まない。"""
        az = FakeAz(healthy())
        self.run_main("health", az=az)
        self.assertEqual([c for c in az.calls if "admin-key" in c or "keys" in c or "show-connection-string" in c], [])
        self.assertEqual(sum(1 for c in az.calls if c[:3] == ("search", "query-key", "list")), 1)
        self.assertTrue(az.calls)


# ------------------------------------------------------------------ health：インデックスの文書の数

URL_BASE = "https://srch-acme-suika.search.windows.net/indexes"
TITLE = "インデックスの文書の数（参考。下の OK・まだ・NG には入りません）"
SUMMARY_OK = "OK 8・まだ 0・NG 0"
BODY_BAD = "答えの形が想定外です"   # AI Search の答えの本文が、数でないとき


class HealthCountsTest(MainCase):
    """health は、AI Search の4つのインデックスの文書の数を、参考として足す。OK・まだ・NG の数と、終了コードは変えない。"""

    def count_lines(self, out):
        return [line for line in out.splitlines() if line.startswith("  ") and "件" in line or line.startswith("  ") and "まだない" in line
                or line.startswith("  ") and "数えられません" in line]

    def run_healthy(self, answers=None, az=None):
        return self.run_main("health", az=az or FakeAz(healthy()), http=FakeHttp(answers))

    def test_health_shows_index_counts(self):
        answers = {"sengoku": 150, "hr-docs": 87, "hotels-blob": 50, "hotels-cosmos": 50}
        code, out, err = self.run_healthy(answers)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(TITLE, out)
        self.assertIn("  sengoku        150件（目安 150）", out)
        self.assertIn("  hr-docs        87件（文書 23 から作ったチャンクの数）", out)
        self.assertIn("  hotels-blob    50件（目安 50）", out)
        self.assertIn("  hotels-cosmos  50件（目安 50）", out)
        self.assertNotIn("目安と違う", out)
        self.assertEqual(len(self.count_lines(out)), 4, out)
        # 判定の行はいつもどおり最後。件数の行は、その前の参考
        self.assertEqual(out.splitlines()[-1], SUMMARY_OK)
        self.assertLess(out.index(TITLE), out.index(SUMMARY_OK))

    def test_health_asks_the_count_of_each_index_with_the_query_key(self):
        self.run_healthy({"sengoku": 150})
        urls = [r.full_url for r in self.http.requests]
        self.assertEqual(urls, [f"{URL_BASE}/{name}/docs/$count?api-version=2024-07-01"
                                for name in ("sengoku", "hr-docs", "hotels-blob", "hotels-cosmos")])
        for request in self.http.requests:
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.data)
            self.assertEqual(request.get_header("Api-key"), FAKE_KEY)

    def test_health_counts_with_a_bom_and_spaces(self):
        _, out, _ = self.run_healthy({"sengoku": b"\xef\xbb\xbf150\r\n"})
        self.assertIn("  sengoku        150件（目安 150）", out)

    def test_health_marks_different_count_without_error(self):
        answers = {"sengoku": 148, "hr-docs": 87, "hotels-blob": 0, "hotels-cosmos": 51}
        code, out, _ = self.run_healthy(answers)
        self.assertEqual(code, 0, out)
        self.assertIn("  sengoku        148件（目安 150 と違う）", out)
        self.assertIn("  hotels-blob    0件（目安 50 と違う）", out)
        self.assertIn("  hotels-cosmos  51件（目安 50 と違う）", out)
        self.assertIn(SUMMARY_OK, out)
        self.assertNotIn("NG    ", out)

    def test_health_hr_docs_counts_chunks_so_more_than_documents_is_normal(self):
        for count, same in ((23, True), (24, True), (400, True), (22, False), (0, False)):
            with self.subTest(count=count):
                _, out, _ = self.run_healthy({"hr-docs": count})
                line = next(ln for ln in out.splitlines() if ln.startswith("  hr-docs"))
                self.assertIn(f"{count}件（文書 23 から作ったチャンクの数", line)
                self.assertEqual("目安と違う" not in line, same, line)

    def test_health_marks_missing_index_as_not_yet(self):
        code, out, err = self.run_healthy({"sengoku": 150, "hr-docs": 87, "hotels-blob": 50})   # hotels-cosmos は 404
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("  hotels-cosmos  まだない", out)
        self.assertIn("  hotels-blob    50件（目安 50）", out)   # ほかの行は続く
        self.assertNotIn("NG    ", out)
        self.assertIn(SUMMARY_OK, out)

    def test_health_all_indexes_missing_is_not_error(self):
        code, out, _ = self.run_healthy()
        self.assertEqual(code, 0, out)
        for name in ("sengoku", "hr-docs", "hotels-blob", "hotels-cosmos"):
            self.assertRegex(out, rf"  {name} +まだない")
        self.assertIn(SUMMARY_OK, out)

    def test_health_uncountable_index_says_why_and_keeps_going(self):
        """AI Search が答えた失敗（HTTP の失敗・答えの形が想定外）は、1つずつ理由を出して、残りも数える。"""
        answers = {"sengoku": http_error(500), "hr-docs": b"<html>", "hotels-blob": http_error(403), "hotels-cosmos": 50}
        code, out, err = self.run_healthy(answers)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("  sengoku        数えられません（HTTP 500）", out)
        self.assertIn(f"  hr-docs        数えられません（{BODY_BAD}）", out)
        self.assertIn("  hotels-blob    数えられません（キーが合いません。HTTP 403）", out)
        self.assertIn("  hotels-cosmos  50件（目安 50）", out)
        self.assertEqual(len(self.http.requests), 4)
        self.assertNotIn("Traceback", out)
        self.assertIn(SUMMARY_OK, out)

    def test_health_connection_failure_stops_asking_the_rest(self):
        """つながらない（接続の失敗・時間切れ）が1つあったら、残りは問い合わせず「つながりません」にまとめる（待ち時間を重ねない）。"""
        names = ("sengoku", "hr-docs", "hotels-blob", "hotels-cosmos")
        failures = ((urllib.error.URLError("no route"), "つながりません"), (OSError("reset"), "つながりません"),
                    (TimeoutError(), "時間内に終わりません"), (urllib.error.URLError(TimeoutError()), "時間内に終わりません"))
        for position in range(len(names)):
            for failure, why in failures:
                with self.subTest(position=position, failure=type(failure).__name__, why=why):
                    answers = {name: 50 for name in names[:position]}
                    answers[names[position]] = failure
                    answers.update({name: 50 for name in names[position + 1:]})   # 残りは答えられるが、問い合わせない
                    code, out, err = self.run_healthy(answers)
                    self.assertEqual((code, err), (0, ""), out)
                    self.assertEqual(len(self.http.requests), position + 1)
                    for before in names[:position]:
                        self.assertRegex(out, rf"  {before} +50件")
                    self.assertRegex(out, rf"  {names[position]} +数えられません（{why}）")
                    for after in names[position + 1:]:
                        self.assertRegex(out, rf"  {after} +数えられません（つながりません）")
                    self.assertIn(SUMMARY_OK, out)
                    self.assertNotIn("Traceback", out)

    def test_health_other_failures_before_a_connection_failure_do_not_stop_early(self):
        """HTTP の失敗・答えの形の失敗は、つながっているので、止めない。つながらないものが出てから止める。"""
        answers = {"sengoku": http_error(500), "hr-docs": b"x", "hotels-blob": OSError("reset"), "hotels-cosmos": 50}
        _, out, _ = self.run_healthy(answers)
        self.assertEqual(len(self.http.requests), 3)
        self.assertIn("  sengoku        数えられません（HTTP 500）", out)
        self.assertIn(f"  hr-docs        数えられません（{BODY_BAD}）", out)
        self.assertIn("  hotels-blob    数えられません（つながりません）", out)
        self.assertIn("  hotels-cosmos  数えられません（つながりません）", out)

    def test_health_counts_with_an_unnamed_default_query_key(self):
        """名前のない既定の検索用のキー（名前が null・空・欄なし）でも、名前に頼らず、並びの最初のキーで数える。"""
        for label, entry in (("null", {"name": None, "key": FAKE_KEY}), ("empty", {"name": "", "key": FAKE_KEY}),
                             ("absent", {"key": FAKE_KEY})):
            with self.subTest(name=label):
                az = FakeAz(override(healthy(), (("search", "query-key", "list"), [entry])))
                code, out, err = self.run_main("health", az=az, http=FakeHttp({"sengoku": 150, "hr-docs": 87}))
                self.assertEqual((code, err), (0, ""), out)
                self.assertIn("  sengoku        150件（目安 150）", out)
                self.assertIn("  hr-docs        87件（文書 23 から作ったチャンクの数）", out)
                self.assertEqual({r.get_header("Api-key") for r in self.http.requests}, {FAKE_KEY})
                self.assertNotIn("検索用のキーを読めません", out)
                self.assertNotIn(FAKE_KEY, out + err)

    def test_health_wrong_key_is_shown_per_index_not_as_missing(self):
        for code_wanted in (401, 403):
            with self.subTest(code=code_wanted):
                answers = {name: http_error(code_wanted) for name in ("sengoku", "hr-docs", "hotels-blob", "hotels-cosmos")}
                code, out, _ = self.run_healthy(answers)
                self.assertEqual(code, 0, out)
                self.assertIn(f"  sengoku        数えられません（キーが合いません。HTTP {code_wanted}）", out)
                self.assertNotIn("まだない", out)

    def test_health_odd_bodies_are_not_counts(self):
        for body in (b"", b"-1", b"12abc", b"1.5", b'{"value": 3}', b"\xff\xfe", b"9" * 40):
            with self.subTest(body=body):
                _, out, _ = self.run_healthy({"sengoku": body})
                self.assertIn(f"  sengoku        数えられません（{BODY_BAD}）", out)

    def test_health_four_states_sample(self):
        """present/matching、present/different、missing、not countable が、1回の出力に並ぶ。"""
        answers = {"sengoku": 150, "hr-docs": 12, "hotels-blob": http_error(500)}   # hotels-cosmos は 404
        code, out, _ = self.run_healthy(answers)
        self.assertEqual(code, 0, out)
        block = out[out.index(TITLE):out.index(SUMMARY_OK)].rstrip("\n").splitlines()
        self.assertEqual(block, [
            TITLE + "：",
            "  sengoku        150件（目安 150）",
            "  hr-docs        12件（文書 23 から作ったチャンクの数。23 件以上のはずなので、目安と違う）",
            "  hotels-blob    数えられません（HTTP 500）",
            "  hotels-cosmos  まだない",
        ])

    def test_health_counts_never_change_the_verdict(self):
        """件数がどうでも、OK・まだ・NG の数と終了コードは、件数なしのときと同じ。"""
        scenarios = {
            "healthy": (healthy(), 0),
            "wrong search": (override(healthy(), (("search", "service", "show"),
                             {"provisioningState": "succeeded", "status": "running", "sku": {"name": "standard"}, "semanticSearch": "free"})), 1),
        }
        for label, (responses, code_wanted) in scenarios.items():
            outputs = []
            for answers in ({}, {"sengoku": 150, "hr-docs": 87, "hotels-blob": 50, "hotels-cosmos": 50}, {"sengoku": 1, "hr-docs": http_error(500)}):
                code, out, _ = self.run_healthy(answers, az=FakeAz(responses))
                outputs.append(([ln for ln in out.splitlines() if ln.startswith(("OK    ", "まだ  ", "NG    ")) or ln.startswith("OK ")], code))
            with self.subTest(case=label):
                self.assertEqual(outputs[0], outputs[1])
                self.assertEqual(outputs[0], outputs[2])
                self.assertEqual(outputs[0][1], code_wanted)

    def test_health_without_search_service_gives_one_line_and_asks_nothing(self):
        az = FakeAz(default=NOTFOUND)
        code, out, _ = self.run_main("health", az=az)
        self.assertEqual(code, 0, out)
        self.assertIn("インデックスの文書の数（参考）：数えません。AI Search がまだ OK ではありません", out)
        self.assertNotIn("sengoku", out)
        self.assertEqual(self.http.requests, [])
        self.assertFalse([c for c in az.calls if "query-key" in c])
        self.assertIn("OK 0・まだ 8・NG 0", out)

    def test_health_search_not_ok_is_not_counted(self):
        for state in ("provisioning", "Failed", "deleting"):
            with self.subTest(state=state):
                responses = override(healthy(), (("search", "service", "show"),
                                                 {"provisioningState": state, "sku": {"name": "basic"}, "semanticSearch": "free"}))
                code, out, _ = self.run_main("health", az=FakeAz(responses))
                self.assertIn("数えません。AI Search がまだ OK ではありません", out)
                self.assertEqual(self.http.requests, [])

    def test_health_unreadable_query_key_gives_one_line(self):
        cases = (
            (CheckError("notfound", "ResourceNotFound"), "AI Search srch-acme-suika がまだありません"),
            (CheckError("denied", "AuthorizationFailed"), "AI Search srch-acme-suika のキーを読む権限がありません"),
            (CheckError("other", "az が時間内に終わりません"), "az が時間内に終わりません"),
            ([], "検索用のキーがありません"),
            (None, BAD),
            ({"key": FAKE_KEY}, BAD),
            ([{"name": "x"}], BAD),
            ([{"key": "has space"}, ], BAD),
        )
        for answer, why in cases:
            with self.subTest(answer=repr(answer)[:30]):
                responses = override(healthy(), (("search", "query-key", "list"), answer))
                code, out, err = self.run_main("health", az=FakeAz(responses))
                self.assertEqual((code, err), (0, ""), out)
                self.assertIn("インデックスの文書の数（参考）：数えません。検索用のキーを読めません。", out)
                self.assertIn(why, out)
                self.assertEqual(self.http.requests, [])
                self.assertIn(SUMMARY_OK, out)
                self.assertNotIn(FAKE_KEY, out)

    def test_health_sign_in_lost_while_reading_the_key_gives_same_guide(self):
        lost = override(healthy(), (("search", "query-key", "list"), CheckError("login", "")))
        code, out, _ = self.run_main("health", az=FakeAz(lost))
        self.assertEqual(code, 1)
        self.assertIn(f"az login --tenant {TENANT}", out)

    def test_health_uses_the_first_query_key_and_never_the_admin_key(self):
        keys = [{"name": "member", "key": FAKE_KEY}, {"name": "other", "key": "second-" + FAKE_KEY}]
        az = FakeAz(override(healthy(), (("search", "query-key", "list"), keys), (("search", "admin-key", "show"), {"primaryKey": FAKE_ADMIN})))
        self.run_main("health", az=az, http=FakeHttp({"sengoku": 150}))
        self.assertEqual({r.get_header("Api-key") for r in self.http.requests}, {FAKE_KEY})
        self.assertEqual([c for c in az.calls if "admin-key" in c], [])

    def test_health_never_prints_keys(self):
        """画面（標準出力・標準エラー）に、キーがない。通信の失敗の文や、az の答えにキーが入っていても出さない。"""
        leaky = lambda text: text + " " + FAKE_KEY  # noqa: E731
        answers = {
            "sengoku": urllib.error.HTTPError("https://x/", 500, leaky("boom"), {}, io.BytesIO(leaky("body").encode())),
            "hr-docs": leaky("not a count").encode(),
            "hotels-blob": urllib.error.URLError(leaky("refused")),     # つながらない失敗が出たら、残りは問い合わせない
            "hotels-cosmos": OSError(leaky("reset")),
        }
        az = FakeAz(healthy())
        code, out, err = self.run_main("health", az=az, http=FakeHttp(answers))
        self.assertEqual(len(self.http.requests), 3)
        for shown in (out, err):
            self.assertNotIn(FAKE_KEY, shown)
            self.assertNotIn(FAKE_KEY[:12], shown)
            self.assertNotIn(FAKE_ADMIN, shown)
        # az に渡す引数にも、キーはない（キーは、HTTP の api-key ヘッダーにだけ入る）
        self.assertFalse([c for c in az.calls if any(FAKE_KEY in str(part) for part in c)])
        # 全部の失敗でも、画面は崩れない
        self.assertEqual(len(re.findall("数えられません", out)), 4, out)

    def test_health_never_prints_keys_when_the_connection_fails_first(self):
        """つながらない失敗（OSError・時間切れ）の文にキーが入っていても、出さない。"""
        for failure in (OSError(FAKE_KEY + " reset"), TimeoutError(FAKE_KEY + " slow"), urllib.error.URLError(FAKE_KEY)):
            with self.subTest(failure=type(failure).__name__):
                code, out, err = self.run_healthy({"sengoku": failure})
                self.assertEqual(len(self.http.requests), 1)
                self.assertNotIn(FAKE_KEY, out + err)
                self.assertNotIn(FAKE_KEY[:12], out + err)
                self.assertEqual(len(re.findall("数えられません", out)), 4, out)

    def test_health_never_prints_keys_on_a_good_run(self):
        code, out, err = self.run_healthy({"sengoku": 150, "hr-docs": 87, "hotels-blob": 50, "hotels-cosmos": 50})
        self.assertNotIn(FAKE_KEY, out + err)
        self.assertNotIn("api-key", (out + err).lower())

    def test_health_text_without_counts_is_unchanged(self):
        rows = [team.Row(team.OK, "a", "b"), team.Row(team.MADA, "c")]
        text, code = team.health_text("suika", rows)
        self.assertEqual(text, "チーム suika の状態（読み取りだけ）\nOK    a（b）\nまだ  c\nOK 1・まだ 1・NG 0")
        self.assertEqual(code, 0)

    def test_check_names_and_env_do_not_count(self):
        az = FakeAz(names_free())
        self.run_main("check-names", az=az)
        self.assertEqual(self.http.requests, [])


# ------------------------------------------------------------------ 想定外の答え

BAD = "az の答えの形が想定外です"
BOOL_BAD = (None, {}, [], "false", 0)   # true か false のはずの答え
DICT_BAD = (None, {}, [], "yes", 3)     # dict のはずの答え


def availability_bad(key):
    """{key: true/false} のはずの答えとして、ありえない形。"""
    return (*DICT_BAD, {"available": True}, {key: "true"}, {key: None})


class UnexpectedAnswerTest(MainCase):
    """az の答えの形が違うとき、「使える」「ほかで使われている」「まだ」と言い切らず、画面に traceback も出さない。"""

    def assert_unknown(self, out, line_start):
        lines = [line for line in out.splitlines() if line.startswith(line_start)]
        self.assertEqual(len(lines), 1, out)
        self.assertEqual(lines[0], f"{line_start}：確認できない（{BAD}）", out)

    def test_check_names_unexpected_answer_is_unknown(self):
        cases = (
            ("リソース グループ rg-acme-suika", ("group", "exists"), BOOL_BAD),
            ("Storage stacmesuika", ("storage", "account", "check-name"), availability_bad("nameAvailable")),
            ("Cosmos DB cosmos-acme-suika", ("cosmosdb", "check-name-exists"), BOOL_BAD),
            ("AI Search srch-acme-suika", ("rest", "post", "checkNameAvailability"), availability_bad("nameAvailable")),
            ("Foundry ai-acme-suika", ("rest", "post", "checkDomainAvailability"), availability_bad("isSubdomainAvailable")),
        )
        for line_start, prefix, bad_answers in cases:
            for bad in bad_answers:
                with self.subTest(row=line_start, answer=bad):
                    code, out, err = self.run_main("check-names", az=FakeAz(override(names_free(), (prefix, bad))))
                    self.assertEqual(code, 1, out)
                    self.assertEqual(err, "")
                    self.assert_unknown(out, line_start)
                    self.assertNotIn("すべて使えます", out)

    def test_check_names_unexpected_resource_list_is_unknown(self):
        for bad in (None, {}, "x", 3):
            with self.subTest(answer=bad):
                taken = override(names_free(), (("storage", "account", "check-name"), {"nameAvailable": False}), (("resource", "list"), bad))
                code, out, _ = self.run_main("check-names", az=FakeAz(taken))
                self.assertEqual(code, 1)
                self.assert_unknown(out, "Storage stacmesuika")
                self.assertNotIn("ほかで使われている", out)

    def test_check_names_invalid_name_is_not_taken(self):
        cases = (
            ("Storage stacmesuika", ("storage", "account", "check-name"), {"nameAvailable": False, "reason": "AccountNameInvalid"}),
            ("AI Search srch-acme-suika", ("rest", "post", "checkNameAvailability"), {"nameAvailable": False, "reason": "Invalid"}),
            ("Foundry ai-acme-suika", ("rest", "post", "checkDomainAvailability"), {"isSubdomainAvailable": False, "reason": "SubdomainInvalid"}),
        )
        for line_start, prefix, answer in cases:
            with self.subTest(row=line_start):
                code, out, _ = self.run_main("check-names", az=FakeAz(override(names_free(), (prefix, answer), (("resource", "list"), []))))
                self.assertEqual(code, 1)
                row = next(line for line in out.splitlines() if line.startswith(line_start))
                self.assertIn("確認できない（名前として受け付けられません（", row)
                self.assertNotIn("ほかで使われている", row)

    def test_check_names_already_exists_reason_is_still_taken(self):
        taken = override(names_free(),
                         (("storage", "account", "check-name"), {"nameAvailable": False, "reason": "AlreadyExists"}),
                         (("rest", "post", "checkNameAvailability"), {"nameAvailable": False, "reason": "AlreadyExists"}),
                         (("rest", "post", "checkDomainAvailability"), {"isSubdomainAvailable": False, "reason": "SubdomainAlreadyExists"}),
                         (("resource", "list"), []))
        code, out, _ = self.run_main("check-names", az=FakeAz(taken))
        self.assertEqual(code, 1)
        for line_start in ("Storage stacmesuika", "AI Search srch-acme-suika", "Foundry ai-acme-suika"):
            self.assertIn(f"{line_start}：ほかで使われている", out)

    def test_health_unexpected_answer_is_ng_not_mada(self):
        cases = (
            ("リソース グループ rg-acme-suika", ("group", "show")),
            ("Storage stacmesuika", ("storage", "account", "show")),
            ("AI Search srch-acme-suika", ("search", "service", "show")),
            ("Foundry ai-acme-suika", ("cognitiveservices", "account", "show")),
        )
        for label, prefix in cases:
            for bad in (None, [], "x", 3):
                with self.subTest(row=label, answer=bad):
                    code, out, err = self.run_main("health", az=FakeAz(override(healthy(), (prefix, bad))))
                    self.assertEqual(code, 1, out)
                    self.assertEqual(err, "")
                    self.assertIn(f"NG    {label}（{BAD}）", out)

    def test_health_empty_group_answer_does_not_look_like_nothing_built(self):
        """リソース グループの答えが空でも、「全部まだ・終了コード 0」にしない。"""
        az = FakeAz([(("group", "show"), None)], default=NOTFOUND)
        code, out, _ = self.run_main("health", az=az)
        self.assertEqual(code, 1)
        self.assertIn(f"NG    リソース グループ rg-acme-suika（{BAD}）", out)
        self.assertNotIn("OK 0・まだ 8・NG 0", out)

    def test_health_unexpected_deployment_list_is_ng(self):
        for bad in (None, {}, "x", 3):
            with self.subTest(answer=bad):
                code, out, _ = self.run_main("health", az=FakeAz(override(healthy(), (("cognitiveservices", "account", "deployment", "list"), bad))))
                self.assertEqual(code, 1)
                self.assertIn("OK    Foundry ai-acme-suika", out)
                for name in ("text-embedding-3-small", "gpt-5-mini"):
                    self.assertIn(f"NG    デプロイ {name}（{BAD}）", out)

    def test_health_junk_in_deployment_list_is_ignored(self):
        junk = [None, "x", 3, {"name": ["a"]}, {"sku": {}}]
        code, out, _ = self.run_main("health", az=FakeAz(override(healthy(), (("cognitiveservices", "account", "deployment", "list"), junk))))
        self.assertEqual(code, 0)
        self.assertIn("まだ  デプロイ text-embedding-3-small", out)
        self.assertIn("まだ  デプロイ gpt-5-mini", out)

    def test_health_wrong_nested_types_do_not_crash(self):
        weird = override(
            healthy(),
            (("group", "show"), {"properties": "x"}),
            (("storage", "account", "show"), {"provisioningState": "Succeeded", "sku": "x", "kind": "y"}),
            (("search", "service", "show"), {"provisioningState": "succeeded", "sku": ["a"], "semanticSearch": "free"}),
            (("cognitiveservices", "account", "show"), {"kind": "AIServices", "properties": [1]}),
            (("cognitiveservices", "account", "deployment", "list"),
             [{"name": "gpt-5-mini", "sku": "x", "properties": "y"}, {"name": "text-embedding-3-small", "sku": [], "properties": None}]),
        )
        code, out, err = self.run_main("health", az=FakeAz(weird))
        self.assertIn(code, (0, 1))
        self.assertEqual(err, "")
        self.assertNotIn("Traceback", out)
        self.assertIn("NG    AI Search 価格レベル（None。Basic のはず）", out)   # 分からないものを OK とは読まない
        self.assertNotIn("OK    Foundry ai-acme-suika", out)
        self.assertNotIn("OK    デプロイ", out)


# ------------------------------------------------------------------ main（設定・名前・サインイン）

class MainTest(MainCase):
    def test_names_prints_names_without_az(self):
        class NoAz:
            def __getattr__(self, name):
                raise AssertionError("names は az を呼ばない")

        code, out, _ = self.run_main("names", az=NoAz())
        self.assertEqual(code, 0)
        for text in ("rg-acme-suika", "stacmesuika", "srch-acme-suika", "cosmos-acme-suika", "ai-acme-suika",
                     "text-embedding-3-small", "gpt-5-mini", "japaneast", '$env:WORKSHOP_TEAM = "suika"',
                     "check-names --team suika"):
            self.assertIn(text, out)
        self.assertNotIn(SUB, out)

    def test_team_from_environment(self):
        code, out, _ = self.run_main("names", team_name=None, environ={"WORKSHOP_TEAM": "suika"})
        self.assertEqual(code, 0)
        self.assertIn("rg-acme-suika", out)

    def test_team_argument_wins_over_environment(self):
        code, out, _ = self.run_main("names", team_name="melon", environ={"WORKSHOP_TEAM": "suika"})
        self.assertEqual(code, 0)
        self.assertIn("rg-acme-melon", out)

    def test_team_missing(self):
        code, out, err = self.run_main("names", team_name=None, environ={})
        self.assertEqual(code, 2)
        self.assertIn("WORKSHOP_TEAM", err)
        self.assertEqual(out, "")

    def test_team_rule_violation(self):
        for bad in ("Suika", "shared1", "ab", "1abc", "su-ika"):
            with self.subTest(team=bad):
                code, out, err = self.run_main("names", team_name=bad)
                self.assertEqual(code, 2)
                self.assertIn("チームの名前", err)
                self.assertEqual(out, "")

    def test_bad_org_points_to_config(self):
        self.config = self.write_config(CONFIG_TEXT.replace("WORKSHOP_ORG=acme", "WORKSHOP_ORG=ACME-corp"))
        for command in ("names", "check-names", "health"):
            with self.subTest(command=command):
                code, out, err = self.run_main(command, az=FakeAz(default=NOTFOUND))
                self.assertEqual(code, 2)
                self.assertIn("workshop.config の WORKSHOP_ORG を直してください", err)
                self.assertIn("組織の名前", err)
                self.assertEqual(out, "")

    def test_missing_config(self):
        self.config = self.dir / "none.config"
        code, out, err = self.run_main("names")
        self.assertEqual(code, 2)
        self.assertIn("設定ファイルがありません", err)

    def test_config_missing_key(self):
        self.config = self.write_config("WORKSHOP_ORG=acme\n")
        code, _, err = self.run_main("names")
        self.assertEqual(code, 2)
        self.assertIn("AZURE_SUBSCRIPTION_ID", err)

    def test_not_signed_in_points_to_az_login_with_tenant(self):
        az = FakeAz([(("account", "show"), CheckError("login", "az login"))])
        for command in ("check-names", "health"):
            with self.subTest(command=command):
                code, out, _ = self.run_main(command, az=az)
                self.assertEqual(code, 1)
                self.assertIn(f"az login --tenant {TENANT}", out)
        self.assertEqual({c[:2] for c in az.calls}, {("account", "show")}, "サインインできなければ、先へ進まない")

    def test_invisible_subscription_counts_as_not_signed_in(self):
        for kind in ("denied", "notfound"):
            with self.subTest(kind=kind):
                code, out, _ = self.run_main("health", az=FakeAz([(("account", "show"), CheckError(kind, "x"))]))
                self.assertEqual(code, 1)
                self.assertIn(f"az login --tenant {TENANT}", out)
                self.assertIn("AZURE_SUBSCRIPTION_ID", out)

    def test_sign_in_lost_midway_gives_same_guide(self):
        lost = override(healthy(), (("storage", "account", "show"), CheckError("login", "")))
        code, out, _ = self.run_main("health", az=FakeAz(lost))
        self.assertEqual(code, 1)
        self.assertIn(f"az login --tenant {TENANT}", out)

    def test_az_not_installed(self):
        with mock.patch("teamlib.az.shutil.which", return_value=None):
            code, out, _ = self.run_main("health")
        self.assertEqual(code, 1)
        self.assertIn("winget install", out)

    def test_other_preflight_error_is_shown(self):
        code, out, _ = self.run_main("health", az=FakeAz([(("account", "show"), CheckError("other", "az が時間内に終わりません"))]))
        self.assertEqual(code, 1)
        self.assertIn("NG    az が時間内に終わりません", out)

    def test_real_az_gets_the_configured_subscription(self):
        with mock.patch("teamlib.az.shutil.which", return_value="/fake/az"):
            with mock.patch("teamlib.az.subprocess.run", return_value=completed("", "ERROR: Please run 'az login'", 1)) as run:
                code, out, _ = self.run_main("health")
        self.assertEqual(code, 1)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--subscription") + 1], SUB)

    def test_default_config_is_in_the_repo_root_not_the_working_folder(self):
        parser = team.build_parser()
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(elsewhere.name)
        for command in ("names", "check-names", "health"):
            with self.subTest(command=command):
                self.assertEqual(Path(parser.parse_args([command]).config), REPO_DIR / "workshop.config")
        self.assertEqual(Path(parser.parse_args(["env", "--role", "member"]).config), REPO_DIR / "workshop.config")

    def test_missing_default_config_names_the_repo_root_path(self):
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.dir)   # workshop.config があるのは一時フォルダー。Repo 直下の ほうを探すので、見つからない
        (self.dir / "workshop.config").write_text(CONFIG_TEXT, encoding="utf-8")
        if (REPO_DIR / "workshop.config").exists():
            self.skipTest("Repo 直下に workshop.config がある環境")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = team.main(["names", "--team", "suika"])
        self.assertEqual(code, 2)
        self.assertIn("設定ファイルがありません", err.getvalue())
        self.assertIn(str(REPO_DIR), err.getvalue())

    def test_invalid_subscription_id_stops_before_az(self):
        class NoAz:
            def __getattr__(self, name):
                raise AssertionError("設定が違うとき、az を呼んではいけない")

        for bad in ("sub-for-test", '"' + SUB + '"'):
            with self.subTest(bad=bad):
                self.config = self.write_config(CONFIG_TEXT.replace(SUB, bad))
                for command in ("names", "check-names", "health"):
                    code, out, err = self.run_main(command, az=NoAz())
                    self.assertEqual(code, 2)
                    self.assertIn("AZURE_SUBSCRIPTION_ID", err)
                    self.assertEqual(out, "")

    def test_subcommand_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                team.main([])

    def test_output_is_utf8(self):
        """Windows の既定（cp932 など日本語以外）で開いた画面でも、main が UTF-8 にする。"""
        def run(argv):
            raw_out, raw_err = io.BytesIO(), io.BytesIO()
            out = io.TextIOWrapper(raw_out, encoding="cp1252", errors="strict")
            err = io.TextIOWrapper(raw_err, encoding="cp1252", errors="strict")
            with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
                code = team.main(argv)
            out.flush()
            err.flush()
            return code, raw_out.getvalue(), raw_err.getvalue()

        code, out_bytes, _ = run(["names", "--config", str(self.config), "--team", "suika"])
        self.assertEqual(code, 0)
        self.assertIn("チームの名前", out_bytes.decode("utf-8"))

        code, _, err_bytes = run(["names", "--config", str(self.config), "--team", "Suika"])
        self.assertEqual(code, 2)
        self.assertIn("チームの名前", err_bytes.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
