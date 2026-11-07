"""Azure OpenAI の呼び出し（埋め込みと回答の生成）。呼んだ回数を数えて、あとで表示できるようにする。"""
import time
from collections import Counter

from .clients import openai_client
from .config import SetupError, get_settings

CALLS: Counter = Counter()  # {"embedding": 回数, "chat": 回数}

EMBED_BATCH = 32  # 1回の呼び出しで埋め込む文の数
RETRY_LIMIT = 4   # 「呼びすぎ（429）」と言われたときに、待って再試行する回数


def _with_retry(call):
    """Azure OpenAI が「短い時間に呼びすぎ（429）」と返したら、少し待って再試行する。

    チームの全員が同時に実行すると、この制限に当たることがある。待つ秒数は、Azure が返す Retry-After に従う。
    """
    from openai import RateLimitError

    for attempt in range(RETRY_LIMIT + 1):
        try:
            return call()
        except RateLimitError as e:
            if attempt == RETRY_LIMIT:
                raise
            wait = 15
            headers = getattr(getattr(e, "response", None), "headers", None)
            if headers and headers.get("retry-after"):
                try:
                    wait = min(max(int(float(headers["retry-after"])), 5), 60)
                except ValueError:
                    pass
            print(f"  Azure OpenAI が混み合っています（呼びすぎの制限）。{wait} 秒待って、もう一度送ります（{attempt + 1}/{RETRY_LIMIT}）。")
            time.sleep(wait)


def embed_texts(texts: list, label: str = "", show_progress: bool = True) -> list:
    """文の一覧を埋め込み、同じ並びのベクトルの一覧を返す。

    EMBED_BATCH 件ずつ Azure OpenAI に送る。次元は .env.local の EMBEDDING_DIMENSIONS。
    """
    s = get_settings()
    client = openai_client()
    vectors: list = []
    total = len(texts)
    for start in range(0, total, EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        res = _with_retry(lambda: client.embeddings.create(model=s.embedding_deployment, input=batch, dimensions=s.dimensions))
        CALLS["embedding"] += 1
        data = sorted(res.data, key=lambda d: d.index)
        for d in data:
            if len(d.embedding) != s.dimensions:
                raise SetupError(
                    f"埋め込みの長さが {len(d.embedding)} でした（.env.local の EMBEDDING_DIMENSIONS は {s.dimensions}）。\n"
                    "  EMBEDDING_DIMENSIONS と、埋め込みモデルの次元を合わせてください。"
                )
            vectors.append(list(d.embedding))
        if show_progress and total > EMBED_BATCH:
            print(f"  埋め込み {min(start + EMBED_BATCH, total)}/{total} 件{('（' + label + '）') if label else ''}")
    return vectors


def embed_one(text: str) -> list:
    return embed_texts([text], show_progress=False)[0]


_model_name_cache: dict = {}


def embedding_model_name() -> str:
    """いま使っている埋め込みモデルの名前（Azure が返す名前）。短い文を1回埋め込んで調べる。"""
    if "name" not in _model_name_cache:
        s = get_settings()
        res = _with_retry(lambda: openai_client().embeddings.create(
            model=s.embedding_deployment, input=["モデル名の確認"], dimensions=s.dimensions))
        CALLS["embedding"] += 1
        _model_name_cache["name"] = res.model
    return _model_name_cache["name"]


def sent_conditions(max_tokens: int = 4000) -> dict:
    """chat が実際に送る条件（記録・表示用）。temperature は送らないので「未指定」と書く。"""
    s = get_settings()
    return {"temperature": "未指定（送っていない）", "reasoning_effort": s.reasoning_effort or "未指定",
            "max_completion_tokens": max_tokens}


def chat(messages: list, temperature: float = 0.0, max_tokens: int = 4000) -> str:
    """messages を Azure OpenAI に送り、回答の文章を返す。

    推論モデルは temperature を受け付けないので、temperature は渡さない（引数は呼ぶ側との互換のために残してある）。
    max_tokens は max_completion_tokens として渡す。.env.local の AZURE_OPENAI_REASONING_EFFORT があれば reasoning_effort で渡す。
    答えが空のとき、出力の上限に達して途中で切れたときは、原因を書いた SetupError で止める。
    """
    s = get_settings()
    kwargs = {"max_completion_tokens": max_tokens}
    if s.reasoning_effort:
        kwargs["reasoning_effort"] = s.reasoning_effort
    res = _with_retry(lambda: openai_client().chat.completions.create(
        model=s.chat_deployment, messages=messages, **kwargs,
    ))
    CALLS["chat"] += 1
    choice = res.choices[0]
    text = (choice.message.content or "").strip()
    reason = choice.finish_reason
    if reason == "length" or not text:
        used = getattr(getattr(res, "usage", None), "completion_tokens_details", None)
        thinking = getattr(used, "reasoning_tokens", None)
        why = "出力の上限（max_completion_tokens）に達して、途中で切れました" if reason == "length" else "答えが空でした"
        hint = f"（考えるために使った分 {thinking} トークン）" if thinking else ""
        raise SetupError(
            f"回答を作れませんでした：{why}。終わり方 finish_reason={reason}{hint}\n"
            "  推論モデルは、答える前の「考える」分も上限に数えます。.env.local の AZURE_OPENAI_REASONING_EFFORT は、考える量を決める設定です（既定は low）。\n  この行がなくなっていないか確かめてください。"
        )
    return text
