# %% [markdown]
# # 17 更新と削除（1）応募の取り下げ：ファイルを消すだけでは、索引に残る
#
# 応募者が応募を取り下げたので、その人の書類を検索から消したい、という場面です。
# チームの Storage の入れ物にある本物の書類（経歴書・メール・スキャン）を、そのまま消します。最後に元に戻します。
#
# **この演習のあいだ、チームの検索の結果も変わります**（取り下げた応募の書類が、検索に出たり出なかったりします）。
# ほかのメンバーが 15・16・18・19 を動かしていないときに実行してください。
#
# 実行：python withdraw_application.py
#       python withdraw_application.py --keep        最後に元に戻さない（取り下げた状態のまま見たいとき。元に戻すのは cleanup.py）
#       python withdraw_application.py --application APP-0392
#
# 準備：構築する人の .env.local（Storage の接続文字列と AI Search の管理者キー）。メンバーの設定では、始めに止まります。
#
# 見るところ（流れ）：
#   1. 取り下げる応募の書類（経歴書・メール・スキャン）が、Storage にあり、索引にチャンクがある
#   2. 失敗：メールの blob を消しただけ → インデクサーを動かしても、索引のチャンクは残る。検索にも出てくる
#   3. 正しい方法：blob のメタデータに IsDeleted=true を足す → インデクサーを動かす → 索引から消える → そのあと blob を消す
#   4. 消してしまった後でも、同じ名前で IsDeleted=true を付けて置き直せば、取り残しを消せる
#   5. 最後に元に戻す（data/ から置き直して、インデクサーを動かし、見てよい人を付け直す）
#
# 検索は、この応募の書類だけに絞って行います（面接の評価の Excel のように、応募をまたぐ文書は、この演習では消しません）。

# %%
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import clients, config, docops, pipeline, show  # noqa: E402

# 変えてよい値。None なら下の既定
APPLICATION = None        # 取り下げる応募。None なら APP-0471（書類選考中の人。経歴書・メール・スキャンがある）
KEEP = False              # True にすると、最後に元に戻さない

parser = argparse.ArgumentParser(description="応募の取り下げ（削除）")
parser.add_argument("--application", help="取り下げる応募の番号")
parser.add_argument("--keep", action="store_true", help="最後に元に戻さない")
args, _ = parser.parse_known_args()
application = args.application or APPLICATION or "APP-0471"
keep = args.keep or KEEP

config.require_admin_key()                  # メンバーの設定（検索だけのキー）なら、ここで日本語で止まる
config.get_settings(need_storage=True)      # Storage の項目がなければ、ここで日本語で止まる
app = next((a for a in config.load_manifest()["applications"] if a["application_id"] == application), None)
if app is None:
    raise config.SetupError(f"応募 {application} が manifest.json にありません。")
files = docops.application_files(application)
mail_files = [f for f in files if f.startswith("mail/")]        # 失敗の例に使う（blob だけ消す）
other_files = [f for f in files if not f.startswith("mail/")]   # 正しい方法で消す（経歴書・スキャン）
if not mail_files or not other_files:
    raise config.SetupError(f"{application} は、メールと、メール以外の書類が両方ある応募を選んでください（APP-0471 など）。")
name = app["candidate_name"]
cc = clients.container_client()

show.title(f"17 応募の取り下げ：{application}（{name}）")
print(f"  取り下げる応募の書類：{', '.join(Path(f).name for f in files)}")
print("  Storage の名前：" + "、".join(pipeline.blob_name(f) for f in files))


def hits_for_name():
    """取り下げた人の名前で、この応募の書類を検索する（キーワード検索。名前をひとまとまりで探す）。"""
    return docops.index_chunks(files, select=["title", "kind"], search_text=f'"{name}"')


