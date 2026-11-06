"""Azure に接続する道具（AI Search、Storage）。キーは .env.local から読む。

スクリプトからは、次を呼ぶ。
  index_client()          インデックスを作る・読む・消す（SearchIndexClient）。管理者キー（構築する人）だけ
  indexer_client()        データソース・スキルセット・インデクサーを作る・読む・動かす（SearchIndexerClient）。管理者キーだけ
  search_client(名前)     検索する・登録する（SearchClient）。登録・削除・付け直しは管理者キーだけ。検索はメンバーのキー（検索だけ）でもできる
  container_client()      Storage の入れ物を読み書きする（BlobServiceClient）。構築する人の設定（Storage の項目）だけ

.env.local の AZURE_SEARCH_KEY_ROLE が query（メンバー用のキー）のとき、AI Search は文書の検索（と件数）しか受け付けない。
作る・変える・消す・調べる・動かす・登録する操作は、不透明な 403 になる前に、「構築する人の設定（--role builder）で実行します」の日本語で止める。
"""
from .config import get_settings, require_admin_key

# 文書を書き換えるメソッド（SearchClient）。検索キー（query）では呼べない
_DOCUMENT_WRITES = frozenset({"upload_documents", "merge_documents", "merge_or_upload_documents", "delete_documents", "index_documents"})


class _AdminOnly:
    """index_client()・indexer_client()・search_client() が返す、本物のクライアントを包むもの。

    メンバー用のキー（検索だけ）のとき、管理者キーが要るメソッド（index_client・indexer_client の全部、search_client の登録・削除）は、
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


def credential():
    from azure.core.credentials import AzureKeyCredential

    return AzureKeyCredential(get_settings().search_key)


def index_client():
    """インデックスを作る・読む道具。管理者キー（構築する人）だけ。"""
    from azure.search.documents.indexes import SearchIndexClient

    return _AdminOnly(SearchIndexClient(get_settings().search_endpoint, credential()))


def indexer_client():
    """データソース・スキルセット・インデクサーを作る・読む・動かす道具。管理者キー（構築する人）だけ。"""
    from azure.search.documents.indexes import SearchIndexerClient

    return _AdminOnly(SearchIndexerClient(get_settings().search_endpoint, credential()))


def search_client(index_name: str):
    """1つのインデックスを検索する道具。登録・削除・付け直しは管理者キーだけ（検索はメンバーのキーでもできる）。"""
    from azure.search.documents import SearchClient

    return _AdminOnly(SearchClient(get_settings().search_endpoint, index_name, credential()), blocked=_DOCUMENT_WRITES)


def container_client():
    """Storage の入れ物（人事の文書の置き場）を読み書きする道具。構築する人の設定（Storage の項目）だけ。"""
    from azure.storage.blob import BlobServiceClient

    require_admin_key()                         # メンバーの設定では、Storage には触らない
    s = get_settings(need_storage=True)         # Storage の項目がなければ、日本語で止まる
    return BlobServiceClient.from_connection_string(s.storage_connection_string).get_container_client(s.storage_container)

