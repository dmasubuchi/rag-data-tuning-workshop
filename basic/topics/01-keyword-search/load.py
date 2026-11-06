# %% [markdown]
# # 武将の JSON の中身を見る
#
# `data/sengoku/bushou.json` を読み、項目の名前、先頭の数人の中身、全体の様子を表示します。
# Azure には接続しません（.env.local がなくても動きます）。
#
# 実行：`python load.py`（このフォルダで。Notebook なら上から順にセルを実行）

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells
from lib.config import BUSHOU_JSON, display_path
from lib.data import load_bushou
from lib.show import one_line, section, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
SHOW_COUNT = 3      # 項目を全部見せる人数（先頭から）
NAME = None         # 名前を入れると、その人を見せる。例 "伊達政宗"
# ============================================================================

# %% [markdown]
# ## 1. 読み込む
# **見るところ**：人数と、1人あたりの項目の名前と型。

# %%
people = load_bushou()
title("武将の JSON を読み込みました")
print(f"ファイル：{display_path(BUSHOU_JSON)}")
print(f"人数　　：{len(people)} 人")

section("1人あたりの項目（先頭の人の項目名と型）")
for key, value in people[0].items():
    print(f"  {key:<9}: {type(value).__name__}")

# %% [markdown]
# ## 2. 中身を見る
# `NAME` がなければ先頭から `SHOW_COUNT` 人、あればその名前の人を見せます。
# **見るところ**：項目ごとの値（リストの項目は「、」でつないで表示します）。

# %%
picked = people[:SHOW_COUNT] if not NAME else [p for p in people if p["name"] == NAME]
if not picked:
    print(f"\n{NAME} は見つかりませんでした。名前は次のとおりです。")
    print("  " + "、".join(p["name"] for p in people))
else:
    section(f"中身（{'名前で指定' if NAME else '先頭から ' + str(len(picked)) + ' 人'}）")
    for p in picked:
        print()
        for key, value in p.items():
            if isinstance(value, list):
                value = "、".join(str(v) for v in value) if value else "（なし）"
            elif value is None:
                value = "（なし）"
            print(f"  {key:<9}: {value}")

# %% [markdown]
# ## 3. 全体の様子
# **見るところ**：profile の文字数、家（clan）の数、名前の一覧。

# %%
if picked:
    section("全体の様子")
    lengths = [len(p["profile"]) for p in people]
    print(f"  profile の文字数：最短 {min(lengths)}、最長 {max(lengths)}、平均 {sum(lengths) / len(lengths):.0f}")
    clans = sorted({p["clan"] for p in people})
    print(f"  家（clan）の数：{len(clans)}　{one_line('、'.join(clans), 70)}")
    print("  名前の一覧：")
    names = [p["name"] for p in people]
    for i in range(0, len(names), 10):
        print("    " + "、".join(names[i:i + 10]))

    print("\n次は：python create_index.py（検索の入れ物＝インデックスを作る）")
