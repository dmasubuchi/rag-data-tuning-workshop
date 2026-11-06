"""武将のインデックス sengoku を作る・登録する・ベクトルを足す部品。

01-keyword-search（create_index.py、upload.py）と 03-vector-search（embed.py）のセルが使う。
lib/state.py も、トピックの開始の状態を作り直すときにこれを使う。
スクリプトはセル形式で、上から順に実行するもの。読み込んだだけで動き出さないように、関数はここにまとめてある。
"""
import time

from .config import (SENGOKU_EMBEDDINGS, SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, SetupError, VECTOR_ALGORITHM, VECTOR_PROFILE,
                     get_settings)
from .data import embedding_text
from .indexing import upload, wait_for_count
from .vectorstore import get_vectors

ANALYZER = "ja.microsoft"       # 日本語の分かち書きをするアナライザー（検索する項目に使う）
BATCH_SIZE = 50                 # 1回に送る件数
WAIT_TRIES = 30                 # ベクトルが検索に出てくるまで待つ回数（1回1秒）
MAX_FETCH = 1000                # AI Search の1回の取得の上限
FIELDS = ("id", "name", "aliases", "battles", "profile", "clan", "province", "born", "died")   # 登録する項目


# ------------------------------------------------------------------ 01 インデックスを作る・登録する

def build_index(name: str, analyzer: str = ANALYZER):
    """武将用のインデックスの定義を作る（state.py もこの関数を使う）。"""
    from azure.search.documents.indexes.models import SearchField, SearchIndex

    fields = [
        # id：文書を1件ずつ区別するキー
        SearchField(name="id", type="Edm.String", searchable=False, key=True, filterable=True, sortable=True),
        # 検索する項目：searchable=True。日本語の文章なので ja.microsoft で単語に分ける
        SearchField(name="name", type="Edm.String", searchable=True, filterable=True, analyzer_name=analyzer),
        SearchField(name="aliases", type="Collection(Edm.String)", searchable=True, analyzer_name=analyzer),
        SearchField(name="battles", type="Collection(Edm.String)", searchable=True, analyzer_name=analyzer),
        SearchField(name="profile", type="Edm.String", searchable=True, analyzer_name=analyzer),
        # 絞り込みに使う項目：filterable=True。検索はしないので searchable=False と明示する
        # （文字列の項目は、書かないと「検索する」になる。clan に「織田家」があると「織田家の家臣」で当たってしまう）
        SearchField(name="clan", type="Edm.String", searchable=False, filterable=True, facetable=True),
        SearchField(name="province", type="Edm.String", searchable=False, filterable=True, facetable=True),
        SearchField(name="born", type="Edm.Int32", filterable=True, sortable=True),
        SearchField(name="died", type="Edm.Int32", filterable=True, sortable=True),
    ]
    return SearchIndex(name=name, fields=fields)


def make_documents(people: list) -> list:
    """JSON の1人分から、インデックスにある項目だけを取り出して、登録用の辞書にする。"""
    return [{k: p.get(k) for k in FIELDS} for p in people]


def register(client, people: list, batch_size: int = BATCH_SIZE) -> int:
    """武将を登録して、登録後の文書数を返す。"""
    docs = make_documents(people)
    upload(client, docs, mode="upload", batch_size=batch_size)
    return wait_for_count(client, len(docs))


# ------------------------------------------------------------------ 03 ベクトルを足す

def add_vector_fields(client, name: str, dims: int) -> bool:
    """インデックスにベクトルの項目とセマンティックの設定を足す。すでにあれば何もしない（戻り値 False）。"""
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration, HnswParameters, SearchField, SemanticConfiguration, SemanticField,
        SemanticPrioritizedFields, SemanticSearch, VectorSearch, VectorSearchProfile)

    index = client.get_index(name)
    if any(f.name == SENGOKU_VECTOR_FIELD for f in index.fields):
        return False

    # ベクトルの項目：数の並び（Collection(Edm.Single)）。次元は埋め込みモデルに合わせる
    index.fields.append(SearchField(
        name=SENGOKU_VECTOR_FIELD, type="Collection(Edm.Single)", searchable=True, retrievable=False,
        vector_search_dimensions=dims, vector_search_profile_name=VECTOR_PROFILE,
    ))
    # ベクトル検索の設定：近いものを探す方法（HNSW）と、近さの測り方（コサイン類似度）
    index.vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=VECTOR_ALGORITHM, parameters=HnswParameters(metric="cosine"))],
        profiles=[VectorSearchProfile(name=VECTOR_PROFILE, algorithm_configuration_name=VECTOR_ALGORITHM)],
    )
    # セマンティックランカーの設定（04-hybrid-ranker で使う）：見出しは name、本文は profile、キーワードは aliases
    index.semantic_search = SemanticSearch(configurations=[SemanticConfiguration(
        name=SENGOKU_SEMANTIC,
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="name"),
            content_fields=[SemanticField(field_name="profile")],
            keywords_fields=[SemanticField(field_name="aliases")],
        ),
    )])
    client.create_or_update_index(index)
    return True


def ids_with_vectors(client) -> set:
    """ベクトルが入っていて、いま検索に出てくる武将の id。ありえない向きのベクトルで近い順に全件を取る（ベクトルのない文書は出てこない）。"""
    from azure.search.documents.models import VectorizedQuery

    probe = [1.0] + [0.0] * (get_settings().dimensions - 1)
    res = client.search(search_text=None, select=["id"], top=MAX_FETCH,
                        vector_queries=[VectorizedQuery(vector=probe, k_nearest_neighbors=MAX_FETCH, fields=SENGOKU_VECTOR_FIELD)])
    return {r["id"] for r in res}


def wait_for_vectors(client, ids, tries: int = WAIT_TRIES) -> None:
    """登録したベクトルが、全部検索に出てくるまで待つ（文書の件数が合っていても、ベクトルの反映は少し遅れることがある）。

    tries 秒たっても揃わなければ、参加者向けの案内を書いた SetupError で止める。
    """
    expected = set(ids)
    announced = False
    for i in range(tries + 1):
        found = ids_with_vectors(client) & expected
        if found == expected:
            return
        if not announced:
            print(f"  ベクトルが検索に出てくるのを待っています（いま {len(found)}/{len(expected)} 件）")
            announced = True
        if i < tries:
            time.sleep(1.0)
    raise SetupError(
        f"登録したベクトル {len(expected)} 件のうち、{len(found)} 件しか、まだ検索に出てきません（反映に時間がかかっています）。\n"
        "  少し待ってから、もう一度 embed.py を実行してください。"
    )


def embed_and_register(search, people: list, use_file: bool, batch_size: int = BATCH_SIZE) -> int:
    """武将を埋め込み、登録済みの文書にベクトルを足す。戻り値は、登録後の文書数。"""
    texts = [embedding_text(p) for p in people]
    vectors = get_vectors(texts, SENGOKU_EMBEDDINGS, use_file, label="武将")
    docs = [{"id": p["id"], SENGOKU_VECTOR_FIELD: v} for p, v in zip(people, vectors)]
    upload(search, docs, mode="merge", batch_size=batch_size)
    count = wait_for_count(search, len(docs))
    wait_for_vectors(search, [d["id"] for d in docs])
    return count
