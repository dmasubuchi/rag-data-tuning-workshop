"""tools/teamlib/names.py の試験。

組織の名前・チームの名前の規則と、Azure のリソース名の組み立て、設定ファイルの読み込みを確かめる。
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))

from teamlib.names import (  # noqa: E402
    ConfigError,
    NameRuleError,
    Names,
    WorkshopConfig,
    check_org,
    check_team,
    load_config,
    make_names,
)

EXAMPLE_CONFIG = REPO_DIR / "config" / "workshop.example.config"

SUB = "0123abcd" + "-4567-" + "89ab-cdef-" + "0123456789ab"   # サブスクリプション ID の形（つないで作る）

FULL_CONFIG = (
    f"AZURE_SUBSCRIPTION_ID={SUB}\n"
    "AZURE_LOCATION=japaneast\n"
    "WORKSHOP_ORG=acme\n"
    "AZURE_TENANT=tenant-for-test\n"
)


class ConfigFileCase(unittest.TestCase):
    """一時フォルダーに設定ファイルを書いて読む。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, text: str, name: str = "workshop.config", encoding: str = "utf-8") -> Path:
        path = self.dir / name
        path.write_text(text, encoding=encoding)
        return path


class MakeNamesTest(unittest.TestCase):
    def test_make_names_example(self):
        n = make_names("acme", "suika")
        self.assertEqual(
            n,
            Names(
                org="acme",
                team="suika",
                resource_group="rg-acme-suika",
                storage="stacmesuika",
                search="srch-acme-suika",
                cosmos="cosmos-acme-suika",
                foundry="ai-acme-suika",
            ),
        )

    def test_make_names_checks_inputs(self):
        with self.assertRaises(NameRuleError):
            make_names("acme", "Suika")
        with self.assertRaises(NameRuleError):
            make_names("abcdefg", "suika")

    def test_storage_name_within_limits(self):
        n = make_names("abcdef", "abcdefgh")  # org 6 字・team 8 字がいちばん長い
        self.assertLessEqual(len(n.storage), 24)
        self.assertRegex(n.storage, r"^[a-z0-9]+$")
        self.assertLessEqual(len(n.search), 60)
        self.assertLessEqual(len(n.cosmos), 44)


class RuleTest(unittest.TestCase):
    def test_team_rules(self):
        for bad in ("Suika", "ab", "1abc", "sharedx", "abcdefghi"):
            with self.subTest(bad=bad):
                with self.assertRaises(NameRuleError):
                    check_team(bad)
        self.assertEqual(check_team("suika"), "suika")

    def test_team_rules_other_bad_values(self):
        for bad in ("", "   ", "su-ika", "su_ika", "su ika", "すいか", None):
            with self.subTest(bad=bad):
                with self.assertRaises(NameRuleError):
                    check_team(bad)

    def test_team_limits_are_inclusive(self):
        self.assertEqual(check_team("abc"), "abc")
        self.assertEqual(check_team("abcdefgh"), "abcdefgh")

    def test_team_strips_surrounding_whitespace(self):
        self.assertEqual(check_team("  suika\n"), "suika")

    def test_team_error_message_is_japanese_and_names_the_rule(self):
        with self.assertRaises(NameRuleError) as cm:
            check_team("ab")
        self.assertIn("チーム", str(cm.exception))
        self.assertIn("3〜8", str(cm.exception))

    def test_org_rules(self):
        with self.assertRaises(NameRuleError):
            check_org("abcdefg")
        for bad in ("Acme", "ab", "1abc", "", "ac-me"):
            with self.subTest(bad=bad):
                with self.assertRaises(NameRuleError):
                    check_org(bad)
        self.assertEqual(check_org("acme"), "acme")
        self.assertEqual(check_org("abc"), "abc")
        self.assertEqual(check_org("abcdef"), "abcdef")

    def test_org_may_start_with_shared(self):
        # shared の制限があるのは、チームの名前だけ
        self.assertEqual(check_org("shared"), "shared")

    def test_org_error_message_is_japanese(self):
        with self.assertRaises(NameRuleError) as cm:
            check_org("abcdefg")
        self.assertIn("組織", str(cm.exception))
        self.assertIn("3〜6", str(cm.exception))


