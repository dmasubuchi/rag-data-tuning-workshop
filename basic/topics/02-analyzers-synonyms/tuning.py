# %% [markdown]
# # （発展）検索の順位を人が調整する
#
# 実行：`python tuning.py`
#
# 同義語のほかにも、AI Search には順位を人が調整する仕組みがある。武将のデータで、入れる前と後の上位を並べる。
#
# 1. 語の重み：検索語ごとに重みを付ける（`上杉^3`、`上杉^0.2`）
# 2. 項目の重み：名前の項目で当たった武将を重く、プロフィールで当たった武将を軽くする（スコアリングプロファイル）
# 3. 除外の落とし穴：「小早川」から「隆景」を外したいとき、`-隆景` と書くと何が起きるか
# 4. 一方向の置き換え：データにない呼び名（「第六天魔王」「関白」）を、武将に結ぶ
#
# 設定には2種類ある。
# - 検索の要求に付ける設定：語の重み（`^`）、searchMode、フィルター、使うスコアリングプロファイルの名前。その検索にだけ効く。
# - インデックスに持つ設定：スコアリングプロファイルの定義、項目への同義語マップの割り当て。
#   同義語マップは、項目に割り当てると、検索の要求で指定しなくても、その項目を検索するたびに効く。
#   スコアリングプロファイルは、定義しただけでは効かない。検索の要求で名前を指定したとき（または既定のプロファイルにしたとき）に効く。
# どちらも、文書を登録し直す必要はない。
#
# Google の Vertex AI Search の「順位を下げる（bury）」のような、負の数で下げる指定は、Azure AI Search の公式資料では確認できていない。
# 重みは正の数の倍率（公式資料）。1 より小さい倍率を付けると、このデータでは順位が下がった（下の 1・2 で確かめる）。

# %%
import copy
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:            # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib
from lib import cells, state, synonyms
from lib.clients import index_client, search_client
from lib.config import require_admin_key
from lib.data import names_by_id
from lib.show import section, table, title

cells.start()

# ===== 変えてよい値 ==========================================================
TOP = 5                                       # 並べる人数
BOOSTS = ["上杉 武田", "上杉^3 武田", "上杉 武田^3", "上杉^0.2 武田", "上杉 武田^0.2"]   # 1. 語の重みを付けた検索語
FIELD_QUERY = "上杉"                          # 2. 項目の重みを試す検索語
PROFILES = {                                  # 2. スコアリングプロファイル（名前: 項目ごとの重み。書かない項目は 1）
    "name-first": {"name": 5, "aliases": 3},
    "profile-light": {"profile": 0.2},
}
EXCLUDE_BASE = "小早川"                        # 3. 除外を試す検索語
EXCLUDE_WORD = "隆景"                          # 3. 外したい武将の名前の一部
EXCLUDE_ID = "b070"                            # 3. 外したい武将の id（小早川隆景）
ONE_WAY_RULES = ["第六天魔王 => 織田信長", "関白 => 太閤"]   # 4. データにない呼び名を結ぶ
ONE_WAY_QUERIES = ["第六天魔王", "関白", "関白になった武将は誰ですか"]
RESTORE = True                                # 最後に（途中で止まったときも）、プロファイルと辞書を実行前の状態に戻す
REBUILD = False
# ============================================================================

# %% [markdown]
# ## 準備
#
# 操作する相手（武将のインデックスと辞書）を、ここで1回だけ決める（`T`）。
# 変える前の状態（2 で使う名前のプロファイル、辞書のルール、項目へのつなぎ）を取っておき、最後にその状態に戻す。
#
# 後片付け：スクリプトのときは、途中で止まっても最後に戻す（`RESTORE = True` のとき）。
# Notebook では、途中で止まったときも、最後の「後片付け」のセルを実行する。

