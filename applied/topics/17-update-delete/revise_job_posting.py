# %% [markdown]
# # 17 更新と削除（2）求人票の改訂：同じ名前で上書きすると、索引が新しい内容に変わる
#
# 求人票 REQ-042 が v1 から v3 に改訂された、という場面です。Storage の同じ名前のファイルを、新しい版で上書きします。
# チームの Storage の入れ物にある本物の求人票（jobs/JOB-REQ042-v3.pdf）を、まず旧い版（v1）の中身に差し替え、
# そのあと v3 で上書きします。ファイルの名前は、どちらも同じです。最後は、始める前と同じ状態（v3）になります。
#
# **この演習のあいだ、チームの検索の結果も変わります**（REQ-042 の求人票が、旧い版になる時間があります）。
# ほかのメンバーが 15・16・18・19 を動かしていないときに実行してください。
#
# 実行：python revise_job_posting.py
#
# 準備：構築する人の .env.local（Storage の接続文字列と AI Search の管理者キー）。メンバーの設定では、始めに止まります。
#
# 見るところ（流れ）：
#   1. v1 を置く → インデクサー → 検索で v1 の内容（年収 500 万円から 700 万円、試用期間）が当たる。チャンクは 3 件
#   2. 同じ名前で v3 に上書き → インデクサー → v3 の内容（年収 600 万円から 800 万円）に変わる。チャンクは 2 件
#      更新は、blob の最終更新日時が前回より新しいことで見つかる（削除と違い、設定は要らない）
#   3. v1 にしかない語を含むチャンクが、索引に残っていないか。チャンクの数が 3 件から 2 件に減っても、古いチャンクは残らない
#
# 途中で止めたときは、cleanup.py で元に戻します。

# %%
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import clients, config, docops, pipeline, show  # noqa: E402

# 変えてよい値
SEARCH_TERMS = ["試用期間", "500万円", "600万円"]  # 版ごとに、当たる数がどう変わるか見る語（v1 と v3 で違う語）


config.require_admin_key()                  # メンバーの設定（検索だけのキー）なら、ここで日本語で止まる
config.get_settings(need_storage=True)      # Storage の項目がなければ、ここで日本語で止まる
cc = clients.container_client()
JOB = docops.JOB_REL                           # jobs/JOB-REQ042-v3.pdf（manifest の名前。版が変わっても、この名前のまま上書きする）
blob_name = pipeline.blob_name(JOB)
V1_ONLY = ["試用期間", "500万円", "入社後の流れ"]     # v1 にだけ書いてあった語

show.title("17 求人票の改訂：REQ-042 の v1 → v3")
print(f"  求人票の名前：{blob_name}（版を名前に入れない。同じ名前で上書きする）")


def last_modified():
    """blob の最終更新日時。インデクサーは、これが前回より新しい blob を、更新として取り込み直す。"""
    props = cc.get_blob_client(blob_name).get_blob_properties()
    return props.last_modified.astimezone().strftime("%H:%M:%S")


def read_posting():
    """索引の中の、この求人票のチャンクを、並び順に読む。"""
    chunks = sorted(docops.index_chunks([JOB], select=["chunk_id", "chunk", "doc_id"]), key=lambda d: d["chunk_id"])
    text = " ".join(" ".join(c["chunk"].split()) for c in chunks)
    version = re.search(r"REQ-042 (v\d+)", text)
    salary = re.search(r"(\d+万円から\d+万円)", text)
    office = re.search(r"週(\d)日出社で、週(\d)日までリモート", text)
    facts = [["版", version.group(1) if version else "-"],
             ["文書の番号（メタデータの doc_id）", ", ".join(sorted({c["doc_id"] for c in chunks})) or "-"],
             ["年収", salary.group(1) if salary else "-"],
             ["勤務", f"週{office.group(1)}日出社・週{office.group(2)}日までリモート" if office else "-"],
             ["「試用期間」の記載", "ある" if "試用期間" in text else "ない"]]
    return chunks, facts


def show_posting(label):
    chunks, facts = read_posting()
    show.section(f"{label}：索引の中の求人票（チャンク {len(chunks)} 件）")
    show.table(["チャンク", "文字数", "冒頭"], [[i, len(c["chunk"]), show.one_line(c["chunk"], 44)] for i, c in enumerate(chunks)])
    print()
    show.table(["項目", "索引の中の値"], facts)
    return chunks


def search_terms(label):
    """SEARCH_TERMS を、キーワード検索（ひとまとまりで一致）で探して、当たったチャンクの数を返す。"""
    found = {}
    for term in SEARCH_TERMS:
        found[term] = len(docops.index_chunks([JOB], select=["chunk_id"], search_text=f'"{term}"'))
    show.section(f"{label}：キーワード検索で当たったチャンクの数（この求人票だけ）")
    show.table(["検索語", "当たったチャンク"], [[k, v] for k, v in found.items()])
    return found


