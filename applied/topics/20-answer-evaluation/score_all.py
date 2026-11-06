# %% [markdown]
# # 20 答えを評価する（2）10問 × 2方式 × 3回を採点して、点のぶれを見る
#
# 19 の答え（10 問 × ① 普通の検索 / ② エージェント型検索 × 3 回 = 60 件）を、2通りの方法で採点します。
#
# - 自前の採点プロンプト：根拠への忠実さ・質問への答え・要点の網羅（各 1〜5）
# - 組み込みの評価器：groundedness（資料に基づいているか）・relevance（質問に答えているか）（各 1〜5）
#
# 同じ質問・同じ方式の答えを、別々に3回ずつ作ってあります。その3つの答えを1回ずつ採点して、**3回の最小・最大で点のぶれ**を見ます。
# このぶれは、答えの生成のぶれ（同じ質問でも答えが少しずつ違う）と、採点のぶれ（同じ答えでも点が少し変わる）を合わせたものです。
# LLM が答えを作り、LLM が採点するので、1回だけ採点して「① より ② が良い」と決めることはできません。
#
# **これは進行役のデモ用です**（呼び出しが多い：採点 60 件で、LLM を自前 60 回、組み込み 120 回）。
# 19 の保存（`applied/_work/19_answers.json`）がなければ、19 の関数で先に作ります（答えの生成 60 回、質問の分解 30 回が加わる）。
# 結果は `applied/_work/20_scores.json` に保存します（途中で止まっても、続きから採点できます）。
#
# 実行：python score_all.py                  採点して、集計を見る
#       python score_all.py --summary        保存した採点を集計するだけ（LLM を呼ばない）
#       python score_all.py --no-builtin     自前の採点だけ（azure-ai-evaluation が入っていないとき）
#       python score_all.py --only q01 q02   質問を絞る
#       python score_all.py --fresh          採点の保存を消して、採点し直す
#       python score_all.py --summary --threshold 4     合格のしきい値を 4 にして、合否を数え直す（LLM を呼ばない）
#
# 採点の保存は、入力（質問・答え・渡した資料・想定の要点・採点の基準）が同じものだけ使い回します。答えや基準が変わったら、その分を採点し直します。
# 自前だけで採点したあとに組み込みの評価器を使うと、足りない組み込みの分だけを採点します。
#
# 組み込みの評価器には、次が要ります：pip install -r applied/requirements-eval.txt（Repo 直下で）
#
# 見るところ：
#   1. 方式ごとの平均点：① と ② の差。差は小さく、どちらかが必ず良いとは限らない
#   2. 質問ごとの点の幅：同じ質問・同じ方式の3回（別々の答え）で、点が 1〜2 点動く。差は、このぶれの範囲に収まるか
#   3. 「注意」：groundedness の 3 は「根拠にできる情報がない」の段なのに、しきい値 3 では合格になる。しきい値を変えて数え直せる
#   4. 2通りの採点の一致：自前と組み込みで、点は同じ傾向か。同じ観点でも、基準が違えば点は違う

# %%
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import agentic, evaluation, show  # noqa: E402

# ===== 変えてよい値 ==========================================================
RUNS = 3               # 1つの質問・方式あたり、何回分の答えを採点するか（--runs でも指定できる）
ONLY = None            # 質問を絞る。例 ["q01", "q03"]（--only q01 q03 でも指定できる）。None なら 10 問すべて
BUILTIN = True         # False のとき、自前の採点だけ（--no-builtin でも指定できる）
SUMMARY_ONLY = False   # True のとき、保存した採点を集計するだけ（--summary でも指定できる）
FRESH = False          # True のとき、採点の保存を消して採点し直す（--fresh でも指定できる）
THRESHOLD = 3          # 合格のしきい値（--threshold でも指定できる）。評価器の既定は 3。変えると、保存した点をこの値で判定し直して数える
# ============================================================================

