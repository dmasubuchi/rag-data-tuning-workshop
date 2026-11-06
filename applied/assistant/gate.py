"""採用アシスタントの画面の入口：合言葉と、1 日の質問の回数の上限。Streamlit を使わずに試せるよう、画面から分けてある。"""
import hmac

DEFAULT_MAX_QUESTIONS = 200


def access_ok(given: str, expected: str | None) -> bool:
    """合言葉が合っているか。expected が空なら合言葉なし（自分の PC で動かすとき）。"""
    if not expected:
        return True
    return hmac.compare_digest((given or "").strip().encode(), expected.strip().encode())


def under_limit(count: int, limit: int) -> bool:
    """今日の質問の数が、上限より少ないか。"""
    return count < limit


def order_questions(questions: list[dict], first: tuple) -> list[dict]:
    """用意した質問のうち、デモで使うもの（first の番号）を、その順で先頭に並べる。残りは元の順。"""
    by_id = {q["id"]: q for q in questions}
    head = [by_id[i] for i in first if i in by_id]
    return head + [q for q in questions if q["id"] not in first]


def max_questions(env: dict) -> int:
    """1 日の上限。環境変数 ASSISTANT_MAX_QUESTIONS（数でなければ既定の 200）。"""
    try:
        return int(env.get("ASSISTANT_MAX_QUESTIONS", DEFAULT_MAX_QUESTIONS))
    except ValueError:
        return DEFAULT_MAX_QUESTIONS
