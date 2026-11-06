# %% [markdown]
# # 18 関係で探す（紹介）求人 → 応募 → 職務経歴書 → 面接の評価を、番号でたどる
#
# 「REQ-043 に応募した人の、面接の評価の推奨は？」という質問は、1回の検索では答えにくい質問です。
# 答えは、求人 → 応募した人 → その人の職務経歴書・面接の評価、と書類をまたいでいて、
# 「REQ-043」と「評価の推奨」が同じ文章に書かれているとは限らないからです。
# 採用の文書には、求人番号（req_id）・応募番号（application_ids）・人物キー（person_keys）が付いています。
# この番号を欄で絞って、1段ずつたどります。読むだけで、何も変えません。
#
# 実行：python trace_relations.py
#       python trace_relations.py --req REQ-042      別の求人で試す（応募が5件ある）
#
# 見るところ：
#   1. 各段で、どの欄で何を絞ったか（表の「絞った欄」）。前の段で見つけた番号が、次の段の絞り込みに入る
#   2. たどると、答え（評価と推奨）が決まって出る。検索は 4 回（応募が何件あっても同じ）
#   3. 1回のハイブリッド検索は、意味が近い文を集めるだけ。必要な評価の一部しか出ず、別の求人の応募の評価が混ざる
#
# 絞り込みは、16 の採用担当の立場（role:recruiter）で行います。応募を横断して比べるので、採用担当の立場で実行します。

# %%
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import acl, clients, config, show  # noqa: E402

# 変えてよい値。None なら REQ-043
REQ_ID = None

parser = argparse.ArgumentParser(description="番号をたどって、求人から面接の評価まで探す")
parser.add_argument("--req", help="求人番号（例 REQ-042）")
args, _ = parser.parse_known_args()
req_id = args.req or REQ_ID or "REQ-043"

manifest = config.load_manifest()
req = next((r for r in manifest["requisitions"] if r["req_id"] == req_id), None)
if req is None:
    raise config.SetupError(f"求人 {req_id} が manifest.json にありません。" + "、".join(r["req_id"] for r in manifest["requisitions"]) + " から選んでください。")

sc = clients.search_client(config.HR_INDEX)
BASE = acl.scope_filter(acl.VIEWER_RECRUITER)   # 採用担当に見えるチャンク
# 面接の評価の1行（Excel の「面接評価」シート）。チャンクの本文から、評価番号・応募番号・段階・推奨を取り出す
ROW = re.compile(r"(EV-\d{3}) (APP-\d{4}) C-\d{3} \S+ \S+ REQ-\d{3} .*? (一次面接|二次面接|最終面接) \d{4}-\d\d-\d\d \d\d:\d\d"
                 r" (U-\d{4}) \S+ \S+ (?:\d )*(強く推奨|推奨|保留|見送り|下書き（未提出）)")
searches = 0     # たどるために、検索を何回したか

show.title(f"18 関係で探す：{req_id} {req['title']}")
print(f"  共通の絞り込み：{BASE}")

# %% [markdown]
# ## 0. 番号でつながる、書類の関係（manifest.json）
#
# 教材のデータの目録（manifest.json）には、応募ごとに、書類と評価の番号が並んでいます。
# 実際の業務では、採用管理システムのデータベースにあたるものです。ここでは「正解」としても使います。
# たどった結果が、この表と合っているかを、最後に確かめます。

# %%
show.title("0. 目録（manifest.json）にある関係")
apps = [a for a in manifest["applications"] if a["req_id"] == req_id]
show.table(["応募", "人物キー", "段階", "経歴書", "メール", "スキャン", "面接の評価（評価番号）"],
           [[a["application_id"], a["person_key"], a["step"], len(a["documents"]["resume"]), len(a["documents"]["mail"]),
             len(a["documents"]["scans"]), ", ".join(a["documents"]["evaluation_ids"]) or "なし"] for a in apps])
wanted_eval = sorted(e for a in apps for e in a["documents"]["evaluation_ids"])
print(f"\n  この求人の応募は {len(apps)} 件。面接の評価は {len(wanted_eval)} 行（{', '.join(wanted_eval)}）。")

