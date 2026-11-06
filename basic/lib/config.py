"""設定（.env.local）、データの場所、インデックスの名前。

設定は Repo 直下の .env.local だけ。構築する人が `python tools/team.py env --team <チーム> --role builder` で作り、メンバーは構築する人から member.local.env を受け取って .env.local という名前で置く（Git には入らない）。
  AZURE_SEARCH_ENDPOINT・AZURE_SEARCH_API_KEY    チームの AI Search の接続先とキー
  AZURE_SEARCH_KEY_ROLE                          admin（構築する人。作る・登録する）か query（メンバー。検索だけ）
  AZURE_OPENAI_ENDPOINT・AZURE_OPENAI_API_KEY    チームの Foundry（Azure OpenAI）の接続先とキー
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT・AZURE_OPENAI_CHAT_DEPLOYMENT   埋め込みとチャットのデプロイ名
  AZURE_OPENAI_REASONING_EFFORT                  推論モデルの「考える量」（既定 low）
  EMBEDDING_DIMENSIONS                           埋め込みの次元

認証はキー（AI Search のキー、Azure OpenAI のキー）だけ。
Azure の値は、いつも .env.local のファイルの中身を使う。端末に残っている AZURE_* の環境変数は読まない
（別の環境の接続先やキーで動いてしまわないため）。試験のときだけ、環境変数 WORKSHOP_ENV_FILE で別のファイルを指せる。

インデックスの名前（チームごとに自分の AI Search を持つので、名前は固定）
  sengoku            武将
  sengoku-synonyms   同義語マップ（02 で作る）
"""
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import BASIC_DIR, REPO_DIR

DATA_DIR = BASIC_DIR / "data"
SENGOKU_DIR = DATA_DIR / "sengoku"

BUSHOU_JSON = SENGOKU_DIR / "bushou.json"
QUESTIONS_JSON = SENGOKU_DIR / "questions.json"

# 埋め込み済みファイル（tools/make_embeddings.py が作る）。時間が足りないとき用
EMBEDDINGS_DIR = BASIC_DIR / "embeddings"
SENGOKU_EMBEDDINGS = EMBEDDINGS_DIR / "sengoku.json"

ENV_LOCAL = REPO_DIR / ".env.local"

REQUIRED_KEYS = (
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "EMBEDDING_DIMENSIONS",
)
KEY_ROLES = ("admin", "query")      # AZURE_SEARCH_KEY_ROLE：admin は構築する人、query はメンバー


class SetupError(Exception):
    """設定や準備のまちがい。メッセージは、そのまま参加者に見せる日本語の文章にする。"""


def display_path(path) -> str:
    """画面に出すときのパス。自分のパソコンのフォルダ名（ユーザー名など）が出ないようにする。

    Repo の中なら、Repo 直下からの相対パス（例 basic/data/sengoku/bushou.json、.env.local）。
    ホームフォルダの下なら ~/… に置き換える。それ以外はそのまま。
    """
    p = Path(path)
    try:
        p = p.resolve()
        if REPO_DIR in p.parents or p == REPO_DIR:
            return os.path.relpath(p, REPO_DIR).replace("\\", "/")
        home = Path.home().resolve()
        if home in p.parents:
            return "~/" + str(p.relative_to(home)).replace("\\", "/")
    except (OSError, ValueError):
        pass
    return str(path).replace("\\", "/")


_SAFE_ARG = re.compile(r"[A-Za-z0-9_./:-]+")   # 引用符なしで、bash・PowerShell・cmd のどれでもそのまま渡る文字


def quote_arg(arg: str) -> str:
    """コマンドの引数を、PowerShell・bash・cmd にそのまま貼れる形にする。空白や ( ) & などを含むときは引用符で囲む。"""
    if _SAFE_ARG.fullmatch(arg):
        return arg
    if not any(c in arg for c in "\"$`'"):
        return f'"{arg}"'                       # 三つのシェルで同じ意味になる二重引用符
    if "'" not in arg:
        return f"'{arg}'"                       # $ や ` を含むときは、文字どおりに渡る一重引用符
    if os.name == "nt":
        return "'" + arg.replace("'", "''") + "'"       # PowerShell
    return "'" + arg.replace("'", "'\\''") + "'"         # bash


def command_to(path, *args) -> str:
    """いまいるフォルダから path のスクリプトを実行するコマンド（画面の案内に出す。そのまま貼って動く）。

    path に空白などがあるときは、引用符で囲む。args に None は渡せない（引数なしのときは何も渡さない）。
    """
    try:
        rel = os.path.relpath(Path(path), Path.cwd())
    except ValueError:      # Windows で別のドライブにあるとき
        rel = str(path)
    if os.sep != "/":
        rel = rel.replace(os.sep, "/")          # PowerShell でも / で動く
    return " ".join(["python", quote_arg(rel), *(quote_arg(str(a)) for a in args)])


def reset_command(topic: str) -> str:
    """「その直前の状態に戻す」コマンド。topic はトピックの番号（例 "03"）。"""
    return command_to(BASIC_DIR / "tools" / "reset.py", "--to", topic)


# ------------------------------------------------------------------ .env.local

ENV_LOCAL_HOWTO = ("構築する人は、Repo 直下で `python tools/team.py env --team <チーム> --role builder` を実行すると .env.local を作れます。"
                   "メンバーは、構築する人から member.local.env を受け取り、Repo 直下に .env.local という名前で置きます。")


