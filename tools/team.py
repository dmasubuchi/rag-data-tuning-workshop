#!/usr/bin/env python3
"""チームの名前から Azure のリソース名を決める。作る前の名前の確認と、作ったあとの状態の確認。

使い方（Repo 直下で）：
  python tools/team.py names       --team suika   名前を検査して、リソース名と PowerShell の1行を表示する
  python tools/team.py check-names --team suika   作る前に、名前が使えるかを Azure に聞く（何も作らない）
  python tools/team.py health      --team suika   作ったものの状態を見る（読み取りだけ）
  python tools/team.py env --role member --team suika   接続の設定 .env.local を作る（--role は builder か member）
  python tools/team.py env --role member --team suika --out member.local.env   メンバーに渡す設定を別の名前で書き出す

--team を省略すると、環境変数 WORKSHOP_TEAM を使う（PowerShell では $env:WORKSHOP_TEAM = "suika"）。
--config は組織の設定ファイル（既定は Repo 直下の workshop.config。どのフォルダーで実行しても同じ。雛形は
config/workshop.example.config）。

env は az でキーを読み、設定ファイルに書く（画面には出さない）。書き先は、既定では Repo 直下の .env.local。
--out PATH を付けると、そこに書く（構築する人が、メンバー用の設定を書き出して渡すとき）。Repo の中に書くなら、
Git に入らない名前（.env.local、*.local.env）にする。
  builder（構築する人）は AI Search の管理者キーと Storage の接続文字列（人に渡さない）、
  member（メンバー）は検索用のキー（チームの外に渡さない。Storage の接続文字列は入らない）。

動かすのは Python の標準ライブラリと az だけ。Azure に何かを作る・変える・消すコマンドは、このファイルに入っていない
（az に渡せるコマンドは teamlib/az.py の READ_ONLY の一覧に限る）。
"""
import argparse
import os
import sys
from pathlib import Path
from typing import NamedTuple

from teamlib.az import ARM, Az, CheckError
from teamlib.envfile import CHAT_DEPLOYMENT, EMBEDDING_DEPLOYMENT, ENV_FILE, ROLES, write_env
from teamlib.names import ConfigError, Names, NameRuleError, check_org, check_team, load_config, make_names

ENV_NAME = "WORKSHOP_TEAM"
REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_DIR / "workshop.config"   # 作業場所でなく Repo 直下
DEPLOYMENTS = (EMBEDDING_DEPLOYMENT, CHAT_DEPLOYMENT)


# ------------------------------------------------------------------ チームの名前

def powershell_line(team: str) -> str:
    return f'$env:{ENV_NAME} = "{team}"'


def resolve_team(arg, environ=None) -> str:
    """--team があればそれ、なければ環境変数 WORKSHOP_TEAM。どちらもなければ NameRuleError。"""
    environ = os.environ if environ is None else environ
    if arg is not None:
        return check_team(arg)
    if environ.get(ENV_NAME, "").strip():
        return check_team(environ[ENV_NAME])
    raise NameRuleError(f'チームの名前がありません。--team <名前> を付けるか、PowerShell で {powershell_line("<名前>")} を実行します。')


def names_text(location: str, n: Names) -> str:
    return "\n".join([
        f"チームの名前：{n.team}（組織 {n.org}）",
        f"場所：{location}",
        f"リソース グループ：{n.resource_group}",
        f"Storage：{n.storage}",
        f"AI Search：{n.search}（Basic、セマンティック ランカー Free）",
        f"Cosmos DB：{n.cosmos}",
        f"Foundry：{n.foundry}（デプロイ {'、'.join(DEPLOYMENTS)}）",
        "",
        "PowerShell に貼る（このウィンドウの間だけ有効。新しく開いたら、もう一度）：",
        powershell_line(n.team),
        "",
        f"次に、名前が使えるかを確かめる：python tools/team.py check-names --team {n.team}",
    ])


# ------------------------------------------------------------------ 画面に出す理由

def _why(error: CheckError) -> str:
    if error.kind == "denied":
        return "権限がありません"
    return error.detail or "理由が分かりません"


UNEXPECTED = "az の答えの形が想定外です"


def _answer(value, kind, key=None):
    """az の答えが想定の型（dict か list か bool）で、key があれば dict にそのキーがあることを確かめて返す。違えば CheckError。

    空の答え（None）や、キーのない dict を、「ない」「使える」と読まないための確認。
    """
    if not isinstance(value, kind) or (key is not None and key not in value):
        raise CheckError("other", UNEXPECTED)
    return value


