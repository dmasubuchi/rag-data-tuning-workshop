# %% [markdown]
# # キーワード検索をする
#
# 検索語で武将を検索し、スコアの高い順に上位の数人を表示します。
# キーワード検索は、検索語を分かち書きして、同じ語を持つ文書を、珍しい語ほど重く見て（BM25）並べます。
#
# 実行：`python keyword_search.py`
# 検索語を一時的に変える：`python keyword_search.py --q "姉川"`
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
from lib.show import print_bushou_hits, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUERY = "桶狭間"          # 検索語（合戦名、地名、年号など）。--q があれば、そちらを使う
TOP = 5                   # 画面に出す件数
SEARCH_FIELDS = None      # 検索する項目。None は全部（name、aliases、battles、profile）。
                          # 例：["profile"] にすると、本文だけを検索する（発展）
REBUILD = False           # True にすると、武将のインデックスを、01 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="キーワード検索")
parser.add_argument("--q", default=None, help="検索語（省略すると、QUERY）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUERY = args.q or QUERY
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 準備：インデックスを確かめる
# 武将のインデックスと、登録した武将があるか確かめます（足りなければ、どうすればよいかを出して止まります）。

# %%
state.ensure("03", rebuild=REBUILD)      # 武将のインデックスと、登録した武将があるか
name = sengoku_index_name()
client = search_client(name)

title(f"キーワード検索：「{QUERY}」")
print(f"インデックス：{name}")
print(f"検索する項目：{', '.join(SEARCH_FIELDS) if SEARCH_FIELDS else 'すべて（name、aliases、battles、profile）'}")

# %% [markdown]
# ## 2. 検索する
# `search_text` に検索語を渡すと、AI Search が分かち書きして BM25 で並べます。
# **見るところ**：一致した武将の人数と、スコアの高い順。珍しい語を含むほどスコアが高くなります。

# %%
results = client.search(search_text=QUERY, search_fields=SEARCH_FIELDS, top=TOP, include_total_count=True)
hits = list(results)
total = results.get_count()

print(f"\n一致した武将：{total} 人（上位 {min(TOP, len(hits))} 人を表示）\n")
print_bushou_hits(hits, limit=TOP)

if total == 0:
    print("\n1人も一致しませんでした。検索語の言い方を変えてみてください。")
else:
    print("\nスコアは、この検索語の中で珍しい語を含むほど高くなります。")
print("\n次は：python analyze.py（質問が、どんな単語に分かれるかを見る）")