parser = argparse.ArgumentParser(description="19 の答えを採点して、点のぶれを見る")
parser.add_argument("--runs", type=int, help="1つの質問・方式あたりの回数")
parser.add_argument("--only", nargs="+", help="質問を絞る（q01 q03 …）")
parser.add_argument("--no-builtin", action="store_true", help="自前の採点だけ")
parser.add_argument("--summary", action="store_true", help="保存した採点を集計するだけ")
parser.add_argument("--fresh", action="store_true", help="採点の保存を消して採点し直す")
parser.add_argument("--threshold", type=float, help="合格のしきい値（既定 3）")
args, _ = parser.parse_known_args()
runs = args.runs or RUNS
only = args.only or ONLY
use_builtin = BUILTIN and not args.no_builtin
summary_only = SUMMARY_ONLY or args.summary
fresh = FRESH or args.fresh
threshold = args.threshold if args.threshold is not None else THRESHOLD

questions = agentic.load_questions()
if only:
    unknown = [q for q in only if q not in {x["id"] for x in questions}]
    if unknown:
        raise lib.config.SetupError(f"質問の番号が違います: {', '.join(unknown)}（q01〜q10）")
    questions = [q for q in questions if q["id"] in only]
ids = {q["id"] for q in questions}

show.title("答えの評価：2通りの採点と、点のぶれ")
if use_builtin and not summary_only and not evaluation.builtin_available():
    print("azure-ai-evaluation が入っていないので、自前の採点だけにします。組み込みの評価器を使うには：")
    print(evaluation.INSTALL_HINT)
    use_builtin = False
print(f"質問 {len(questions)} 問 × 方式 2 × {runs} 回 = {len(questions) * 2 * runs} 件" + ("　（集計だけ）" if summary_only else ""))

# %% [markdown]
# ## 1. 19 の答えを用意する
#
# 保存してある答えを読みます。なければ（足りなければ）、19 の関数で作ります。**見るところ**：件数（質問 × 2 方式 × 回数）。

# %%
if summary_only:
    answers = agentic.load_answers()
    print("集計だけなので、答えは作りません。")
else:
    answers = agentic.ensure_answers(runs=runs, questions=questions)
    print(f"答えの件数：{len([i for i in answers['items'] if i['question_id'] in ids and i['run'] <= runs])}")

# %% [markdown]
# ## 2. 採点する
#
# 1件ごとに保存します。1件あたり、LLM を自前の採点で 1 回、組み込みの評価器で 2 回呼びます。

# %%
if summary_only:
    scores = evaluation.load_scores()
    if scores is None:
        raise lib.config.SetupError("採点の保存がありません。--summary を付けずに実行してください。")
else:
    items = [i for i in answers["items"] if i["run"] <= runs]
    scores = evaluation.score_answers({**answers, "items": items}, questions, builtin=use_builtin, fresh=fresh)
records = [r for r in scores["records"] if r["question_id"] in ids and r["run"] <= runs]
if summary_only and answers:
    old = evaluation.stale_records(scores, answers, questions)
    if old:
        print(f"注意：保存した採点のうち {len(old)} 件は、今の答え・想定の要点・採点の基準と入力が違います（古い採点）。--summary を付けずに実行すると採点し直します。")
has_builtin = any(r.get("builtin") for r in records)
print(f"採点済み：{len(records)} 件（組み込みの評価器 {'あり' if has_builtin else 'なし'}）")

metrics = [("own.faithfulness", "自前：根拠への忠実さ"), ("own.answers_question", "自前：質問への答え"), ("own.coverage", "自前：要点の網羅")]
if has_builtin:
    metrics += [("builtin.groundedness", "組み込み：groundedness"), ("builtin.relevance", "組み込み：relevance")]


def fmt(x):
    return "-" if x is None else f"{x:.2f}"


# %% [markdown]
# ## 3. 方式ごとの平均点
#
# 全質問・全回の平均です。**見るところ**：② - ① の差。差が 0.3 点ほどなら、次の「点の幅」と見比べてください。

# %%
show.section("方式ごとの平均点（1〜5）")
rows = []
for metric, label in metrics:
    means = evaluation.method_means(records, metric)
    diff = None if None in means.values() else means["agentic"] - means["plain"]
    rows.append([label, fmt(means["plain"]), fmt(means["agentic"]), "-" if diff is None else f"{diff:+.2f}"])
show.table(["観点", "① 普通の検索", "② エージェント型検索", "② - ①"], rows)

