# %% [markdown]
# # 19 エージェント型検索（3）用意した10問の答えを作って保存する（20 で採点する）
#
# 用意した質問 10 問（questions.json）を、① 普通の検索と ② エージェント型検索のそれぞれで、同じ質問を複数回ずつ答えさせて保存します。
# 保存先は `applied/_work/19_answers.json`（Git に入れない）。質問・方式・回・答え・渡した資料（チャンクの ID と本文）が入ります。
# 20（答えを評価する）は、この保存を読んで採点します。保存がなければ、20 がこのスクリプトと同じ関数で作ります。
#
# **これは進行役のデモ用です。参加者が全員で動かすと、呼び出しが多くなります**（下の「呼び出しの数」を見てください）。
# 参加者が試すときは、質問を絞る（--only）か、回数を減らす（--runs 1）にしてください。
#
# 実行：python make_answers.py                  10 問 × 2 方式 × 3 回（60 件）を作る
#       python make_answers.py --runs 1         1 回ずつ（20 件）
#       python make_answers.py --only q01 q03   質問を絞る
#       python make_answers.py --fresh          保存を消して作り直す
#
# 保存があるときは、できていない分だけを足します（途中で止まっても、続きから作れます）。
#
# 見るところ：
#   1. 方式ごとの平均：検索の回数、時間、トークン。② は分解の分だけ増える
#   2. 質問ごとの分解：質問をどんな検索文に分けたか（low では3つ前後に分けることが多い）
#
# 呼び出しの数：1 問・1 回あたり、① は検索 1 回＋答えの生成 1 回、② は知識ベース 1 回（LLM の分解 1 回、検索は 3 回前後）＋答えの生成 1 回。
# 10 問 × 3 回では、答えの生成 60 回、質問の分解 30 回、知識ベース 30 回、普通の検索 30 回。

# %%
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import agentic, show  # noqa: E402

# ===== 変えてよい値 ==========================================================
RUNS = 3               # 1つの質問・方式あたり、何回答えさせるか（--runs でも指定できる）
ONLY = None            # 質問を絞る。例 ["q01", "q03"]（--only q01 q03 でも指定できる）。None なら 10 問すべて
EFFORT = "low"         # ② の考える量（--effort でも指定できる）
TOP_N = agentic.TOP_N  # 答えに渡す資料の件数。①②で同じ（--top でも指定できる）
FRESH = False          # True のとき、保存を消して作り直す（--fresh でも指定できる）
# ============================================================================

parser = argparse.ArgumentParser(description="用意した10問の答えを作って保存する")
parser.add_argument("--runs", type=int, help="1つの質問・方式あたりの回数")
parser.add_argument("--only", nargs="+", help="質問を絞る（q01 q03 …）")
parser.add_argument("--effort", choices=agentic.EFFORTS, help="② の考える量")
parser.add_argument("--top", type=int, help="答えに渡す資料の件数")
parser.add_argument("--fresh", action="store_true", help="保存を消して作り直す")
args, _ = parser.parse_known_args()
runs = args.runs or RUNS
only = args.only or ONLY
effort = args.effort or EFFORT
top_n = args.top or TOP_N
fresh = args.fresh or FRESH

questions = agentic.load_questions()
if only:
    unknown = [q for q in only if q not in {x["id"] for x in questions}]
    if unknown:
        raise lib.config.SetupError(f"質問の番号が違います: {', '.join(unknown)}（q01〜q10）")
    questions = [q for q in questions if q["id"] in only]

show.title("用意した質問の答えを作る（①普通の検索 と ②エージェント型検索）")
print(agentic.PREVIEW_NOTICE)
print(f"質問 {len(questions)} 問 × 方式 2 × {runs} 回 = {len(questions) * 2 * runs} 件　② の考える量：{effort}　答えに渡す資料：{top_n} 件")
print(f"保存先：{lib.config.display_path(agentic.ANSWERS_JSON)}")
agentic.require_knowledge_base()      # 構築する人が作った知識ベースがあるか（読むだけ）

# %% [markdown]
# ## 1. 答えを作って保存する
#
# 1件ごとに保存します。**見るところ**：② の検索の回数（分解で3回前後に増える）と、時間。

# %%
data = agentic.make_answers(questions, runs=runs, effort=effort, top_n=top_n, fresh=fresh)

# %% [markdown]
# ## 2. 方式ごとに集計する
#
# **見るところ**：検索の回数・時間・トークンが、② でどれだけ増えたか。答えの良し悪しは 20 で採点します。

# %%
show.section("方式ごとの平均（1件あたり）")
items = [i for i in data["items"] if i["question_id"] in {q["id"] for q in questions}]
rows = []
for method in agentic.METHODS:
    xs = [i for i in items if i["method"] == method]
    if not xs:
        continue
    n = len(xs)
    rows.append([agentic.METHOD_LABELS[method], n, f"{sum(i['search_count'] for i in xs) / n:.1f}",
                 f"{sum(i['planning_calls'] for i in xs) / n:.1f}", f"{sum(i['seconds'] for i in xs) / n:.1f}",
                 f"{sum(i['tokens']['planning_input'] + i['tokens']['answer_input'] for i in xs) / n:,.0f}",
                 f"{sum(i['tokens']['planning_output'] + i['tokens']['answer_output'] for i in xs) / n:,.0f}"])
show.table(["方式", "件数", "検索の回数", "分解（LLM）", "時間(秒)", "LLM 入力トークン", "LLM 出力トークン"], rows)

show.section("質問ごとの ② の分解（1 回目の検索文）")
for q in questions:
    first = next((i for i in items if i["question_id"] == q["id"] and i["method"] == "agentic"), None)
    if first:
        print(f"\n{q['id']}  {show.one_line(q['question'], 56)}")
        for n, query in enumerate(first["queries"], start=1):
            print(f"    {n}. {query}")

# %%
show.section("この実行の呼び出し")
agentic.usage_table()
print(f"\n保存しました：{lib.config.display_path(agentic.ANSWERS_JSON)}（{len(data['items'])} 件）。次は 20-answer-evaluation で採点します。")
