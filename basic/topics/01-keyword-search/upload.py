# %% [markdown]
# # 武将をインデックスに登録する
#
# `bushou.json` の武将を、1人＝1件の文書として登録します。
# インデックスにある項目だけを送ります（id、name、aliases、battles、profile、clan、province、born、died）。
#
# 実行：`python upload.py`（先に `create_index.py` でインデックスを作っておく）

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, sengoku
from lib.clients import require_index, search_client
from lib.config import require_admin_key, sengoku_index_name
from lib.data import load_bushou
from lib.indexing import upload, wait_for_count
from lib.show import section, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
BATCH_SIZE = sengoku.BATCH_SIZE     # 1回に送る件数
# ============================================================================

# %% [markdown]
# ## 1. 登録する文書を作る
# JSON の1人分から、インデックスにある項目だけを取り出して、登録用の辞書にします（`lib/sengoku.py` の `make_documents()`）。
# **見るところ**：文書の件数（武将の人数と同じ）と、1件目の中身。

# %%
require_admin_key()      # メンバー用のキー（検索だけ）なら、ここで止まる
name = sengoku_index_name()
title(f"武将を登録します：{name}")
require_index(name, "先に python create_index.py を実行して、インデックスを作ってください。")
client = search_client(name)

people = load_bushou()
docs = sengoku.make_documents(people)
print(f"登録する文書：{len(docs)} 件（武将 {len(people)} 人）")
section("登録する文書の例（1件目）")
for k, v in docs[0].items():
    text = "、".join(map(str, v)) if isinstance(v, list) else v
    print(f"  {k:<9}: {str(text)[:70]}{'…' if len(str(text)) > 70 else ''}")

# %% [markdown]
# ## 2. 登録する
# `BATCH_SIZE` 件ずつ送ります。反映に数秒かかることがあるので、文書の数が合うまで待って数えます。
# **見るところ**：インデックスの文書数が、登録した件数と合うこと。

# %%
section("登録")
upload(client, docs, mode="upload", batch_size=BATCH_SIZE)
count = wait_for_count(client, len(docs))
print(f"\nインデックスの文書数：{count} 件")
if count != len(docs):
    print(f"登録した {len(docs)} 件と合いません。数秒おいて、もう一度 python upload.py を実行してみてください。")
else:
    print("登録できました。次は：python keyword_search.py（キーワード検索）")
