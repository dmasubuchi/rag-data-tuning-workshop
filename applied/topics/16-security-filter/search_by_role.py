# %% [markdown]
# # 16 見せてよい人で絞る（1）同じ質問を、3つの立場で検索する
#
# 採用の文書には、全員に見せてよいもの（求人票）と、見せてはいけないもの（面接の評価、現在の年収など）が混ざっています。
# インデックス hr-docs の各チャンクには、「見てよい人」（allowed）が付いています。
#   role:recruiter（採用担当）・role:interviewer（面接官）・role:employee（一般社員）・user:U-1006（個人の面接官）
# 検索するときに、検索する人の印と allowed が1つでも重なるチャンクだけに絞ります（filter）。
# 同じ質問でも、立場によって結果が変わります。読むだけで、何も変えません。
#
# 実行：python search_by_role.py
#       python search_by_role.py --interviewer U-1007
#       python search_by_role.py --question "REQ-043 に応募した人の経歴を教えてください"
#
# 見るところ：
#   1. 立場ごとに、見えるチャンクの数が違う（採用担当は全部、面接官は担当する応募だけ、一般社員は求人票だけ）
#   2. 絞り込みの式（filter）は、立場の印を入れ替えるだけ。式そのものを画面に出している
#   3. 同じ質問でも、立場によって上位に出る文書が変わる。見えないものは、順位にも出ない
#   4. 現在の年収が書いてあるチャンクは、採用担当の検索にしか出ない
#   5. 限界：面接官が見えるチャンクに、担当でない応募が混ざることがある（取り込みの切り方の問題）

# %%
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import acl, clients, config, show  # noqa: E402

# 変えてよい値。None なら下の既定
QUESTION = None          # 1つ目の質問（応募の経歴を探す）
INTERVIEWER = "U-1006"   # 面接官の立場で検索する人の ID（面接の評価一覧の「面接官ID」。U-1006 か U-1007）

parser = argparse.ArgumentParser(description="同じ質問を3つの立場で検索する")
parser.add_argument("--question", help="1つ目の質問")
parser.add_argument("--interviewer", help="面接官の ID（例 U-1007）")
args, _ = parser.parse_known_args()
question = args.question or QUESTION or "REQ-042 に応募した人の職務経歴を教えてください"
interviewer = args.interviewer or INTERVIEWER

# 立場 → 検索する人の印。面接官は、役割（role:interviewer）と個人（user:…）の両方を持つ
ROLES = [
    ("採用担当", acl.VIEWER_RECRUITER),
    (f"面接官 {interviewer}", acl.viewer_interviewer(interviewer)),
    ("一般社員", acl.VIEWER_EMPLOYEE),
]
sc = clients.search_client(config.HR_INDEX)
FIELDS = ["title", "kind", "chunk", "application_ids"]

# %% [markdown]
# ## 1. 立場ごとの絞り込みの式と、見えるチャンクの数
#
# filter の式を読んでください。どの立場も、同じ形で、`search.in` の中の印だけが違います。
#   allowed/any(a: search.in(a, '印1,印2'))  ＝ チャンクの allowed のどれかが、印のどれかと同じなら見える
# 「見えるチャンク」の種類ごとの数を見てください。一般社員は job_posting（求人票）だけです。

# %%
show.title("1. 立場ごとの絞り込みの式と、見えるチャンクの数")
rows = []
for name, who in ROLES:
    flt = acl.scope_filter(who)
    print(f"  {name}")
    print(f"    filter = {flt}")
    res = sc.search("*", filter=flt, facets=["kind,count:10"], top=0, include_total_count=True)
    kinds = {k["value"]: k["count"] for k in res.get_facets()["kind"]}
    rows.append([name, res.get_count()] + [kinds.get(k, 0) for k in
                                           ("job_posting", "resume", "mail", "scan", "interview_evaluations")])
print()
show.table(["立場", "見えるチャンク", "求人票", "経歴書", "メール", "スキャン", "面接の評価"], rows)
total = sc.search("*", top=0, include_total_count=True).get_count()
print(f"\n  （参考）allowed で絞らないと、だれの検索にも {total} 件すべてが対象になります。")
mine = sorted(k for k, v in acl.interviewer_assignments().items() if interviewer in v)
print(f"  面接官 {interviewer} が担当する応募：{', '.join(mine)}（面接の評価一覧の「面接官ID」から）")