if has_builtin:
    show.section(f"組み込みの評価器の合格率（しきい値 {threshold:g} 以上が pass。保存した点をこの値で判定し直したもの）")
    rows = []
    for name, label in evaluation.BUILTIN_METRICS:
        row = [label]
        for method in agentic.METHODS:
            ok, n = evaluation.pass_counts(records, name, method, threshold)
            row.append(f"{ok} / {n}")
        rows.append(row)
    show.table(["評価器", "① 合格 / 件数", "② 合格 / 件数"], rows)
    if threshold != 3:
        print("（評価器の既定のしきい値は 3 です。THRESHOLD や --threshold で変えると、点は同じで、合格の数だけが変わります）")

# %% [markdown]
# ## 4. 点のぶれ：同じ質問・同じ方式の3回の最小〜最大
#
# 「3〜5」は、別々に作った3つの答えの点が 3 点から 5 点まで動いたということです（答えの生成のぶれと、採点のぶれを合わせたもの）。
# **見るところ**：幅が 2 点ある行は、1回の採点では点が決まらない。① と ② の平均の差（上の表）は、この幅の範囲に収まっているか。

# %%
show_metrics = [m for m in ("own.coverage", "builtin.groundedness", "builtin.relevance") if m in dict(metrics)]
spreads = {m: evaluation.group_spreads(records, m) for m, _ in metrics}
show.section("質問ごとの点の幅（別々に作った3つの答えの最小〜最大）")
cols = [(m, dict(metrics)[m].replace("自前：", "").replace("組み込み：", "")) for m in show_metrics]
headers = ["質問"] + [f"{name} {agentic.METHOD_LABELS[method][:1]}" for m, name in cols for method in agentic.METHODS]
rows = []
for q in questions:
    row = [q["id"]]
    for m, _ in cols:
        for method in agentic.METHODS:
            row.append(evaluation.range_text(spreads[m].get((q["id"], method), evaluation.spread([]))))
    rows.append(row)
show.table(headers, rows)
print("（列の ① は普通の検索、② はエージェント型検索。点の幅は、別々に作った 3 つの答えの最小〜最大）")

show.section("ぶれの大きさ：点の幅（最大 - 最小）の平均と、幅が 2 点以上の（質問・方式）の数")
rows = []
for m, label in metrics:
    sp = spreads[m]
    row = [label]
    for method in agentic.METHODS:
        big = sum(1 for (q, mm), s in sp.items() if mm == method and s["range"] is not None and s["range"] >= 2)
        total = sum(1 for (q, mm) in sp if mm == method)
        row.append(f"{fmt(evaluation.mean_range(sp, method))}（幅2以上 {big} / {total}）")
    rows.append(row)
show.table(["観点", "① の幅の平均", "② の幅の平均"], rows)

cov = evaluation.method_means(records, "own.coverage")
if None not in cov.values():
    gap = abs(cov["agentic"] - cov["plain"])
    wide = max(evaluation.mean_range(spreads["own.coverage"], m) or 0 for m in agentic.METHODS)
    print(f"\n要点の網羅の平均の差は {gap:.2f} 点。同じ方式の3つの答えの点の幅は、平均 {wide:.2f} 点まで動いています（答えの生成と採点の両方のぶれ）。"
          + ("差はぶれより小さいので、この採点だけで方式の勝ち負けは決められません。" if gap < wide else "差はぶれより大きいですが、質問ごとの幅も見て判断してください。"))

# %% [markdown]
# ## 5. 注意：groundedness の 3 と、出力の欄の名前
#
# - 組み込みの groundedness の採点基準では、3 は「答えが資料に基づいていない（根拠にできる情報がない）」の段です。
#   しきい値の既定が 3 なので、**3 点でも「合格（pass）」になります。** 合否だけで見ると、資料に基づかない答えを見逃します。
#   しきい値を 4 にすれば 3 点は不合格になりますが、4 点未満の答えがすべて不合格になる。しきい値は、目的に合わせて自分で決めます。
# - 出力の欄の名前は版で変わります。この版（azure-ai-evaluation 1.18.10）は `groundedness`・`groundedness_result`・`groundedness_reason` で、
#   公式の古い例にある `gpt_groundedness` のような欄はありません。トークン数は `groundedness_properties` の中です。

