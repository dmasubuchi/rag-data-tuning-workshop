"""検索結果から、LLM に渡すプロンプトを組む部品（06-answer-from-results のスクリプトが使う、武将の RAG の最小の形）。

  retrieve()      方式 method で武将を検索して、上位 top_n 件を返す
  build_prompt()  検索で見つけた武将の文を並べ、そのあとに質問を置く
  can_reuse()     generate_answer.py が保存した答えを、compare_no_search.py が使ってよいか
スクリプトはセル形式で、上から順に実行するもの。読み込んだだけで動き出さないように、関数はここにまとめてある。
"""
from . import llm, search
from .clients import search_client
from .config import SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, sengoku_index_name

METHOD = "hybrid_ranker"    # 検索の方式：keyword / vector / hybrid / hybrid_ranker
TOP_N = 3                   # プロンプトに入れる件数


def retrieve(question: str, method: str = METHOD, top_n: int = TOP_N) -> list:
    """方式 method で検索し、上位 top_n 件を返す。"""
    client = search_client(sengoku_index_name())
    vec = llm.embed_one(question) if method != "keyword" else None
    hits = search.by_method(method, client, question, vec, SENGOKU_VECTOR_FIELD, SENGOKU_SEMANTIC, top=top_n)
    return hits[:top_n]


def build_prompt(question: str, hits: list) -> str:
    """検索で見つけた武将の文を並べ、そのあとに質問を置く。"""
    parts = ["次の資料を参考にして、質問に答えてください。", ""]
    for i, h in enumerate(hits, start=1):
        parts.append(f"【資料{i}】{h['name']}")
        parts.append(h["profile"])
        parts.append("")
    parts.append(f"【質問】{question}")
    return "\n".join(parts)


def can_reuse(saved, question: str, method: str = METHOD, top_n: int = TOP_N) -> bool:
    """generate_answer.py が保存した答えを使ってよいか。質問に加えて、検索の方式・件数も同じときだけ。"""
    if not saved or saved.get("question") != question:
        return False
    s = saved.get("settings") or {}
    return s.get("method") == method and s.get("top_n") == top_n
