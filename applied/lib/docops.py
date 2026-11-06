"""人事の文書を、チームの Storage の入れ物とインデックスの上で直す道具（トピック 17 更新と削除、build_hr_index.py が使う）。

17 の考え方：
  - チームの入れ物（既定 hr-docs）にある本物の文書を、そのまま直す。写しは作らない。文書は manifest の相対パスのまま置いてある
    （例 jobs/JOB-REQ042-v3.pdf）。
  - 同じデータソース・同じインデクサー（hr-docs-ixr）・同じインデックス（hr-docs）に取り込まれる。
  - 直しているあいだ、チームの検索の結果も変わる（取り下げた応募の書類が消える、求人票が旧い版になる、など）。
    だから、最後に必ず元に戻す（restore）。
  - インデクサーを動かしたあとは、見てよい人（allowed）を付け直す（reindex が acl.sync を呼ぶ）。
    取り込み直されたチャンクは allowed が空に戻り、空のチャンクはだれにも見えないため。

元に戻す（restore）は、manifest の全部の文書が、data/ のとおりに Storage とインデックスにある状態にする。
  data/ と違う（中身かメタデータ）文書だけを置き直し、manifest にない blob は、削除の印を付けて索引から消してから消す。
  そのあと、インデクサーを動かし、見てよい人を付け直す。何度実行しても、同じ結果になる。
"""
import time
from pathlib import Path

from . import acl, clients, errors, pipeline
from .config import DATA_DIR, HR_INDEX, HR_INDEXER, SetupError, load_manifest, manifest_files

UPDATES_DIR = DATA_DIR / "updates"      # 17 だけで使う、求人票の旧い版（manifest には入れない）
BUSY_WAIT_SECONDS = 10                  # インデクサーが実行中で断られたとき、待つ秒数
WAIT_SECONDS = 900                      # 実行が終わるまで待つ上限
POLL_SECONDS = 4
GONE_WAIT_SECONDS = 20                  # 索引から消えた・入ったのが検索に見えるまで待つ上限（17 の確認）

CONTENT_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".eml": "message/rfc822",
                 ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def content_type(path) -> str:
    return CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


# ------------------------------------------------------------------ 文書の一覧

def entry_of(manifest_path: str) -> dict:
    """manifest の中の1ファイル分（doc_id、kind、req_id、application_ids、person_keys）。"""
    for f in manifest_files():
        if f["path"] == manifest_path:
            return f
    raise SetupError(f"データの一覧（manifest.json）に {manifest_path} がありません。")


JOB_REL = "jobs/JOB-REQ042-v3.pdf"      # 求人票 REQ-042 の、Storage の中の名前（manifest の名前。版が変わっても、この名前のまま上書きする）


def job_version(version: str) -> tuple:
    """求人票 REQ-042 の版 → (ファイルの場所, メタデータの元になる1ファイル分)。

    v1 は 17 だけで使う旧い版（data/updates/）。v3 は manifest にある現行の版（data/jobs/）と同じもの。
    """
    if version == "v1":
        return UPDATES_DIR / "JOB-REQ042-v1.pdf", {"doc_id": "JOB-REQ042-v1", "kind": "job_posting", "req_id": "REQ-042",
                                                  "application_ids": [], "person_keys": []}
    if version == "v3":
        return DATA_DIR / JOB_REL, entry_of(JOB_REL)
    raise SetupError(f"版は v1 か v3 です（今は {version!r}）。")


def application_files(application_id: str) -> list:
    """1つの応募の書類（職務経歴書・メール・スキャン）の manifest の path。面接の評価の Excel は応募をまたぐので入れない。"""
    for a in load_manifest()["applications"]:
        if a["application_id"] == application_id:
            d = a["documents"]
            return list(d["resume"]) + list(d["mail"]) + list(d["scans"])
    raise SetupError(f"応募 {application_id} が manifest.json にありません。")


# ------------------------------------------------------------------ Storage に置く・メタデータ・消す

