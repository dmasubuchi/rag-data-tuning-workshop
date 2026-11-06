# %% [markdown]
# # （発展）埋め込んだ数の並びの中身を見る
#
# 質問と武将の文を埋め込み、数の並びの最初の 10 個、長さ、大きさを表示します。
# さらに、質問と各武将の「近さ」（コサイン類似度＝2本の矢印の角度の近さ）を計算して並べます。1.0 に近いほど向きが近く、意味が近い。
# インデックスは使いません（Azure OpenAI の埋め込みだけを使います）。
#
# 実行：`python peek_vector.py`
# 自分の言い換え：`python peek_vector.py --q "自分で考えた言い換え"`

# %%
import math
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, llm
from lib.data import embedding_text, load_bushou, qid_note, resolve_question
from lib.show import pad, section, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None     # None のとき、questions.json の言い換えの質問。自分の質問は "…" と書く（--q でも指定できる）
COMPARE_NAMES = ["伊達政宗", "最上義光", "織田信長"]   # 近さを比べる武将（正解の武将は自動で加える）
FIRST_N = 10                                              # 先頭から何個見せるか
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="埋め込みの中身を見る")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION

# %% [markdown]
# ## 1. 質問と武将の文を埋め込む
# 比べる武将は `COMPARE_NAMES` に、質問の正解の武将を先頭に加えたものです。

# %%
people = {p["name"]: p for p in load_bushou()}
question, q = resolve_question(QUESTION, "paraphrase")

names = list(COMPARE_NAMES)
if q:
    by_id = {p["id"]: p["name"] for p in people.values()}
    for i in q.get("answer_ids", []):
        if by_id.get(i) and by_id[i] not in names:
            names.insert(0, by_id[i])
names = [n for n in names if n in people]

title("埋め込みの中身")
texts = [question] + [embedding_text(people[n]) for n in names]
vectors = llm.embed_texts(texts, show_progress=False)
qv, pvs = vectors[0], vectors[1:]

# %% [markdown]
# ## 2. 数の並びの中身
# **見るところ**：数の並びの長さ、最初の 10 個、矢印の長さ（大きさ）。数の一つひとつに意味はありません。

# %%
def show_vector(text: str, vec: list) -> None:
    print(f"文：{text}")
    print(f"長さ：{len(vec)}（数が {len(vec)} 個並んでいます）")
    print(f"最初の {FIRST_N} 個：")
    print("  " + ", ".join(f"{x:+.4f}" for x in vec[:FIRST_N]))
    print(f"矢印の長さ（大きさ）：{math.sqrt(sum(x * x for x in vec)):.4f}（埋め込みは長さ 1 にそろえてあります）")


section("質問")
show_vector(f"{question}{qid_note(q)}", qv)

section(f"武将の文（{names[0]}）")
show_vector(texts[1][:40] + "…", pvs[0])

# %% [markdown]
# ## 3. 質問との近さ
# 2本の数の並びの向きの近さ（コサイン類似度）を計算して、近い順に並べます。
# **見るところ**：数の一つひとつに意味はなく、2つの数の並びの「向きの近さ」だけが、意味の近さの目安になります。

# %%
def cosine(a: list, b: list) -> float:
    """2本の数の並びの向きの近さ（コサイン類似度）。"""
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


section("質問との近さ（コサイン類似度）")
scored = sorted(zip(names, pvs), key=lambda t: cosine(qv, t[1]), reverse=True)
for n, v in scored:
    print(f"  {pad(n, 10)} {cosine(qv, v):.4f}")
print("\n数の一つひとつに意味はありません。2つの数の並びの『向きの近さ』だけが、意味の近さの目安になります。")
