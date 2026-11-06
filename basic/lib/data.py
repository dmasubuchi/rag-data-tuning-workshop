"""データ（武将の JSON と質問）を読む道具。

武将の人数や質問の数には依存しない書き方にしてある（ファイルにあるだけ読む）。
"""
import json
import unicodedata
from pathlib import Path

from .config import BUSHOU_JSON, QUESTIONS_JSON, SetupError, display_path


def read_json(path: Path):
    if not path.is_file():
        raise SetupError(f"データのファイルが見つかりません: {display_path(path)}\n  basic/data フォルダがあるか確かめてください（Repo を取得し直すと戻ります）。")
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 武将

def load_bushou() -> list:
    return read_json(BUSHOU_JSON)


def embedding_text(person: dict) -> str:
    """武将を埋め込むときの文字列。name ＋「。」＋ profile（）。"""
    return f"{person['name']}。{person['profile']}"


def load_questions() -> list:
    """questions.json。ファイルがなくても止めず、空の一覧を返す（正解の順位を出さないだけ）。"""
    if not QUESTIONS_JSON.is_file():
        return []
    return read_json(QUESTIONS_JSON)


def _is_selected(q: dict) -> bool:
    v = q.get("selected")
    if isinstance(v, str):
        return v.strip().lower() not in ("", "false", "no", "0", "none")
    return bool(v)


def _selected_id(kind: str):
    """data/sengoku/selection.json でハンズオン資料用に選んだ質問の id（なければ None）。"""
    path = QUESTIONS_JSON.parent / "selection.json"
    if not path.is_file():
        return None
    return read_json(path).get(kind)


def _by_id(qid):
    for q in load_questions():
        if q.get("qid") == qid:
            return q
    return None


def climax_question() -> dict:
    """山場の質問。selection.json の climax、なければ questions.json で selected が付いたもの、なければ intent が climax の最初のもの。"""
    q = _by_id(_selected_id("climax"))
    if q:
        return q
    qs = load_questions()
    for q in qs:
        if _is_selected(q):
            return q
    for q in qs:
        if q.get("intent") == "climax":
            return q
    raise SetupError("questions.json に、山場の質問（selected が付いたもの、または intent が climax のもの）がありません。")


def paraphrase_question() -> dict:
    """言い換えの質問（03-vector-search）。selection.json の paraphrase、なければ intent が vector-wins の最初のもの。"""
    q = _by_id(_selected_id("paraphrase"))
    if q:
        return q
    for q in load_questions():
        if q.get("intent") == "vector-wins":
            return q
    raise SetupError("questions.json に、言い換えの質問（intent が vector-wins のもの）がありません。")


def resolve_question(given, kind: str):
    """質問の文章と、questions.json の行（なければ None）を返す。

    given が文字列ならそれを使う（自分の質問）。None なら、kind に応じて questions.json から選ぶ。
      kind="paraphrase"  言い換えの質問（selection.json の paraphrase、なければ intent が vector-wins の最初）
      kind="climax"      山場の質問（selection.json の climax、なければ selected、なければ intent が climax の最初）
    """
    if given:
        return given, find_question(given)
    q = paraphrase_question() if kind == "paraphrase" else climax_question()
    return q["question"], q


def qid_note(q) -> str:
    """質問の出どころの一言。例「（questions.json の q03）」。questions.json にない質問は空。"""
    return f"（questions.json の {q['qid']}）" if q and q.get("qid") else ""


def find_question(text: str):
    """質問の文章が questions.json にあれば、その行を返す（正解の武将の id を知るため）。なければ None。"""
    norm = _norm_q(text)
    for q in load_questions():
        if _norm_q(q.get("question", "")) == norm:
            return q
    return None


def _norm_q(s: str) -> str:
    return "".join(unicodedata.normalize("NFC", s).split())


def answer_rank(results: list, answer_ids) -> "int | None":
    """results（上から順）の中で、正解の id が最初に出てくる順位（1 始まり）。なければ None。"""
    ids = set(answer_ids or [])
    for i, r in enumerate(results, start=1):
        if r.get("id") in ids:
            return i
    return None


def names_by_id() -> dict:
    return {p["id"]: p["name"] for p in load_bushou()}