# %% [markdown]
# ## 2. 同じ質問を、3つの立場で検索する
#
# 質問は同じです。立場ごとに、上位に出る文書が変わります。「応募」の列を見てください。
# 採用担当には REQ-042 の応募が全部出ます。面接官には、担当する応募だけ。一般社員には、求人票しか出ません。
# 見えない応募は、順位が下がるのではなく、検索の対象にならないので出てきません。

# %%
from azure.search.documents.models import VectorizableTextQuery  # noqa: E402


def search_as(text, who, top=5):
    """text を、who（検索する人の印）の立場でハイブリッド検索する。"""
    vq = VectorizableTextQuery(text=text, k_nearest_neighbors=20, fields=config.VECTOR_FIELD)
    return list(sc.search(text, vector_queries=[vq], filter=acl.scope_filter(who), top=top, select=FIELDS))


def apps_of(h):
    """そのチャンクに出てくる応募の番号。Excel のチャンクは、文書ぜんたいではなく、チャンクの本文から拾う。"""
    if h.get("kind") == "interview_evaluations":
        found = sorted(set(re.findall(r"APP-\d{4}", h.get("chunk") or "")))
    else:
        found = (h.get("application_ids") or "").split()
    return " ".join(found) or "-"


def print_hits(hits):
    show.table(["順位", "種類", "ファイル", "応募"],
               [[i, h.get("kind"), h.get("title"), show.one_line(apps_of(h), 30)] for i, h in enumerate(hits, start=1)])


show.title(f"2. 同じ質問を3つの立場で：「{question}」")
for name, who in ROLES:
    show.section(f"{name}　filter = {acl.scope_filter(who)}")
    print_hits(search_as(question, who))

# %% [markdown]
# ## 3. 現在の年収は、採用担当にしか見えない
#
# 職務経歴書の中の「現年収は…万円です」というチャンクは、allowed が role:recruiter だけです。
# 「現年収」で探して、そのチャンクが何件当たるかを立場ごとに数えます。採用担当だけが 2 件、ほかは 0 件のはずです。
# 面接官の絞り込みにも、この2件は入りません。同じ職務経歴書の、現年収を含まないチャンクは面接官にも見えます。

# %%
show.title("3. 現在の年収が書いてあるチャンク（「現年収」で検索）")
rows = []
for name, who in ROLES:
    hits = list(sc.search("現年収", filter=acl.scope_filter(who), top=20, select=["title", "chunk"]))
    with_salary = [h for h in hits if "現年収" in " ".join((h.get("chunk") or "").split())]
    rows.append([name, len(with_salary), ", ".join(sorted({h["title"] for h in with_salary})) or "-"])
show.table(["立場", "現年収を含むチャンク", "どのファイル"], rows)

# %% [markdown]
# ## 4. 限界：見えるチャンクに、担当でない応募が混ざることがある
#
# 絞り込みは、チャンクを単位にします。面接の評価の Excel は、Azure の取り込みで 400 文字ずつに切るので、
# 「選考状況」や「選考履歴」のチャンクに、複数の応募の行が入ります。そのうち1つでも担当する応募なら、チャンクごと見えます。
# 面接官に見える面接の評価のチャンクから、担当でない応募の番号が出てくるものを数えます。
# 14 のように Excel を1行ずつ取り込めば、行ごとに allowed を変えられます。見せる単位と、切る単位をそろえる、ということです。

# %%
show.title(f"4. 面接官 {interviewer} に見える評価のチャンクに、担当でない応募が混ざっていないか")
who = acl.viewer_interviewer(interviewer)
evals = list(sc.search("*", filter=acl.scope_filter(who) + " and kind eq 'interview_evaluations'",
                       top=100, select=["chunk", "chunk_id"]))
mixed = []
for h in evals:
    others = sorted(set(re.findall(r"APP-\d{4}", h["chunk"])) - set(mine))
    if others:
        mixed.append((show.one_line(h["chunk"], 36), others))
print(f"  見える評価のチャンク：{len(evals)} 件。そのうち担当でない応募の番号が出てくるもの：{len(mixed)} 件")
show.table(["チャンクの冒頭", "担当でない応募"], [[c, ", ".join(o)] for c, o in mixed])
print("\n  → 担当でない応募の「選考状況」の行などが、チャンクごと見えてしまう。取り込みの切り方で解決する問題です。")

# %% [markdown]
# ## まとめ
#
# - 見せてよい人は、検索する前に filter で決める。式は、立場の印を入れ替えるだけ。
# - 絞り込みの精度は、チャンクの切り方で決まる（見せる単位＝チャンク）。
# - 次は 16 の悪い例（leak_demo.py）：絞り込みをせず、プロンプトで「答えるな」と頼むだけにすると、どうなるか。
