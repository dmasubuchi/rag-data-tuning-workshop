# %% [markdown]
# # 検索なしで聞いた答えと、検索して渡した答えを並べる
#
# 同じ質問を、資料を渡さずにそのまま Azure OpenAI に聞きます。`generate_answer.py` の答えと並べて表示します。
# RAG が役に立つのは、LLM が知らない情報を渡すときです。武将は有名なので、検索なしで答えられることもあります。
# 結果は、出たとおりに見てください（検索なしでも当たるとは限りません）。
#
# 実行：`python compare_no_search.py`
# 自分の質問：`python compare_no_search.py --q "自分の質問"`
#
# 前提：04-hybrid-ranker までが終わっていること。先に `generate_answer.py` を実行しておくと、その答えを使います（ランカーの無料枠を節約するため）。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, llm, rag_prompt, state, worklog
from lib.data import names_by_id, qid_note, resolve_question
from lib.show import api_calls_line, section, title

cells.start()
calls0 = llm.CALLS.copy()      # Notebook では呼び出しの回数がカーネルに残るので、この実行の分だけを数える

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None             # None のとき、questions.json の山場の質問。自分の質問は "…" と書く（--q でも指定できる）
METHOD = "hybrid_ranker"    # 検索の方式（generate_answer.py と同じにする。違うと、保存された答えを使わず、ここで検索し直す）
TOP_N = 3                   # プロンプトに入れる件数（generate_answer.py と同じにする）
TEMPERATURE = 0.0           # 互換のために残してある引数。いまのチャットのモデルには送らない
REBUILD = False             # True にすると、武将のインデックスを、04 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="検索なしの答えと並べる")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 検索なしで聞く
# 資料を渡さず、質問だけを送ります。

# %%
question, q = resolve_question(QUESTION, "climax")

state.ensure("06", rebuild=REBUILD)      # 武将にベクトルとセマンティックの設定が入っているか
title("検索なしで聞く")
print(f"質問：{question}{qid_note(q)}")

plain = llm.chat([{"role": "user", "content": question}], temperature=TEMPERATURE)

# %% [markdown]
# ## 2. 検索して渡した答えを用意する
# `generate_answer.py` の答えがあれば、それを使います。保存された答えは、質問・検索の方式・件数がいまと同じときだけ使います
# （設定を変えたら、ここで検索して作り直します）。

# %%
saved = worklog.load("generate_answer")
if rag_prompt.can_reuse(saved, question, METHOD, TOP_N):
    rag, used, note = saved["answer"], saved["names"], "（generate_answer.py で表示した答えです）"
else:
    hits = rag_prompt.retrieve(question, METHOD, TOP_N)
    rag = llm.chat([{"role": "user", "content": rag_prompt.build_prompt(question, hits)}], temperature=TEMPERATURE)
    used, note = [h["name"] for h in hits], "（この場で検索して作った答えです）"

# %% [markdown]
# ## 3. 2つの答えを並べる
# **見るところ**：2つの答えを、正解の武将と見比べる。検索なしでも当たるとは限りません。

# %%
section("検索なしで聞いた答え（資料を渡していない）")
print(plain)
section(f"検索して上位3件を渡した答え {note}")
print(f"渡した武将：{'、'.join(used)}")
print(rag)
if q:
    names = names_by_id()
    print("\n正解の武将：" + "、".join(names.get(i, i) for i in q["answer_ids"]))
    print("2つの答えを、正解の武将と見比べてください。")
print("\n" + api_calls_line(llm.CALLS - calls0))
print("RAG が効くのは、LLM が知らない情報（その会社の社内文書など）を渡すとき。次は応用編で、社内文書を取り込んで検索します。")