def _dict(value) -> dict:
    """入れ子の項目用。dict でなければ空の dict（項目は「分からない」になり、OK とは読まれない）。"""
    return value if isinstance(value, dict) else {}


def _keep_going(error: CheckError) -> None:
    """サインインが切れたときだけは、1行の結果にせず上へ投げる（main が az login の案内を出す）。"""
    if error.kind == "login":
        raise error


# ------------------------------------------------------------------ check-names

FREE = "使える"
TAKEN = "ほかで使われている（チームの名前を変える）"
EXISTS = "このサブスクリプションに作成済み"


def _arm(az, provider, action):
    return f"{ARM}/subscriptions/{az.subscription}/providers/{provider}/{action}"


def _available(answer, key) -> bool:
    """名前の空き確認の答え（dict の key が true か false）から、空いているかを取る。

    形が違うとき、名前として受け付けられないとき（reason に Invalid）は CheckError。「ほかで使われている」とは言わない。
    """
    answer = _answer(answer, dict, key)
    free = _answer(answer[key], bool)
    reason = str(answer.get("reason") or "")
    if not free and "invalid" in reason.lower():
        raise CheckError("other", f"名前として受け付けられません（{reason[:40]}）")
    return free


def check_names(az, n: Names):
    """名前ごとに (ラベル, 名前, 状態) を返す。状態は FREE、TAKEN、EXISTS、または「確認できない（理由）」。"""
    def storage(name):
        return _available(az.run("storage", "account", "check-name", "-n", name), "nameAvailable")

    def cosmos(name):
        return not _answer(az.run("cosmosdb", "check-name-exists", "-n", name), bool)   # true なら、その名前がある

    def search(name):
        url = _arm(az, "Microsoft.Search", "checkNameAvailability") + "?api-version=2023-11-01"
        return _available(az.post(url, {"name": name, "type": "searchServices"}), "nameAvailable")

    def foundry(name):
        url = _arm(az, "Microsoft.CognitiveServices", "checkDomainAvailability") + "?api-version=2023-05-01"
        body = {"subdomainName": name, "type": "Microsoft.CognitiveServices/accounts", "kind": "AIServices"}
        return _available(az.post(url, body), "isSubdomainAvailable")

    def in_subscription(name):
        return bool(_answer(az.run("resource", "list", "--name", name), list))

    rows = []
    group = n.resource_group
    try:
        rows.append(("リソース グループ", group, EXISTS if _answer(az.run("group", "exists", "-n", group), bool) else FREE))
    except CheckError as error:
        _keep_going(error)
        rows.append(("リソース グループ", group, f"確認できない（{_why(error)}）"))
    for label, name, free in (("Storage", n.storage, storage), ("AI Search", n.search, search),
                              ("Cosmos DB", n.cosmos, cosmos), ("Foundry", n.foundry, foundry)):
        try:
            if free(name):
                state = FREE
            else:
                state = EXISTS if in_subscription(name) else TAKEN
        except CheckError as error:
            _keep_going(error)
            state = f"確認できない（{_why(error)}）"
        rows.append((label, name, state))
    return rows


def check_names_text(team: str, rows) -> tuple:
    lines = [f"チーム {team} の名前を確かめます（Azure には何も作りません）"]
    lines += [f"{label} {name}：{state}" for label, name, state in rows]
    states = [state for _, _, state in rows]
    if any(s.startswith("確認できない") for s in states):
        lines.append("確認できない名前があります。上の理由を直して、もう一度実行します。")
        code = 1
    elif TAKEN in states:
        lines.append("ほかで使われている名前があります。チームの名前を変えて、もう一度確かめます。")
        code = 1
    elif EXISTS in states:
        lines.append("作成済みのものは、自分のチームが作りかけのときだけです。そうでなければ、チームの名前を変えます。")
        code = 0
    else:
        lines.append("すべて使えます。names の表示どおりに作れます。")
        code = 0
    return "\n".join(lines), code


# ------------------------------------------------------------------ health

OK, MADA, NG = "OK", "まだ", "NG"
PREFIX = {OK: "OK    ", MADA: "まだ  ", NG: "NG    "}
FAILED_STATES = ("failed", "canceled", "cancelled")


