"""採用アシスタントの画面の、表示の判断。Streamlit を使わずに試せるよう、画面（app.py）から分けてある。

  考えている間   LLM が次の検索を決めるまで 8 秒ほど、右の「検索の段」が空に見える。次の段の枠に「考えています」を出す
  段のカード     1 段を 3 行に収める（4 段と「答えに使った資料」が 1 画面に入るように）。画面に描く間隔も空ける
  出典の見出し   同じファイルの別のチャンクを見分けられるよう、チャンクに出てくる人を添える
  質問のボタン   デモの質問には短い題を付ける
"""
import math
import re
import time
from typing import Callable

from .engine import applicants_of

THINKING = "次の手を考えています…"   # 次が検索か答えかは、そのときにならないと分からない。待ちの文言は 1 つ
MAX_PEOPLE = 3     # 出典の見出しに並べる人の数。これより多ければ「ほか」
HEAD_CHARS = 16    # 人がいないチャンクや、人だけでは見分けがつかないチャンクは、本文の先頭をこの文字数だけ出す
LONG_CHARS = 40    # それでも同じなら、この文字数まで
ARGS_CHARS = 50    # カードの 1 行目に出す、検索の語や条件の長さ
SMALL_CHARS = 56   # カードの 3 行目（文書名と注）の長さ
MIN_TITLE_CHARS = 8   # 注が長くても、先頭の文書名はこの文字数までは出す
STEP_PAUSE = 0.6   # 段を画面に描く最低の間隔（秒）
MAX_PAUSE = 3.0    # 環境変数で変えられる上限

SEPARATORS = "・ 　"
EVAL_ID = re.compile(r"EV-\d{3}")
MARKDOWN_MARKS = re.compile(r"[\\`*_{}\[\]<>#$:~|&]")


# ------------------------------------------------------------------ 考えている間

def thinking_slot(drawn: int, slots: int) -> int | None:
    """「考えています」を出す枠の番号（0 から）。drawn 段を描いたあとなら drawn 番目。枠が尽きていれば None。"""
    return drawn if drawn < slots else None


def slots_to_clear(drawn: int, slots: int) -> list[int]:
    """終わったあとに表示を消す枠の番号。段を描かなかった枠（「考えています」が残るかもしれない枠）。"""
    return list(range(drawn, slots))


def wait_seconds(last_drawn: float | None, now: float, pause: float) -> float:
    """次の段を描く前に待つ秒数。前の段を描いてから pause 秒たっていなければ、その残り。検索や LLM に使った時間は数える。"""
    if last_drawn is None or pause <= 0:
        return 0.0
    return max(0.0, pause - (now - last_drawn))


def step_pause(env: dict) -> float:
    """段を描く最低の間隔。環境変数 ASSISTANT_STEP_PAUSE（秒、0 で間隔なし、3 まで）。数でなければ既定の 0.6。

    ask は段ごとに同期で描くので、段が速く続いたときだけ、その待ちの分（段ごとに最大この秒数）、次の検索と LLM の呼び出しが遅れる。"""
    try:
        value = float(env.get("ASSISTANT_STEP_PAUSE", STEP_PAUSE))
    except ValueError:
        return STEP_PAUSE
    return min(MAX_PAUSE, max(0.0, value)) if math.isfinite(value) else STEP_PAUSE


def ask_live(question: str, slots: list, ask: Callable, render: Callable, tail=None, pause: float = 0.0,
             clock: Callable = time.monotonic, sleep: Callable = time.sleep):
    """質問を実行しながら、段を枠に描く。ask(question, on_step) の返り値を返す。

    次の段の枠には「次の手を考えています」を出す。枠が尽きたら tail の枠に出す。終わったら（止まったときも）使わなかった枠と tail を消す。
    pause 秒より速く次の段が来たら、描く前に残りを待つ。ask は同期で on_step を呼ぶので、その分だけ次の検索と LLM の呼び出しも遅れる
    （段が速く続いたときだけ。LLM に数秒かかる普通の段では待たない）。
    """
    drawn, last_at, tail_used = 0, None, False

    def notice() -> None:
        nonlocal tail_used
        i = thinking_slot(drawn, len(slots))
        if i is not None:
            slots[i].caption(THINKING)
        elif tail is not None:
            tail.caption(THINKING)
            tail_used = True

    def on_step(step) -> None:
        nonlocal drawn, last_at
        wait = wait_seconds(last_at, clock(), pause)
        if wait > 0:
            sleep(wait)
        render(slots[step.no - 1], step)
        drawn, last_at = step.no, clock()
        notice()

    notice()
    try:
        return ask(question, on_step)
    finally:
        for i in slots_to_clear(drawn, len(slots)):
            slots[i].empty()
        if tail_used:
            tail.empty()


# ------------------------------------------------------------------ 段のカード

def escape_markdown(text: str) -> str:
    """Markdown として読まれる記号（* _ $ : [ ] # ` など）の前に \\ を付ける。expander の見出しや caption は Markdown で描かれる。"""
    return MARKDOWN_MARKS.sub(lambda m: "\\" + m.group(0), text or "")


