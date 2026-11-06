# %% [markdown]
# # インデックス（検索の入れ物）を作る
#
# AI Search に、武将用のインデックス `sengoku` を作ります。文字の項目だけです。
# 検索する項目（name、aliases、battles、profile）には、日本語のアナライザー `ja.microsoft` を使います。
# ベクトルの項目は、03-vector-search で足します。
#
# 実行：`python create_index.py`
# すでにあるインデックスを消して作り直す：`python create_index.py --recreate`（Notebook では先頭の `RECREATE = True`）

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
from lib.clients import index_client, index_exists
from lib.config import require_admin_key, sengoku_index_name
from lib.show import section, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
ANALYZER = sengoku.ANALYZER   # 日本語の分かち書きをするアナライザー（検索する項目に使う。ja.microsoft）
RECREATE = False              # True にすると、すでにあるインデックスを消して作り直す（中の文書も消える）
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="武将のインデックスを作る")
parser.add_argument("--recreate", action="store_true", help="すでにあるインデックスを消して作り直す")
args, _ = parser.parse_known_args()
RECREATE = RECREATE or args.recreate

# %% [markdown]
# ## 1. インデックスの定義を作る
# 項目ごとに、何に使うかを決めます。
# - **キー**：`id`。文書を1件ずつ区別する
# - **検索する**（searchable）：name、aliases、battles、profile。日本語の文章なので `ja.microsoft` で単語に分けます
# - **絞り込む**（filterable）：clan、province、born、died など。検索はしないので `searchable=False` と明示します
#   （文字列の項目は、書かないと「検索する」になります。clan に「織田家」があると「織田家の家臣」で当たってしまいます）
#
# 定義は `lib/sengoku.py` の `build_index()` にあります。
# **見るところ**：項目ごとの型と、キー・検索する・絞り込みの区別。

# %%
require_admin_key()      # メンバー用のキー（検索だけ）なら、ここで止まる
name = sengoku_index_name()
client = index_client()
title(f"インデックスを作ります：{name}")

index = sengoku.build_index(name, ANALYZER)


def plain(value) -> str:
    """列挙型の値を、REST API で使う文字列（Edm.String など）に直す。"""
    return str(getattr(value, "value", value))


def describe(field) -> str:
    flags = []
    if field.key:
        flags.append("キー")
    if field.searchable:
        flags.append(f"検索する（{plain(field.analyzer_name)}）")
    if field.filterable:
        flags.append("絞り込み")
    return "、".join(flags) if flags else "-"


section("項目の定義")
for f in index.fields:
    print(f"  {f.name:<9} {plain(f.type):<24} {describe(f)}")

# %% [markdown]
# ## 2. 作る
# すでにあるときは、何もしません（`RECREATE = True` なら消して作り直します）。

# %%
exists = index_exists(name)
if exists and not RECREATE:
    print(f"\nインデックス {name} はすでにあります。何もしません。")
    print("作り直したいときは python create_index.py --recreate（中の文書も消えます）。")
else:
    if exists:
        print(f"\nインデックス {name} を消して、作り直します。")
        client.delete_index(name)
    created = client.create_or_update_index(index)
    print(f"\nインデックス {created.name} を作りました（項目 {len(created.fields)} 個）。")
    print("まだ文書は 0 件です。次は：python upload.py（武将を登録する）")
