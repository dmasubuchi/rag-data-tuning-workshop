# %% [markdown]
# # ハイブリッド検索に、セマンティックランカーを付けて実行する
#
# `hybrid_search.py` と同じ条件（キーワード ＋ ベクトル、k=50）に、`query_type="semantic"` を足して実行します。
# ランカーは、前段（ハイブリッド）の上位の候補（最大 50 件）を、質問と本文の意味を読んで並べ直すものです。
# 新しい候補を探すものではないので、前段の 50 件に正解がなければ、ランカーでも拾えません。
#
# **注意**：セマンティックランカーの無料枠には月ごとの上限があります（料金ページ https://azure.microsoft.com/ja-jp/pricing/details/search/）。必要なときだけ実行してください（この操作は 1 回使います）。
#
# 実行：`python ranker.py`
# 自分の質問：`python ranker.py --q "自分の質問"`
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
from lib import cells, llm, state
from lib.clients import search_client
from lib.config import SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, sengoku_index_name
from lib.data import answer_rank, names_by_id, qid_note, resolve_question
from lib.search import hybrid
from lib.show import MEASURED_TOP, print_bushou_hits, rank_label, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None     # None のとき、questions.json の山場の質問。自分の質問は "…" と書く（--q でも指定できる）
TOP = 5             # 画面に出す件数
K = 50              # ベクトル側の候補数（ランカーが並べ直す対象は、この前段の上位 50 件まで）
REBUILD = False     # True にすると、武将のインデックスを、03 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="ハイブリッド検索 ＋ セマンティックランカー")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 質問を埋め込み、ランカーなしのハイブリッドの順位を取っておく
# 比べるために、ランカーなしのハイブリッドの順位も取ります（ランカーの無料枠は使いません）。

# %%
question, q = resolve_question(QUESTION, "climax")

state.ensure("04", rebuild=REBUILD)      # 武将にベクトルとセマンティックの設定が入っているか
client = search_client(sengoku_index_name())

title("ハイブリッド検索 ＋ セマンティックランカー")
print(f"質問：{question}{qid_note(q)}")
vec = llm.embed_one(question)

before = hybrid(client, question, vec, SENGOKU_VECTOR_FIELD, k=K, top=MEASURED_TOP)
before_rank = {h["id"]: r for r, h in enumerate(before, start=1)}

# %% [markdown]
# ## 2. ランカーを付ける
# ハイブリッドと同じ呼び出しに、`query_type="semantic"` と設定の名前を足すだけです。
# **見るところ**：ランカーなしのハイブリッドと、ランカーありの正解の順位。「ランカー」の列は、ランカーが質問と本文の意味を読んで付けた点です（0〜4 の目安）。

# %%
from azure.search.documents.models import VectorizedQuery

hits = list(client.search(
    search_text=question,
    vector_queries=[VectorizedQuery(vector=vec, k_nearest_neighbors=K, fields=SENGOKU_VECTOR_FIELD)],
    top=MEASURED_TOP,
    query_type="semantic",
    semantic_configuration_name=SENGOKU_SEMANTIC,
))

answer_ids = q["answer_ids"] if q else None
extra = {h["id"]: ("ランカーなしのハイブリッドでは " + rank_label(before_rank.get(h["id"]), len(before))) for h in hits[:TOP]}
print(f"\n上位 {TOP} 人（ランカー後）\n")
print_bushou_hits(hits, limit=TOP, answer_ids=answer_ids, extra=extra)
if answer_ids:
    names = names_by_id()
    after = answer_rank(hits, answer_ids)
    prev = answer_rank(before, answer_ids)
    print(f"\n正解の武将：{'、'.join(names.get(i, i) for i in answer_ids)}")
    print(f"ランカーなしのハイブリッド：{rank_label(prev, len(before))}  →  ランカーあり：{rank_label(after, len(hits))}")
    if prev is None:
        print("正解が前段の上位 50 件に入っていないため、ランカーは並べ直す対象にできません。")
print("\n「ランカー」の列は、ランカーが質問と本文の意味を読んで付けた点です（0〜4 の目安）。")
print("次は：python compare_methods.py（4つの方式で、正解の順位を並べる）")