# %%
require_admin_key()      # メンバー用のキー（検索だけ）なら、ここで止まる
state.ensure("02", rebuild=REBUILD)
T = synonyms.target()
ic = index_client()
sc = search_client(T.index_name)
names = names_by_id()

saved_profiles = [copy.deepcopy(p) for p in (ic.get_index(T.index_name).scoring_profiles or []) if p.name in PROFILES]
saved_synonyms = synonyms.snapshot(T)
restored = []          # 後片付けを済ませたら印を入れる（スクリプトの終わりに2回目を呼ばないため）


def restore_profiles() -> None:
    """PROFILES の名前のプロファイルを、実行前に戻す（前からあった同じ名前のものは、その定義に戻す。なかったものは消す）。"""
    synonyms.check(T)
    index = ic.get_index(T.index_name)
    others = [p for p in (index.scoring_profiles or []) if p.name not in PROFILES]
    index.scoring_profiles = others + saved_profiles
    ic.create_or_update_index(index)


def cleanup() -> None:
    if RESTORE and not restored:
        restore_profiles()
        synonyms.restore(T, saved_synonyms)
        restored.append(True)


cells.at_exit(cleanup)


def top_names(hits: list, n: int = TOP) -> str:
    return "、".join(names.get(h["id"], h["id"]) for h in hits[:n]) or "（0件）"


def search(text: str, **kw) -> list:
    return list(sc.search(search_text=text, top=50, select=["id"], **kw))


# %% [markdown]
# ## 1. 語の重み（`語^数`）
#
# 見るところ
# - `^3` を付けた語を持つ武将が上に来る。
# - `^0.2`（1 より小さい重み）を付けた語は軽く扱われ、その語だけで当たっていた武将が下がる。
#   2026-11-03 の実測では、`上杉 武田` で1位の武田信玄が、`上杉 武田^0.2` では5位以下に下がった。
# - `^` は、Lucene の完全な構文（`query_type="full"`）のときに使える。検索の要求に付ける設定なので、その検索にだけ効く。

# %%
title("1. 語の重み")
rows = []
for q in BOOSTS:
    hits = search(q, query_type="full")
    rows.append([q, top_names(hits)])
table(["検索語", f"上位{TOP}人"], rows)

# %% [markdown]
# ## 2. 項目の重み（スコアリングプロファイル）
#
# インデックスに「項目ごとの重み」のセット（スコアリングプロファイル）を名前つきで足し、検索の要求で名前を指定して使う。
#
# 見るところ
# - `name-first`（名前 5、別名 3）：名前に「上杉」がある謙信と景勝が、点数で大きく離れて上に来る。
# - `profile-light`（プロフィール 0.2）：プロフィールだけで当たった武将の点数が、およそ5分の1になる（2026-11-03 の実測。北条氏康 3.9 → 0.8）。
#   公式資料は「正の数の倍率」とだけ書いている。1 より小さい倍率で下がったのは、このデータでの実測（点数は実行のたびに少し変わる）。
# - プロファイルを足しても、検索で名前を指定しなければ順位は変わらない。

# %%
from azure.search.documents.indexes.models import ScoringProfile, TextWeights  # noqa: E402

title("2. 項目の重み")
synonyms.check(T)
index = ic.get_index(T.index_name)
kept = [p for p in (index.scoring_profiles or []) if p.name not in PROFILES]
index.scoring_profiles = kept + [ScoringProfile(name=n, text_weights=TextWeights(weights=w)) for n, w in PROFILES.items()]
ic.create_or_update_index(index)

rows = []
for profile in [None, *PROFILES]:
    hits = list(sc.search(search_text=FIELD_QUERY, top=50, select=["id"], scoring_profile=profile))
    scores = "、".join(f"{h['@search.score']:.1f}" for h in hits[:TOP])
    rows.append([profile or "（なし）", top_names(hits), scores])
table(["プロファイル", f"上位{TOP}人", "点数"], rows)

