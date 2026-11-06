"""4つの検索方式。同じインデックス・同じ質問で、変えるのは次のところだけ。

  keyword        search_text だけ
  vector         ベクトルのクエリだけ（k=50）
  hybrid         search_text ＋ ベクトルのクエリ（k=50）
  hybrid_ranker  hybrid と同じ条件に query_type="semantic" を足す

どれも、結果は「上から順に並んだ辞書の一覧」で返る（辞書に "@search.score" などが入っている）。
測る範囲は上位 50 件（top=50）。画面には、スクリプトのほうで上位 5 件などを出す。
"""
from .show import MEASURED_TOP

K_NEAREST = 50  # ベクトル側の候補数 k
TOP_ALL = 1000  # キーワードに一致した文書をすべて取りたいときの上限（AI Search の1回の上限）


def _vector_query(vector: list, field: str, k: int):
    from azure.search.documents.models import VectorizedQuery

    return VectorizedQuery(vector=vector, k_nearest_neighbors=k, fields=field)


def keyword(client, query: str, *, top: int = MEASURED_TOP, select=None, search_fields=None, filter=None) -> list:
    """キーワード検索。search_text だけ。"""
    res = client.search(search_text=query, top=top, select=select, search_fields=search_fields, filter=filter)
    return list(res)


def vector(client, vec: list, field: str, *, k: int = K_NEAREST, top: int = MEASURED_TOP, select=None, filter=None) -> list:
    """ベクトル検索。ベクトルのクエリだけ（search_text は渡さない）。"""
    res = client.search(search_text=None, vector_queries=[_vector_query(vec, field, k)], top=top, select=select, filter=filter)
    return list(res)


def hybrid(client, query: str, vec: list, field: str, *, k: int = K_NEAREST, top: int = MEASURED_TOP,
           select=None, search_fields=None, filter=None) -> list:
    """ハイブリッド検索。search_text とベクトルのクエリを両方渡す。順位は AI Search が RRF で決める。"""
    res = client.search(search_text=query, vector_queries=[_vector_query(vec, field, k)], top=top,
                        select=select, search_fields=search_fields, filter=filter)
    return list(res)


def hybrid_ranker(client, query: str, vec: list, field: str, semantic_config: str, *, k: int = K_NEAREST,
                  top: int = MEASURED_TOP, select=None, search_fields=None, filter=None) -> list:
    """ハイブリッド＋セマンティックランカー。hybrid と同じ条件に query_type="semantic" を足しただけ。

    ランカーは、前段（ハイブリッド）の上位の候補（最大50件）を並べ直す。新しい候補を探すものではない。
    """
    res = client.search(search_text=query, vector_queries=[_vector_query(vec, field, k)], top=top,
                        select=select, search_fields=search_fields, filter=filter,
                        query_type="semantic", semantic_configuration_name=semantic_config)
    return list(res)


def count(client, *, filter=None, query: str = "*") -> int:
    """絞り込みに合う文書の件数（検索の順位ではなく、数える）。"""
    res = client.search(search_text=query, filter=filter, include_total_count=True, top=0)
    list(res)  # 結果を読み切る（件数は読んだあとに取れる）
    return res.get_count()


def by_method(method: str, client, query: str, vec, field: str, semantic_config: str, **kw) -> list:
    """方式の名前（keyword / vector / hybrid / hybrid_ranker）で選んで検索する。"""
    if method == "keyword":
        return keyword(client, query, **{k: v for k, v in kw.items() if k in ("top", "select", "search_fields", "filter")})
    if method == "vector":
        return vector(client, vec, field, **{k: v for k, v in kw.items() if k in ("k", "top", "select", "filter")})
    if method == "hybrid":
        return hybrid(client, query, vec, field, **kw)
    if method == "hybrid_ranker":
        return hybrid_ranker(client, query, vec, field, semantic_config, **kw)
    raise ValueError(f"方式は keyword / vector / hybrid / hybrid_ranker のどれかにしてください（今は {method!r}）")
