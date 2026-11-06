# %% [markdown]
# # 20 答えを評価する（1）1つの答えを、2通りの方法で採点する
#
# 19 で作った答え1件を、LLM に採点させます。採点の方法は2通りあります。
#
# - 自前の採点プロンプト：採点の基準を日本語の文で書き、1〜5 で採点させる。観点は3つ（根拠への忠実さ・質問への答え・要点の網羅）
# - 組み込みの評価器：azure-ai-evaluation の GroundednessEvaluator（資料に基づいているか）と RelevanceEvaluator（質問に答えているか）。1〜5
#
# 実行：python score_one.py
#       python score_one.py --id q06 --method plain
#       python score_one.py --answer "自分で書いた答え"      答えを自分で書き換えて、点がどう変わるか見る
#
# 前提：19 の make_answers.py で答えを保存してあること。なければ、その場で1件だけ作ります（保存はしません）。
# 組み込みの評価器には、次が要ります（なければ、自前の採点だけを行います）。
#   pip install -r applied/requirements-eval.txt     （Repo 直下で）
#
# 見るところ：
#   1. 自前の採点：観点ごとの点と理由。「要点の網羅」は、想定の要点（資料から作ったもの）と比べる
#   2. 組み込みの評価器：出力の欄の名前（版で変わる。gpt_ 付きの欄はない）。groundedness は資料に基づくか、relevance は質問に答えているか
#   3. 「注意」の表：確認の質問のように、資料に基づかない答えでも groundedness が 3 で「合格」になる
#
# 呼び出しの数（1回の実行）：自前の採点 1 回、組み込みの評価器 2 回、注意の確かめで 2 回。合計 LLM 5 回（保存がないときは、答えの生成などが加わる）。

# %%
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import agentic, evaluation, show  # noqa: E402

# ===== 変えてよい値 ==========================================================
QUESTION_ID = "q06"     # 採点する質問の番号 q01〜q10（--id でも指定できる）
METHOD = "agentic"      # plain（① 普通の検索）か agentic（② エージェント型検索）（--method でも指定できる）
RUN = 1                 # 19 で保存した何回目の答えか（--run でも指定できる）
ANSWER = None           # None のとき、保存した答え。自分で書いた答えを採点するなら "…" と書く（--answer でも指定できる）
SHOW_THRESHOLD_DEMO = True   # True のとき、「注意」の確かめ（確認の質問を採点する、LLM 2 回）をする
# ============================================================================

parser = argparse.ArgumentParser(description="1つの答えを、自前の採点と組み込みの評価器で採点する")
parser.add_argument("--id", help="質問の番号（q01〜q10）")
parser.add_argument("--method", choices=agentic.METHODS, help="方式")
parser.add_argument("--run", type=int, help="何回目の答えか")
parser.add_argument("--answer", help="自分で書いた答え")
args, _ = parser.parse_known_args()
qid = args.id or QUESTION_ID
method = args.method or METHOD
run = args.run or RUN
custom_answer = args.answer or ANSWER

question = next((q for q in agentic.load_questions() if q["id"] == qid), None)
if question is None:
    raise lib.config.SetupError(f"質問の番号 {qid!r} はありません。q01〜q10 のどれかにしてください。")

show.title(f"採点する答え：{qid} {agentic.METHOD_LABELS[method]} 第{run}回")
print(f"質問：{question['question']}")
has_builtin = evaluation.builtin_available()
if not has_builtin:
    print("\n（azure-ai-evaluation が入っていないので、組み込みの評価器は使いません。入れるには：）")
    print(evaluation.INSTALL_HINT)

# %% [markdown]
# ## 1. 採点する答えと、想定の要点
#
# 保存した答え（19）を読みます。**見るところ**：答えが、想定の要点をどれだけ含んでいるか（自分の目で先に確かめてから、点を見てください）。

# %%
saved = agentic.load_answers()
item = None
if saved:
    item = next((i for i in saved["items"] if (i["question_id"], i["method"], i["run"]) == (qid, method, run)), None)
if item is None:
    print("19 の保存に該当の答えがないので、その場で作ります（保存はしません）。")
    made = agentic.run_method(method, question["question"])
    item = {"question": question["question"], "context": made["context"], "answer": made["answer"]}
answer = custom_answer or item["answer"]

show.section("答え" + ("（自分で書いたもの）" if custom_answer else ""))
print(answer)
show.section("想定の要点（資料から作ったもの）")
for p in question["expect"]:
    print(f"  - {p}")
