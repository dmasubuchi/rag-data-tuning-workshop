# %% [markdown]
# # 19 エージェント型検索（1）同じ質問を、普通の検索と並べる
#
# 同じ質問を、次の2つの方法で探して、同じプロンプトで LLM に答えさせます。違いは「資料の選ばれ方」だけです。
#
# - ① 普通の検索：質問をそのまま、ハイブリッド検索＋セマンティックランカーで1回探す
# - ② エージェント型検索：知識ベース（hr-docs-kb）に質問を渡す。LLM が質問を検索文に分解し、複数回探して、まとめて返す
#
# どちらも、同じ絞り込み（採用担当が見てよいもの）と、同じ件数の資料を渡します。
#
# **注意：エージェント型検索の LLM を使う機能（質問の分解）は、プレビューの API です（この教材は 2026-08-01-preview を使います）。仕様が変わることがあります。**
#
# 実行：python compare_search.py
#       python compare_search.py --id q07
#       python compare_search.py --question "市川さんの二次面接はいつでしたか"
#       python compare_search.py --effort medium
#
# 見るところ：
#   1. ②の「質問の分解」の表：LLM が質問をどんな検索文に分けたか。検索の回数
#   2. ②の「出典」の表：答えに渡した資料と、どの検索文が見つけたか
#   3. 最後の「誰の資料が入ったか」の表：データにある書類と、①②に入った書類。足りない人がいないか
#   4. ①と②の答えを読み比べる。どちらかが必ず良いとは限らない
#
# 呼び出しの数（1回の実行）：普通の検索 1 回、知識ベース 1 回（LLM が質問を分解する呼び出しを含む）、答えの生成 2 回。

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
QUESTION_ID = "q01"  # 用意した質問の番号 q01〜q10（questions.json）。--id でも指定できる
EFFORT = "low"       # 考える量：low（既定）か medium。minimal は分解しない、auto は様子を見て上げる（--effort でも指定できる）
TOP_N = agentic.TOP_N    # 答えに渡す資料の件数。①②で同じにする（--top でも指定できる）
# ============================================================================

parser = argparse.ArgumentParser(description="同じ質問を、普通の検索とエージェント型検索で並べる")
parser.add_argument("--question", help="自分の質問")
parser.add_argument("--id", help="用意した質問の番号（q01〜q10）")
parser.add_argument("--effort", choices=agentic.EFFORTS, help="考える量")
parser.add_argument("--top", type=int, help="答えに渡す資料の件数")
args, _ = parser.parse_known_args()
qid, question = agentic.resolve_question(args.question or QUESTION, args.id or QUESTION_ID)
effort = args.effort or EFFORT
top_n = args.top or TOP_N

show.title(f"質問（{qid}）：{question}")
print(agentic.PREVIEW_NOTICE)
print(f"考える量：{effort}　答えに渡す資料：{top_n} 件　絞り込み：採用担当（role:recruiter）が見てよいもの")
agentic.require_knowledge_base()      # 構築する人が作った知識ベースがあるか（読むだけ）


def evidence_table(evidence, found_by=None):
    rows = []
    for i, e in enumerate(evidence, start=1):
        score = e.get("score")
        row = [i, agentic.short_id(e["chunk_id"], e["title"]), f"{score:.2f}" if isinstance(score, (int, float)) else "-"]
        if found_by is not None:
            row.append(found_by.get(e["chunk_id"], "-"))
        rows.append(row)
    headers = ["番号", "資料（ファイル#チャンク）", "点"] + (["見つけた検索文"] if found_by is not None else [])
    show.table(headers, rows)


# %% [markdown]
# ## 1. ① 普通の検索（1回）で探して、答えさせる
#
# 質問をそのまま検索文にして、1回だけ探します。**見るところ**：質問に出てくる人や書類が、上位の資料に入っているか。

# %%
show.section("① 普通の検索：渡した資料")
plain = agentic.run_plain(question, top_n)
evidence_table(plain["context"])
show.section("① の答え")
print(plain["answer"])
print(f"\n検索 {plain['search_count']} 回（{plain['search_seconds']} 秒）、答えの生成 1 回（{plain['answer_seconds']} 秒）")

