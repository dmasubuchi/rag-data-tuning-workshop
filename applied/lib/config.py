"""設定（.env.local）、データの場所、人事のインデックスの名前。

設定は Repo 直下の .env.local だけ。構築する人が `python tools/team.py env --team <チーム> --role builder` で作り、メンバーは構築する人から member.local.env を受け取って .env.local という名前で置く（Git には入らない）。
  AZURE_SEARCH_ENDPOINT・AZURE_SEARCH_API_KEY    チームの AI Search の接続先とキー
  AZURE_SEARCH_KEY_ROLE                          admin（構築する人。作る・登録する）か query（メンバー。検索だけ）
  AZURE_OPENAI_ENDPOINT・AZURE_OPENAI_API_KEY    チームの Foundry（Azure OpenAI）の接続先とキー
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT・AZURE_OPENAI_CHAT_DEPLOYMENT   埋め込みとチャットのデプロイ名
  AZURE_OPENAI_CHAT_MODEL                        チャットのモデル名（知識ベースが使う。既定 gpt-5-mini）
  AZURE_OPENAI_REASONING_EFFORT                  推論モデルの「考える量」（既定 low）
  EMBEDDING_DIMENSIONS                           埋め込みの次元
  AZURE_STORAGE_CONNECTION_STRING・AZURE_STORAGE_CONTAINER   人事の文書の置き場（構築する人だけ。メンバーの設定には入らない）

Storage は、文書を置く・直す段（build_hr_index.py と 17）でだけ要る。get_settings(need_storage=True) のときだけ必須にして、
14〜16・18〜20（メンバーが動かす）は、Storage がなくても動く。

認証はキー（AI Search のキー、Azure OpenAI のキー、Storage の接続文字列）だけ。
Azure の値は、いつも .env.local のファイルの中身を使う。端末に残っている AZURE_* の環境変数は読まない
（別の環境の接続先やキーで動いてしまわないため）。試験のときだけ、環境変数 WORKSHOP_ENV_FILE で別のファイルを指せる。

人事のインデックスなどの名前（チームごとに自分の AI Search を持つので、名前は固定）
  hr-docs        インデックス（チャンク単位。インデクサーが作る）
  hr-docs-ds     データソース（Storage の入れ物の全体）
  hr-docs-ss     スキルセット（OCR → 文字の結合 → 分割 → 埋め込み）
  hr-docs-ixr    インデクサー
  hr-docs-ks     知識ソース（lib/agentic.py）
  hr-docs-kb     知識ベース（lib/agentic.py）
これらを作る・消すのは、構築する人の tools/build_hr_index.py と tools/build_hr_kb.py だけ。ほかのスクリプトは読むだけ（17 は、文書を直して、最後に元へ戻す）。
"""
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import APPLIED_DIR, REPO_DIR

DATA_DIR = APPLIED_DIR / "data"
MANIFEST_JSON = DATA_DIR / "manifest.json"
ENV_LOCAL = REPO_DIR / ".env.local"

HR_INDEX = "hr-docs"
HR_DATASOURCE = "hr-docs-ds"
HR_SKILLSET = "hr-docs-ss"
HR_INDEXER = "hr-docs-ixr"

# インデックスの中の名前（スクリプトどうしで合わせる）
VECTOR_FIELD = "text_vector"
VECTOR_PROFILE = "applied-vec-profile"
VECTOR_ALGORITHM = "applied-hnsw"
VECTORIZER = "applied-aoai"
SEMANTIC_CONFIG = "applied-semantic"

REQUIRED_KEYS = (
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "EMBEDDING_DIMENSIONS",
)
STORAGE_KEYS = (            # Storage を使う段（build_hr_index.py、17）でだけ必須
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_CONTAINER",
)
KEY_ROLES = ("admin", "query")      # AZURE_SEARCH_KEY_ROLE：admin は構築する人、query はメンバー
DEFAULT_CHAT_MODEL = "gpt-5-mini"


class SetupError(Exception):
    """設定や準備のまちがい。メッセージは、そのまま参加者に見せる日本語の文章にする。"""