def keep_blobs_if_left(rel_paths):
    """索引から、これらの文書のチャンクが 0 件になるまで確かめる。残っていたら、blob は消さずに止めて、案内する。

    blob を先に消すと、削除の印を読めなくなる（取り残しになる）。索引から消えたことを確かめてから、blob を消す。
    """
    left = docops.wait_until_removed(rel_paths)
    if left:
        raise config.SetupError(
            "印を付けたのに、索引にチャンクが残っています：" + "、".join(f"{n} {c} 件" for n, c in left.items()) + "\n"
            "  blob は、消さずに残しました（先に消すと、印を読めなくなります）。\n"
            "  少し待ってから、もう一度このスクリプトを実行するか、元に戻すなら  python cleanup.py  を実行してください。")


def search_name():
    hits = hits_for_name()
    if hits:
        # 名前が出てくる点数は同じなので、順位は付けず、ファイル名の順に並べる
        show.table(["種類", "ファイル"], [[h["kind"], h["title"]] for h in sorted(hits, key=lambda h: h["title"])])
    else:
        print("  何も当たりません。")


# %% [markdown]
# ## 1. 取り下げる応募の書類は、いま Storage にあり、索引にもある
#
# 前の回が途中で止まっていても、先に元に戻して、同じ状態から始めます。
# blob には、文書の番号（doc_id）・種類（kind）・応募番号（application_ids）などを、メタデータとして付けてあります。
# 索引の同じ名前の欄に、インデクサーがそのまま写します。メタデータの IsDeleted が、後で削除の印になります。
#
# 「状態」の表：Storage にファイルがあるか、索引にチャンクが何件あるかを並べています。
# ここでは、3つとも「ある」で、チャンクが1件以上あるのを確かめてください。

# %%
show.section("前の回の途中で止まっていても、先に元に戻す")
docops.restore()

show.title("1. 取り下げる応募の書類（いまの状態）")
sample = other_files[0]
print(f"  メタデータの例（{pipeline.blob_name(sample)}）：")
print("    " + str(dict(cc.get_blob_client(pipeline.blob_name(sample)).get_blob_properties().metadata)))

show.section("状態")
show.table(["ファイル", "Storage", "索引のチャンク", "メモ"], docops.state_rows(files))
show.section(f"「{name}」で検索（この応募の書類だけ）")
search_name()

# %% [markdown]
# ## 2. 失敗：メールの blob を消しただけ
#
# 応募が取り下げられたので、メールのファイルを Storage から消しました。インデクサーを動かして、索引を確かめます。
# 「状態」の表を見てください。メールは Storage に「ない」のに、索引のチャンクが残っています（取り残し）。
# 検索でも、消したはずのメールが出てきます。インデクサーは、変わったファイルは見つけますが、
# なくなったファイルは、何も印がなければ気づきません。

# %%
show.title("2. 失敗：blob を消しただけ（インデクサーを動かしても、索引に残る）")
for rel in mail_files:
    docops.delete_blob(rel)
print(f"  Storage から消しました：{', '.join(Path(f).name for f in mail_files)}")
docops.reindex()

show.section("状態")
show.table(["ファイル", "Storage", "索引のチャンク", "メモ"], docops.state_rows(files))
show.section(f"「{name}」で検索")
search_name()
print("  → メールの blob は消したのに、検索には出てくる。個人情報が検索から消えていない状態です。")

# %% [markdown]
# ## 3. 正しい方法：削除の印を付けて、インデクサーを動かして、そのあと blob を消す
#
# データソースに「削除の検出」を設定してあります（hr-docs-ds）。
#   blob のメタデータ IsDeleted が true なら、インデクサーは、その文書のチャンクを索引から消す
# 手順は3段です。
#   (1) メタデータに IsDeleted=true を足す。
#       注意：Azure の set_blob_metadata は、メタデータを全部置き換えます。足すだけのつもりで呼ぶと、
#       doc_id・kind などが消えます。だから、今のメタデータを読んで、IsDeleted を足してから渡します。
#   (2) インデクサーを動かす → 索引から消える
#   (3) 索引から消えたことを確かめて、そのあとで blob を消す（先に消すと、印を読めない。消えていなければ、blob は残して止まる）
# 経歴書とスキャンで試します。メタデータの「前」と「後」で、IsDeleted が足されて、ほかは残っているのを見てください。