# %% [markdown]
# ## 2. ② エージェント型検索で探して、同じプロンプトで答えさせる
#
# 知識ベースに質問を渡します。LLM が質問をいくつかの検索文に分解し、それぞれで探して、結果をまとめて返します。
# **見るところ**：「質問の分解」の表の検索文（元の質問と、どう違うか）。「出典」の表の「見つけた検索文」（どの検索文が、どの資料を見つけたか）。

# %%
retrieval = agentic.retrieve(question, effort, max_documents=top_n)
act = retrieval["activity"]

show.section("② 質問の分解（activity の searchIndex の記録）")
if act["planning_calls"]:
    print(f"LLM が質問を分解しました（{act['planning_calls']} 回、入力 {act['input_tokens']:,} / 出力 {act['output_tokens']:,} トークン、"
          f"{act['planning_ms'] / 1000:.1f} 秒）。")
else:
    print(f"考える量 {effort} では LLM を使いません。質問がそのまま検索文になります。")
show.table(["検索", "検索文", "しきい値を超えた件数", "時間(ms)"],
           [[n, s["query"], s["count"], s["elapsed_ms"]] for n, s in enumerate(act["searches"], start=1)])
print(f"検索の回数：{act['search_count']} 回（searchIndex の記録の数）。元の質問の検索文：{question}")

# %%
show.section("② 出典（references）：答えに渡した資料")
number_of = {s["id"]: n for n, s in enumerate(act["searches"], start=1)}
found_by = {}
for r in retrieval["references"]:
    n = number_of.get(r["activity_source"])
    found_by[r["doc_key"]] = f"検索 {n}" if n else "-"
evidence_table(retrieval["evidence"], found_by)
print(f"\n知識ベースが返した出典は {len(retrieval['references'])} 件。そのまま答えに渡します（件数は maxOutputDocuments={top_n} で ① とそろえています）。")

# %%
ans = agentic.make_answer(question, retrieval["evidence"])    # ①と同じプロンプト・同じ件数
show.section("② の答え")
print(ans["answer"])
print(f"\n検索 {act['search_count']} 回（知識ベース全体で {retrieval['elapsed_s']} 秒）、答えの生成 1 回（{ans['seconds']} 秒）")

# %% [markdown]
# ## 3. 並べて比べる
#
# **見るところ**：検索の回数と時間（②は分解の分だけ増える）。「誰の資料が入ったか」の表で、データにある書類（左）に対して、
# ①②の資料に、その人の書類が入っているか。**データにない書類（たとえば面接の評価が 0 の人）は、入りようがありません。
# 答えが「資料にありません」と書けているかを、答えの文で確かめてください。**

# %%
show.section("方式の比べ")
show.table(
    ["", "① 普通の検索", "② エージェント型検索"],
    [["検索の回数", plain["search_count"], act["search_count"]],
     ["質問の分解（LLM）", "なし", f"{act['planning_calls']} 回" if act["planning_calls"] else "なし"],
     ["渡した資料", f"{len(plain['context'])} 件", f"{len(retrieval['evidence'])} 件"],
     ["検索にかかった時間", f"{plain['search_seconds']} 秒", f"{retrieval['elapsed_s']} 秒"],
     ["LLM のトークン（分解）", "-", f"{act['input_tokens']:,} / {act['output_tokens']:,}"],
     ["LLM のトークン（答え）", f"{plain['tokens']['answer_input']:,} / {plain['tokens']['answer_output']:,}",
      f"{ans['input_tokens']:,} / {ans['output_tokens']:,}"]])

plain_keys = {e["chunk_id"] for e in plain["context"]}
agentic_keys = {e["chunk_id"] for e in retrieval["evidence"]}
only = {"① だけ": [e for e in plain["context"] if e["chunk_id"] not in agentic_keys],
        "② だけ": [e for e in retrieval["evidence"] if e["chunk_id"] not in plain_keys]}
for label, items in only.items():
    print(f"\n{label}に入った資料：" + ("、".join(agentic.short_id(e["chunk_id"], e["title"]) for e in items) or "なし"))

show.section("誰の資料が入ったか（応募ごと。データにある書類と、入った資料のチャンクの数）")
show.table(["応募", "名前", "データにある書類", "① に入った資料", "② に入った資料"],
           agentic.coverage_rows(plain["context"], retrieval["evidence"]))

# %%
show.section("この実行の呼び出し")
agentic.usage_table()
print("\n別の質問を試すには：python compare_search.py --question \"…\"（質問に出てくる人や求人番号を入れると、探しやすくなります）")
