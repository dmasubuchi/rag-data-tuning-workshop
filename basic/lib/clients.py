"""Azure AI Search と Azure OpenAI に接続する道具。API キーで認証する。

スクリプトからは、次の4つを呼ぶ。
  index_client()          インデックスと同義語マップを作る・消す・調べる（SearchIndexClient）。管理者キー（構築する人）だけ
  search_client(名前)     検索する・登録する（SearchClient）。登録は管理者キーだけ。検索はメンバーのキー（検索だけ）でもできる
  openai_client()         埋め込み・回答の生成（OpenAI クライアント。Azure OpenAI の v1 の接続先）
  index_exists(名前)      インデックスがあるか

.env.local の AZURE_SEARCH_KEY_ROLE が query（メンバー用のキー）のとき、AI Search は文書の検索（と件数）しか受け付けない。
作る・変える・消す・調べる・登録する操作は、不透明な 403 になる前に、「構築する人の設定（--role builder）で実行します」の日本語で止める。
"""
from functools import lru_cache

from .config import SetupError, get_settings, is_query_key, require_admin_key

# 文書を書き換えるメソッド（SearchClient）。検索キー（query）では呼べない
_DOCUMENT_WRITES = frozenset({"upload_documents", "merge_documents", "merge_or_upload_documents", "delete_documents", "index_documents"})


class _AdminOnly:
    """index_client()・search_client() が返す、本物のクライアントを包むもの。

    メンバー用のキー（検索だけ）のとき、管理者キーが要るメソッド（index_client の全部、search_client の登録・削除）は、
    呼ぶ前に止める。それ以外は、そのまま本物に渡す。
    """

    def __init__(self, client, blocked=None):
        self._client = client
        self._blocked = blocked      # None なら、"_" で始まらない（close 以外の）全部のメソッド

    def __getattr__(self, name):
        if name in ("_client", "_blocked"):     # まだ作りかけのとき（コピーなど）に、無限に呼び合わない
            raise AttributeError(name)
        attr = getattr(self._client, name)
        if name.startswith("_") or name == "close" or not callable(attr):
            return attr
        if self._blocked is None or name in self._blocked:
            require_admin_key()     # 検索だけのキー（メンバー用）なら、ここで日本語で止まる。管理者キーなら、何もしない
        return attr


@lru_cache(maxsize=1)
def index_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    s = get_settings()
    return _AdminOnly(SearchIndexClient(endpoint=s.search_endpoint, credential=AzureKeyCredential(s.search_key)))


def search_client(index_name: str):
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    s = get_settings()
    client = SearchClient(endpoint=s.search_endpoint, index_name=index_name, credential=AzureKeyCredential(s.search_key))
    return _AdminOnly(client, blocked=_DOCUMENT_WRITES)


@lru_cache(maxsize=1)
def openai_client():
    from openai import OpenAI

    s = get_settings()
    # Azure OpenAI の v1：接続先 + /openai/v1/。日付つきの api-version は付けない。接続先の末尾の / はあってもなくてもよい
    return OpenAI(base_url=s.openai_endpoint.rstrip("/") + "/openai/v1/", api_key=s.openai_key)


def index_exists(name: str) -> bool:
    if is_query_key():
        # 検索だけのキーは、インデックスの一覧を読めない。文書の件数を数えて、なければ「ない」とする
        from azure.core.exceptions import ResourceNotFoundError

        try:
            search_client(name).get_document_count()
            return True
        except ResourceNotFoundError:
            return False
    return name in set(index_client().list_index_names())


def require_index(name: str, hint: str) -> None:
    """インデックスがなければ、何をすればよいかを添えて SetupError にする。"""
    if not index_exists(name):
        raise SetupError(f"インデックス {name} がありません。\n  {hint}")