def display_path(path) -> str:
    """画面に出すときのパス。Repo の中なら Repo 直下からの相対パス、ホームの下なら ~/…（ユーザー名を出さない）。"""
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
    embedding_deployment: str
    chat_deployment: str
    dimensions: int
    env_file: str
    chat_model: str = DEFAULT_CHAT_MODEL    # AZURE_OPENAI_CHAT_MODEL（モデル名。デプロイ名とは限らない）
    reasoning_effort: str = ""  # AZURE_OPENAI_REASONING_EFFORT。空なら、16・19 は渡さない。採用アシスタントは low にする（assistant/azure_io.py）
    key_role: str = ""          # AZURE_SEARCH_KEY_ROLE：admin（構築する人）か query（メンバー）。書いてなければ空
    storage_connection_string: str = field(default="", repr=False)    # 構築する人だけ。メンバーは空
    storage_container: str = ""


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


@lru_cache(maxsize=4)
def get_settings(need_storage: bool = False) -> Settings:
    """.env.local を読む。need_storage=True のときだけ、Storage の2項目（接続文字列・入れ物）を必須にする。

    Storage を使うのは build_hr_index.py と 17 だけ。そのほかは、メンバーの設定（Storage なし）でも動く。
    """
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
    storage = {k: env.get(k, "") for k in STORAGE_KEYS}
    if need_storage:
        missing = [k for k, v in storage.items() if not v]
        if missing:
            raise SetupError(
                f"この手順は Storage（人事の文書の置き場）につなぎます。{path.name} に、次の項目がありません（または空です）: {', '.join(missing)}\n"
                "  Storage の項目は、構築する人の設定（--role builder）にだけ入ります。メンバーの設定では実行できません。\n"
                f"  構築する人が実行するか、構築する人の .env.local で実行してください。{ENV_LOCAL_HOWTO}"
            )
    placeholders = [k for k, v in {**values, **storage}.items() if "<" in v and ">" in v]
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
        embedding_deployment=values["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        chat_deployment=values["AZURE_OPENAI_CHAT_DEPLOYMENT"],
        dimensions=dims,
        env_file=str(path),
        chat_model=env.get("AZURE_OPENAI_CHAT_MODEL", "") or DEFAULT_CHAT_MODEL,
        reasoning_effort=env.get("AZURE_OPENAI_REASONING_EFFORT", ""),
        key_role=key_role,
        storage_connection_string=storage["AZURE_STORAGE_CONNECTION_STRING"],
        storage_container=storage["AZURE_STORAGE_CONTAINER"],
    )


def is_query_key() -> bool:
    """いまの .env.local が、検索だけのキー（メンバー用。AZURE_SEARCH_KEY_ROLE=query）か。"""
    return get_settings().key_role == "query"


ADMIN_ONLY_MESSAGE = (
    "この手順は構築する人の設定（--role builder）で実行します。\n"
    "  いまの .env.local は検索だけのキー（メンバー用）なので、インデックス・インデクサー・知識ベースなどを作る・変える・調べる、"
    "文書を登録する・直すことはできません。\n"
    "  構築する人が実行するか、構築する人の .env.local（`python tools/team.py env --team <チーム> --role builder`）で実行してください。"
)


def require_admin_key() -> None:
    """作る・変える・消す・文書を直す手順の始めに呼ぶ。検索だけのキー（メンバー用）なら、不透明な 403 の前に、日本語で止まる。"""
    if is_query_key():
        raise SetupError(ADMIN_ONLY_MESSAGE)


# ------------------------------------------------------------------ データの一覧（manifest.json）

@lru_cache(maxsize=1)
def load_manifest() -> dict:
    if not MANIFEST_JSON.is_file():
        raise SetupError(f"データの一覧が見つかりません: {display_path(MANIFEST_JSON)}")
    return json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))


def manifest_files() -> list:
    """データの各ファイル（path、kind、doc_id、req_id、application_ids、person_keys など）。"""
    return list(load_manifest()["files"])
