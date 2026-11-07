"""評価の道具が使う接続先とキー（標準ライブラリだけ）。

読むのは Repo 直下の .env.local だけ（環境変数 WORKSHOP_ENV_FILE で別のファイルを指せる。試験用）。
端末の AZURE_* の環境変数は読まない。検索はメンバーの query キーでよい（検索するだけで、何も作らない・変えない）。
キーは repr にも出さない。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
ENV_HOWTO = ("構築する人は、Repo 直下で `python tools/team.py env --team <チーム> --role builder` を実行すると作れます。"
             "メンバーは、構築する人から member.local.env を受け取り、.env.local という名前で Repo 直下に置きます。")
SEARCH_KEYS = ("AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_API_KEY")
EMBEDDING_KEYS = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "EMBEDDING_DIMENSIONS")


class SettingsError(Exception):
    """利用者に見せる日本語の理由つきの失敗（設定のファイルが読めない・項目がない）。"""


@dataclass(frozen=True)
class Settings:
    search_endpoint: str
    search_key: str = field(repr=False)
    openai_endpoint: str = ""
    openai_key: str = field(default="", repr=False)
    embedding_deployment: str = ""
    dimensions: int = 0


def env_path() -> Path:
    given = os.environ.get("WORKSHOP_ENV_FILE")
    return Path(given).expanduser() if given else REPO_DIR / ".env.local"


def read_env(path) -> dict:
    """設定のファイルを {名前: 値} にする（環境変数は見ない）。"""
    env = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            env[name.strip()] = value.strip().strip("\"'")
    return env


def load_settings(*, need_embedding: bool, path=None) -> Settings:
    """設定のファイルから読む。need_embedding は、質問の埋め込み（Azure OpenAI）を使うとき。足りなければ SettingsError。"""
    path = Path(path or env_path())
    try:
        env = read_env(path)
    except (OSError, ValueError):
        raise SettingsError(f"{path.name} が読めません。{ENV_HOWTO}") from None
    required = SEARCH_KEYS + (EMBEDDING_KEYS if need_embedding else ())
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise SettingsError(f"{path.name} に、次の項目がありません：{'、'.join(missing)}。{ENV_HOWTO}")
    dimensions = 0
    if need_embedding:
        try:
            dimensions = int(env["EMBEDDING_DIMENSIONS"])
        except ValueError:
            raise SettingsError(f"EMBEDDING_DIMENSIONS は整数で書いてください（今は {env['EMBEDDING_DIMENSIONS']!r}）。") from None
    return Settings(
        search_endpoint=env["AZURE_SEARCH_ENDPOINT"].rstrip("/"), search_key=env["AZURE_SEARCH_API_KEY"],
        openai_endpoint=env.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/"), openai_key=env.get("AZURE_OPENAI_API_KEY", ""),
        embedding_deployment=env.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""), dimensions=dimensions)