# %% [markdown]
# ## 3. 除外の落とし穴
#
# 「小早川」で探して、小早川隆景だけを外したい。「一致した件数」は、取得した件数（最大50件）ではなく、検索に一致した文書の総数。
#
# 見るところ
# - `小早川 -隆景`（既定の searchMode=any）：「小早川を含む」**または**「隆景を含まない」になり、何も外れないうえ、
#   関係のない武将まで一致する（2026-11-03 の実測で、7件から 149件に増えた。150人のうち、外れたのは
#   「隆景」を含み「小早川」を含まない毛利元就だけ）。
# - searchMode=all：「隆景」と本文に書いてある武将が全部外れる。秀秋も、プロフィールに「隆景」とあるので一緒に消える（2件だけ残る）。
# - 確実に1人だけ外すなら、語ではなく項目で絞る（フィルター `id ne 'b070'`）。

# %%
title("3. 除外")
cases = [
    ("そのまま", EXCLUDE_BASE, {}),
    (f"-{EXCLUDE_WORD}（any）", f"{EXCLUDE_BASE} -{EXCLUDE_WORD}", {"search_mode": "any"}),
    (f"-{EXCLUDE_WORD}（all）", f"{EXCLUDE_BASE} -{EXCLUDE_WORD}", {"search_mode": "all"}),
    (f"フィルター id ne '{EXCLUDE_ID}'", EXCLUDE_BASE, {"filter": f"id ne '{EXCLUDE_ID}'"}),
]
rows = []
for label, q, kw in cases:
    res = sc.search(search_text=q, top=50, select=["id"], include_total_count=True, **kw)
    hits = list(res)
    rows.append([label, res.get_count(), top_names(hits, 7)])
table(["書き方", "一致した件数", "上位7人"], rows)

# %% [markdown]
# ## 4. 一方向の置き換え（`A => B`）
#
# データにない呼び名で検索されたとき、データにある言葉に置き換える。辞書に2行を足して、項目につなぐ。
# つないだあとは、検索の要求で辞書を指定しなくても効く（インデックスに持つ設定）。
#
# 見るところ
# - 「第六天魔王」：辞書なしでは三国志の武将など、関係のない人が出る。置き換えると織田信長が上位に入る
#   （1位とは限らない。プロフィールに「織田信長」と書かれた浅井長政なども一緒に上がる）。
# - 「関白」：辞書なしでは0件。「太閤」（豊臣秀吉の別名）に置き換えると秀吉が出る。
# - 「関白になった武将は誰ですか」のような文では、ほかの語（「なっ」「武将」など）にも引っ張られ、置き換えても上位に来にくい。
#   辞書は語を広げるだけで、質問の意味は読まない。

# %%
title("4. 一方向の置き換え")
synonyms.attach(T, False)
before = {q: search(q) for q in ONE_WAY_QUERIES}
waited = synonyms.apply(T, saved_synonyms["rules"] + ONE_WAY_RULES)
after = {q: search(q) for q in ONE_WAY_QUERIES}
print(f"足したルール：{' ／ '.join(ONE_WAY_RULES)}（効き始めるまで {waited:.0f} 秒）")
table(["検索語", "辞書なし", "辞書あり"], [[q, top_names(before[q], 3), top_names(after[q], 3)] for q in ONE_WAY_QUERIES])

# %% [markdown]
# ## 後片付け
#
# `RESTORE = True` のとき、実行前の状態に戻す。
# - プロファイル：2 で使った名前のものを消す（同じ名前のものが前からあれば、その定義に戻す）。
# - 辞書：実行前のルールに戻す（辞書がなかったときは消す）。項目へのつなぎも実行前のとおりにする。
# Notebook では、途中のセルで止まったときも、このセルを実行する。

# %%
cleanup()
if RESTORE:
    print("プロファイルと辞書を、実行前の状態に戻しました。")
else:
    print("プロファイルと辞書は、このスクリプトで変えたままです。戻すには RESTORE = True にしてもう一度実行します。")
