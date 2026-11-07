"""AI Search の検索と、Azure OpenAI の埋め込みを、REST で呼ぶ（標準ライブラリだけ）。

呼ぶのは次の2つだけ（どちらも読むだけ。管理キーは要らない）。
  search()  POST <接続先>/indexes/<名前>/docs/search?api-version=…        （メンバーの query キーでよい）
  embed()   POST <Azure OpenAI の接続先>/openai/v1/embeddings             （tools/hotel_vectors.py と同じ呼び方）

失敗は RestError。status は HTTP の番号で、つながらなかったときは None。
呼びすぎ（429）は待って再試行し、サーバーの失敗（5xx）とつながらない失敗は1回だけやり直す。
"""
import http.client
import json
import time
import urllib.error
import urllib.request

SEARCH_API = "2024-07-01"        # tools/search_demo.py と同じ
TIMEOUT = 60
BUSY_RETRIES = 4                 # 429 のとき、待って再試行する回数
DETAIL_CHARS = 300


class RestError(Exception):
    def __init__(self, status, detail=""):
        super().__init__(f"{status}: {detail}")
        self.status = status     # HTTP の番号。つながらない・読めないときは None
        self.detail = detail


def _wait_seconds(error) -> int:
    try:
        return min(max(int(float(error.headers.get("retry-after", 15))), 5), 60)
    except (AttributeError, TypeError, ValueError):
        return 15


def post_json(url, key, body):
    """JSON を POST して、答えの JSON を返す。キーは api-key のヘッダーで送る（画面にもファイルにも出さない）。"""
    data = json.dumps(body).encode("utf-8")        # 日本語は \uXXXX に直す（tools/search_demo.py と同じ。本文は ASCII だけ）
    headers = {"api-key": key, "Content-Type": "application/json"}
    busy, retried = 0, False
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method="POST"),
                                        timeout=TIMEOUT) as res:
                raw = res.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:DETAIL_CHARS]
            if error.code == 429 and busy < BUSY_RETRIES:
                busy += 1
                time.sleep(_wait_seconds(error))
                continue
            if error.code >= 500 and not retried:
                retried = True
                time.sleep(2)
                continue
            raise RestError(error.code, detail) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            if not retried:
                retried = True
                time.sleep(2)
                continue
            raise RestError(None, str(getattr(error, "reason", error))) from None
        except ValueError:
            raise RestError(None, "接続先の形が違います（http:// か https:// で始まる URL を書きます）") from None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise RestError(None, "答えが JSON として読めません") from None


def search(settings, index, body) -> dict:
    url = f"{settings.search_endpoint}/indexes/{index}/docs/search?api-version={SEARCH_API}"
    return post_json(url, settings.search_key, body)


def embed(settings, text):
    """質問を埋め込む。(ベクトル, 使ったトークン数) を返す。トークンは答えの usage.total_tokens。"""
    body = {"model": settings.embedding_deployment, "input": [text], "dimensions": settings.dimensions}
    answer = post_json(f"{settings.openai_endpoint}/openai/v1/embeddings", settings.openai_key, body)
    try:
        vector = answer["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError):
        raise RestError(None, "埋め込みの答えの形が違います") from None
    if len(vector) != settings.dimensions:
        raise RestError(None, f"埋め込みの長さが {len(vector)} でした（EMBEDDING_DIMENSIONS は {settings.dimensions}）")
    usage = answer.get("usage") if isinstance(answer, dict) else None
    tokens = 0
    if isinstance(usage, dict):
        tokens = usage.get("total_tokens", usage.get("prompt_tokens", 0))
    return vector, tokens if isinstance(tokens, int) else 0
