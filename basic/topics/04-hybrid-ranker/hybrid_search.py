# %% [markdown]
# # ハイブリッド検索を実行する
#
# 同じ質問を、キーワードとベクトルの両方で探して、順位を1つにまとめます（AI Search が RRF で行います）。
# `search_text`（キーワード側）と `vector_queries`（ベクトル側）を同じ呼び出しに渡すだけで、ハイブリッドになります。
#
# 実行：`python hybrid_search.py`
# 自分の質問：`python hybrid_search.py --q "自分の質問"`
#
# 前提：03-vector-search が終わっていること（武将にベクトルが入っていること）。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, llm, state
from lib.clients import search_client
from lib.config import SENGOKU_VECTOR_FIELD, sengoku_index_name
from lib.data import answer_rank, names_by_id, qid_note, resolve_question
from lib.show import MEASURED_TOP, print_bushou_hits, rank_label, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None     # None のとき、questions.json の山場の質問。自分の質問は "…" と書く（--q でも指定できる）
TOP = 5             # 画面に出す件数
K = 50              # ベクトル側の候補数
REBUILD = False     # True にすると、武将のインデックスを、03 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="ハイブリッド検索")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 質問を埋め込む

# %%
question, q = resolve_question(QUESTION, "climax")

state.ensure("04", rebuild=REBUILD)      # 武将にベクトルが入っているか（03-vector-search の embed.py が終わっているか）
client = search_client(sengoku_index_name())

title("ハイブリッド検索（キーワード ＋ ベクトル）")
print(f"質問：{question}{qid_note(q)}")
vec = llm.embed_one(question)

# %% [markdown]
# ## 2. ハイブリッド検索する
# キーワード側（`search_text`）とベクトル側（`vector_queries`）を、1回の呼び出しに両方渡します。
# **見るところ**：上位の武将と、正解の武将の順位。スコアは RRF（順位の逆数の合計）で決まる値で、キーワードやベクトルのスコアとは別物です。

# %%
from azure.search.documents.models import VectorizedQuery

hits = list(client.search(
    search_text=question,
    vector_queries=[VectorizedQuery(vector=vec, k_nearest_neighbors=K, fields=SENGOKU_VECTOR_FIELD)],
    top=MEASURED_TOP,
))

answer_ids = q["answer_ids"] if q else None
print(f"\n上位 {TOP} 人\n")
print_bushou_hits(hits, limit=TOP, answer_ids=answer_ids)
if answer_ids:
    names = names_by_id()
    rank = answer_rank(hits, answer_ids)
    print(f"\n正解の武将：{'、'.join(names.get(i, i) for i in answer_ids)}")
    print(f"ハイブリッド検索での順位：{rank_label(rank, len(hits))}")
print("\nスコアは RRF（順位の逆数の合計）で決まる値で、キーワードやベクトルのスコアとは別物です。")
print("次は：python rrf.py（この順位がどう決まったかを、計算の途中から追う）")