# %%
if has_builtin:
    show.section("groundedness の点の分布（採点した答えの数）")
    groundedness = [r["builtin"]["groundedness"] for r in records if r.get("builtin")]
    show.table(["点", "1", "2", "3", "4", "5"],
               [["件数"] + [sum(1 for g in groundedness if g["score"] == k) for k in (1, 2, 3, 4, 5)]])
    threes = [r for r in records if r.get("builtin") and r["builtin"]["groundedness"]["score"] == 3.0]
    passed = threes if evaluation.judge(3.0, threshold) else []
    print(f"\ngroundedness が 3 点：{len(threes)} 件、そのうち pass（合格）：{len(passed)} 件"
          f"（しきい値 {threshold:g} で判定。採点した {len(records)} 件のうち）")
    for r in passed[:3]:
        print(f"  {r['question_id']} {agentic.METHOD_LABELS[r['method']]} 第{r['run']}回：" + show.one_line(r["builtin"]["groundedness"]["reason"], 100))
    if not threes:
        print("3 点がないのは、この答えがどれも資料を使って答えているからです（3 点は、確認の質問のように根拠にできる情報がない答えに付く点）。")
        print("3 点が pass になる様子は、score_one.py の「確認の質問」の確かめで見られます。")
    first = next(r for r in records if r.get("builtin"))
    show.section("評価器の出力の欄の名前")
    print("  " + ", ".join(first["builtin"]["groundedness"]["fields"]))
else:
    print("組み込みの評価器の採点がないので、ここは飛ばします。")

# %% [markdown]
# ## 6. 2通りの採点は一致するか
#
# 「資料に基づくか」を見る自前の観点1と groundedness、「質問に答えているか」を見る自前の観点2と relevance を、1件ずつ比べます。
# **見るところ**：同じ点の割合と、1点以内の割合。基準の文が違えば、点は同じにならない。

# %%
if has_builtin:
    show.section("自前の採点と組み込みの評価器の一致")
    rows = []
    for a, b, label in (("own.faithfulness", "builtin.groundedness", "根拠への忠実さ と groundedness"),
                        ("own.answers_question", "builtin.relevance", "質問への答え と relevance")):
        rows.append(evaluation.agreement_row(label, evaluation.agreement(records, a, b)))      # 評価器が全部スキップなら「比べる相手なし」
    show.table(["組み合わせ", "件数", "同じ点", "1点以内", "平均の差（自前 - 組み込み）"], rows)
else:
    print("組み込みの評価器の採点がないので、ここは飛ばします。")

# %%
show.section("呼び出しの数とトークン（保存した採点・答えから集計）")
own_n = len(records)
b_n = sum(1 for r in records if r.get("builtin"))
own_in = sum(r["own_tokens"]["input_tokens"] for r in records)
own_out = sum(r["own_tokens"]["output_tokens"] for r in records)
b_in = sum(r["builtin"][n]["input_tokens"] for r in records if r.get("builtin") for n, _ in evaluation.BUILTIN_METRICS)
b_out = sum(r["builtin"][n]["output_tokens"] for r in records if r.get("builtin") for n, _ in evaluation.BUILTIN_METRICS)
rows = [["自前の採点", own_n, f"{own_in:,} / {own_out:,}"], ["組み込みの評価器", b_n * 2, f"{b_in:,} / {b_out:,}"]]
a_items = [i for i in (agentic.load_answers() or {"items": []})["items"] if i["question_id"] in ids and i["run"] <= runs]
a_in = sum(i["tokens"]["answer_input"] for i in a_items)
a_out = sum(i["tokens"]["answer_output"] for i in a_items)
p_in = sum(i["tokens"]["planning_input"] for i in a_items)
p_out = sum(i["tokens"]["planning_output"] for i in a_items)
rows += [["（19）答えの生成", len(a_items), f"{a_in:,} / {a_out:,}"],
         ["（19）質問の分解", sum(i["planning_calls"] for i in a_items), f"{p_in:,} / {p_out:,}"]]
show.table(["何に", "LLM の呼び出し", "トークン（入力 / 出力）"], rows)
print(f"\n採点の LLM のトークン：入力 {own_in + b_in:,} / 出力 {own_out + b_out:,}"
      f"　19 を含めた合計：入力 {own_in + b_in + a_in + p_in:,} / 出力 {own_out + b_out + a_out + p_out:,}")
print("採点の結果は applied/_work/20_scores.json にあります（Git には入りません）。")
