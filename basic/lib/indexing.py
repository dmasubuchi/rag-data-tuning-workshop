"""登録（アップロード）の道具。数百件ずつに分けて送り、成功と失敗の件数を数える。"""
import time

from .config import SetupError
from .runner import redact


def upload(client, documents: list, *, mode: str = "upload", batch_size: int = 50) -> int:
    """documents を batch_size 件ずつ登録する。

    mode="upload"：丸ごと登録（同じキーがあれば置き換える）
    mode="merge" ：同じキーの文書に、渡した項目だけを足す（ベクトルの項目を足すときに使う）
    戻り値は成功した件数。1件でも失敗したら、理由を表示して SetupError にする。
    """
    sender = {"upload": client.upload_documents, "merge": client.merge_or_upload_documents}[mode]
    ok = 0
    failed: list = []
    total = len(documents)
    for start in range(0, total, batch_size):
        batch = documents[start:start + batch_size]
        results = sender(documents=batch)
        for r in results:
            if r.succeeded:
                ok += 1
            else:
                failed.append((r.key, r.error_message))
        print(f"  登録 {min(start + batch_size, total)}/{total} 件（成功 {ok} 件）")
    if failed:
        for key, msg in failed[:5]:
            print(redact(f"  失敗: {key}: {msg}"))     # 応答の文にキーが混じっていても、表示の前に伏せる
        raise SetupError(f"{len(failed)} 件の登録に失敗しました。上の理由を確かめてください（項目の名前や型がインデックスの定義と合っているか）。")
    return ok


def wait_for_count(client, expected: int, timeout: float = 30.0) -> int:
    """登録した件数が、検索側のカウントに現れるまで待つ（反映に1〜数秒かかることがある）。"""
    t0 = time.time()
    n = client.get_document_count()
    while n < expected and time.time() - t0 < timeout:
        time.sleep(1.0)
        n = client.get_document_count()
    return n