def ensure_container() -> bool:
    """Storage の入れ物（.env.local の AZURE_STORAGE_CONTAINER）がなければ、非公開で作る。作ったら True、もうあれば False。

    何度実行しても同じ（あれば何もしない）。構築する人の設定だけ（clients.container_client が、メンバーの設定を止める）。
    """
    from azure.core.exceptions import ResourceExistsError

    try:
        clients.container_client().create_container()
    except ResourceExistsError:
        return False
    return True


def put_blob(rel_path: str, source, entry: dict) -> str:
    """source のファイルを、Storage の rel_path に置く（同じ名前があれば上書き）。名前を返す。メタデータは entry（manifest の1ファイル分）から作る。"""
    from azure.storage.blob import ContentSettings

    name = pipeline.blob_name(rel_path)
    with open(source, "rb") as fh:
        clients.container_client().upload_blob(
            name, fh, overwrite=True, metadata=pipeline.blob_metadata(entry),
            content_settings=ContentSettings(content_type=content_type(source)))
    return name


def put_manifest(only_changed: bool = False, existing: dict = None) -> list:
    """manifest の全部の文書を、data/ から Storage に置く。置いた名前の一覧を返す。

    build_hr_index.py の「置く」と、元に戻す（restore）が、同じこの関数を使う。
    only_changed=False：全部を置く（上書き。blob の更新日時が新しくなるので、インデクサーは全部を取り込み直す）。
    only_changed=True ：data/ と違う（中身かメタデータ）もの、Storage にないものだけを置く。existing は {名前: blob の情報}（なければ読む）。
    """
    cc = clients.container_client()
    if only_changed and existing is None:
        existing = {b.name: b for b in cc.list_blobs(include=["metadata"])}
    put = []
    for f in manifest_files():
        name = pipeline.blob_name(f["path"])
        source = DATA_DIR / f["path"]
        if only_changed and is_as_in_data(cc, existing.get(name), source, f):
            continue
        put_blob(f["path"], source, f)
        put.append(name)
    return put


def is_as_in_data(cc, blob, source, entry: dict) -> bool:
    """Storage の blob（list_blobs の1件。なければ None）が、data/ の source とメタデータ（entry から作る）のとおりか。

    メタデータが違えば（削除の印 IsDeleted が付いたままの blob なども）、違うものとして扱う。大きさが同じときは、中身も比べる。
    """
    if blob is None:
        return False
    if dict(getattr(blob, "metadata", None) or {}) != pipeline.blob_metadata(entry):
        return False
    local = Path(source).read_bytes()
    size = getattr(blob, "size", None)
    if size is not None and size != len(local):
        return False
    return cc.get_blob_client(blob.name).download_blob().readall() == local


def merge_metadata(existing, extra: dict) -> dict:
    """既存のメタデータを残したまま、extra を足す（同じ名前があれば extra が勝つ）。"""
    merged = dict(existing or {})
    merged.update(extra)
    return merged


def add_metadata(blob, **extra) -> dict:
    """blob のメタデータに extra を足す。既存のものは残す。足したあとのメタデータを返す。

    set_blob_metadata は、指定したもので全部を置き換える（足すのではない）。
    doc_id・kind などが消えないよう、先に読んでから足す。
    """
    merged = merge_metadata(blob.get_blob_properties().metadata, extra)
    blob.set_blob_metadata(merged)
    return merged


def mark_deleted(rel_path: str) -> dict:
    """Storage の rel_path に、削除の印（IsDeleted=true）を足す。足したあとのメタデータを返す。blob はまだ消さない。"""
    blob = clients.container_client().get_blob_client(pipeline.blob_name(rel_path))
    return add_metadata(blob, **{pipeline.DELETE_MARK: "true"})


def delete_blob(rel_path: str) -> None:
    """Storage の rel_path の blob を1つ消す（索引には何もしない）。"""
    clients.container_client().delete_blob(pipeline.blob_name(rel_path))


