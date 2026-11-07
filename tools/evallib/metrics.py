"""検索の良し悪しの数字（文書の順位から計算する。通信しない。標準ライブラリだけ）。

ndcg_at_k・recall_at_k・hit_at_1・first_rank は、basic/lib/metrics.py（05-measure-search）と同じ式。
（basic は Notebook の教材なので、ここに写して持つ。同じ値になることは tests/test_eval_search.py が確かめる。）

  ranked    検索結果の文書の ID を、上から順に並べた一覧（同じ文書は1回だけ）
  relevant  正解の文書の ID の並び

答えの文書が1件もない質問（権限で見えないはずの質問）は、再現率や nDCG が決まらないので、score() は None を返し、
平均（summarize）から外す。その質問は、見えてはいけない文書が出た数（漏れ）で別に数える。
"""
import math


def discount(rank: int) -> float:
    return 1.0 / math.log2(rank + 1)


def gains(ranked, relevant, k: int) -> list:
    rel = set(relevant or [])
    return [1 if doc_id in rel else 0 for doc_id in list(ranked)[:k]]


def dcg(gain_list) -> float:
    return sum(g * discount(i) for i, g in enumerate(gain_list, start=1))


def ideal_dcg(relevant, k: int) -> float:
    return dcg([1] * min(len(set(relevant or [])), k))


def ndcg_at_k(ranked, relevant, k: int = 10) -> float:
    ideal = ideal_dcg(relevant, k)
    return dcg(gains(ranked, relevant, k)) / ideal if ideal else 0.0


def recall_at_k(ranked, relevant, k: int = 10) -> float:
    rel = set(relevant or [])
    if not rel:
        return 0.0
    return len(rel & set(list(ranked)[:k])) / len(rel)


def hit_at_1(ranked, relevant) -> float:
    ranked = list(ranked)
    return 1.0 if ranked and ranked[0] in set(relevant or []) else 0.0


def first_rank(ranked, relevant):
    """正解が最初に出てくる順位（1 始まり）。なければ None。"""
    rel = set(relevant or [])
    for i, doc_id in enumerate(ranked, start=1):
        if doc_id in rel:
            return i
    return None


def score(ranked, relevant, k: int) -> dict:
    """1問・1方式の点。正解がない質問は、すべて None（平均に入れない）。"""
    if not set(relevant or []):
        return {"ndcg": None, "recall": None, "hit1": None, "first_rank": None}
    return {"ndcg": ndcg_at_k(ranked, relevant, k), "recall": recall_at_k(ranked, relevant, k),
            "hit1": hit_at_1(ranked, relevant), "first_rank": first_rank(ranked, relevant)}


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def summarize(questions, method) -> dict:
    """結果の質問の並び（questions）から、1つの方式の平均を出す。

    questions   結果の JSON の "questions"（各質問の results に、方式ごとの点と leaks が入っている）
    scored      点がついた質問の数（正解のある質問）。nDCG・再現率・1位の割合は、この質問だけの平均
    leak_questions  漏れが1件以上あった質問の数、leaks  漏れた文書の合計（正解のない質問も含めて、全部の質問で数える）
    leakable    漏れうる質問の数（質問の "leakable" が真。聞く人が採用担当でない、または hidden_ids がある質問）。
                漏れの割合は、leak_questions ÷ leakable（全部の質問で割らない）。"leakable" のない古い結果は、全部を漏れうる質問に数える
    """
    measured = [q for q in questions if method in q.get("results", {})]
    results = [q["results"][method] for q in measured]
    scored = [r for r in results if r.get("ndcg") is not None]
    return {"questions": len(results), "scored": len(scored),
            "ndcg": mean(r["ndcg"] for r in scored), "recall": mean(r["recall"] for r in scored),
            "hit1": mean(r["hit1"] for r in scored),
            "leak_questions": sum(1 for r in results if r.get("leaks", 0) > 0),
            "leaks": sum(r.get("leaks", 0) for r in results),
            "leakable": sum(1 for q in measured if q.get("leakable", True))}


def leak_rate(summary):
    """漏れた質問の割合（漏れうる質問に対して）。漏れうる質問がなければ None。"""
    return summary["leak_questions"] / summary["leakable"] if summary["leakable"] else None