# %% [markdown]
# ## 1. v1 を置いて、取り込む
#
# 前の回が途中で止まっていても、先に元に戻して、同じ状態から始めます。
# v1 は、17 だけで使う旧い版です（applied/data/updates/。manifest にはありません）。
# 見るところ：チャンクの数（3 件）と、「年収 500万円から700万円」「試用期間」が v1 の内容として索引に入っていること。

# %%
show.section("前の回の途中で止まっていても、先に元に戻す")
docops.restore()

show.title("1. v1 を置いて、インデクサーで取り込む")
file_v1, entry_v1 = docops.job_version("v1")
docops.put_blob(JOB, file_v1, entry_v1)
print(f"  置きました：{Path(file_v1).name} → {blob_name}　最終更新日時 {last_modified()}")
docops.reindex()
chunks_v1 = show_posting("v1 の取り込み後")
found_v1 = search_terms("v1 の取り込み後")

# %% [markdown]
# ## 2. 同じ名前で v3 に上書きして、もう一度取り込む
#
# 同じ名前（jobs/JOB-REQ042-v3.pdf）に、v3 を上書きします。名前も場所も同じなので、blob の最終更新日時だけが新しくなります。
# インデクサーは、その日時が前回より新しい blob を「更新された」と見て、取り込み直します（設定は要りません）。
# 見るところ：
#   - 最終更新日時が、上書きの前と後で変わっている
#   - 年収が 600万円から800万円に変わった。「試用期間」は書かれていない。500万円で探しても、もう当たらない
#   - チャンクの数が 3 件から 2 件になった（v3 は文章が短い）
#   - 上書きが終わると、チームの求人票は、始める前と同じ（v3）になっている

# %%
show.title("2. 同じ名前で v3 に上書きして、取り込み直す")
before_time = last_modified()
file_v3, entry_v3 = docops.job_version("v3")
docops.put_blob(JOB, file_v3, entry_v3)
print(f"  上書きしました：{Path(file_v3).name} → {blob_name}")
print(f"  最終更新日時：{before_time} → {last_modified()}")
docops.reindex()
chunks_v3 = show_posting("v3 の取り込み後")
found_v3 = search_terms("v3 の取り込み後")

# %% [markdown]
# ## 3. 古いチャンクは残っていないか
#
# v1 は 3 つのチャンクでした。v3 は 2 つです。上書きしたら、v1 の 3 つ目（余ったチャンク）が残るのではないか、
# が気になるところです。残っていれば、v1 にしかない語（試用期間、500万円、入社後の流れ）で当たってしまいます。
# 索引の中の、この求人票のチャンクを全部読んで、確かめます。
# （この実測では、チャンクが減る向き（v1 → v3）も、増える向き（v3 → v1）も、古いチャンクは残りませんでした。
#  インデクサーは、親の文書（blob）が変わると、その子のチャンクを消してから、作り直します。）

# %%
show.title("3. 古いチャンクの確認")
all_chunks = docops.index_chunks([JOB], select=["chunk_id", "chunk", "doc_id"])
stale = [(w, d["chunk_id"][-8:]) for w in V1_ONLY for d in all_chunks if w in d["chunk"]]
print(f"  索引の中のこの求人票のチャンク：{len(all_chunks)} 件（v1 のとき {len(chunks_v1)} 件 → v3 のとき {len(chunks_v3)} 件）")
print(f"  v1 にしかない語（{', '.join(V1_ONLY)}）を含むチャンク：{len(stale)} 件")
print(f"  文書の番号（doc_id）：{', '.join(sorted({d['doc_id'] for d in all_chunks}))}")

show.section("まとめ：検索語ごとの、当たったチャンクの数")
show.table(["検索語", "v1 のとき", "v3 のとき"], [[t, found_v1[t], found_v3[t]] for t in SEARCH_TERMS])
if stale or len(all_chunks) != len(chunks_v3):
    print("\n  → 古いチャンクが残っています（v1 にしかない語を含むものがある、または数が v3 と合いません）。")
else:
    print("\n  → 上書きしただけで、索引は新しい内容に変わった。v1 の内容は、チャンクの数が減っても、残らなかった。")

# %% [markdown]
# ## まとめ
#
# - 更新は、同じ名前で上書きするだけ。インデクサーが、最終更新日時で見つけて、取り込み直す。
# - チャンクの数が変わっても、親の文書ごと作り直されるので、古いチャンクは残らない（この実測では）。
# - 版を名前に入れて別の blob として置く（JOB-REQ042-v1.pdf と JOB-REQ042-v3.pdf を並べる）と、旧い版も検索に出続ける。
#   旧い版を検索から外したいときは、前のスクリプトの方法（IsDeleted）で消す。
# - 更新のあとは、見てよい人（allowed）も付け直す（インデクサーが取り込み直したチャンクは、allowed が空に戻る）。

# %% [markdown]
# ## 元の状態に戻っているか
#
# 最後の手順（2）で、求人票は v3 に戻りました。始める前と同じ状態です。
# 途中で止めたときは、cleanup.py で元に戻せます。

# %%
show.title("元の状態に戻っているか")
show.table(["ファイル", "Storage", "索引のチャンク", "メモ"], docops.state_rows([JOB]))