# %% [markdown]
# ## 1. たどる：求人票 → 応募 → 職務経歴書 → 面接の評価
#
# 各段で、`filter`（絞り込みの式）を表示します。前の段で見つけた番号が、次の段の式に入ります。
#   1 求人票：kind が job_posting で、req_id がこの求人
#   2 応募   ：req_id がこの求人の、求人票以外の文書（経歴書・メール・スキャン）から、application_ids を集める
#   3 経歴書 ：kind が resume で、application_ids に、2 で見つけた応募番号が含まれる（search.ismatch）
#   4 評価   ：kind が interview_evaluations で、本文に応募番号が出てくるチャンクから、評価の行を読む（応募が何件でも1回）
# 評価の Excel は、応募番号が文書ぜんたいの欄にまとめて入っているので（6件分）、欄では絞れません。
# 本文の応募番号で探します（チャンクの切り方と、欄の付け方で、たどり方が変わるところです）。

# %%
show.title(f"1. たどる：{req_id} → 応募 → 経歴書 → 面接の評価")
steps = []

# 1. 求人票
f1 = f"{BASE} and kind eq 'job_posting' and req_id eq '{req_id}'"
r1 = list(sc.search("*", filter=f1, select=["title", "doc_id"]))
searches += 1
steps.append(["1 求人", f"kind eq 'job_posting' and req_id eq '{req_id}'",
              f"{r1[0]['title']}（チャンク {len(r1)} 件）" if r1 else "見つからない"])

# 2. 応募（求人票以外の文書にある application_ids を集める）
f2 = f"{BASE} and kind ne 'job_posting' and req_id eq '{req_id}'"
r2 = list(sc.search("*", filter=f2, top=100, select=["application_ids", "kind"]))
searches += 1
apps_found = sorted({a for x in r2 for a in (x.get("application_ids") or "").split() if a.startswith("APP-")})
steps.append(["2 応募", f"kind ne 'job_posting' and req_id eq '{req_id}'", ", ".join(apps_found) or "なし"])
only_manifest = sorted(set(req["application_ids"]) - set(apps_found))
apps_all = sorted(set(apps_found) | set(req["application_ids"]))

# 3. 職務経歴書
ids = " ".join(apps_all)
f3 = f"{BASE} and kind eq 'resume' and search.ismatch('{ids}', 'application_ids', 'simple', 'any')"
r3 = list(sc.search("*", filter=f3, top=100, select=["title", "application_ids", "person_keys"]))
searches += 1
resume_of = {x["application_ids"]: (x["title"], x["person_keys"]) for x in r3}
steps.append(["3 経歴書", f"kind eq 'resume' and search.ismatch('{show.one_line(ids, 28)}', 'application_ids', 'simple', 'any')",
              ", ".join(f"{t}（{pk}）" for t, pk in resume_of.values()) or "なし"])

# 4. 面接の評価（本文に応募番号が出てくる評価のチャンクを探して、評価の行を読む）
evals = {}     # 応募番号 → {(評価番号, 段階, 面接官, 推奨)}
phrases = " ".join(f'"{a}"' for a in apps_all)       # "APP-0386" "APP-0391" … と、応募番号をひとまとまりで並べる
for h in sc.search(phrases, search_mode="any", search_fields=["chunk"], top=100, select=["chunk"],
                   filter=f"{BASE} and kind eq 'interview_evaluations'"):
    for m in ROW.finditer(" ".join(h["chunk"].split())):
        if m.group(2) in apps_all:
            evals.setdefault(m.group(2), set()).add((m.group(1), m.group(3), m.group(4), m.group(5)))
searches += 1
steps.append(["4 評価", "kind eq 'interview_evaluations'、本文に応募番号（search_fields=chunk）",
              f"評価 {sum(len(v) for v in evals.values())} 行"])

show.table(["段", "絞った欄", "見つかったもの"], steps)
if only_manifest:
    print(f"\n  目録にだけある応募：{', '.join(only_manifest)}（経歴書・メール・スキャンがなく、面接の評価の Excel にだけ出てくる）")

