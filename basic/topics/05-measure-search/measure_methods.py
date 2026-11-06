# %% [markdown]
# # 検索の良し悪しを数字で測る（60問×4方式）
#
# 実行：`python measure_methods.py`
#
# 正解の武将を決めた質問（data/sengoku/questions.json の60問）を、4つの方式で検索し、
# nDCG@10・再現率@10・1位の割合の平均を出す。そのあと、方式によって勝ち負けが入れ替わる質問を並べる。
# 自分で考えた質問と正解を、先頭の `MY_QUESTIONS` に足すこともできる。
#
# Azure の呼び出し：質問の埋め込み（数回）と検索 240 回。セマンティックランカーを質問の数だけ使う（月ごとの無料枠を、チームの AI Search 全体で使う）。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:            # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib
from lib import cells, metrics, search, state, vectorstore
from lib.clients import search_client
from lib.config import SENGOKU_EMBEDDINGS, SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, sengoku_index_name
from lib.data import load_bushou, load_questions
from lib.show import METHOD_LABELS, section, table, title

cells.start()

# ===== 変えてよい値 ==========================================================
K = 10                  # 上位何件で測るか
EXAMPLES = 2            # 入れ替わる質問を、種類ごとに何問ずつ見せるか
# 自分の質問と正解。（質問, 正解の武将の名前）を1〜3問。名前は bushou.json の name と同じに書く
MY_QUESTIONS = [
    # ("鉄砲を3段に構えて武田の騎馬隊を破った戦いで、織田と組んだ大名は誰ですか。", "徳川家康"),
]
REBUILD = False
# ============================================================================

# %% [markdown]
# ## 準備
#
# 03-vector-search までを終えた、武将のインデックスを使う。
# 自分の質問の正解の名前が武将の一覧にないときは、その質問を飛ばして知らせる。

# %%
state.ensure("05", rebuild=REBUILD)
sc = search_client(sengoku_index_name())
people = load_bushou()
names = {p["id"]: p["name"] for p in people}
id_of = {p["name"]: p["id"] for p in people}

questions = [{"qid": q["qid"], "question": q["question"], "answer_ids": q["answer_ids"], "mine": False}
             for q in load_questions()]
for i, (text, answer) in enumerate(MY_QUESTIONS, start=1):
    answers = [answer] if isinstance(answer, str) else list(answer)
    missing = [a for a in answers if a not in id_of]
    if missing:
        print(f"自分の質問 {i} を飛ばします：正解の名前 {'、'.join(missing)} が武将の一覧にありません（bushou.json の name と同じに書く）。")
        continue
    questions.append({"qid": f"my{i}", "question": text, "answer_ids": [id_of[a] for a in answers], "mine": True})
title(f"{len(questions)}問を、4つの方式で検索する")

# %% [markdown]
# ## 検索する
#
# 質問を埋め込み（埋め込み済みファイルになければ Azure OpenAI で）、1問ずつ4つの方式で上位50件を取る。

# %%
vectors = vectorstore.get_vectors([q["question"] for q in questions], SENGOKU_EMBEDDINGS, use_file=True, label="質問")
ranked = {m: [] for m in METHOD_LABELS}          # 方式 → 質問ごとの id の並び
for n, (q, vec) in enumerate(zip(questions, vectors), start=1):
    for m in METHOD_LABELS:
        hits = search.by_method(m, sc, q["question"], vec, SENGOKU_VECTOR_FIELD, SENGOKU_SEMANTIC, select=["id"])
        ranked[m].append([h["id"] for h in hits])
    if n % 10 == 0 or n == len(questions):
        print(f"  検索 {n}/{len(questions)} 問")
scores = {m: [metrics.evaluate(ids, q["answer_ids"], K) for ids, q in zip(ranked[m], questions)] for m in METHOD_LABELS}

# %% [markdown]
# ## 1. 4つの方式の平均
#
# 見るところ
# - 平均では、ハイブリッド＋ランカーが高くなりやすい。
# - ハイブリッドが、いつもキーワードとベクトルの両方より良いとは限らない。
#   2026-11-03 にこの60問で測ったときは、nDCG@10 がキーワード 0.58、ベクトル 0.38、ハイブリッド 0.56、ハイブリッド＋ランカー 0.76 だった
#   （武将の本文には合戦の名前などの固有名詞が多く、キーワードが強いデータ）。
# - 平均の差だけで「いつもこの方式が良い」とは言えない。次の表で、1問ずつ見ると勝ち負けが入れ替わる。

