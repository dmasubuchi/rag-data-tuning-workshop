# %% [markdown]
# # 19 エージェント型検索（2）考える量（reasoning effort）を変える
#
# 知識ベースには「どれだけ考えてから探すか」を決める設定があります（retrievalReasoningEffort）。同じ質問で、設定を変えて比べます。
#
# - minimal：LLM を使わない。質問をそのまま検索文にして探す（質問は messages でなく intents で渡す）
# - low：LLM が質問を検索文に分解して、1回計画する（何も指定しないときの既定）
# - medium：low のあと、結果を見て足りなければ、見直した計画でもう1回やり直す
# - auto：まず軽く探し、足りなければ medium まで上げる（2026-08-01-preview で足された。LLM を呼ぶ回数は質問ごとに変わる）
#
# **注意：LLM を使う機能（low・medium・auto）はプレビューの API です。low・medium はそれより前のプレビューにもあり、auto は 2026-08-01-preview で足されました。
# この教材は auto がある 2026-08-01-preview を使います。GA の API（2026-04-01）は minimal だけで、retrievalReasoningEffort の欄自体がありません。**
#
# 実行：python effort_levels.py
#       python effort_levels.py --id q10
#       python effort_levels.py --question "市川さんの二次面接はいつでしたか"
#       python effort_levels.py --efforts minimal low
#
# 見るところ：
#   1. 「考える量ごとの比べ」の表：検索文の数・検索の回数・LLM の呼び出し・時間・トークンが、考える量でどう変わるか
#   2. 「検索文」：minimal は質問そのまま。low・medium は分解した文。medium は2回目の計画で検索文が増える
#   3. 「同じ資料が選ばれたか」：考える量を上げると、選ばれる資料が変わるか（変わらないこともある）
#   4. 実行するたびに、分解は少しずつ変わります（LLM の出力だから）。同じ質問をもう一度実行して確かめてください
#
# 呼び出しの数（1回の実行）：知識ベース 4 回（minimal・low・medium・auto）と、GA の API で 1 回。LLM を呼ぶ回数は考える量で変わります。
# minimal は 0 回、low は 1 回、medium と auto は結果を見て続けるので質問ごとに変わります（実測では medium が 2 回、auto が 1 回）。答えの生成はしません。

# %%
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import agentic, show  # noqa: E402

# ===== 変えてよい値 ==========================================================
QUESTION = None      # None のとき、用意した質問（QUESTION_ID）。自分の質問は "…" と書く（--question でも指定できる）
QUESTION_ID = "q10"  # 用意した質問の番号 q01〜q10（questions.json）。--id でも指定できる
EFFORTS = ["minimal", "low", "medium", "auto"]    # 比べる考える量（--efforts minimal low … でも指定できる）
TOP_N = agentic.TOP_N    # 返してもらう資料の件数（--top でも指定できる）
TRY_GA = True            # True のとき、GA の API（2026-04-01）でも minimal を1回試す
# ============================================================================

parser = argparse.ArgumentParser(description="考える量を変えて、エージェント型検索を比べる")
parser.add_argument("--question", help="自分の質問")
parser.add_argument("--id", help="用意した質問の番号（q01〜q10）")
parser.add_argument("--efforts", nargs="+", choices=agentic.EFFORTS, help="比べる考える量")
parser.add_argument("--top", type=int, help="返してもらう資料の件数")
args, _ = parser.parse_known_args()
qid, question = agentic.resolve_question(args.question or QUESTION, args.id or QUESTION_ID)
efforts = args.efforts or EFFORTS
top_n = args.top or TOP_N

show.title(f"質問（{qid}）：{question}")
print(agentic.PREVIEW_NOTICE)
print(f"比べる考える量：{', '.join(efforts)}　返してもらう資料：{top_n} 件")
agentic.require_knowledge_base()      # 構築する人が作った知識ベースがあるか（読むだけ）

