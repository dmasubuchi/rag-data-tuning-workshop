# %% [markdown]
# # 同じ質問を、ベクトル検索で実行する
#
# 質問を埋め込み（数の並びにして）、意味が近い武将を探します。上位 5 人と、正解の武将の順位を表示します。
# 質問の埋め込みで Azure OpenAI を 1 回呼びます。
#
# 実行：`python vector_search.py`
# 自分の言い換え：`python vector_search.py --q "自分で考えた言い換え"`
#
# 前提：`embed.py` で、武将にベクトルが入っていること。

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
QUESTION = None     # None のとき、01-keyword-search の search_paraphrase.py と同じ質問（言い換えの質問）。自分の質問は "…" と書く
TOP = 5             # 画面に出す件数
K = 50              # ベクトル側の候補数（近い順に何件を候補にするか）
REBUILD = False     # True にすると、武将のインデックスを、03 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="ベクトル検索")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 質問を埋め込む
# 本文と同じモデルで、質問を数の並びにします。
# **見るところ**：質問が、長さ 1536 の数の並びになること。

# %%
question, q = resolve_question(QUESTION, "paraphrase")

state.ensure("04", rebuild=REBUILD)      # 武将にベクトルが入っているか（この topic の embed.py が終わっているか）
client = search_client(sengoku_index_name())

title("ベクトル検索")
print(f"質問：{question}{qid_note(q)}")

vec = llm.embed_one(question)
print(f"質問を埋め込みました（長さ {len(vec)} の数の並び。先頭の3つ：{', '.join(f'{x:.4f}' for x in vec[:3])}）")

# %% [markdown]
# ## 2. 近い武将を探す
# `search_text` は渡さず、ベクトルのクエリだけで探します。
# **見るところ**：上位の武将と、正解の武将の印（◀ 正解）。スコアは、キーワード検索とは別の物差し（近さ）です。

# %%
from azure.search.documents.models import VectorizedQuery

hits = list(client.search(
    search_text=None,
    vector_queries=[VectorizedQuery(vector=vec, k_nearest_neighbors=K, fields=SENGOKU_VECTOR_FIELD)],
    top=MEASURED_TOP,
))

answer_ids = q["answer_ids"] if q else None
print(f"\n上位 {TOP} 人\n")
print_bushou_hits(hits, limit=TOP, answer_ids=answer_ids)

# %% [markdown]
# ## 3. 正解の順位
# **見るところ**：同じ質問で、正解の武将の順位がキーワード検索と比べてどう変わるか。

# %%
if answer_ids:
    names = names_by_id()
    rank = answer_rank(hits, answer_ids)
    print(f"\n正解の武将：{'、'.join(names.get(i, i) for i in answer_ids)}")
    print(f"ベクトル検索での順位：{rank_label(rank, len(hits))}")
    if rank is not None and rank <= 3:
        print("→ 言葉は違っても、意味が近い武将を見つけられました。")
    else:
        print("→ この質問では、ベクトル検索でも正解が上位に来ませんでした。ベクトル検索は万能ではありません。")
else:
    print("\nこの質問は questions.json にないので、正解の順位は出しません。上位の武将を自分の目で確かめてください。")
print("\nスコアは、キーワード検索とは別の物差し（近さ）です。値の大きさを、方式のあいだで比べないでください。")
print("次は 04-hybrid-ranker：python ../04-hybrid-ranker/hybrid_search.py")
