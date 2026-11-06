# %% [markdown]
# # 15 Azure の仕組みに置き換える（1）取り込みの設計図を読む
#
# 14 で手元の Python がしたこと（文書を開く → 文字を取り出す → チャンクに切る）を、
# Azure AI Search では「データソース → インデクサー → スキルセット → インデックス」が行います。
# 構築する人が build_hr_index.py で1回だけ流して、インデックス hr-docs を作ってあります。
# このスクリプトは、その設計図（lib/pipeline.py。build_hr_index.py が Azure に送るものと同じ）と、
# 取り込みの結果（インデックスの中のチャンクの数）を表示します。何も変えません。
# 設計図は手元のコードから読むので、検索だけのキー（メンバー用）でも動きます。
#
# 実行：python show_pipeline.py
#
# 見るところ：
#   1. データソース：Storage のどこを読むか（入れ物の全体）。削除の印（IsDeleted）の決まり
#   2. スキルセット：OCR → 文字の結合 → 分割 → 埋め込み の4段。それぞれ何を受け取り、何を出すか
#   3. インデックス：チャンクごとに、どんな欄があるか（後のトピックで使う欄もある）
#   4. 取り込みの結果：23 文書が何件のチャンクになったか（文書の種類ごと）

# %%
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import clients, config, pipeline, show  # noqa: E402

# %% [markdown]
# ## 1. データソース：どこの文書を読むか
#
# Storage の入れ物の全体を読みます（文書は manifest の相対パスのまま、入れ物の直下に置きます）。接続はキー（接続文字列）です。
# 「削除の検出」は、blob のメタデータ IsDeleted が true のものをインデックスから消す決まりです（17 で使います）。
# 更新の検出は、blob の最終更新日時をインデクサーが自動で見ます（設定は要りません）。

# %%
show.title("1. データソース")
print(f"  名前：{config.HR_DATASOURCE}　種類：azureblob")
print("  読む場所：Storage の入れ物の全体（フォルダを指定しない）")
print(f"  削除の検出：メタデータ {pipeline.DELETE_MARK} が true なら消す")
print("  更新の検出：blob の最終更新日時（自動）")

show.section("Storage に置く名前と、文書ごとのメタデータ（先頭 8 件）")
files = config.manifest_files()
show.table(["Storage の名前", "種類", "求人", "応募"],
           [[pipeline.blob_name(f["path"]), pipeline.blob_metadata(f)["kind"], pipeline.blob_metadata(f)["req_id"],
             pipeline.blob_metadata(f)["application_ids"]] for f in files[:8]])
print(f"  （全部で {len(files)} ファイル。文書ごとの情報は blob のメタデータに付けてある）")

# %% [markdown]
# ## 2. スキルセット：取り出したものに、順に手を加える
#
# 「受け取るもの」と「出すもの」の列を見てください。前の段が出したもの（text、merged_content、pages）を、
# 次の段が受け取っています。/document/normalized_images/* は、文書から取り出した画像（スキャン）の1枚1枚です。
# OCR の課金先は、チームの Foundry（AI Services）につないであります。

# %%
show.title("2. スキルセット")
ss = pipeline.skillset()
show.table(
    ["段", "何をするか", "どの単位で", "受け取るもの", "出すもの"],
    [[s.name, s.description, s.context,
      ", ".join(f"{i.name}={i.source}" for i in s.inputs),
      ", ".join(o.target_name for o in s.outputs)] for s in ss.skills],
)
proj = ss.index_projection.selectors[0]
show.section("インデックスの射影（親の文書 → チャンク）")
print(f"  チャンクの単位：{proj.source_context}　親の番号を入れる欄：{proj.parent_key_field_name}")
show.table(["インデックスの欄", "どこから"], [[m.name, m.source] for m in proj.mappings])

# %% [markdown]
# ## 3. インデックス：チャンクごとの欄
#
# chunk（本文。OCR で読んだ文字を含む）と text_vector（ベクトル）のほかに、
# 後のトピックで使う欄があります。
#   allowed          見てよい人（16 見せてよい人で絞る）。取り込みの後に構築する人のツールが付ける
#   req_id など       求人・応募・人の番号（18 関係で探す）

# %%
show.title("3. インデックス")
idx = pipeline.index()


def attrs(f):
    a = []
    if f.key:
        a.append("キー")
    if f.searchable:
        a.append("検索")
    if f.filterable:
        a.append("絞り込み")
    if f.facetable:
        a.append("ファセット")
    return "・".join(a)


show.table(["欄", "型", "使い方", "アナライザー"],
           [[f.name, show.plain(f.type), attrs(f), show.plain(f.analyzer_name)] for f in idx.fields])
vz = idx.vector_search.vectorizers[0]
print(f"\n  ベクトル化（検索のときに質問をベクトルにする）：{vz.vectorizer_name}（{show.plain(vz.kind)}）")

# %% [markdown]
# ## 4. インデクサーの結果
#
# 23 の文書が、何件のチャンクになったかを見ます。インデックスの中を検索して数えます（検索だけのキーでもできます）。
# 文書の種類ごとの件数に scan（スキャン）が入っていれば、OCR で文字が取れたということです。

# %%
show.title("4. 取り込みの結果")
sc = clients.search_client(config.HR_INDEX)
res = sc.search("*", facets=["kind,count:10"], top=0, include_total_count=True)
print(f"  チャンク：{res.get_count()} 件")
kinds = res.get_facets().get("kind", [])
if not kinds:
    print("  まだ取り込まれていません。構築する人に聞いてください（applied/tools/build_hr_index.py で作ります）。")
else:
    show.table(["文書の種類", "チャンク"], [[k["value"], k["count"]] for k in kinds])
print()
print("次は search_documents.py：14 で当たらなかった語を、このインデックスで探します。")