show.section("答えに渡した資料")
show.table(["番号", "資料（ファイル#チャンク）"],
           [[n, agentic.short_id(c["chunk_id"], c["title"])] for n, c in enumerate(item["context"], start=1)])

# %% [markdown]
# ## 2. 自前の採点プロンプトで採点する
#
# 採点の基準は `lib/evaluation.py` の OWN_SYSTEM に、日本語の文で書いてあります（1〜5 の各段の意味）。LLM は 1 回呼びます。
# **見るところ**：観点ごとの点と理由。「要点の網羅」が低いとき、理由が足りない要点を挙げているか。

# %%
own = evaluation.score_own(question["question"], item["context"], question["expect"], answer)
show.section("自前の採点")
show.table(["観点", "点（1〜5）", "理由"],
           [[label, own[key]["score"], show.one_line(own[key]["reason"], 70)] for key, label in evaluation.OWN_METRICS])

# %% [markdown]
# ## 3. 組み込みの評価器（azure-ai-evaluation）で採点する
#
# GroundednessEvaluator には質問・答え・資料（context）を、RelevanceEvaluator には質問・答えを渡します。それぞれ LLM を 1 回呼びます。
# gpt-5 系のモデルでは、評価器を作るときに `is_reasoning_model=True` が要ります（付けないと「max_tokens は使えない」という 400 になる）。
# **見るところ**：出力の欄の名前の一覧。公式の古い例にある `gpt_groundedness` のような欄は、この版にはありません。

# %%
builtin = None
if has_builtin:
    evaluators = evaluation.builtin_evaluators()
    builtin = evaluation.score_builtin(evaluators, question["question"], item["context"], answer)
    show.section("組み込みの評価器")
    show.table(["評価器", "点（1〜5）", "しきい値", "合否", "理由（一部）"],
               [[label, builtin[name]["score"], builtin[name]["threshold"], builtin[name]["result"],
                 show.one_line(builtin[name]["reason"], 60)] for name, label in evaluation.BUILTIN_METRICS])
    show.section("評価器の出力の欄の名前（groundedness のもの）")
    print("  " + ", ".join(builtin["groundedness"]["fields"]))
else:
    print("azure-ai-evaluation が入っていないので、ここは飛ばします。")

# %% [markdown]
# ## 4. 注意：groundedness の 3 は「根拠にできる情報がない」の段
#
# 組み込みの groundedness の採点基準では、3 は「答えが資料に基づいていない（確認の質問、あいさつなど、根拠にできる情報がない）」の段です。
# ところが、しきい値の既定は 3 で、**3 以上が合格**です。つまり、資料に基づかない答えでも、3 なら「合格（pass）」になります。
# 確認の質問を答えとして採点して確かめます。**見るところ**：groundedness が 3 の「pass」になるか。relevance（質問に答えているか）は低いか。

# %%
CLARIFYING_ANSWER = "ご質問ありがとうございます。どの求人（求人番号）について知りたいか、教えていただけますか。"
if has_builtin and SHOW_THRESHOLD_DEMO:
    demo = evaluation.score_builtin(evaluators, question["question"], item["context"], CLARIFYING_ANSWER)
    show.section("確認の質問を答えとして採点する")
    print(f"答え（確認の質問）：{CLARIFYING_ANSWER}")
    show.table(["評価器", "点（1〜5）", "合否", "理由（一部）"],
               [[label, demo[name]["score"], demo[name]["result"], show.one_line(demo[name]["reason"], 60)]
                for name, label in evaluation.BUILTIN_METRICS])
    print("\n点のつけ方は実行するたびに少し変わります。groundedness が 3 のとき、しきい値 3 では pass（合格）になります。")
    print("資料に基づく答えかどうかを見たいときは、合否ではなく点そのものと、しきい値（threshold）を自分で決めて使ってください。")
else:
    print("確かめは飛ばしました（azure-ai-evaluation が入っていないか、SHOW_THRESHOLD_DEMO = False です）。")

# %%
show.section("この実行の呼び出し")
agentic.usage_table()
llm_in, llm_out = agentic.USAGE.llm_tokens()
print(f"\nLLM のトークンの合計：入力 {llm_in:,} / 出力 {llm_out:,}")
print("全 10 問 × 2 方式 × 3 回の採点と、点のぶれは score_all.py で見ます（進行役が実行します）。")