def list_blobs() -> list:
    """入れ物の中の blob の一覧。名前順。"""
    return sorted(clients.container_client().list_blobs(include=["metadata"]), key=lambda b: b.name)


# ------------------------------------------------------------------ インデックスの中のチャンク

def _titles_filter(rel_paths) -> str:
    """索引の title（ファイル名）が、これらの文書のどれかである、という絞り込みの式。"""
    names = sorted({Path(r).name for r in rel_paths})
    bad = [n for n in names if not n or any(c in n for c in ",'\" ")]
    if bad:
        raise SetupError(f"ファイル名に、絞り込みに使えない文字（空白・カンマ・引用符）が入っています: {bad!r}")
    return f"search.in(title, '{','.join(names)}')"


def index_chunks(rel_paths=None, select=None, search_text: str = "*") -> list:
    """インデックスの中のチャンク。rel_paths があれば、その文書（ファイル名＝title）のものだけ。"""
    kwargs = {"filter": _titles_filter(rel_paths)} if rel_paths else {}
    sc = clients.search_client(HR_INDEX)
    return list(sc.search(search_text, top=1000, select=select or ["chunk_id", "title", "chunk"], **kwargs))


def chunk_counts(rel_paths=None) -> dict:
    """{ファイル名: チャンクの数}。rel_paths があれば、その文書の分だけ。"""
    out = {}
    for d in index_chunks(rel_paths, select=["chunk_id", "title"]):
        out[d["title"]] = out.get(d["title"], 0) + 1
    return dict(sorted(out.items()))


def state_rows(rel_paths) -> list:
    """[[ファイル名, Storage に blob があるか, 索引のチャンクの数, メモ]]（rel_paths の文書の分）。Storage と索引の食い違い（取り残し）が見える。"""
    wanted = {pipeline.blob_name(r) for r in rel_paths}
    blobs = {Path(b.name).name for b in list_blobs() if b.name in wanted}
    counts = chunk_counts(rel_paths)
    rows = []
    for name in sorted(blobs | set(counts)):
        orphan = name not in blobs and counts.get(name, 0) > 0
        rows.append([name, "ある" if name in blobs else "ない", counts.get(name, 0),
                     "← 取り残し（blob はないのに、索引に残っている）" if orphan else ""])
    return rows


def chunks_left(rel_paths) -> dict:
    """索引に、これらの文書（manifest の相対パス）のチャンクが、まだ何件あるか。{ファイル名: 件数}（0 件のものは入れない）"""
    counts = chunk_counts(rel_paths)
    names = {Path(r).name for r in rel_paths}
    return {n: counts[n] for n in sorted(names) if counts.get(n)}


def wait_until_removed(rel_paths, wait_seconds: int = None) -> dict:
    """これらの文書のチャンクが、索引から 0 件になるまで待つ。まだ残っているもの {ファイル名: 件数} を返す（空なら、全部消えた）。

    インデクサーが終わっても、消えたことが検索に見えるまで、1〜2 秒かかる。
    """
    wait_seconds = GONE_WAIT_SECONDS if wait_seconds is None else wait_seconds
    left = chunks_left(rel_paths)
    t0 = time.time()
    while left and time.time() - t0 < wait_seconds:
        time.sleep(2)
        left = chunks_left(rel_paths)
    return left


def chunks_missing(rel_paths) -> list:
    """索引に、チャンクが1件もない文書のファイル名の一覧。"""
    counts = chunk_counts(rel_paths)
    return sorted({Path(r).name for r in rel_paths} - set(counts))


def wait_until_present(rel_paths, wait_seconds: int = None) -> list:
    """これらの文書のチャンクが、索引に入るまで待つ。まだ入っていない文書のファイル名の一覧を返す（空なら、全部入った）。"""
    wait_seconds = GONE_WAIT_SECONDS if wait_seconds is None else wait_seconds
    missing = chunks_missing(rel_paths)
    t0 = time.time()
    while missing and time.time() - t0 < wait_seconds:
        time.sleep(2)
        missing = chunks_missing(rel_paths)
    return missing


