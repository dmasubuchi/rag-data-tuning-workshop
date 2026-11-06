# %% [markdown]
# # 検索結果の上位3件で、プロンプトを組んで表示する（手動 RAG）
#
# 質問で検索し、上位 3 件の武将の文を貼り付けた「プロンプト」を作って、そのまま表示します。
# 表示された枠の中をコピーして、Azure OpenAI のプレイグラウンドなどに貼れば、手で RAG ができます。
# ここでは回答の生成はしません（質問の埋め込みで Azure OpenAI を 1 回、検索でランカーを 1 回使います）。
#
# 実行：`python build_prompt.py`
# 自分の質問：`python build_prompt.py --q "自分の質問"`
#
# 前提：04-hybrid-ranker までが終わっていること（武将にベクトルとセマンティックの設定が入っていること。04 のスクリプト自体は何も残さない）。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, llm, search, state
from lib.clients import search_client
from lib.config import SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, sengoku_index_name
from lib.data import names_by_id, qid_note, resolve_question
from lib.show import METHOD_LABELS, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None             # None のとき、questions.json の山場の質問。自分の質問は "…" と書く（--q でも指定できる）
METHOD = "hybrid_ranker"    # 検索の方式：keyword / vector / hybrid / hybrid_ranker
TOP_N = 3                   # プロンプトに入れる件数
REBUILD = False             # True にすると、武将のインデックスを、04 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="手動 RAG：プロンプトを組んで表示する")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 質問で検索して、上位の武将を選ぶ
# 方式 `METHOD` で検索し、上位 `TOP_N` 件を選びます。
# **見るところ**：選ばれた武将と、正解の武将がプロンプトに入ったか。

# %%
question, q = resolve_question(QUESTION, "climax")

state.ensure("06", rebuild=REBUILD)      # 武将にベクトルとセマンティックの設定が入っているか
title("プロンプトを組む（手動 RAG）")
print(f"質問：{question}{qid_note(q)}")
print(f"検索の方式：{METHOD_LABELS[METHOD]}　　プロンプトに入れる件数：{TOP_N}")

client = search_client(sengoku_index_name())
vec = llm.embed_one(question) if METHOD != "keyword" else None
hits = search.by_method(METHOD, client, question, vec, SENGOKU_VECTOR_FIELD, SENGOKU_SEMANTIC, top=TOP_N)[:TOP_N]
print("選ばれた武将：" + "、".join(h["name"] for h in hits))
if q:
    names = names_by_id()
    got = [names.get(i, i) for i in q["answer_ids"] if i in {h["id"] for h in hits}]
    print("正解の武将がプロンプトに入ったか：" + ("入っている（" + "、".join(got) + "）" if got else "入っていない"))

# %% [markdown]
# ## 2. プロンプトを組む
# 検索で見つけた武将の文を「【資料1】名前」の形で並べ、そのあとに「【質問】…」を置きます。
# `generate_answer.py` と `compare_no_search.py` は、同じ組み立てを `lib/rag_prompt.py` の `build_prompt()` で使います。
# **見るところ**：「【資料1】… 【質問】…」の形。下の2本の線のあいだが、LLM に渡す文章です。

# %%
def build_prompt(question: str, hits: list) -> str:
    """検索で見つけた武将の文を並べ、そのあとに質問を置く。"""
    parts = ["次の資料を参考にして、質問に答えてください。", ""]
    for i, h in enumerate(hits, start=1):
        parts.append(f"【資料{i}】{h['name']}")
        parts.append(h["profile"])
        parts.append("")
    parts.append(f"【質問】{question}")
    return "\n".join(parts)


prompt = build_prompt(question, hits)
print("\nプロンプト（下の2本の線のあいだが、LLM に渡す文章です。コピーして使えます）")
print("-" * 64)
print(prompt)
print("-" * 64)
print(f"（{len(prompt)} 文字）")
print("次は：python generate_answer.py（同じことを、コピーなしで Azure OpenAI に送る）")