# %% [markdown]
# ## 1. 考える量ごとに、同じ質問で知識ベースを呼ぶ
#
# 答えの生成はしません（検索の違いだけを見ます）。**見るところ**：minimal は LLM の呼び出しが 0 回、検索は1回。

# %%
results = {}
for effort in efforts:
    results[effort] = agentic.retrieve(question, effort, max_documents=top_n)
    a = results[effort]["activity"]
    print(f"  {effort:<8} {results[effort]['elapsed_s']} 秒　検索 {a['search_count']} 回　LLM の呼び出し {a['planning_calls']} 回")

# %% [markdown]
# ## 2. 並べて比べる
#
# 「検索文の数」は、重複を除いた検索文の数です。「LLM の呼び出し」は、質問の分解（クエリの計画）の回数です（medium は最初の結果を見てやり直すと2回になる）。
# 「検索側のトークン」は、AI Search が数えたトークン（reasoningTokens。セマンティックランカーなどで使う分）で、LLM のトークンとは別です。

# %%
show.section("考える量ごとの比べ")
rows = []
for effort, r in results.items():
    a = r["activity"]
    rows.append([effort, len(a["distinct_queries"]), a["search_count"], a["planning_calls"], f"{r['elapsed_s']:.1f}",
                 f"{a['input_tokens']:,} / {a['output_tokens']:,}" if a["planning_calls"] else "-", f"{a['search_tokens']:,}"])
show.table(["考える量", "検索文の数", "検索の回数", "LLM の呼び出し", "時間(秒)", "LLM のトークン（入力 / 出力）", "検索側のトークン"], rows)

# %%
show.section("検索文（activity の searchIndex の記録）")
for effort, r in results.items():
    print(f"\n[{effort}]")
    for n, s in enumerate(r["activity"]["searches"], start=1):
        print(f"  {n}. {s['query']}")

# %% [markdown]
# ## 3. 選ばれた資料は変わるか
#
# minimal の資料を基準にして、ほかの考える量で、同じ資料が何件入っているかを数えます。
# **見るところ**：件数が少ないほど、考える量を上げたことで選ばれる資料が変わったということです。変わっても、答えが良くなるとは限りません（20 で確かめます）。

# %%
show.section("同じ資料が選ばれたか（基準は先頭の考える量）")
base_name = efforts[0]
base_keys = [e["chunk_id"] for e in results[base_name]["evidence"]]
rows = []
for effort, r in results.items():
    keys = [e["chunk_id"] for e in r["evidence"]]
    new = [e for e in r["evidence"] if e["chunk_id"] not in base_keys]
    rows.append([effort, len(keys), len(set(keys) & set(base_keys)),
                 "、".join(agentic.short_id(e["chunk_id"], e["title"]) for e in new[:4]) or "-"])
show.table(["考える量", "資料の数", f"{base_name} と同じ資料", f"{base_name} になかった資料（4件まで）"], rows)

# %% [markdown]
# ## 4. GA の API でも試す（minimal だけ）
#
# GA の API（2026-04-01）では LLM を使う機能は使えません。minimal と同じ「質問をそのまま探す」だけを、GA の要求の形（intents だけ）で呼びます。
# **見るところ**：LLM の呼び出しが 0 回。件数の上限（maxOutputDocuments）は GA にないので、資料の数が多くなります。

# %%
if TRY_GA:
    show.section(f"GA の API（{agentic.GA_API_VERSION}）で minimal")
    ga = agentic.retrieve_ga(question)
    a = ga["activity"]
    print(f"検索 {a['search_count']} 回、LLM の呼び出し {a['planning_calls']} 回、資料 {len(ga['evidence'])} 件（上限なし）、{ga['elapsed_s']} 秒")
else:
    print("TRY_GA = False なので、GA の API は試しません。")

# %%
show.section("この実行の呼び出し")
agentic.usage_table()
print("\nどの考える量で答えが良くなったかは、20 で点数にして比べます。")
