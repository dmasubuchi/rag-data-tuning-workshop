"""組織の設定（workshop.config）と、チームごとの Azure リソースの名前。

固定の ID・テナント・場所はこのファイルに書かない。workshop.config から読む（雛形は config/workshop.example.config）。
動かすのは Python の標準ライブラリだけ。
"""
import re
from pathlib import Path
from typing import NamedTuple

ORG_MIN, ORG_MAX = 3, 6
TEAM_MIN, TEAM_MAX = 3, 8
ORG_RULE = f"組織の名前：小文字の英字と数字だけ、{ORG_MIN}〜{ORG_MAX}文字、英字で始める（例 acme）"
TEAM_RULE = f"チームの名前：小文字の英字と数字だけ、{TEAM_MIN}〜{TEAM_MAX}文字、英字で始める、shared で始めない（例 suika）"

GUID_SHAPE = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
GUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
QUOTES = "\"'`\u2018\u2019\u201c\u201d"   # 半角・全角の引用符

# workshop.config のキー → WorkshopConfig の項目（並びは WorkshopConfig と同じ）
CONFIG_KEYS = (
    ("AZURE_SUBSCRIPTION_ID", "subscription_id"),
    ("AZURE_LOCATION", "location"),
    ("WORKSHOP_ORG", "org"),
    ("AZURE_TENANT", "tenant"),
)


class NameRuleError(Exception):
    """名前の規則に合わない。メッセージは日本語の理由つき。"""


class ConfigError(NameRuleError):
    """設定ファイルが読めない、またはキーが足りない。"""


# ------------------------------------------------------------------ 設定ファイル

class WorkshopConfig(NamedTuple):
    subscription_id: str
    location: str
    org: str
    tenant: str


def load_config(path: Path) -> WorkshopConfig:
    """KEY=VALUE の設定ファイルを読む。空行と # の行は読み飛ばす。4つのキーが揃っていなければ ConfigError。"""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")  # Windows のメモ帳の BOM も読める
    except FileNotFoundError:
        raise ConfigError(f"設定ファイルがありません：{path}\n  config/workshop.example.config を {path.name} という名前でコピーして、値を書いてください（置き場所は Repo 直下）。") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"設定ファイルを読めません：{path}（{e}）") from None

    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    missing = [key for key, _ in CONFIG_KEYS if not values.get(key)]
    if missing:
        raise ConfigError(f"設定ファイル {path.name} に、次のキーの値がありません：{'、'.join(missing)}")
    check_subscription_id(values["AZURE_SUBSCRIPTION_ID"], path.name)
    return WorkshopConfig(**{field: values[key] for key, field in CONFIG_KEYS})


def check_subscription_id(value: str, file_name: str) -> None:
    """サブスクリプション ID が GUID の形かを確かめる。引用符つきで貼った値は、そのことを言って止める。"""
    if value and (value[0] in QUOTES or value[-1] in QUOTES):
        raise ConfigError(f"設定ファイル {file_name} の AZURE_SUBSCRIPTION_ID に引用符がついています。引用符は外して、ID だけを書いてください。")
    if not GUID_RE.fullmatch(value):
        raise ConfigError(f"設定ファイル {file_name} の AZURE_SUBSCRIPTION_ID が ID の形ではありません。"
                          f"{GUID_SHAPE} の形で書いてください（Azure ポータルの「サブスクリプション」で見られます）。")


# ------------------------------------------------------------------ 名前の規則

def _check(value, label: str, low: int, high: int, rule: str) -> str:
    name = (value or "").strip()
    if not name:
        raise NameRuleError(f"{label}が空です。\n  {rule}")
    if not re.fullmatch(r"[a-z0-9]+", name):
        hint = "大文字は小文字にします。" if re.fullmatch(r"[A-Za-z0-9]+", name) else "ハイフン・下線・空白・日本語は使えません。"
        raise NameRuleError(f"{label}が使えません（今は {name!r}）。{hint}\n  {rule}")
    if not name[0].isalpha():
        raise NameRuleError(f"{label}は、英字で始めます（今は {name!r}）。\n  {rule}")
    if not low <= len(name) <= high:
        raise NameRuleError(f"{label}は {low}〜{high} 文字です（今は {len(name)} 文字）。\n  {rule}")
    return name


def check_org(value) -> str:
    """組織の名前の形を確かめて、確かめた名前を返す。違えば NameRuleError。"""
    return _check(value, "組織の名前", ORG_MIN, ORG_MAX, ORG_RULE)


def check_team(value) -> str:
    """チームの名前の形を確かめて、確かめた名前を返す。違えば NameRuleError。"""
    name = _check(value, "チームの名前", TEAM_MIN, TEAM_MAX, TEAM_RULE)
    if name.startswith("shared"):
        raise NameRuleError(f"shared で始まる名前は、共有のインデックスの名前なので使えません（今は {name!r}）。\n  {TEAM_RULE}")
    return name


# ------------------------------------------------------------------ リソースの名前

class Names(NamedTuple):
    org: str
    team: str
    resource_group: str
    storage: str
    search: str
    cosmos: str
    foundry: str


def make_names(org: str, team: str) -> Names:
    """組織とチームの名前（検査つき）から、各リソースの名前を決める。"""
    org = check_org(org)
    team = check_team(team)
    return Names(
        org=org,
        team=team,
        resource_group=f"rg-{org}-{team}",
        storage=f"st{org}{team}",
        search=f"srch-{org}-{team}",
        cosmos=f"cosmos-{org}-{team}",
        foundry=f"ai-{org}-{team}",
    )
