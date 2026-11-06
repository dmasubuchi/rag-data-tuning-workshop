# %% [markdown]
# # RRF（順位の逆数の合計）の計算の途中を追う
#
# 1. キーワード検索で、一致した武将をすべて取る（順位つき）
# 2. ベクトル検索で、近い上位 50 人を取る（順位つき）
# 3. 武将ごとに「1 / (60 + 順位)」を方式ごとに計算して足す（これが RRF）
# 4. 自分の計算の順位と、AI Search のハイブリッド検索の順位を並べて照合する
#
# どちらかの方式で見つからなかった武将は、その方式の分を 0 として足します。
#
# 実行：`python rrf.py`
# 自分の質問：`python rrf.py --q "自分の質問"`
#
# 前提：03-vector-search が終わっていること（武将にベクトルが入っていること）。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, llm, state
from lib.clients import search_client
from lib.config import SENGOKU_VECTOR_FIELD, sengoku_index_name
from lib.data import names_by_id, qid_note, resolve_question
from lib.search import TOP_ALL, hybrid, keyword, vector
from lib.show import MEASURED_TOP, rank_label, section, table, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None     # None のとき、questions.json の山場の質問。自分の質問は "…" と書く（--q でも指定できる）
RRF_K = 60          # RRF の定数（AI Search は 60）
SHOW = 10           # 表に出す件数
K = 50              # ベクトル側の候補数
REBUILD = False     # True にすると、武将のインデックスを、03 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="RRF の計算の途中を追う")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 3つの検索結果を取る
# キーワード（一致した武将すべて）、ベクトル（近い上位 `K` 人）、AI Search のハイブリッドを取ります。
# **見るところ**：キーワード側とベクトル側の人数。

# %%
question, q = resolve_question(QUESTION, "climax")

state.ensure("04", rebuild=REBUILD)      # 武将にベクトルが入っているか（03-vector-search の embed.py が終わっているか）
client = search_client(sengoku_index_name())

title("RRF の計算の途中")
print(f"質問：{question}{qid_note(q)}")
vec = llm.embed_one(question)

kw_hits = keyword(client, question, top=TOP_ALL)
vec_hits = vector(client, vec, SENGOKU_VECTOR_FIELD, k=K, top=K)
az_hits = hybrid(client, question, vec, SENGOKU_VECTOR_FIELD, k=K, top=MEASURED_TOP)
print(f"\nキーワード検索で一致した武将：{len(kw_hits)} 人（すべて取得）")
print(f"ベクトル検索の候補：{len(vec_hits)} 人（k={K}）")
print(f"定数：{RRF_K}　　1人あたりの計算：1/({RRF_K}+キーワード順位) ＋ 1/({RRF_K}+ベクトル順位)")

# %% [markdown]
# ## 2. RRF を自分で計算する
# 武将ごとに、方式ごとの `1 / (RRF_K + 順位)` を足します。並べ方は、合計の大きい順。同点のときは、順位が良いほう（小さいほう）、それでも同じなら id の順です。

# %%
def rrf_table(kw_ids: list, vec_ids: list, rrf_k: int = RRF_K) -> list:
    """RRF の計算。各行は辞書：id、kw（キーワードの順位 または None）、vec、kw_score、vec_score、total。

    並べ方：合計の大きい順。同点のときは、順位が良いほう（小さいほう）、それでも同じなら id の順。
    """
    kw_rank = {i: r for r, i in enumerate(kw_ids, start=1)}
    vec_rank = {i: r for r, i in enumerate(vec_ids, start=1)}
    rows = []
    for i in dict.fromkeys(kw_ids + vec_ids):
        kr, vr = kw_rank.get(i), vec_rank.get(i)
        ks = 1.0 / (rrf_k + kr) if kr else 0.0
        vs = 1.0 / (rrf_k + vr) if vr else 0.0
        rows.append({"id": i, "kw": kr, "vec": vr, "kw_score": ks, "vec_score": vs, "total": ks + vs})
    rows.sort(key=lambda r: (-round(r["total"], 12), min(x for x in (r["kw"], r["vec"]) if x), r["id"]))
    return rows


