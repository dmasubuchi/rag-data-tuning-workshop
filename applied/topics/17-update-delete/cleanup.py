# %% [markdown]
# # 17 元に戻す：チームの文書を、データのとおりに戻す
#
# withdraw_application.py と revise_job_posting.py は、チームの本物の文書（Storage の入れ物と、インデックス hr-docs）を、
# そのまま直します。withdraw_application.py は最後に自分で元に戻します（revise_job_posting.py は、最後の手順が元に戻す手順です）。
# 途中で止めたときや、--keep を付けたときは、このスクリプトで元に戻します。何度実行しても同じです（変わっていなければ、何も置き直しません）。
#
# 元に戻すこと：
#   - manifest の 23 文書が、applied/data/ のとおりに、Storage とインデックスにある状態にする
#     （data/ と違うものだけ置き直す。削除の印 IsDeleted が付いたままのものも）
#   - manifest にない blob があれば消す（削除の印を付けて、索引から消えたのを確かめてから）
#   - インデクサーを動かし、見てよい人（allowed）を付け直す
#
# 実行：python cleanup.py
#
# 準備：構築する人の .env.local（Storage の接続文字列と AI Search の管理者キー）。メンバーの設定では、始めに止まります。

# %%
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import config, docops, show  # noqa: E402

config.require_admin_key()                  # メンバーの設定（検索だけのキー）なら、ここで日本語で止まる
config.get_settings(need_storage=True)      # Storage の項目がなければ、ここで日本語で止まる
show.title("17 元に戻す：チームの文書を、データのとおりに戻す")
docops.restore()