show.section(f"たどった結果：{req_id} に応募した人と、面接の評価の推奨")
rows = []
for a in apps_all:
    got = sorted(evals.get(a, ()))
    rows.append([a, resume_of.get(a, ("経歴書なし", "-"))[1],
                 " / ".join(f"{e[0]} {e[1]} {e[3]}" for e in got) or "評価なし"])
show.table(["応募", "人物キー", "面接の評価（評価番号 段階 推奨）"], rows)
got_ids = sorted(e[0] for v in evals.values() for e in v)
print(f"\n  目録の評価番号と同じか：{'同じ' if got_ids == wanted_eval else '違う（目録 ' + str(wanted_eval) + '、たどった結果 ' + str(got_ids) + '）'}")
print(f"  検索の回数：{searches} 回")

# %% [markdown]
# ## 2. 1回のハイブリッド検索で、同じ質問をすると
#
# 同じ質問を、普通のハイブリッド検索（キーワード＋ベクトル）に1回だけ投げます。上位 5 件のチャンクを見ます。
# ベクトル検索は、質問と意味が近い文を集めます。「REQ-043 に応募した人」という関係は文の中にないので、
# 別の求人の応募の評価や、関係のない文書も混ざります。必要な評価の行が、全部は出てこないこともあります。
# 見るところ：「欲しい評価」のうち何行が出たか、「別の求人」のチャンクがいくつ混ざったか。

# %%
from azure.search.documents.models import VectorizableTextQuery  # noqa: E402

question = f"{req_id} に応募した人の面接評価の推奨は？"
show.title(f"2. 1回の検索：「{question}」")
vq = VectorizableTextQuery(text=question, k_nearest_neighbors=20, fields=config.VECTOR_FIELD)
hits = list(sc.search(question, vector_queries=[vq], filter=BASE, top=5, select=["title", "kind", "chunk"]))
rows, found_eval, off_target = [], set(), 0
for i, h in enumerate(hits, start=1):
    text = " ".join(h["chunk"].split())
    apps_in = sorted(set(re.findall(r"APP-\d{4}", text)))
    evs = sorted(set(re.findall(r"EV-\d{3}", text)))
    found_eval |= set(evs) & set(wanted_eval)
    other = apps_in and not (set(apps_in) & set(apps_all))
    off_target += 1 if other else 0
    rows.append([i, h["kind"], h["title"], " ".join(apps_in) or "-", " ".join(evs) or "-",
                 "別の求人の応募だけ" if other else ""])
show.table(["順位", "種類", "ファイル", "出てくる応募", "出てくる評価番号", "メモ"], rows)

complete = found_eval == set(wanted_eval) and off_target == 0
show.section("2つの方法を並べる")
show.table(["方法", "検索の回数", f"欲しい評価（{len(wanted_eval)} 行）のうち出た行", "別の求人だけのチャンク", "答えが決まるか"],
           [["たどる（欄で絞る）", searches, f"{len(set(got_ids) & set(wanted_eval))} 行", "0 件", "決まる（応募ごとの評価と推奨）"],
            ["1回のハイブリッド検索（上位5件）", 1, f"{len(found_eval)} 行（{', '.join(sorted(found_eval)) or 'なし'}）",
             f"{off_target} 件", "この質問では決まった" if complete else "決まらない（足りない行・余計な行がある）"]])

# %% [markdown]
# ## まとめ
#
# - 「Aに応募した人のBは？」のような、関係をたどる質問は、ベクトル検索1回では答えにくい。意味が近い文を集めるだけで、関係を知らないから。
# - 文書に番号（req_id・application_ids・person_keys）が欄として付いていれば、欄で絞って1段ずつたどれる。取り込みの時に、番号を欄にしておくことが大事。
# - 欄の付け方で、たどれるかが決まる。Excel のように1文書に複数の応募が入るものは、文書ぜんたいの欄では絞れない（本文や、1行ずつのチャンクで対応する）。
# - 関係が多い・深い質問（何段もたどる、関係の種類が多い）では、番号をたどる処理を自分で書くのが大変になる。
#   GraphRAG（文書から人・求人・組織などの関係をグラフにして探す）や、オントロジー（関係の決まりを先に定義する）を使う方法がある。README に紹介します。
