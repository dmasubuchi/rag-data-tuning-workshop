# %% [markdown]
# # nDCG を1問だけ、手で計算する
#
# 実行：`python ndcg_by_hand.py`
#       `python ndcg_by_hand.py --q "自分の質問"`（questions.json にある質問なら正解がわかる）
#
# 検索の良し悪しを数字にする指標 nDCG（エヌ・ディー・シー・ジー）を、1問だけ計算の途中を見せながら出す。
# 次の `measure_methods.py` は、これを60問×4方式で行い、平均で比べる。
#
# nDCG の考え方
# - 正解の武将には 1 点、それ以外は 0 点。
# - 順位が下がるほど割り引く：k 位の点は 1 / log2(k + 1) 倍（1位 1.00、2位 0.63、3位 0.50、10位 0.29）。
# - 割り引いた点の合計（DCG）を、正解を全部上から並べたときの合計（IDCG）で割る。
#   IDCG は、1位から min(正解の数, 10) 位までの割り引きの和。
# - 正解が1人のとき（用意した60問はすべてそう）：IDCG = 1.00。1位なら 1.0、上位10件にないなら 0。
#   正解が複数のときは、全員が上位にそろって初めて 1.0 になる（最後の 3 で確かめる）。

# %%
import argparse
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:            # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib
from lib import cells, llm, metrics, search, state
from lib.clients import search_client
from lib.config import SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, sengoku_index_name
from lib.data import names_by_id, qid_note, resolve_question
from lib.show import METHOD_LABELS, section, table, title

cells.start()

# ===== 変えてよい値 ==========================================================
QUESTION = None          # None のとき、04 で使った山場の質問。自分の質問は "…" と書く（--q でも指定できる）
METHOD = "hybrid_ranker"  # 計算の途中を見せる方式（keyword / vector / hybrid / hybrid_ranker）
K = 10                   # 上位何件で測るか（nDCG@10、再現率@10）
REBUILD = False
# ============================================================================

parser = argparse.ArgumentParser(description="nDCG を1問だけ手で計算する")
parser.add_argument("--q", default=None, help="質問（省略すると、このファイルの QUESTION）")
args, _ = parser.parse_known_args()

# %% [markdown]
# ## 準備
#
# 03-vector-search までを終えた、武将のインデックスを使う（4方式を使うので、ベクトルとセマンティックの設定が要る）。

# %%
state.ensure("05", rebuild=REBUILD)
sc = search_client(sengoku_index_name())
names = names_by_id()
question, q = resolve_question(args.q or QUESTION, "climax")
relevant = q["answer_ids"] if q else []
title("nDCG を1問だけ手で計算する")
print(f"質問：{question}{qid_note(q)}")
if not relevant:
    print("この質問は questions.json にないので、正解がわかりません。点はすべて 0 になります。")
else:
    print(f"正解：{'、'.join(names.get(i, i) for i in relevant)}")
vec = llm.embed_one(question)
results = {m: [h["id"] for h in search.by_method(m, sc, question, vec, SENGOKU_VECTOR_FIELD, SENGOKU_SEMANTIC, select=["id"])]
           for m in METHOD_LABELS}

# %% [markdown]
# ## 1. 1つの方式で、上位10件の点を1件ずつ出す
#
# 見るところ
# - 「正解」の行だけに 1 点が付き、順位に応じた割り引きを掛けた点になる。
# - DCG は「割り引いた点」の合計。IDCG は正解を全部上から並べたときの DCG（この質問は正解が1人なので 1.00）。
# - nDCG = DCG ÷ IDCG。正解が1人なら、2位で 0.63、3位で 0.50、11位以下で 0。
# - 山場の質問（藤堂高虎）では、ハイブリッド＋ランカーで2位、ハイブリッドだけだと上位10件の外（2026-11-03 の実測で11〜12位）で 0 点になる。
#   `METHOD = "hybrid"` に変えて、全部の行が 0 点になるのを確かめてみる。

# %%
section(f"{METHOD_LABELS[METHOD]}の上位{K}件")
ranked = results[METHOD]
table(["順位", "武将", "正解か", "点", "割り引き", "割り引いた点"],
      metrics.trace_rows(ranked, relevant, K, label=lambda i: names.get(i, i)))
dcg = metrics.dcg(metrics.gains(ranked, relevant, K))
idcg = metrics.ideal_dcg(relevant, K)
print(f"\n  DCG = {dcg:.2f}　IDCG = {idcg:.2f}　nDCG@{K} = {metrics.ndcg_at_k(ranked, relevant, K):.2f}")

# %% [markdown]
# ## 2. 同じ質問を、4つの方式で
#
# 見るところ
# - 04 で並べた「正解の順位」が、そのまま nDCG の数字になる。順位が1つ下がるだけで点がかなり減る。
# - 再現率@10 は「正解のうち、上位10件に入った割合」（何位かは問わない）。1位か は「1位が正解か」。
#   正解が1人のこの質問では、どちらも 0 か 1。次の `measure_methods.py` で60問の平均を出すと、方式の違いが見えてくる。

# %%
section("4つの方式の指標（この1問）")
rows = []
for m, ids in results.items():
    e = metrics.evaluate(ids, relevant, K)
    rows.append([METHOD_LABELS[m], f"{e['rank']} 位" if e["rank"] else "圏外", f"{e['ndcg']:.2f}", f"{e['recall']:.2f}", f"{e['hit1']:.0f}"])
table(["方式", "正解の順位", f"nDCG@{K}", f"再現率@{K}", "1位か"], rows)

# %% [markdown]
# ## 3. 正解が複数のとき（Azure は使わない）
#
# 自分の質問（`measure_methods.py` の `MY_QUESTIONS`）では、正解を2人以上にできる。正解が A と B の2人のとき、
# IDCG = 1.00（1位）＋ 0.63（2位）= 1.63 になる。
#
# 見るところ
# - 1位に A だけが入り、B が上位10件にないと、1位か は 1 なのに nDCG は 0.61、再現率は 0.5。
# - A と B が1位と2位にそろって、初めて nDCG が 1.0 になる。
# - 「正解の順位」は、正解のうち最初に出てきた順位。

# %%
section("正解が A と B の2人のときの例")
EXAMPLES = {
    "A が1位、B は圏外": ["A"] + [f"x{i}" for i in range(9)],
    "A が1位、B が3位": ["A", "x1", "B"] + [f"x{i}" for i in range(2, 9)],
    "A が1位、B が2位": ["A", "B"] + [f"x{i}" for i in range(2, 10)],
    "B が5位だけ": ["x1", "x2", "x3", "x4", "B"] + [f"x{i}" for i in range(5, 10)],
}
rows = []
for name, ranked_ids in EXAMPLES.items():
    e = metrics.evaluate(ranked_ids, ["A", "B"], K)
    d = metrics.dcg(metrics.gains(ranked_ids, ["A", "B"], K))
    rows.append([name, f"{d:.2f}", f"{metrics.ideal_dcg(['A', 'B'], K):.2f}", f"{e['ndcg']:.2f}", f"{e['recall']:.2f}", f"{e['hit1']:.0f}"])
table(["並び", "DCG", "IDCG", f"nDCG@{K}", f"再現率@{K}", "1位か"], rows)
print("\n次は：python measure_methods.py（60問×4方式の平均で比べる）")
