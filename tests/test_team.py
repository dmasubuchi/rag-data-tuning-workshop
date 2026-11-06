"""tools/team.py と tools/teamlib/az.py の試験。

通信しない。az は、本物の Az を継いで _call だけ差し替えた偽物（FakeAz）を使う。
そのため、names・check-names・health が許可リスト（READ_ONLY）の外のコマンドを呼べば、試験の中でも CheckError になる。
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))

import team  # noqa: E402
from teamlib.az import READ_ONLY, Az, CheckError, find_az  # noqa: E402
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

    def run_main(self, command, *extra, team_name="suika", az=None, environ=None):
        argv = [command, "--config", str(self.config)]
        if team_name is not None:
            argv += ["--team", team_name]
        argv += list(extra)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with mock.patch.dict(os.environ, environ or {}, clear=environ is not None):
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

    def test_health_reads_no_keys(self):
        az = FakeAz(healthy())
        self.run_main("health", az=az)
        self.assertEqual([c for c in az.calls if "admin-key" in c or "keys" in c or "query-key" in c], [])
        self.assertTrue(az.calls)


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
