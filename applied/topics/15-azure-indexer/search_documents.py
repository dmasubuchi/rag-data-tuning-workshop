# %% [markdown]
# # 15 Azure の仕組みに置き換える（2）14 で当たらなかった語を探す
#
# 14 では、スキャンした内定承諾書にしか書いていない「入社予定日」が、手元の検索で1件も当たりませんでした。
# 同じ語を、構築する人が作ったインデックス hr-docs で探します。読むだけで、何も変えません。
#
# 実行：python search_documents.py
#       python search_documents.py --term "夜間当番"
#       python search_documents.py --question "石田さんはいつから働き始めますか"
#
# 見るところ：
#   1. キーワード検索で、スキャン（scan）の内定承諾書が上位に来る。OCR で読んだ文字が本文に入っている
#   2. 言い換えた質問（ハイブリッド検索）でも見つかる。質問のベクトル化は AI Search が行う（手元で埋め込まない）

# %%
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import clients, config, show  # noqa: E402

# 探す語。None なら「入社予定日」（14 と同じ）
TERM = None
# 言い換えた質問。None なら下の既定
QUESTION = None

parser = argparse.ArgumentParser(description="インデックス hr-docs で探す")
parser.add_argument("--term", help="キーワード検索で探す語")
parser.add_argument("--question", help="ハイブリッド検索で聞く質問")
args, _ = parser.parse_known_args()
term = args.term or TERM or "入社予定日"
question = args.question or QUESTION or "石田さんはいつから働き始めますか"

sc = clients.search_client(config.HR_INDEX)
FIELDS = ["title", "kind", "chunk", "parent_id"]


def print_hits(hits, mark_word=None):
    rows = []
    for i, h in enumerate(hits, start=1):
        text = " ".join((h.get("chunk") or "").split())
        if mark_word and mark_word in text:
            at = text.index(mark_word)
            text = "…" + text[max(0, at - 15):at + 25] + "…"
        rows.append([i, h.get("kind"), h.get("title"), show.one_line(text, 44)])
    show.table(["順位", "種類", "ファイル", "チャンク（一部）"], rows)


# %% [markdown]
# ## 1. キーワード検索で「入社予定日」を探す
#
# 1位の「種類」が scan（スキャンした書類）になっているかを見てください。
# 14 では 0 文字だった書類が、OCR で文字になり、検索で当たるようになりました。

# %%
show.title(f"1. キーワード検索：「{term}」")
hits = list(sc.search(term, top=5, select=FIELDS))
print_hits(hits, term)
scan_hits = [h for h in hits if h.get("kind") == "scan" and term in (h.get("chunk") or "")]
if scan_hits:
    show.section("スキャンの書類から OCR で読んだ文字（このチャンクの全文）")
    print(" ".join(scan_hits[0]["chunk"].split()))
else:
    print("\n  スキャンの書類には当たりませんでした（語を変えたときは、当たらないこともあります）。")

# %% [markdown]
# ## 2. 言い換えた質問で探す（ハイブリッド検索）
#
# 「入社予定日」という語を使わずに聞きます。キーワードとベクトルの両方で探し、順位をまとめます。
# 質問のベクトル化は、インデックスに設定したベクトル化（Azure OpenAI）を使って AI Search が行います。
# 基礎編のように、手元で埋め込んでから送る必要はありません（統合ベクトル化）。

# %%
show.title(f"2. ハイブリッド検索：「{question}」")
from azure.search.documents.models import VectorizableTextQuery  # noqa: E402

vq = VectorizableTextQuery(text=question, k_nearest_neighbors=20, fields=config.VECTOR_FIELD)
hits = list(sc.search(question, vector_queries=[vq], top=5, select=FIELDS))
print_hits(hits, "入社予定日")

# %% [markdown]
# ## まとめ
#
# - 取り込みで読めなかった文字は、検索では取り戻せない（14）。OCR を取り込みに入れると探せるようになる（15）。
# - Azure では、取り込みの手順（OCR・分割・埋め込み）をスキルセットとして書いておくと、インデクサーが全文書に順に流す。
# - Azure の分割は長さで切る。14 のように Excel の1行・Word の見出しで切りたいときは、手元で前処理するか、別の仕組みを足す。

# %%
print()
print("このインデックスは、16（見せてよい人で絞る）以降でも使います。")