def state_status(state) -> str:
    """作成の状態（provisioningState）から、OK・まだ・NG を決める。Succeeded だけが OK、Failed・Canceled は NG、ほかは「まだ」。"""
    lowered = str(state).lower()
    if lowered == "succeeded":
        return OK
    return NG if lowered in FAILED_STATES else MADA


class Row(NamedTuple):
    status: str
    label: str
    note: str = ""

    def text(self) -> str:
        return PREFIX[self.status] + self.label + (f"（{self.note}）" if self.note else "")


def error_row(label: str, error: CheckError) -> Row:
    """読めなかった項目の行。「まだない」は _found が先に拾うので、ここに来るのは NG だけ。"""
    _keep_going(error)
    return Row(NG, label, _why(error))


def _found(fn, kind):
    """fn() を呼んで、kind の型の答えを返す。まだない（notfound）なら None。答えの形が違えば（空の答えも）CheckError。"""
    try:
        return _answer(fn(), kind)
    except CheckError as error:
        if error.kind == "notfound":
            return None
        raise


def health(az, n: Names):
    """読み取りだけの状態確認。Row のリストを返す。まだないものは「まだ」。エラーでは止まらない（サインイン切れは除く）。"""
    rows = []

    def add(status, label, note=""):
        rows.append(Row(status, label, note))

    def later(*labels):
        rows.extend(Row(MADA, label) for label in labels)

    def guard(label, fn):
        try:
            fn()
        except CheckError as error:
            rows.append(error_row(label, error))

    rg = n.resource_group
    L_RG, L_ST, L_SR = f"リソース グループ {rg}", f"Storage {n.storage}", f"AI Search {n.search}"
    L_PRICE, L_SEM = "AI Search 価格レベル", "AI Search セマンティック ランカー"
    L_FD = f"Foundry {n.foundry}"
    L_DEP = [f"デプロイ {d}" for d in DEPLOYMENTS]

    # リソースグループ
    try:
        group = _found(lambda: az.run("group", "show", "-n", rg), dict)
    except CheckError as error:
        rows.append(error_row(L_RG, error))
    else:
        if group is None:
            later(L_RG, L_ST, L_SR, L_PRICE, L_SEM, L_FD, *L_DEP)
            return rows
        state = _dict(group.get("properties")).get("provisioningState")
        add(state_status(state), L_RG, state or "状態が分かりません")   # Deleting などは OK にしない

    # Storage
    def storage_section():
        st = _found(lambda: az.run("storage", "account", "show", "-n", n.storage, "-g", rg), dict)
        if st is None:
            later(L_ST)
            return
        state = st.get("provisioningState")
        if state_status(state) != OK:
            add(state_status(state), L_ST, state or "状態が分かりません")
            return
        add(OK, L_ST, f"{_dict(st.get('sku')).get('name')}・{st.get('kind')}")

    guard(L_ST, storage_section)

    # AI Search（価格レベル Basic、セマンティック ランカー Free）
    def search_section():
        sv = _found(lambda: az.run("search", "service", "show", "-n", n.search, "-g", rg), dict)
        if sv is None:
            later(L_SR, L_PRICE, L_SEM)
            return
        state = str(sv.get("provisioningState"))
        status = state_status(state)
        add(status, L_SR, sv.get("status") if status == OK else state)
        sku = _dict(sv.get("sku")).get("name")
        add(OK if sku == "basic" else NG, L_PRICE, "Basic" if sku == "basic" else f"{sku}。Basic のはず")
        semantic = sv.get("semanticSearch")
        if semantic == "free":
            add(OK, L_SEM, "Free")
        else:
            add(NG, L_SEM, f"{'無効' if semantic in (None, 'disabled') else semantic}。Free にする")

    guard(L_SR, search_section)

    # Foundry とデプロイ
    def foundry_section():
        fd = _found(lambda: az.run("cognitiveservices", "account", "show", "-n", n.foundry, "-g", rg), dict)
        if fd is None:
            later(L_FD, *L_DEP)
            return
        state = _dict(fd.get("properties")).get("provisioningState")
        kind = fd.get("kind")
        if kind != "AIServices":
            add(NG, L_FD, f"種類 {kind}。AIServices のはず")
        else:
            status = state_status(state)
            add(status, L_FD, "" if status == OK else str(state))
        try:
            listing = _found(lambda: az.run("cognitiveservices", "account", "deployment", "list", "-n", n.foundry, "-g", rg), list) or []
        except CheckError as error:
            rows.extend(error_row(label, error) for label in L_DEP)   # 一覧を読めなかった。Foundry の行はそのまま
            return
        by_name = {d["name"]: d for d in listing if isinstance(d, dict) and isinstance(d.get("name"), str)}
        for name, label in zip(DEPLOYMENTS, L_DEP):
            d = by_name.get(name)
            if d is None:
                add(MADA, label)
                continue
            sku = _dict(d.get("sku"))
            dstate = str(_dict(d.get("properties")).get("provisioningState"))
            note = f"{sku.get('name')}・容量{sku.get('capacity')}・{dstate}"
            add(state_status(dstate), label, note)

    guard(L_FD, foundry_section)
    return rows