# ------------------------------------------------------------------ インデクサーを動かす

def _plain(value) -> str:
    return str(getattr(value, "value", value) or "")


def _indexer_status(irc, tries: int = 3, wait: float = 2):
    """インデクサーの状態を取る。通信の失敗（接続・混雑・サーバーの一時的な失敗）は、待ってやり直す。

    4xx（インデクサーがない、キーが違うなど）は、やり直しても同じなので、そのまま出す。
    やり直しても取れなかったら、SetupError で止める（取れなかったことを、「実行の記録がない」と取り違えない）。
    """
    for attempt in range(tries):
        try:
            return irc.get_indexer_status(HR_INDEXER)
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "status_code", 0) or 0
            if 400 <= code < 500 and code != 429:
                raise
            if attempt == tries - 1:
                raise SetupError("インデクサーの状態を取得できませんでした（通信の失敗が続きました）。\n"
                                 "  ネットワークを確かめて、少し待ってから、もう一度実行してください。") from e
            time.sleep(wait)


def _last_start(irc):
    """直近の実行の開始時刻。実行の記録がまだなければ None（状態を取れなかったときは None にせず、_indexer_status が止まる）。"""
    last = _indexer_status(irc).last_result
    return last.start_time if last is not None else None


def wait_until_indexer_idle(say=print, wait_seconds: int = WAIT_SECONDS, settle: float = 2.0) -> None:
    """インデクサーが実行中でなくなるまで待つ。

    実行を頼んでから、実行中になるまで、1〜2 秒かかる。そのすき間を見逃さないよう、
    「実行中でない」を、間をあけて 2 回続けて確かめてから戻る。
    """
    irc = clients.indexer_client()
    t0, said, idle = time.time(), False, 0
    while True:
        last = _indexer_status(irc).last_result
        if last is None or _plain(last.status) != "inProgress":
            idle += 1
            if idle >= 2:
                return
            time.sleep(settle)
            continue
        idle = 0
        if time.time() - t0 > wait_seconds:
            raise SetupError(f"{wait_seconds} 秒待っても、インデクサーが終わりません。少し置いてから、もう一度実行してください。")
        if not said:
            say("  インデクサーが実行中なので待ちます")
            said = True
        time.sleep(POLL_SECONDS)


def is_busy(e: BaseException) -> bool:
    """「別の実行が走っているので、今は動かせない」という断りか（HTTP 409）。"""
    if getattr(e, "status_code", 0) == 409:
        return True
    text = str(e).lower()
    return "already" in text or "in progress" in text or "concurrent" in text


def run_indexer(say=print, wait_seconds: int = WAIT_SECONDS, busy_wait: int = BUSY_WAIT_SECONDS) -> dict:
    """インデクサー hr-docs-ixr を動かして、終わるまで待つ。結果（状態・処理件数・失敗件数・秒数）を返す。

    作った直後の自動の実行などが走っていると断られるので、少し待って、もう一度頼む。
    頼みが通ったあとは、そのあとに始まった実行が終わるのを待つ。
    """
    irc = clients.indexer_client()
    t0 = time.time()
    while True:
        before = _last_start(irc)
        try:
            irc.run_indexer(HR_INDEXER)
            break
        except Exception as e:  # noqa: BLE001
            if not is_busy(e):
                raise
            if time.time() - t0 > wait_seconds:
                raise SetupError(f"{wait_seconds} 秒待っても、インデクサーが空きません。少し置いてから、もう一度実行してください。")
            say(f"  インデクサーが実行中なので待ちます（{busy_wait} 秒後に、もう一度頼みます）")
            time.sleep(busy_wait)
    started = time.time()
    while time.time() - started < wait_seconds:
        last = _indexer_status(irc).last_result
        if last is not None and last.start_time != before and _plain(last.status) not in ("inProgress", "reset"):
            result = {"status": _plain(last.status), "items": last.item_count or 0, "failed": last.failed_item_count or 0,
                      "warnings": len(last.warnings or []), "seconds": int(time.time() - started)}
            errs = [errors.redact(e.error_message) for e in (last.errors or [])]
            if result["status"] != "success" or errs:
                raise SetupError("インデクサーが失敗しました：" + (errs[0][:300] if errs else result["status"]))
            return result
        time.sleep(POLL_SECONDS)
    raise SetupError(f"{wait_seconds} 秒たっても、インデクサーが終わりません。")