class LoadConfigTest(ConfigFileCase):
    def test_load_config(self):
        cfg = load_config(self.write(FULL_CONFIG))
        self.assertEqual(
            cfg,
            WorkshopConfig(
                subscription_id=SUB,
                location="japaneast",
                org="acme",
                tenant="tenant-for-test",
            ),
        )

    def test_existing_resource_group_is_optional_and_used_for_names(self):
        cfg = load_config(self.write(FULL_CONFIG + "AZURE_RESOURCE_GROUP=day1-rg\n"))
        self.assertEqual(cfg.resource_group, "day1-rg")
        n = make_names(cfg.org, "suika", cfg.resource_group)
        self.assertEqual(n.resource_group, "day1-rg")
        self.assertEqual(n.search, "srch-acme-suika")     # ほかの名前は変わらない
        self.assertEqual(make_names("acme", "suika").resource_group, "rg-acme-suika")
        self.assertTrue(n.custom_group)
        self.assertFalse(make_names("acme", "suika").custom_group)
        self.assertFalse(make_names("acme", "suika", "").custom_group)
        self.assertEqual(load_config(self.write(FULL_CONFIG + "AZURE_RESOURCE_GROUP=\n")).resource_group, "")

    def test_existing_resource_group_shape_is_checked(self):
        for bad in ('"day1-rg"', "day1 rg", "ends.with.dot.", "x" * 91):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigError) as cm:
                    load_config(self.write(FULL_CONFIG + f"AZURE_RESOURCE_GROUP={bad}\n"))
                self.assertIn("AZURE_RESOURCE_GROUP", str(cm.exception))

    def test_load_config_missing_key(self):
        text = FULL_CONFIG.replace("AZURE_TENANT=tenant-for-test\n", "")
        with self.assertRaises(ConfigError) as cm:
            load_config(self.write(text))
        self.assertIn("AZURE_TENANT", str(cm.exception))

    def test_load_config_reports_every_missing_key(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(self.write("WORKSHOP_ORG=acme\n"))
        msg = str(cm.exception)
        for key in ("AZURE_SUBSCRIPTION_ID", "AZURE_LOCATION", "AZURE_TENANT"):
            self.assertIn(key, msg)
        self.assertNotIn("WORKSHOP_ORG", msg)

    def test_load_config_empty_value_counts_as_missing(self):
        text = FULL_CONFIG.replace("AZURE_LOCATION=japaneast", "AZURE_LOCATION=")
        with self.assertRaises(ConfigError) as cm:
            load_config(self.write(text))
        self.assertIn("AZURE_LOCATION", str(cm.exception))

    def test_load_config_ignores_comments_blank_lines_and_unknown_keys(self):
        text = (
            "# 説明の行\n"
            "\n"
            f"  AZURE_SUBSCRIPTION_ID = {SUB}  \n"
            "AZURE_LOCATION=japaneast\n"
            "# WORKSHOP_ORG=commented\n"
            "WORKSHOP_ORG=acme\n"
            "OTHER_KEY=ignored\n"
            "AZURE_TENANT=tenant=with=equals\n"
        )
        cfg = load_config(self.write(text))
        self.assertEqual(cfg.subscription_id, SUB)
        self.assertEqual(cfg.org, "acme")
        self.assertEqual(cfg.tenant, "tenant=with=equals")

    def test_load_config_accepts_bom_and_crlf(self):
        # Windows のメモ帳で保存した形（BOM つき、CRLF）
        path = self.dir / "workshop.config"
        path.write_bytes(b"\xef\xbb\xbf" + FULL_CONFIG.replace("\n", "\r\n").encode("utf-8"))
        cfg = load_config(path)
        self.assertEqual(cfg.subscription_id, SUB)
        self.assertEqual(cfg.tenant, "tenant-for-test")

    def test_subscription_id_must_look_like_a_guid(self):
        for good in (SUB, SUB.upper()):
            with self.subTest(good=good):
                cfg = load_config(self.write(FULL_CONFIG.replace(SUB, good)))
                self.assertEqual(cfg.subscription_id, good)
        bad_values = ("sub-for-test", SUB[:-1], SUB + "0", SUB.replace("-", ""), "{" + SUB + "}", SUB + " x",
                      SUB.replace("a", "z", 1), "/subscriptions/" + SUB)
        for bad in bad_values:
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigError) as cm:
                    load_config(self.write(FULL_CONFIG.replace(SUB, bad)))
                self.assertIn("AZURE_SUBSCRIPTION_ID", str(cm.exception))
                self.assertIn("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", str(cm.exception))

    def test_quoted_subscription_id_is_stopped_with_a_clear_reason(self):
        for quoted in ('"' + SUB + '"', "'" + SUB + "'", "\u201c" + SUB + "\u201d", '"' + SUB, SUB + "'"):
            with self.subTest(quoted=quoted):
                with self.assertRaises(ConfigError) as cm:
                    load_config(self.write(FULL_CONFIG.replace(SUB, quoted)))
                self.assertIn("引用符", str(cm.exception))
                self.assertIn("AZURE_SUBSCRIPTION_ID", str(cm.exception))

    def test_other_values_are_not_shape_checked(self):
        # テナントはドメインの形（contoso.onmicrosoft.com）もある。場所・組織は別の規則
        cfg = load_config(self.write(FULL_CONFIG.replace("tenant-for-test", "contoso.onmicrosoft.com")))
        self.assertEqual(cfg.tenant, "contoso.onmicrosoft.com")

    def test_load_config_file_not_found(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(self.dir / "no-such.config")
        self.assertIn("no-such.config", str(cm.exception))

    def test_config_error_is_a_name_rule_error(self):
        # 呼び出し側が NameRuleError だけを受けても、設定の誤りを拾える
        self.assertTrue(issubclass(ConfigError, NameRuleError))


class ExampleConfigTest(unittest.TestCase):
    def test_example_has_four_keys_and_the_optional_group_with_empty_values(self):
        lines = EXAMPLE_CONFIG.read_text(encoding="utf-8").splitlines()
        pairs = [line.split("=", 1) for line in lines if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(
            [k for k, _ in pairs],
            ["AZURE_SUBSCRIPTION_ID", "AZURE_LOCATION", "WORKSHOP_ORG", "AZURE_TENANT", "AZURE_RESOURCE_GROUP"],
        )
        self.assertTrue(all(v == "" for _, v in pairs), "example の値は空にする")

    def test_example_explains_each_key_on_one_line(self):
        lines = EXAMPLE_CONFIG.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if re.match(r"[A-Z_]+=", line):
                self.assertTrue(i > 0 and lines[i - 1].startswith("#"), f"{line} の前に説明の行がない")

    def test_unfilled_example_is_rejected_with_key_names(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(EXAMPLE_CONFIG)
        self.assertIn("AZURE_SUBSCRIPTION_ID", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