# %%
section(f"用意した{sum(not q['mine'] for q in questions)}問の平均")


def average_rows(select) -> list:
    rows = []
    for m in METHOD_LABELS:
        chosen = [s for s, q in zip(scores[m], questions) if select(q)]
        a = metrics.average(chosen)
        rows.append([METHOD_LABELS[m], f"{a['ndcg']:.3f}", f"{a['recall']:.3f}", f"{a['hit1']:.3f}"])
    return rows


HEADERS = ["方式", f"nDCG@{K}", f"再現率@{K}", "1位の割合"]
table(HEADERS, average_rows(lambda q: not q["mine"]))

# %% [markdown]
# ## 2. 方式によって勝ち負けが入れ替わる質問
#
# 見るところ
# - キーワードが勝つ質問：本文にしかない珍しい語（合戦の名前など）を含む質問。ベクトルは意味の近い別の武将に引かれる。
# - ベクトルが勝つ質問：質問と本文で言い方が違う（言い換え）質問。
# - ハイブリッドでかえって下がる質問：片方が上位でも、もう片方で順位が低いと、合わせた順位が下がることがある。
#   片方にしか出ない文書は、両方に出る多くの文書に抜かれ、上位50件の外まで落ちることもある（例 q19 の紀尾井坂の変）。
# - ランカーで上がる質問：ハイブリッドの候補を、質問と本文の意味を読んで並べ直すと上がる。
# 順位の「圏外」は上位50件にないこと。


# %%
def rank_of(m: str, i: int):
    return scores[m][i]["rank"]


def gap(a, b) -> int:
    """順位の差（圏外は 51 位として数える）。a が b より上なら正。"""
    return (b or 51) - (a or 51)


KINDS = [
    ("キーワードが勝つ", lambda i: gap(rank_of("keyword", i), rank_of("vector", i))),
    ("ベクトルが勝つ", lambda i: gap(rank_of("vector", i), rank_of("keyword", i))),
    ("ハイブリッドでかえって下がる",
     lambda i: gap(min(rank_of("keyword", i) or 51, rank_of("vector", i) or 51), rank_of("hybrid", i))),
    ("ランカーで上がる", lambda i: gap(rank_of("hybrid_ranker", i), rank_of("hybrid", i))),
]


def label(rank) -> str:
    return f"{rank}" if rank else "圏外"


prepared = [i for i, q in enumerate(questions) if not q["mine"]]
for kind, score in KINDS:
    found = sorted((i for i in prepared if score(i) > 0), key=score, reverse=True)
    section(f"{kind}（{len(found)}問。差の大きい順に{min(EXAMPLES, len(found))}問）")
    rows = []
    for i in found[:EXAMPLES]:
        q = questions[i]
        rows.append([q["qid"], q["question"][:30] + "…", "、".join(names[a] for a in q["answer_ids"])]
                    + [label(rank_of(m, i)) for m in METHOD_LABELS])
    if rows:
        table(["質問", "文", "正解"] + [METHOD_LABELS[m] for m in METHOD_LABELS], rows)
    else:
        print("  ありません。")

# %% [markdown]
# ## 3. 自分の質問
#
# `MY_QUESTIONS` に足した質問の順位と、足したあとの平均。
# 正解を決めた質問を作るのは手間がかかる。けれど、これがないと方式の良し悪しを数字で比べられない。

# %%
mine = [i for i, q in enumerate(questions) if q["mine"]]
if not mine:
    print("自分の質問はまだありません。先頭の MY_QUESTIONS に（質問, 正解の武将の名前）を1〜3問書いて、もう一度実行してください。")
else:
    section("自分の質問の順位")
    rows = [[questions[i]["question"][:30] + "…", "、".join(names[a] for a in questions[i]["answer_ids"])]
            + [label(rank_of(m, i)) for m in METHOD_LABELS] for i in mine]
    table(["文", "正解"] + [METHOD_LABELS[m] for m in METHOD_LABELS], rows)
    section(f"自分の質問を足した{len(questions)}問の平均")
    table(HEADERS, average_rows(lambda q: True))

print(f"\nセマンティックランカーを {len(questions)} 回使いました（月ごとの無料枠を、チームの AI Search 全体で使います）。")
