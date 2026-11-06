# %% [markdown]
# # 同じプロンプトを、Azure OpenAI に送って答えさせる
#
# `build_prompt.py` と同じ検索・同じプロンプトを、コピーなしで Azure OpenAI（チャット）に送り、答えを表示します。
# Azure OpenAI の呼び出しは、質問の埋め込み 1 回と、回答の生成 1 回です。
#
# 実行：`python generate_answer.py`
# 自分の質問：`python generate_answer.py --q "自分の質問"`
#
# 前提：04-hybrid-ranker までが終わっていること（武将にベクトルとセマンティックの設定が入っていること）。

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
from lib.config import get_settings
from lib.data import names_by_id, qid_note, resolve_question
from lib.show import METHOD_LABELS, api_calls_line, section, title

cells.start()
calls0 = llm.CALLS.copy()      # Notebook では呼び出しの回数がカーネルに残るので、この実行の分だけを数える

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None             # None のとき、questions.json の山場の質問。自分の質問は "…" と書く（--q でも指定できる）
METHOD = "hybrid_ranker"    # 検索の方式：keyword / vector / hybrid / hybrid_ranker（build_prompt.py と同じ）
TOP_N = 3                   # プロンプトに入れる件数（build_prompt.py と同じ）
TEMPERATURE = 0.0           # 互換のために残してある引数。いまのチャットのモデルには送らない（llm.chat は温度を送らない）
REBUILD = False             # True にすると、武将のインデックスを、04 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="検索結果を渡して、Azure OpenAI に答えさせる")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 検索する
# **見るところ**：選ばれた武将。

# %%
question, q = resolve_question(QUESTION, "climax")

state.ensure("06", rebuild=REBUILD)      # 武将にベクトルとセマンティックの設定が入っているか
title("検索して、答えさせる（自動の RAG）")
print(f"質問：{question}{qid_note(q)}")
hits = rag_prompt.retrieve(question, METHOD, TOP_N)
print(f"検索の方式：{METHOD_LABELS[METHOD]}　選ばれた武将：{'、'.join(h['name'] for h in hits)}")

# %% [markdown]
# ## 2. プロンプトを組んで、答えさせる
# `build_prompt.py` で表示したプロンプトと同じものを、Azure OpenAI に送ります。
# **見るところ**：答えと、正解の武将。

# %%
messages = [{"role": "user", "content": rag_prompt.build_prompt(question, hits)}]
answer = llm.chat(messages, temperature=TEMPERATURE)

section("答え")
print(answer)
if q:
    names = names_by_id()
    print("\n正解の武将：" + "、".join(names.get(i, i) for i in q["answer_ids"]))
print("\n" + api_calls_line(llm.CALLS - calls0))

# %% [markdown]
# ## 3. 渡したプロンプトを保存する
# 生成に使った messages をそのまま保存します（`compare_no_search.py` が答えを並べるのに使います）。

# %%
settings = {"method": METHOD, "top_n": TOP_N, **llm.sent_conditions(),
            "chat_deployment": get_settings().chat_deployment}
record = worklog.prompt_record("generate_answer.py", question, settings, [h["id"] for h in hits],
                               [{"label": "回答の生成", "messages": messages, "answers": [answer]}])
record.update({"answer": answer, "names": [h["name"] for h in hits]})
worklog.save("generate_answer", record)
print("次は：python compare_no_search.py（検索なしで聞いた答えと並べる）")