def health_text(team: str, rows) -> tuple:
    count = {s: sum(1 for r in rows if r.status == s) for s in (OK, MADA, NG)}
    lines = [f"チーム {team} の状態（読み取りだけ）"]
    lines += [r.text() for r in rows]
    lines.append(f"OK {count[OK]}・まだ {count[MADA]}・NG {count[NG]}")
    return "\n".join(lines), 1 if count[NG] else 0


# ------------------------------------------------------------------ コマンド

def preflight(az) -> None:
    """サインインしていて、サブスクリプションが見えるかを確かめる。"""
    try:
        az.run("account", "show")
    except CheckError as error:
        if error.kind in ("login", "denied", "notfound"):
            raise CheckError("login", "") from None   # 見えない原因は、サインインしていないか、別のディレクトリ
        raise


def failure_text(error: CheckError, tenant: str) -> str:
    """az が使えないときの案内。サインイン切れ・サブスクリプションが見えないときは az login --tenant を示す。"""
    if error.kind == "login":
        return ("NG    サブスクリプションが見えません。サインインしていないか、設定ファイルの AZURE_SUBSCRIPTION_ID が違います。"
                f"サインインします：\n      az login --tenant {tenant}")
    if error.kind == "noaz":
        return f"NG    {error.detail}。入れます：winget install -e --id Microsoft.AzureCLI（入れたら PowerShell を開き直す）"
    return f"NG    {error.detail}"


def build_parser():
    parser = argparse.ArgumentParser(description="チームの名前から、Azure のリソース名を決める・確かめる")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_ in (("names", "名前を検査して、リソース名を表示する"),
                        ("check-names", "作る前に、名前が使えるかを確かめる（何も作らない）"),
                        ("health", "作ったものの状態を見る（読み取りだけ）"),
                        ("env", "接続の設定 .env.local を作る（キーは画面に出さない）")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--team", help=f"チームの名前（省略すると環境変数 {ENV_NAME}）")
        p.add_argument("--config", default=DEFAULT_CONFIG,
                       help="組織の設定ファイル（既定は Repo 直下の workshop.config）")
        if name == "env":
            p.add_argument("--role", required=True, choices=sorted(ROLES),
                           help="builder＝構築する人（AI Search の管理者キー）、member＝メンバー（検索用のキー）")
            p.add_argument("--out", type=Path, metavar="PATH",
                           help="設定を書き出す場所（既定は Repo 直下の .env.local）。メンバーに渡す設定を別の名前で書くとき")
    return parser


def main(argv=None, az=None, env_path=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    try:
        cfg = load_config(config_path)
        try:
            check_org(cfg.org)
        except NameRuleError as error:
            raise ConfigError(f"{config_path.name} の WORKSHOP_ORG を直してください。\n  {error}") from None
        n = make_names(cfg.org, resolve_team(args.team))
    except NameRuleError as error:   # 設定ファイルの誤り（ConfigError）も含む
        print(error, file=sys.stderr)
        return 2
    if args.command == "names":
        print(names_text(cfg.location, n))
        return 0
    try:
        az = az or Az(subscription=cfg.subscription_id)
        preflight(az)
        if args.command == "check-names":
            text, code = check_names_text(n.team, check_names(az, n))
        elif args.command == "env":
            text, code = write_env(az, n, args.role, args.out or env_path or ENV_FILE), 0
        else:
            text, code = health_text(n.team, health(az, n))
    except CheckError as error:
        print(failure_text(error, cfg.tenant))
        return 1
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
