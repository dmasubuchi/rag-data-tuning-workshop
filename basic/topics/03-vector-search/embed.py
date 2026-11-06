# %% [markdown]
# # ベクトルの項目を足し、武将の文を埋め込んで登録する
#
# 1. インデックスにベクトルの項目 `profile_vector` を足す（ついでに、04-hybrid-ranker で使うセマンティックの設定も足す）
# 2. 武将ごとに「名前。本文」を埋め込む（数の並びに直す）
# 3. 登録済みの文書に、ベクトルだけを足す（文字の項目はそのまま）
#
# 実行：`python embed.py`（Azure OpenAI で埋め込む。いつもはこちら）
# 同梱の埋め込み済みファイルを使う（時間が足りないとき）：`python embed.py --use-file`（Notebook では先頭の `USE_FILE = True`）
# `--use-file` のとき、モデル名か次元が合わないファイルは使わず、その場で埋め込みます。
#
# 前提：01-keyword-search が終わっていること（武将のインデックスと、登録した武将）。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, sengoku, state
from lib.clients import index_client, search_client
from lib.config import SENGOKU_EMBEDDINGS, SENGOKU_VECTOR_FIELD, get_settings, require_admin_key, sengoku_index_name
from lib.data import embedding_text, load_bushou
from lib.indexing import upload, wait_for_count
from lib.show import section, step, title
from lib.vectorstore import get_vectors

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
BATCH_SIZE = sengoku.BATCH_SIZE     # 1回に送る件数
USE_FILE = False                    # True にすると、同梱の埋め込み済みファイルを使う（なければその場で埋め込む）
REBUILD = False                     # True にすると、武将のインデックスを、01 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="ベクトルの項目を足して、埋め込んで登録する")
parser.add_argument("--use-file", action="store_true", help="同梱の埋め込み済みファイルを使う")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
USE_FILE = USE_FILE or args.use_file
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. インデックスにベクトルの項目を足す
# ベクトルの項目は、数の並び（`Collection(Edm.Single)`）で、次元は埋め込みモデルに合わせます。
# 近いものを探す方法（HNSW）と、近さの測り方（コサイン類似度）も設定します。定義は `lib/sengoku.py` の `add_vector_fields()` にあります。
# **見るところ**：埋め込みモデルのデプロイと次元。ベクトルの項目 `profile_vector` を足したか、すでにあったか。

# %%
require_admin_key()      # メンバー用のキー（検索だけ）なら、ここで止まる
s = get_settings()
state.ensure("03", rebuild=REBUILD)      # 01-keyword-search が終わっているか（武将のインデックスと、登録した武将）
name = sengoku_index_name()

title(f"ベクトルの項目を足して登録します：{name}")
print(f"埋め込みモデルのデプロイ：{s.embedding_deployment}（次元 {s.dimensions}）")

step(1, 3, f"インデックスにベクトルの項目 {SENGOKU_VECTOR_FIELD} を足す")
changed = sengoku.add_vector_fields(index_client(), name, s.dimensions)
print("  足しました。" if changed else "  すでにあります（何もしません）。")

# %% [markdown]
# ## 2. 武将の文を埋め込む準備
# 武将ごとに「名前。本文」の文を作ります。
# **見るところ**：埋め込む文の例と、件数。

# %%
step(2, 3, "武将の文を埋め込む（名前。本文 → 数の並び）")
people = load_bushou()
texts = [embedding_text(p) for p in people]
print(f"  埋め込む文の例：{texts[0][:50]}…")
print(f"  件数：{len(people)} 件")

# %% [markdown]
# ## 3. 埋め込む
# 同梱の埋め込み済みファイルがあって使えるときは、そこから探し、なかった分だけ Azure OpenAI で埋め込みます。
# **見るところ**：埋め込みの元（ファイルから何件、Azure OpenAI で何件）。

# %%
step(3, 3, "登録済みの文書に、ベクトルを足す")
vectors = get_vectors(texts, SENGOKU_EMBEDDINGS, USE_FILE, label="武将")

# %% [markdown]
# ## 4. 登録済みの文書に、ベクトルだけを足す
# `mode="merge"` で、同じ id の文書に、ベクトルの項目だけを足します（文字の項目はそのまま）。
# 登録のあと、ベクトルが検索に出てくるまで待ちます（文書の件数が合っていても、ベクトルの反映は少し遅れることがあります。30秒で揃わなければ止まります）。
# **見るところ**：インデックスの文書数（ベクトルを足しても、武将の人数のまま）。

# %%
docs = [{"id": p["id"], SENGOKU_VECTOR_FIELD: v} for p, v in zip(people, vectors)]
search = search_client(name)
upload(search, docs, mode="merge", batch_size=BATCH_SIZE)
count = wait_for_count(search, len(docs))
sengoku.wait_for_vectors(search, [d["id"] for d in docs])

section("結果")
print(f"  インデックスの文書数：{count} 件（ベクトル {len(people)} 件を足しました）")
print(f"  ベクトルの長さ：{s.dimensions}")
print("\n次は：python vector_search.py（同じ質問をベクトル検索で実行する）")
