"""接続の設定ファイル .env.local を作る。キーは az で読み、このファイルにだけ書く（画面にも引数にも出さない）。

役割は2つ。
  builder（構築する人）：AI Search の管理者キー。インデックスを作れる。人に渡さない。
  member（メンバー）  ：AI Search の検索用キー。検索だけできる（管理者キーは、読みもしないし、書かない）。
                        構築する人が書き出して、チームのメンバーに渡す。チームの外には渡さない。
Foundry のキーは、どちらも同じ（key1）。

書き込みは、同じフォルダーの一時ファイル（持ち主だけが読める）に書いてから置き換える。失敗したら、前の設定ファイルはそのまま。

動かすのは Python の標準ライブラリだけ。
"""
import os
import re
import secrets
from pathlib import Path

from .az import CheckError
from .names import Names

ENV_FILE = Path(__file__).resolve().parents[2] / ".env.local"

EMBEDDING_DEPLOYMENT = "text-embedding-3-small"
CHAT_DEPLOYMENT = "gpt-5-mini"
EMBEDDING_DIMENSIONS = "1536"

ROLES = {
    # role: (AZURE_SEARCH_KEY_ROLE の値, 設定ファイルの先頭に書く呼び方, 画面に出す呼び方,
    #        設定ファイルの先頭に書く渡し方の注意, 画面に出す渡し方の注意)
    "builder": ("admin", "構築する人用", "構築する人用、AI Search は管理者キー",
                "人に渡さない", "人に渡しません"),
    "member": ("query", "メンバー用", "メンバー用、AI Search は検索だけのキー",
               "チームの外に渡さない", "チームのメンバーに渡せます。チームの外には渡しません"),
}

UNEXPECTED = "az の答えの形が想定外です"


def env_text(names: Names, role: str, search_key: str, ai_key: str) -> str:
    """.env.local の中身。role は "builder" か "member"。search_key はその役割のキー、ai_key は Foundry のキー。"""
    if role not in ROLES:
        raise ValueError(f"role は builder か member です（今は {role!r}）")
    key_role, short, _, handling, _ = ROLES[role]
    lines = [
        f"# チーム {names.team} の AI Search と Foundry につなぐ設定（{short}）。team.py env が作成。Git に入らない。{handling}",
        f"AZURE_SEARCH_ENDPOINT=https://{names.search}.search.windows.net",
        f"AZURE_SEARCH_API_KEY={search_key}",
        f"AZURE_SEARCH_KEY_ROLE={key_role}",
        f"AZURE_OPENAI_ENDPOINT=https://{names.foundry}.openai.azure.com/",
        f"AZURE_OPENAI_API_KEY={ai_key}",
        f"AZURE_OPENAI_EMBEDDING_DEPLOYMENT={EMBEDDING_DEPLOYMENT}",
        f"AZURE_OPENAI_CHAT_DEPLOYMENT={CHAT_DEPLOYMENT}",
        f"EMBEDDING_DIMENSIONS={EMBEDDING_DIMENSIONS}",
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ az からキーを読む

def _key(answer, name) -> str:
    """answer（dict）の name のキーを取る。dict でない・name がない・空・空白や改行を含む（別の行を書き込めてしまう）なら CheckError。"""
    value = answer.get(name) if isinstance(answer, dict) else None
    if not isinstance(value, str) or not re.fullmatch(r"\S+", value):
        raise CheckError("other", UNEXPECTED)
    return value


def _reading(what, read):
    """read() を呼ぶ。まだない・権限がないは、見せてよい短い文にする。サインイン切れはそのまま上へ（main が az login を案内する）。"""
    try:
        return read()
    except CheckError as error:
        if error.kind == "notfound":
            raise CheckError("other", f"{what} がまだありません。作ってから、もう一度実行します") from None
        if error.kind == "denied":
            raise CheckError("other", f"{what} のキーを読む権限がありません") from None
        raise


def _search_key(az, names: Names, role: str) -> str:
    scope = ("--service-name", names.search, "-g", names.resource_group)
    what = f"AI Search {names.search}"
    if role == "builder":
        return _key(_reading(what, lambda: az.run("search", "admin-key", "show", *scope)), "primaryKey")
    keys = _reading(what, lambda: az.run("search", "query-key", "list", *scope))
    if not isinstance(keys, list):
        raise CheckError("other", UNEXPECTED)
    if not keys:   # 検索用のキーを作る操作は、この道具にない
        raise CheckError("other", f"検索用のキーがありません（{what}）。構築する人に、検索用のキーを作ってもらいます")
    return _key(keys[0], "key")


def _ai_key(az, names: Names) -> str:
    answer = _reading(f"Foundry {names.foundry}",
                      lambda: az.run("cognitiveservices", "account", "keys", "list", "-n", names.foundry, "-g", names.resource_group))
    return _key(answer, "key1")


def _write_private(path: Path, text: str) -> None:
    """同じフォルダーの一時ファイル（持ち主だけが読める）に書いて、path に置き換える。失敗したら一時ファイルを消す。

    O_EXCL は、同じ名前のファイルが先にあれば失敗させる印（他人が仕込んだリンクに書かない）。
    O_BINARY は、Windows が改行を \\r\\n に変えないための印（macOS・Linux にはない）。
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        try:
            view = memoryview(text.encode("utf-8"))
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_env(az, names: Names, role: str, path: Path = ENV_FILE) -> str:
    """az でキーを読み、path（既定は Repo 直下の .env.local）を書き直す。画面に出す文を返す。キーは含めない。

    キーを全部読めてから書く。読めなかったときも、書けなかったときも、前の設定ファイルはそのまま。
    """
    if role not in ROLES:
        raise ValueError(f"role は builder か member です（今は {role!r}）")
    text = env_text(names, role, _search_key(az, names, role), _ai_key(az, names))
    path = Path(path)
    try:
        _write_private(path, text)
    except OSError:
        raise CheckError("other", f"{path.name} を書けません（{path.parent} に書き込めるか確かめます）。"
                                  "前の設定ファイルはそのままです") from None
    shown, handout = ROLES[role][2], ROLES[role][4]
    return (f"OK    {path.name} を作りました（チーム {names.team}：{shown}）。キーは表示しません\n"
            f"      このファイルは Git に入りません。{handout}")
