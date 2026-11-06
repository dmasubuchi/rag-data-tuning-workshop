"""検索の良し悪しを数字で測る道具（05-measure-search）。通信はしない。

どれも「検索結果の id を上から順に並べた一覧（ranked）」と「正解の id の集合（relevant）」から計算する。

  ndcg_at_k(ranked, relevant, 10)    上位10件の nDCG。正解が上にあるほど点が高い（0〜1）
  recall_at_k(ranked, relevant, 10)  再現率。正解のうち、上位10件に入った割合
  hit_at_1(ranked, relevant)         1位が正解（のどれか）なら 1、違えば 0

nDCG の考え方
  ・正解の文書には 1 点（gain）、それ以外は 0 点。
  ・順位が下がるほど割り引く：k 位の点は 1 / log2(k + 1) 倍（1位 1.00、2位 0.63、3位 0.50、10位 0.29）。
  ・割り引いた点の合計が DCG。正解を理想の順（全部上位）に並べたときの DCG（IDCG）で割ったものが nDCG。
  ・IDCG は、1位から min(正解の数, k) 位までの割り引きの和。
      正解が1つ：IDCG = 1.00。1位なら nDCG 1.0、2位なら 0.63、k 位より下なら 0。再現率は 1 か 0。
      正解が2つ：IDCG = 1.00 + 0.63 = 1.63。1位と2位にそろって 1.0。1位に1つだけなら 1.00 / 1.63 = 0.61、再現率 0.5。
"""
import math


def discount(rank: int) -> float:
    """k 位の割り引き：1 / log2(k + 1)"""
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


def evaluate(ranked, relevant, k: int = 10) -> dict:
    """1問分の指標。{"ndcg": …, "recall": …, "hit1": …, "rank": …}"""
    return {
        "ndcg": ndcg_at_k(ranked, relevant, k),
        "recall": recall_at_k(ranked, relevant, k),
        "hit1": hit_at_1(ranked, relevant),
        "rank": first_rank(ranked, relevant),
    }


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def average(per_question: list) -> dict:
    """1問ずつの evaluate() の結果の一覧から、平均を出す。"""
    return {key: mean(r[key] for r in per_question) for key in ("ndcg", "recall", "hit1")}


def trace_rows(ranked, relevant, k: int = 10, label=None) -> list:
    """nDCG の計算の途中（上位 k 件の1件ずつ）。[順位, 名前, 正解か, 点, 割り引き, 割り引いた点]"""
    label = label or (lambda doc_id: doc_id)
    rel = set(relevant or [])
    rows = []
    for i, doc_id in enumerate(list(ranked)[:k], start=1):
        g = 1 if doc_id in rel else 0
        rows.append([i, label(doc_id), "正解" if g else "", g, f"{discount(i):.2f}", f"{g * discount(i):.2f}"])
    return rows
