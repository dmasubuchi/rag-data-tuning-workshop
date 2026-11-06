# %% [markdown]
# # 14 種類の違う文書をまとめて取り込む（手元の Python で読む）
#
# 採用の文書（求人票 PDF、職務経歴書 Word、面接の評価 Excel、連絡メール、スキャンした書類）を、
# 手元の Python で読んで、検索の単位（チャンク）に分けます。Azure は使いません。
#
# 実行：python read_documents.py
#       python read_documents.py --term "決済基盤"   （探す語を一時的に変える）
#
# 見るところ：
#   1. 4種類は文字が取れるが、スキャンした書類だけは 0 文字になる
#   2. 形式ごとに、チャンクの切り方が違う（Excel は1行、Word は見出し、メールは1通）
#   3. スキャンにしか書いていない語（入社予定日）は、手元の検索では1件も当たらない

# %%
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import config, readers, show  # noqa: E402

# 探す語。None なら「入社予定日」（スキャンした内定承諾書にだけ書いてある語）
TERM = None
# 比べるための語。文字の取れる文書に書いてある語
TERM_IN_TEXT = "決済基盤"

parser = argparse.ArgumentParser(description="形式の違う文書を手元で読む")
parser.add_argument("--term", help="探す語")
args, _ = parser.parse_known_args()      # Notebook が渡す余分な引数は無視する
term = args.term or TERM or "入社予定日"

# %% [markdown]
# ## 1. 23 ファイルを、形式ごとのライブラリで読む
#
# 「文字数」の列を見てください。スキャンした書類の3つだけが 0 です。
# PDF でも、文字の層がある求人票は読めて、画像だけのスキャンは読めません。見た目は同じ PDF でも中身が違います。

# %%
docs = readers.read_all(config.manifest_files())

show.title("1. 23 ファイルを読む")
show.table(
    ["種類", "ファイル", "形式", "チャンク", "文字数", "メモ"],
    [[d.kind_label, d.rel, d.format, len(d.chunks), d.chars, d.note] for d in docs],
)
by_format = {}
for d in docs:
    n, chars = by_format.get(d.format, (0, 0))
    by_format[d.format] = (n + 1, chars + d.chars)
print()
print("  形式ごと：" + "、".join(f"{k} {n}件（{c}字）" for k, (n, c) in by_format.items()))

# %% [markdown]
# ## 2. チャンクの切り方は、形式ごとに違う
#
# - Excel：1行を1チャンクにし、「列名: 値」の形にします。「5」だけでは何の点数か分からないからです。
# - Word：見出しごとに1チャンク。このデータの見出しは「見出し」スタイルではなく、太字の大きな文字です。
#   そのため、スタイル名ではなく書式で見出しを見分けています（実務の Word でもよくあります）。
# - メール：1通を1チャンク。件名・差出人・日時を本文の前に付けます。

# %%
show.title("2. チャンクの例")


def first(fmt, label_part=""):
    for d in docs:
        if d.format == fmt:
            for c in d.chunks:
                if label_part in c.label:
                    return d, c
    return None, None


for fmt, part, why in [("xlsx", "面接評価", "Excel の1行（列名: 値）"),
                       ("docx", "職歴", "Word の見出し1つ分"),
                       ("eml", "", "メール1通"),
                       ("pdf", "", "PDF の1ページ")]:
    d, c = first(fmt, part)
    if c is None:
        continue
    show.section(f"{why}：{d.rel}（{c.label}）")
    text = c.text if len(c.text) <= 300 else c.text[:300] + "…"
    print(text)

# %% [markdown]
# ## 3. スキャンした書類は、文字が取れない
#
# 3つのファイルを、画像のビューアーで開いてみてください。人の目には文字が読めます（内定承諾書、面接メモ、送付状）。
# でも、ファイルの中にあるのは「文字」ではなく「絵」なので、Python のライブラリでは 0 文字です。

# %%
show.title("3. スキャンした書類")
scans = [d for d in docs if d.kind == "scan"]
for d in scans:
    print(f"  {d.rel}　{d.chars} 文字　（開いて見る：{config.display_path(d.path)}）")
if show.in_notebook():
    from IPython.display import Image, display

    for d in scans:
        if d.format == "png":
            display(Image(filename=str(d.path), width=420))

# %% [markdown]
# ## 4. 手元で探す：スキャンにしか書いていない語は当たらない
#
# まず、文字の取れる文書に書いてある語（決済基盤）で探します。当たります。
# 次に「入社予定日」で探します。この語は内定承諾書（スキャン）に書いてありますが、1件も当たりません。
# 取り込みで読めなかった文字は、あとでどんなに検索を工夫しても見つかりません。
# Azure の取り込み（OCR）でこれを直すのが、次のトピック 15 です。

# %%
show.title("4. 手元で探す")


def search_local(word):
    hits = []
    for d in docs:
        for c in d.chunks:
            if word in c.text:
                hits.append((d, c))
    return hits


for word in (TERM_IN_TEXT, term):
    hits = search_local(word)
    show.section(f"「{word}」：{len(hits)} 件")
    for d, c in hits[:5]:
        print(f"  {d.kind_label}　{d.rel}（{c.label}）　{show.one_line(c.text, 40)}")
    if not hits:
        in_scan = [d.rel for d in scans]
        print("  （1件も当たりません）")
        print(f"  スキャンした書類（{', '.join(in_scan)}）に書いてあっても、文字が取れていないので探せません。")

print()
print("次は 15：Azure のインデクサーとスキルセット（OCR）で、同じ語を探します。")
