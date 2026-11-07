"""検索の方式と、検索の本文（REST の JSON）を作る部分。通信はしない（標準ライブラリだけ）。

方式は4つ。同じインデックス・同じ質問で、変えるのは次のところだけ（basic/lib/search.py と同じ考え方）。
  keyword    search だけ
  vector     vectorQueries だけ（k=50）
  hybrid     search ＋ vectorQueries
  semantic   hybrid と同じ条件に queryType=semantic を足す（ホテルは、ベクトルの項目がないので search ＋ semantic）
質問に condition があるときは、各方式に絞り込みを足した「<方式>+filter」も測る。

どの方式も、検索の結果は文書の ID の並びにして、同じ文書は、最初に出た順位で1回だけ数える（人事は1文書が多くのチャンクになる）。
"""
from dataclasses import dataclass

METHODS = ("keyword", "vector", "hybrid", "semantic")
FILTER_SUFFIX = "+filter"
NEAREST = 50            # ベクトルの近い候補の数 k（basic/lib/search.py の K_NEAREST と同じ）
FETCH = 50              # 1回の検索で取る件数 top。採点の上位 k 件によらず同じ（k を変えて比べても、取る範囲が同じ）。
                        # 50 は、1回の答えの件数の上限（これを超えると答えが分かれて返る）。人事は、チャンクを文書にまとめると減る


@dataclass(frozen=True)
class Request:
    index: str
    body: dict
    semantic: bool      # セマンティック ランカーを使う検索か（単価が別）


def split_name(name: str):
    """"hybrid+filter" → ("hybrid", True)。"""
    if name.endswith(FILTER_SUFFIX):
        return name[:-len(FILTER_SUFFIX)], True
    return name, False


def needs_vector(dataset, method: str) -> bool:
    return dataset.setups[method].vector_field is not None


def build_request(dataset, method: str, text: str, vector, filter_text) -> Request:
    """方式と質問から、検索の本文を作る。vector は質問の埋め込み（ベクトルを使う方式のとき）。filter_text は None か $filter の式。"""
    setup = dataset.setups[method]
    body = {"top": FETCH, "select": dataset.select}
    if method != "vector":
        body["search"] = text
    if needs_vector(dataset, method):
        if vector is None:
            raise ValueError(f"{method} には質問のベクトルが要ります")
        body["vectorQueries"] = [{"kind": "vector", "vector": vector, "fields": setup.vector_field, "k": max(NEAREST, FETCH)}]
    if method == "semantic":
        body["queryType"] = "semantic"
        body["semanticConfiguration"] = setup.semantic_config
    if filter_text:
        body["filter"] = filter_text
        if "vectorQueries" in body:
            body["vectorFilterMode"] = "preFilter"   # 絞り込んでから近いものを探す（既定と同じ。権限の絞り込みを、はっきりさせる）
    return Request(setup.index, body, method == "semantic")


def documents_in_order(dataset, response) -> list:
    """検索の答えを、文書の ID の並びにする。同じ文書は、最初に出た順位で1回だけ（その文書の最初のチャンクの順位）。"""
    ids = []
    for hit in response.get("value", []) if isinstance(response, dict) else []:
        doc_id = hit.get(dataset.id_field) if isinstance(hit, dict) else None
        if not doc_id and dataset.fallback_id_field and isinstance(hit, dict) and hit.get(dataset.fallback_id_field):
            doc_id = f"(chunk:{hit[dataset.fallback_id_field]})"     # 文書の ID がないチャンク。文書として数え、漏れの点検にも出す
        if doc_id:
            ids.append(str(doc_id))
    return list(dict.fromkeys(ids))