def reindex(say=print) -> dict:
    """インデクサーを動かして、見てよい人（allowed）を、索引の全部のチャンクに付け直す。結果を返す。

    取り込み直されたチャンクは allowed が空に戻るので、動かしたあとは、いつも全部を付け直す。
    """
    result = run_indexer(say)
    # 処理した文書の数は出さない。変更のない文書（直近に取り込んだ最新のもの）も、もう一度処理されることがあるため
    say(f"  インデクサー：{result['status']}　失敗 {result['failed']} 件　（{result['seconds']} 秒）")
    stats = acl.sync()
    say(f"  見てよい人を付け直しました（チャンク {stats['chunks']} 件のうち {stats['changed']} 件）")
    time.sleep(2)       # 検索に反映されるのを、少し待つ
    result["acl"] = stats
    return result


# ------------------------------------------------------------------ 元に戻す

def restore(say=print, wait_seconds: int = WAIT_SECONDS) -> dict:
    """manifest の全部の文書が、data/ のとおりに Storage と索引にある状態に戻す。何度実行しても同じ結果。

    手順：実行中のインデクサーが終わるのを待つ → Storage を data/ と比べる
      ・manifest にない blob：削除の印（IsDeleted=true）を付ける（あとで、索引から消えてから、blob を消す）
      ・data/ と違う（中身かメタデータ。削除の印が付いたままのものも）文書、Storage にない文書：data/ から置き直す
      → インデクサーを動かす → 見てよい人を付け直す → 印を付けた blob の索引のチャンクが 0 件になったのを確かめて、blob を消す
      → 全部の文書のチャンクが索引にあるのを確かめる。
    索引に残ったり、入らなかったりしたときは、SetupError で止まる（元に戻したと言わない）。
    """
    wait_until_indexer_idle(say, wait_seconds)
    cc = clients.container_client()
    existing = {b.name: b for b in cc.list_blobs(include=["metadata"])}
    expected = {pipeline.blob_name(f["path"]) for f in manifest_files()}
    extras = sorted(set(existing) - expected)
    for name in extras:
        add_metadata(cc.get_blob_client(name), **{pipeline.DELETE_MARK: "true"})
    put = put_manifest(only_changed=True, existing=existing)
    result = reindex(say)
    if extras:
        left = wait_until_removed(extras)
        if left:
            raise SetupError("manifest にない文書に印を付けたのに、索引にチャンクが残っています：" + "、".join(f"{n} {c} 件" for n, c in left.items()) + "\n"
                             "  blob は、消さずに残しました（先に消すと、印を読めなくなります）。少し待って、もう一度 cleanup.py を実行してください。")
        for name in extras:
            cc.delete_blob(name)
    missing = wait_until_present([f["path"] for f in manifest_files()])
    if missing:
        raise SetupError("元に戻したはずの文書のチャンクが、索引にありません：" + "、".join(missing) + "\n"
                         "  インデクサーが取り込み終えていないのかもしれません。少し待って、もう一度 cleanup.py を実行してください。")
    say(f"  元に戻しました：Storage に置き直した文書 {len(put)} 件、消した文書 {len(extras)} 件（manifest の {len(expected)} 件が、data/ のとおりです）")
    return {"put": put, "removed": extras, "indexer": result, "acl": result["acl"]}
