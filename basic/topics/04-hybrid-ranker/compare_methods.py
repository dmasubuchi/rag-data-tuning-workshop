# %% [markdown]
# # 同じ質問の正解の順位を、4つの方式で並べる（このトピックの山場）
#
# 同じインデックス・同じ質問で、変えるのは検索の方式だけにして、正解の武将が何位に来るかを並べます。
# キーワード／ベクトル／ハイブリッド／ハイブリッド＋ランカー。順位は上位 50 件まで測ります。
# セマンティックランカーを 1 回使います。
#
# 実行：`python compare_methods.py`
# 自分の質問：`python compare_methods.py --q "自分の質問"`
#
# 前提：03-vector-search が終わっていること（武将にベクトルとセマンティックの設定が入っていること）。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, llm, search, state
from lib.clients import search_client
from lib.config import SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, sengoku_index_name
from lib.data import answer_rank, names_by_id, qid_note, resolve_question
from lib.show import METHOD_LABELS, rank_label, section, table, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None     # None のとき、questions.json の山場の質問。自分の質問は "…" と書く（--q でも指定できる）
SHOW_TOP = 3        # 各方式の上位を何人まで並べるか
K = 50              # ベクトル側の候補数
REBUILD = False     # True にすると、武将のインデックスを、03 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="4つの方式で、正解の順位を並べる")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 質問と正解
# **見るところ**：質問と、正解の武将。

# %%
question, q = resolve_question(QUESTION, "climax")

state.ensure("04", rebuild=REBUILD)      # 武将にベクトルとセマンティックの設定が入っているか
client = search_client(sengoku_index_name())
names = names_by_id()

title("4つの方式で、正解の順位を並べる")
print(f"質問：{question}{qid_note(q)}")
answer_ids = q["answer_ids"] if q else []
if answer_ids:
    print(f"正解の武将：{'、'.join(names.get(i, i) for i in answer_ids)}")
else:
    print("この質問は questions.json にないので、正解の順位は出せません（上位の武将だけ並べます）。")
vec = llm.embed_one(question)

# %% [markdown]
# ## 2. 同じ質問を、4つの方式で検索する
# 変えるのは検索の方式だけです（`lib/search.py` の `keyword`・`vector`・`hybrid`・`hybrid_ranker`）。

# %%
results = {
    "keyword": search.keyword(client, question),
    "vector": search.vector(client, vec, SENGOKU_VECTOR_FIELD, k=K),
    "hybrid": search.hybrid(client, question, vec, SENGOKU_VECTOR_FIELD, k=K),
    "hybrid_ranker": search.hybrid_ranker(client, question, vec, SENGOKU_VECTOR_FIELD, SENGOKU_SEMANTIC, k=K),
}

# %% [markdown]
# ## 3. 正解の順位を並べる
# **見るところ**：4つの方式の表。「方式を変えれば必ず良くなる」わけではありません。

# %%
rows = []
for method, hits in results.items():
    rank = answer_rank(hits, answer_ids) if answer_ids else None
    label = rank_label(rank, len(hits)) if answer_ids else "-"
    rows.append([METHOD_LABELS[method], label, "、".join(names.get(h["id"], h["id"]) for h in hits[:SHOW_TOP])])

section("正解の順位")
table(["方式", "正解の順位", f"上位{SHOW_TOP}人"], rows)

print("\n注意：これは、この1問の結果です。方式の優劣は、質問によって変わります。")
print("「方式を変えれば必ず順に良くなる」わけではありません（ハイブリッドで順位が下がる質問もあります）。")
print("順位の表し方：圏外＝上位50件にない／未ヒット＝検索結果が0件。")
print("次は 06-answer-from-results：python ../06-answer-from-results/build_prompt.py（上位3件でプロンプトを組む）")