def _args_text(args: dict) -> str:
    def clean(v) -> str:
        if isinstance(v, (list, tuple, set)):
            v = "・".join(str(x) for x in v)   # ['APP-0417'] でなく APP-0417・APP-0439
        return re.sub(r"\s+", " ", str(v)).strip().replace("`", "'")   # コードの枠を壊さない

    text = clean(args["query"]) if list(args) == ["query"] else "　".join(f"{k}: {clean(v)}" for k, v in args.items())
    return _cut(text, ARGS_CHARS)


def _cut(text: str, limit: int) -> str:
    """limit 字までに切って「…」を付ける。区切り（・ 空白）の途中で切れるときは、直前の区切りまで戻る（応募番号を途中で切らない）。
    区切りが上限の半分より前にしかなければ、戻らずに切る。"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    if text[limit] not in SEPARATORS and head[-1] not in SEPARATORS:
        at = max(head.rfind(c) for c in SEPARATORS)
        if at >= limit // 2:        # 戻りすぎない（「applicant_ids:…」のように、値が 1 つも出なくなる）
            head = head[:at]
    return head.rstrip(SEPARATORS) + "…"


def step_lines(step) -> tuple[str, str, str]:
    """1 段のカードの 3 行：(やり方と語、候補の人数、薄い字の行)。薄い字の行は、文書名（入りきらなければ後ろを省く）と注。なければ空。"""
    before = "全員" if step.people_before is None else f"{step.people_before} 人"
    after = "全員" if step.people_after is None else f"{step.people_after} 人"
    head = f"**{step.no}　{step.method}**　`{_args_text(step.args)}`"
    count = f"候補 {before} → **{after}**（文書 {step.docs_found} 件）"
    room = SMALL_CHARS - len(step.note)
    shown = []
    for title in step.top_titles:
        if len("　".join(shown + [title])) > room:
            break
        shown.append(title)
    if shown:
        titles = "　".join(escape_markdown(t) for t in shown) + ("…" if len(shown) < len(step.top_titles) else "")
    elif step.top_titles:    # 先頭の文書名だけで入りきらない：名前を切って出す
        titles = escape_markdown(step.top_titles[0][:max(room - 1, MIN_TITLE_CHARS)]) + "…"
    else:
        titles = ""
    small = "　".join(x for x in (titles, escape_markdown(step.note)) if x)
    return head, count, small


# ------------------------------------------------------------------ 出典の見出し

def _people(source: dict, candidates) -> str:
    """チャンクに出てくる人。残った候補を先に、そのあと番号順。MAX_PEOPLE 人まで、それ以上は「ほか」。"""
    found = applicants_of(source)
    mine = sorted(found & set(candidates or ()))
    people = mine + sorted(found - set(mine))
    return "・".join(people[:MAX_PEOPLE]) + (" ほか" if len(people) > MAX_PEOPLE else "")


def _start(source: dict, chars: int) -> str:
    """本文の先頭（空白をまとめる）。長ければ「…」。"""
    text = re.sub(r"\s+", " ", source.get("chunk") or "").strip()
    return text[:chars] + ("…" if len(text) > chars else "")


def _evaluation_ids(source: dict) -> str:
    """面接の評価一覧のチャンクにある評価ID。複数なら「EV-001〜003」。"""
    ids = sorted(set(EVAL_ID.findall(source.get("chunk") or "")))
    return "" if not ids else ids[0] if len(ids) == 1 else f"{ids[0]}〜{ids[-1][3:]}"


def source_headings(sources: list[dict], candidates=None) -> list[str]:
    """出典の見出し（expander の題）。「[1] ファイル名（APP-0417・APP-0439 ほか）」。

    人は残った候補（candidates）を先に。人がいなければ本文の先頭。
    同じ人の別のチャンクなどで見出しが重なったものにだけ、評価ID（なければ本文の先頭）を足して見分ける。
    """
    labels = [(escape_markdown(s.get("title") or ""), _people(s, candidates)) for s in sources]
    tellers = (lambda s: _evaluation_ids(s) or _start(s, HEAD_CHARS), lambda s: _start(s, LONG_CHARS))
    extra = [""] * len(sources)
    for teller in tellers:
        keys = [(title, people, e) for (title, people), e in zip(labels, extra)]
        for i, (s, (_, people)) in enumerate(zip(sources, labels)):
            if people and keys.count(keys[i]) > 1:
                extra[i] = escape_markdown(teller(s))
    heads = []
    for s, (title, people), e in zip(sources, labels, extra):
        label = f"{people}｜{e}" if people and e else people or escape_markdown(_start(s, HEAD_CHARS))
        heads.append(f"[{s['no']}] {title}" + (f"（{label}）" if label else ""))
    return heads


# ------------------------------------------------------------------ 質問のボタン

def button_label(question: dict, titles: dict, chars: int) -> str:
    """質問のボタンの題。titles にある質問（デモの質問）はその題。ほかは先頭の chars 字。"""
    return titles.get(question["id"]) or question["question"][:chars] + "…"