rows = rrf_table([h["id"] for h in kw_hits], [h["id"] for h in vec_hits], RRF_K)
az_rank = {h["id"]: r for r, h in enumerate(az_hits, start=1)}
answer_ids = set(q["answer_ids"]) if q else set()

# %% [markdown]
# ## 3. 自分の計算の上位を表にする
# Azure の列は、AI Search のハイブリッド検索の順位です。
# **見るところ**：自分の計算の順位と、Azure の列（AI Search の順位）が合うか。

# %%
names = names_by_id()
calc = f"1/({RRF_K}+順位)"
headers = ["順位", "武将", "KW順位", calc, "ベクトル順位", calc, "合計", "Azure", ""]


def line(pos: int, r: dict) -> list:
    tie = "＝同点" if sum(1 for x in rows if round(x["total"], 12) == round(r["total"], 12)) > 1 else ""
    mark = "◀ 正解" if r["id"] in answer_ids else ""
    return [pos, names.get(r["id"], r["id"]), r["kw"], f"{r['kw_score']:.6f}", r["vec"], f"{r['vec_score']:.6f}",
            f"{r['total']:.6f}", az_rank.get(r["id"]), (tie + " " + mark).strip()]


shown_rows = [line(pos, r) for pos, r in enumerate(rows[:SHOW], start=1)]
shown = {r["id"] for r in rows[:SHOW]}
for pos, r in enumerate(rows, start=1):
    if r["id"] in answer_ids and r["id"] not in shown:      # 正解が圏外なら、最後に足す
        shown_rows.append(["..."] + [""] * (len(headers) - 1))
        shown_rows.append(line(pos, r))

section(f"自分の計算の上位 {SHOW} 人（Azure の列は AI Search のハイブリッド検索の順位）")
table(headers, shown_rows)

# %% [markdown]
# ## 4. AI Search のハイブリッド検索と照合する
# 順位が合わない箇所があれば、まず3つの条件（候補の範囲、重み、同点の扱い）の違いを確かめます。原因は、確かめるまで断定しません。
# **見るところ**：上位の順番・顔ぶれが一致した人数と、正解の順位。

# %%
section("照合：自分の計算 と AI Search のハイブリッド検索")
mine = [r["id"] for r in rows[:MEASURED_TOP]]
azure = [h["id"] for h in az_hits]
n = min(SHOW, len(mine), len(azure))
same_order = sum(1 for a, b in zip(mine[:n], azure[:n]) if a == b)
same_set = len(set(mine[:n]) & set(azure[:n]))
print(f"  上位 {n} 人の順番が同じ位置で一致：{same_order} / {n} 人")
print(f"  上位 {n} 人に入る顔ぶれが一致　　：{same_set} / {n} 人")
diff = [(i + 1, names.get(a, a), names.get(b, b)) for i, (a, b) in enumerate(zip(mine[:n], azure[:n])) if a != b]
for pos, a, b in diff[:5]:
    print(f"    {pos}位が違う：自分の計算 {a} ／ AI Search {b}")
ties = len({round(r["total"], 12) for r in rows[:n]}) < n
if diff:
    print("  順位が合わない箇所があります。まず次の3つの条件の違いを確かめます。原因は、確かめるまで断定しません。")
    print("    ・候補の範囲（キーワード側を何件まで使うか、ベクトル側の k）")
    print("    ・重み（ここでは両方 1）")
    print("    ・同点の扱い" + ("（この表には同点があります）" if ties else ""))
else:
    print("  上位の順位が一致しました。ハイブリッドの順位は、この足し算で説明できます。")
if answer_ids:
    mine_pos = next((pos for pos, r in enumerate(rows, start=1) if r["id"] in answer_ids), None)
    az_pos = next((pos for pos, h in enumerate(az_hits, start=1) if h["id"] in answer_ids), None)
    print(f"\n  正解の順位：自分の計算 {rank_label(mine_pos, len(rows))}　／　AI Search {rank_label(az_pos, len(az_hits))}")

print("\n同点のときの並べ方：順位が良いほうを先にし、それでも同じなら id の順にしています（AI Search の同点の扱いは公開されていません）。")