@dataclass(frozen=True)
class Settings:
    """.env.local の値。キーは repr に出さない（Notebook で評価しても見えない）。"""
    search_endpoint: str
    search_key: str = field(repr=False)
    openai_endpoint: str
    openai_key: str = field(repr=False)
    api_version: str
    embedding_deployment: str
    chat_deployment: str
    dimensions: int
    env_file: str
    reasoning_effort: str = ""  # 空なら渡さない（AZURE_OPENAI_REASONING_EFFORT）
    key_role: str = ""          # AZURE_SEARCH_KEY_ROLE：admin（構築する人）か query（メンバー）。書いてなければ空


def env_file_path() -> Path:
    """設定ファイルの場所。Repo 直下の .env.local。環境変数 WORKSHOP_ENV_FILE があればそれ（試験用）。"""
    given = os.environ.get("WORKSHOP_ENV_FILE")
    if given:
        return Path(given).expanduser()
    return ENV_LOCAL


def read_env_file(path) -> dict:
    """設定ファイルを読んで、{名前: 値} を返す。環境変数は見ない・変えない（値の補間もしない）。"""
    from dotenv import dotenv_values

    # utf-8-sig：メモ帳で保存した BOM 付きのファイルでも読めるように
    raw = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    return {k: (v or "").strip() for k, v in raw.items()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    path = env_file_path()
    if not path.is_file():
        raise SetupError(
            f"設定ファイルが見つかりません: {display_path(path)}\n"
            f"  {ENV_LOCAL_HOWTO}"
        )
    # 値は、いつもこのファイルの中身を使う（端末に残った AZURE_* の環境変数は使わない）
    env = read_env_file(path)

    values = {k: env.get(k, "") for k in REQUIRED_KEYS}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise SetupError(
            f"{path.name} に、次の項目がありません（または空です）: {', '.join(missing)}\n"
            f"  {ENV_LOCAL_HOWTO}"
        )
    placeholders = [k for k, v in values.items() if "<" in v and ">" in v]
    if placeholders:
        raise SetupError(
            f"{path.name} の次の項目が、まだ見本のままです: {', '.join(placeholders)}\n"
            f"  {ENV_LOCAL_HOWTO}"
        )
    try:
        dims = int(values["EMBEDDING_DIMENSIONS"])
    except ValueError:
        raise SetupError(f"EMBEDDING_DIMENSIONS は整数で書いてください（今は {values['EMBEDDING_DIMENSIONS']!r}）。")
    key_role = env.get("AZURE_SEARCH_KEY_ROLE", "")
    if key_role and key_role not in KEY_ROLES:
        raise SetupError(f"AZURE_SEARCH_KEY_ROLE は {' か '.join(KEY_ROLES)} のどちらかです（今は {key_role!r}）。\n  {ENV_LOCAL_HOWTO}")
    return Settings(
        search_endpoint=values["AZURE_SEARCH_ENDPOINT"],
        search_key=values["AZURE_SEARCH_API_KEY"],
        openai_endpoint=values["AZURE_OPENAI_ENDPOINT"],
        openai_key=values["AZURE_OPENAI_API_KEY"],
        api_version=env.get("AZURE_OPENAI_API_VERSION", ""),  # v1 の呼び出しでは使わない（書いてあっても読める）
        embedding_deployment=values["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        chat_deployment=values["AZURE_OPENAI_CHAT_DEPLOYMENT"],
        dimensions=dims,
        env_file=str(path),
        reasoning_effort=env.get("AZURE_OPENAI_REASONING_EFFORT", ""),
        key_role=key_role,
    )


def is_query_key() -> bool:
    """いまの .env.local が、検索だけのキー（メンバー用。AZURE_SEARCH_KEY_ROLE=query）か。"""
    return get_settings().key_role == "query"


ADMIN_ONLY_MESSAGE = (
    "この手順は構築する人の設定（--role builder）で実行します。\n"
    "  いまの .env.local は検索だけのキー（メンバー用）なので、インデックスや同義語マップを作る・変える・調べる、"
    "文書を登録することはできません。\n"
    "  構築する人が実行するか、構築する人の .env.local（`python tools/team.py env --team <チーム> --role builder`）で実行してください。"
)


def require_admin_key() -> None:
    """インデックスなどを作る・変える・消す手順の始めに呼ぶ。検索だけのキー（メンバー用）なら、不透明な 403 の前に、日本語で止まる。"""
    if is_query_key():
        raise SetupError(ADMIN_ONLY_MESSAGE)


# ------------------------------------------------------------------ インデックスの名前（チームごとに自分の AI Search を持つので固定）

SENGOKU_INDEX = "sengoku"
SYNONYM_MAP = "sengoku-synonyms"


def sengoku_index_name() -> str:
    return SENGOKU_INDEX


def synonym_map_name() -> str:
    """同義語マップの名前（02 で作る）。"""
    return SYNONYM_MAP


def index_names() -> list:
    """このハンズオンが作るインデックス。tools/reset.py が消すのは、この名前だけ（同じ AI Search にある、ほかのインデックスには触らない）。"""
    return [sengoku_index_name()]


# インデックスの中の名前（スクリプトどうしで合わせる）
SENGOKU_VECTOR_FIELD = "profile_vector"
SENGOKU_SEMANTIC = "sengoku-semantic"
VECTOR_PROFILE = "vec-profile"
VECTOR_ALGORITHM = "hnsw-cosine"
