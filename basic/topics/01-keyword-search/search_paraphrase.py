# %% [markdown]
# # 言い換えの質問を、キーワード検索で実行する（正解が外れるのを確かめる）
#
# 質問をそのままキーワード検索にかけ、上位 5 人と、正解の武将の順位を表示します。
# 質問の言い方が本文と違うと、同じ単語が少なく、正解が上位に来ません。
#
# 実行：`python search_paraphrase.py`
# 自分の言い換え：`python search_paraphrase.py --q "自分で考えた言い換え"`
#
# 前提：先に `create_index.py` と `upload.py` を実行して、武将を登録してあること。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, state
from lib.clients import search_client
from lib.config import sengoku_index_name
from lib.data import answer_rank, names_by_id, qid_note, resolve_question
from lib.show import MEASURED_TOP, print_bushou_hits, rank_label, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None     # None のとき、data/sengoku/selection.json の言い換えの質問。自分の質問は "…" と書く（--q でも指定できる）
TOP = 5             # 画面に出す件数
REBUILD = False     # True にすると、武将のインデックスを、01 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="言い換えの質問をキーワード検索で実行する")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 質問をそのままキーワード検索にかける
# 順位を測るため、上位 50 件まで取ります。
# **見るところ**：上位の武将と、正解の武将の印（◀ 正解）。

# %%
question, q = resolve_question(QUESTION, "paraphrase")

state.ensure("03", rebuild=REBUILD)      # 武将のインデックスと、登録した武将があるか
client = search_client(sengoku_index_name())

title("キーワード検索（言い換えの質問）")
print(f"質問：{question}{qid_note(q)}")

hits = list(client.search(search_text=question, top=MEASURED_TOP))
answer_ids = q["answer_ids"] if q else None
print(f"\n上位 {TOP} 人（順位は上位 {MEASURED_TOP} 人まで取得して測ります。取得できた人数：{len(hits)}）\n")
print_bushou_hits(hits, limit=TOP, answer_ids=answer_ids)

# %% [markdown]
# ## 2. 正解の順位
# **見るところ**：正解の武将の順位。言い方が違うと、上位に来ません。

# %%
if answer_ids:
    names = names_by_id()
    rank = answer_rank(hits, answer_ids)
    print(f"\n正解の武将：{'、'.join(names.get(i, i) for i in answer_ids)}")
    print(f"キーワード検索での順位：{rank_label(rank, len(hits))}")
    if rank is None or rank > 3:
        print("→ 質問と本文で使う言葉が違うため、キーワード検索では正解が上位に来ませんでした。")
    else:
        print("→ この質問では、キーワード検索でも正解が上位に来ました。")
else:
    print("\nこの質問は questions.json にないので、正解の順位は出しません。上位の武将を自分の目で確かめてください。")
print("\n次は 03-vector-search：python ../03-vector-search/embed.py（ベクトルの項目を足して、埋め込んで登録する）")
