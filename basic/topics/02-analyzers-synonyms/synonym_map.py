# %% [markdown]
# # 辞書（同義語マップ）で、言い換えの外れを直す
#
# 実行：`python synonym_map.py`
#       `python synonym_map.py --rule "眼球, 目玉"`（自分のルールを1行足す。何回でも書ける）
#
# 辞書 `sengoku-synonyms` を作り、武将のインデックスの検索する項目につなぐ。
# 言い換えの質問3つを、辞書をつなぐ前と後でキーワード検索し、正解の順位を並べる。
#
# ルールの書き方
# - `北海道, 蝦夷地`：どちらで検索しても、両方で探す（同等）
# - `第六天魔王 => 織田信長`：左の語で検索されたら、右の語に置き換えて探す（一方向）

# %%
import argparse
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:            # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib
from lib import cells, state, synonyms
from lib.clients import search_client
from lib.config import require_admin_key
from lib.data import answer_rank, load_questions, names_by_id
from lib.show import section, table, title

cells.start()

# ===== 変えてよい値 ==========================================================
QUESTIONS = ["q21", "q23", "q28"]     # 言い換えの質問（questions.json の qid）
RULES = ["北海道, 蝦夷地"]             # 用意したルール（q28 の「北海道」と本文の「蝦夷地」）
MY_RULES = []                          # 自分で足すルール。例 ["眼球, 目玉"]（--rule でも足せる）
RESTORE = True                         # 最後に（途中で止まったときも）辞書を項目から外す。辞書のルールは残る
REBUILD = False                        # True にすると、武将のインデックスを作り直してから始める
# ============================================================================

parser = argparse.ArgumentParser(description="同義語マップで言い換えの外れを直す")
parser.add_argument("--rule", action="append", default=[], help="自分のルールを1行足す（例 \"眼球, 目玉\"）")
args, _ = parser.parse_known_args()
my_rules = MY_RULES + args.rule

# %% [markdown]
# ## 準備
#
# 操作する相手（武将のインデックスと辞書）を、ここで1回だけ決める（`T`）。
# 別の名前を渡すと、辞書やインデックスを変える前に止まる（名前は固定）。
# 前の実行で辞書がつながったままなら、外してから「前」を測る。
#
# 後片付け：スクリプトのときは、途中で止まっても最後に辞書を外す（`RESTORE = True` のとき）。
# Notebook では、途中で止まったときも、最後の「後片付け」のセルを実行する。

# %%
require_admin_key()      # メンバー用のキー（検索だけ）なら、ここで止まる
state.ensure("02", rebuild=REBUILD)
T = synonyms.target()
sc = search_client(T.index_name)
names = names_by_id()
qs = {q["qid"]: q for q in load_questions()}


def cleanup() -> None:
    """RESTORE = True のとき、辞書を項目から外す（何度呼んでもよい）。"""
    if RESTORE:
        synonyms.attach(T, False)


cells.at_exit(cleanup)
synonyms.attach(T, False)


def ranks() -> dict:
    """言い換えの質問ごとの、キーワード検索での正解の順位。"""
    out = {}
    for qid in QUESTIONS:
        hits = list(sc.search(search_text=qs[qid]["question"], top=50, select=["id"]))
        out[qid] = answer_rank(hits, qs[qid]["answer_ids"])
    return out


before = ranks()

# %% [markdown]
# ## 辞書を作って、つなぐ
#
# 辞書は項目に割り当てる設定なので、つないだあとは、検索の要求で辞書を指定しなくても効く。
# ルールを入れ替えた直後は、しばらく古いルールで検索されることがある。
# そのため、確認用の1行を一緒に入れ、それが効き始めるまで待ってから検索する（ふつうは数秒）。
# 同義語マップは AI Search 全体で3つまで（Basic）。作れないときは、案内を出して止まる。

# %%
title(f"辞書 {T.map_name} を作り、検索する項目につなぐ")
rules = RULES + my_rules
for r in rules:
    print(f"  {r}")
waited = synonyms.apply(T, rules)
print(f"\nつなぎました（項目：{'、'.join(synonyms.SEARCH_FIELDS)}）。効き始めるまで {waited:.0f} 秒待ちました。")
after = ranks()

# %% [markdown]
# ## 前と後の順位
#
# 見るところ
# - 用意したルール（北海道, 蝦夷地）だけで、q28 の榎本武揚が上がる。q21・q23 は変わらない。
# - `--rule "眼球, 目玉"` を足すと q23 の夏侯惇が上がる。
# - q21 の柴田勝家は、1行では上がりきらない（「器」と「水瓶」、「立てこもった」と「籠城」、「壊して」と「割って」の3行が要る）。
#   言い換えは質問ごとに違うので、辞書で全部を先回りするのは手間がかかる。
#   **辞書を書かずに、意味の近さで当てるのが、次の 03-vector-search（ベクトル検索）**。


# %%
def label(rank) -> str:
    return f"{rank} 位" if rank else "圏外"


section("正解の順位（キーワード検索、上位50件まで）")
rows = []
for qid in QUESTIONS:
    b, a = before[qid], after[qid]
    change = "上がった" if (a or 99) < (b or 99) else ("下がった" if (a or 99) > (b or 99) else "同じ")
    rows.append([qid, qs[qid]["question"][:24] + "…", names[qs[qid]["answer_ids"][0]], label(b), label(a), change])
table(["質問", "文", "正解", "辞書なし", "辞書あり", "変化"], rows)

# %% [markdown]
# ## 後片付け
#
# `RESTORE = True` のとき、辞書を項目から外す。辞書のルールは、このスクリプトで入れたものが残る
# （もう一度実行すれば、つなぎ直せる）。つないだままにすると、このあとのトピックのキーワード検索の順位も変わる。
# Notebook では、途中のセルで止まったときも、このセルを実行する。

# %%
cleanup()
if RESTORE:
    print(f"辞書 {T.map_name} を項目から外しました（辞書のルールは残っています）。")
else:
    print(f"辞書 {T.map_name} はつないだままです。外すには RESTORE = True にしてもう一度実行します。")
print("\n発展：python tuning.py（語の重み・項目の重み・除外・一方向の置き換えで、順位を調整する）")
print("次は 03-vector-search：python ../03-vector-search/embed.py")