# %%
show.title("3. 正しい方法：IsDeleted=true を足す → インデクサー → blob を消す")
for rel in other_files:
    blob = cc.get_blob_client(pipeline.blob_name(rel))
    before = dict(blob.get_blob_properties().metadata)
    after = docops.mark_deleted(rel)
    print(f"  {Path(rel).name}")
    print(f"    前：{before}")
    print(f"    後：{after}")
docops.reindex()

show.section("状態（印を付けて、インデクサーを動かしたあと）")
show.table(["ファイル", "Storage", "索引のチャンク", "メモ"], docops.state_rows(files))
show.section(f"「{name}」で検索（印を付けた経歴書とスキャンは出ない。2 で消しただけのメールは、まだ出る）")
search_name()
keep_blobs_if_left(other_files)            # 索引から消えたことを確かめる。消えていなければ、ここで止まって、blob は残る
for rel in other_files:
    docops.delete_blob(rel)
print("\n  索引から消えたのを確かめてから、blob を消しました")

# %% [markdown]
# ## 4. 消してしまった後の直し方（取り残しの掃除）
#
# 2 で、印を付けずに blob を消したメールの取り残しは、まだ索引にあります。
# blob はもうないので、印を付けようがありません。直し方は、同じ名前で、IsDeleted=true を付けて置き直すことです。
# インデクサーは、その blob を見つけて、同じ文書のチャンクを索引から消します。そのあとで blob を消します。
#
# （削除の検出の設定は、最初のインデクサー実行から入れておく必要があります。設定する前に消した blob の取り残しは、
#  設定を足しても、インデクサーをリセットしても消えません。だから、削除の検出は、最初から入れておきます。）

# %%
show.title("4. 取り残しの掃除：同じ名前で、IsDeleted=true を付けて置き直す")
from azure.storage.blob import ContentSettings  # noqa: E402

for rel in mail_files:
    meta = pipeline.blob_metadata(docops.entry_of(rel))
    meta[pipeline.DELETE_MARK] = "true"
    cc.upload_blob(pipeline.blob_name(rel), (config.DATA_DIR / rel).read_bytes(), overwrite=True, metadata=meta,
                   content_settings=ContentSettings(content_type=docops.content_type(rel)))
    print(f"  印つきで置き直しました：{Path(rel).name}")
docops.reindex()
keep_blobs_if_left(mail_files)             # ここも、索引から消えたことを確かめてから、blob を消す
for rel in mail_files:
    docops.delete_blob(rel)

show.section("状態")
rows = docops.state_rows(files)
if rows:
    show.table(["ファイル", "Storage", "索引のチャンク", "メモ"], rows)
else:
    print("  Storage にも索引にも、何も残っていません。")
show.section(f"「{name}」で検索")
search_name()

# %% [markdown]
# ## まとめ
#
# - blob を消すだけでは、インデクサーは気づかない。索引に残る（検索に出る）。
# - 消す前に、メタデータに IsDeleted=true を足す。インデクサーを動かして、索引から消えたのを確かめて、そのあと blob を消す。
# - メタデータを足すときは、今のものを読んで残す（set_blob_metadata は全部を置き換える）。
# - 削除の検出は、最初から設定しておく。
# - 取り下げのような「消す」は、個人情報に関わる。消えたことを、検索で確かめる。

# %% [markdown]
# ## 最後に元に戻す
#
# 取り下げた応募の書類を、data/ から Storage に置き直し、インデクサーを動かして、索引に戻します（見てよい人も付け直します）。
# チームの検索の結果が、この演習の前と同じになります。
# `--keep` を付けたときは戻しません。あとで cleanup.py で戻せます。

# %%
if keep:
    print("  --keep が付いているので、元に戻しません。チームの検索から、この応募の書類が消えたままです。元に戻すときは  python cleanup.py")
else:
    docops.restore()
    show.section("元に戻したあとの状態")
    show.table(["ファイル", "Storage", "索引のチャンク", "メモ"], docops.state_rows(files))
