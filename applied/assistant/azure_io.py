"""採用アシスタントの、Azure とのつなぎ：検索（AI Search）と、道具を選ぶ LLM（Azure OpenAI）。

流れ（ask）
  1. LLM に質問と4つの道具を渡す。LLM が道具と、その語や条件を選ぶ
  2. 道具を実行して、engine.apply_step で候補と根拠を更新する。段の記録は on_step で画面に渡す
  3. 結果の要約（残った人数、見つけた文書と番号、本文の先頭）を LLM に返し、1 に戻る
  4. LLM が道具を使わずに答えたら終わり。段が MAX_STEPS に達したら、道具を使わせずに答えさせる
  5. 文に書いた人と資料の人が合わない出典の番号を外し、範囲の外の番号を消して、使われた資料だけを 1 から振り直す

検索は、いつもチームのインデックス hr-docs を、採用担当の役（role:recruiter）で見る。接続先とキーは .env.local から読む。
検索と LLM だけを使うので、メンバーの設定（検索だけのキー、Storage の項目なし）でも動く。
"""
import json
import os
import re
import time
from typing import Callable

from lib import acl, config

from .engine import EVALUATIONS, JA_CHARS, MAX_STEPS, Run, Step, applicants_of, apply_step, candidate_filter, names_of

INDEX = config.HR_INDEX      # "hr-docs"。チームの人事のインデックス（名前は固定）
SELECT = ["chunk_id", "doc_id", "kind", "req_id", "application_ids", "title", "chunk"]
TOP = {"keyword": 20, "vector": 8, "fields": 50, "follow": 50}
SUMMARY = {"fields": (50, 0), "keyword": (20, 300), "vector": (8, 300), "follow": (50, 500)}   # LLM に返す（文書の数, 本文の長さ）
MAX_LLM_CALLS = MAX_STEPS + 3
LLM_TIMEOUT = 60           # 秒。ハンズオン中に止まったまま待たないように、短めにする
SEARCH_TIMEOUT = 30        # 秒
EFFORTS = ("none", "low", "medium", "high")
DEFAULT_EFFORT = "low"
RETRIES = 4
RETRY_WAIT = 15
REQ = re.compile(r"REQ-\d{3}")
APP = re.compile(r"APP-\d{4}")
KINDS = ("job_posting", "resume", "mail", "scan", "interview_evaluations")

SYSTEM = """あなたは採用担当を助けるアシスタントです。架空の会社の採用の文書（求人票・職務経歴書・面接の評価一覧・連絡メール・スキャンした書類）だけを根拠に答えます。

探し方
- 道具を使って、候補（応募者）を段ごとに絞り込みます。2段目からの検索は、前の段で残った候補の文書だけが対象です。
- 質問に求人番号（REQ-…）や応募番号（APP-…）があれば、まず filter_fields で絞ります。人の名前だけのときは、keyword_search で名前を探します。
- filter_fields の結果には、文書の名前しか出ません。経験・評価・段階・日付などの条件がある質問では、次に必ず keyword_search（同じ言葉が入っている文書）か vector_search（言い方が違っても意味が近い文書）で条件を探し、候補を絞ります。言い方を変えて、もう一度探してもかまいません。
- 候補が決まったら follow_ids で、その人たちの経歴書・面接の評価・メール・スキャンと求人票を集め、中身を読んでから答えます。
- 1つの文書や1人のことだけを聞く質問で、1回の検索で答えられるなら、段を増やしません。段は全部で6つまでです。
- 同じ道具を同じ語や条件で2回使いません。follow_ids は1回だけ使います。探しても見つからないものは、それ以上探さずに答えに進みます。

答え方
- 日本語の、です・ます。人は「名前（応募番号）」の形で書きます。
- 文ごとに、根拠にした資料の番号を [1] のように付けます。番号は、道具の結果に出た番号だけを使います。資料の番号と、その資料に書かれた人（応募番号）が合っているかを確かめてから付けます。
- 資料にないことや確かめられないことは「資料にありません」「資料からは確認できません」と、括弧に入れずに書きます。推測で補いません。
- 質問の求人番号・応募番号・人が資料に見つからないときは、推測で数を答えず「資料にありません」と答えます。
- 本人が担当したのか、ほかの人の手伝いだったのかなど、資料の書き方の違いはそのまま伝えます。
- 「〜のうち、だれ」のように全員を対象にした質問で、絞り込みで外れた人がいれば、「検索で該当する記述が見つかりませんでした」と名前（応募番号）だけを一言添えます。その人のことを推測しません。
- 答えのあとに、追加の提案（「必要であれば〜」など）を書きません。"""

TOOLS = [
    {"type": "function", "function": {
        "name": "keyword_search", "description": "本文に同じ言葉が入っている文書を探し、その文書に出てくる人に候補を絞る。名前や決まった言い方を探すときに使う。",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "探す言葉（空白で区切ってよい）"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "vector_search", "description": "言い方が違っても意味が近い文書を探し、その文書に出てくる人に候補を絞る。経験や様子を探すときに使う。",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "探したい内容を表す短い文"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "filter_fields", "description": "求人番号・文書の種類・応募番号の欄で候補を絞る。",
        "parameters": {"type": "object", "properties": {
            "req_id": {"type": "string", "description": "求人番号（例 REQ-042）"},
            "kind": {"type": "string", "enum": list(KINDS), "description": "文書の種類"},
            "applicant_ids": {"type": "array", "items": {"type": "string"}, "description": "応募番号（例 APP-0391）"}}}}},
    {"type": "function", "function": {
        "name": "follow_ids", "description": "いま残っている候補の人について、応募番号をたどって、経歴書・面接の評価・メール・スキャンと、応募先の求人票を集める。候補は変えない。",
        "parameters": {"type": "object", "properties": {}}}},
]
TOOL_KIND = {"keyword_search": "keyword", "vector_search": "vector", "filter_fields": "fields", "follow_ids": "follow"}


class RateLimited(Exception):
    """Azure OpenAI の呼びすぎ（429）。少し待ってやり直す。
    status_code は lib/errors.py の explain が状態の番号として読む。やり直しを使い切ったときも「Azure が混んでいます」と出る。"""
    status_code = 429


# ------------------------------------------------------------------ Azure

def search(text: str | None, vector_text: str | None, extra_filter: str | None, top: int) -> list[dict]:
    """インデックス hr-docs を検索する。いつも採用担当の役で見る。"""
    from azure.core.exceptions import ServiceResponseError
    from azure.search.documents.models import VectorizableTextQuery

    from lib import clients

    f = acl.scope_filter(acl.VIEWER_RECRUITER)
    if extra_filter:
        f = f"{f} and ({extra_filter})"
    kwargs = {"filter": f, "select": SELECT, "top": top}
    if vector_text:
        kwargs["vector_queries"] = [VectorizableTextQuery(text=vector_text, k_nearest_neighbors=top, fields=config.VECTOR_FIELD)]
    else:
        kwargs["search_fields"] = ["chunk", "title"] if text and text != "*" else None
    kwargs.update(connection_timeout=10, read_timeout=SEARCH_TIMEOUT)
    try:
        return [{k: d.get(k) for k in SELECT} for d in clients.search_client(INDEX).search(text if not vector_text else None, **kwargs)]
    except ServiceResponseError as e:
        raise config.SetupError(f"AI Search の応答が {SEARCH_TIMEOUT} 秒で返りませんでした。もう一度押してください") from e


def reasoning_effort(env: dict, configured: str = "") -> str:
    """LLM の考える量（none・low・medium・high）。次の順で、最初に見つかった、使える値にする。
      1. 環境変数 ASSISTANT_REASONING_EFFORT（人に見せるときの、アプリだけの指定）
      2. configured（.env.local の AZURE_OPENAI_REASONING_EFFORT。呼び出し側が渡す）
      3. 既定の low
    上の 4 つ以外の値は、書いていないものとして次へ進む。
    既定を low にしているのは、none（考えない）では、資料と人の取り違えが出たことがあるため。"""
    for value in (env.get("ASSISTANT_REASONING_EFFORT", ""), configured):
        if value in EFFORTS:
            return value
    return DEFAULT_EFFORT


def openai_llm(messages: list, tools: list, tool_choice: str) -> dict:
    """Azure OpenAI（.env.local のチャットのデプロイ）に、道具つきで送る。返事を {content, tool_calls, usage} にそろえる。"""
    from openai import APITimeoutError, RateLimitError

    from lib import agentic

    s = config.get_settings()
    kwargs = {"max_completion_tokens": 6000, "reasoning_effort": reasoning_effort(os.environ, s.reasoning_effort)}
    client = agentic.openai_client().with_options(timeout=LLM_TIMEOUT, max_retries=1)
    try:
        res = client.chat.completions.create(model=s.chat_deployment, messages=messages, tools=tools,
                                             tool_choice=tool_choice, **kwargs)
    except RateLimitError as e:
        raise RateLimited() from e
    except APITimeoutError as e:
        raise config.SetupError(f"Azure OpenAI の応答が {LLM_TIMEOUT} 秒で返りませんでした。もう一度押してください") from e
    m = res.choices[0].message
    calls = [{"id": t.id, "name": t.function.name, "arguments": t.function.arguments} for t in (m.tool_calls or [])]
    usage = {"input_tokens": getattr(res.usage, "prompt_tokens", 0) or 0, "output_tokens": getattr(res.usage, "completion_tokens", 0) or 0}
    return {"content": (m.content or "").strip(), "tool_calls": calls, "usage": usage}


# ------------------------------------------------------------------ 道具

def _fields_filter(args: dict) -> str:
    parts = []
    req = args.get("req_id")
    if req:
        if not REQ.fullmatch(str(req)):
            raise config.SetupError(f"求人番号の形ではありません（{req!r}）。例 REQ-042")
        # 面接の評価一覧は求人番号の欄が「-」なので、本文の行に求人番号があるものも入れる
        parts.append(f"(req_id eq '{req}' or (kind eq 'interview_evaluations' and search.ismatch('\"{req}\"', 'chunk')))")
    kind = args.get("kind")
    if kind:
        if kind not in KINDS:
            raise config.SetupError(f"文書の種類は {', '.join(KINDS)} のどれかです（{kind!r}）")
        parts.append(f"kind eq '{kind}'")
    ids = args.get("applicant_ids") or []
    if ids:
        if not isinstance(ids, list) or not all(APP.fullmatch(str(x)) for x in ids):
            raise config.SetupError(f"応募番号の形ではありません（{ids!r}）。例 APP-0391")
        parts.append(f"search.ismatch('{' '.join(ids)}', 'application_ids', 'simple', 'any')")
    if not parts:
        raise config.SetupError("絞る欄（求人番号・文書の種類・応募番号）が1つもありません")
    return " and ".join(parts)


def _and(*parts) -> str | None:
    kept = [p for p in parts if p]
    return " and ".join(f"({p})" for p in kept) if kept else None


def run_tool(run: Run, name: str, args: dict, searcher=search) -> Step:
    """道具を1つ実行して、1 段の記録を返す。知らない道具や、形の合わない値は SetupError。"""
    tool = TOOL_KIND.get(name)
    if tool is None:
        raise config.SetupError(f"知らない道具です（{name}）")
    cand = candidate_filter(run.candidates)
    if tool in ("keyword", "vector"):
        query = str(args.get("query") or "").strip()
        if not query:
            raise config.SetupError("探す言葉が空です")
        hits = searcher(query if tool == "keyword" else None, query if tool == "vector" else None, cand, TOP[tool])
        return apply_step(run, tool, {"query": query}, hits, True)
    if tool == "fields":
        hits = searcher("*", None, _and(_fields_filter(args), cand), TOP[tool])
        return apply_step(run, tool, {k: v for k, v in args.items() if v}, hits, True)
    if run.candidates is None:
        raise config.SetupError("まだ候補を絞っていません。先に検索で絞ってから、たどってください")
    reqs = sorted({h.get("req_id") for h in run.evidence.values()
                   if REQ.fullmatch(h.get("req_id") or "") and applicants_of(h) & run.candidates})
    jobs = f"kind eq 'job_posting' and search.in(req_id, '{','.join(reqs)}')" if reqs else None
    f = f"({cand}) or ({jobs})" if jobs else cand
    hits = searcher("*", None, f, TOP[tool])
    return apply_step(run, tool, {"候補": " ".join(sorted(run.candidates))}, hits, False)


def _with_names(apps, by_app: dict[str, str]) -> str:
    """応募番号の並びを、名前が分かる人は「岩崎 俊樹（APP-0471）」、分からない人は番号だけにして、「・」でつなぐ。"""
    return "・".join(f"{by_app[a]}（{a}）" if a in by_app else a for a in sorted(apps))


def summary(run: Run, step: Step, hits_ids: list[str], tool: str) -> str:
    """1 段の結果を、LLM に返す文にする。資料の番号は、run.evidence に入った順（1 から）。

    欄で絞る段は、文書の名前と人だけ（本文を読ませず、次にキーワードかベクトルで中身を探させる）。
    キーワード・ベクトルの段は本文の先頭も。たどる段は、答えの材料になるので、集めた文書を全部、本文つきで。
    人は、ここまでに集めた資料から名前が分かれば「岩崎 俊樹（APP-0471）」の形で出す（番号だけだと、答えに名前が出ないことがあった）。
    """
    order = {cid: i + 1 for i, cid in enumerate(run.evidence)}
    by_app = {app: name for name, apps in sorted(names_of(list(run.evidence.values())).items()) for app in apps}   # ここまでに集めた資料から
    people = "全員（まだ絞っていない）" if run.candidates is None else f"{len(run.candidates)} 人（{_with_names(run.candidates, by_app)}）"
    lines = [f"段 {step.no}（{step.method}）：残った候補 {people}、見つけた文書 {step.docs_found} 件。{step.note}".rstrip()]
    limit, chars = SUMMARY[tool]
    for cid in hits_ids[:limit]:
        h = run.evidence[cid]
        who = _with_names(applicants_of(h), by_app) or "応募なし"
        body = re.sub(r"\s+", " ", _marked(h))[:chars]
        lines.append(f"[{order[cid]}] {h.get('title')}（{h.get('kind')}、求人 {h.get('req_id')}、{who}）{body}".rstrip())
    return "\n".join(lines)


# ------------------------------------------------------------------ 出典

_LIST = re.compile(r"\[(\d+(?:\s*[,、，]\s*\d+)+)\]")
_ONE = re.compile(r"\[(\d+)\]")
_CITE = r"\[\d+(?:\s*[,、，]\s*\d+)*\]"
_SENTENCE = re.compile(rf"[^。\n]*。(?:[ \t　]*{_CITE})*|[^。\n]+")   # 「。」までと、その直後の [n] の並びを 1 文とする。改行も文の切れ目
_CITE_ONE = re.compile(r"[ \t　]*\[(\d+)\]")
# 「資料にありません」の型の文：探して見つからなかったと言うだけの文。番号がなくてよい
_NOT_IN_DOCS = re.compile(r"資料(?:に|から|では|を)(?!基づ|よる|よれ|よっ|照ら|従|判断)[^。\n]{0,40}?"
                          r"(?:ありません|見当たりません|確認できません|見つかりません|存在しません|記載されていません)(?:でした)?[。）)」\s]*$")
NO_CITATION = "答えに出典の番号がありません"
MIN_SURNAME = 2     # 名字だけで人を引くときの、名字の長さ
# 「姓 名さん／様」の形の、名前らしい語（資料の名前の対応にない人かもしれない）
NAME_LIKE = re.compile(rf"[{JA_CHARS}]{{1,6}}[ \u3000]+[{JA_CHARS}]{{1,6}}(?:さん|様|氏)")
PARAGRAPH_BREAK = re.compile(r"(\n[ \t　]*\n\s*)")
CONTINUED = "（ここから前の行の続き。だれの評価かは、この資料からは分からない）"
NEXT_ROW = "（ここから次の行）"
SHEET_HEAD = re.compile(r"_pages_0$")     # 評価一覧の最初のチャンク（シートの見出しで始まる）の chunk_id の終わり


def _people_in(sentence: str, names: dict[str, set[str]]) -> set[str]:
    """文に出てくる人（応募番号）。応募番号が書いてあればそれ。なければ、資料から作った名前の対応で引く（名字だけでも）。"""
    ids = set(APP.findall(sentence))
    if ids:
        return ids
    compact = re.sub(r"\s+", "", sentence)
    by_surname: dict[str, list[tuple[str, set[str]]]] = {}
    for name, apps in names.items():
        surname, _, given = name.partition(" ")
        by_surname.setdefault(surname, []).append((surname + given, apps))
    found: set[str] = set()
    for surname, people in by_surname.items():
        full = [apps for fullname, apps in people if fullname in compact]
        if full:
            found.update(*full)                       # 姓名が書いてあれば、その人だけ（同じ名字の別の人は入れない）
        elif len(surname) >= MIN_SURNAME and re.search(re.escape(surname) + rf"(?![ \u3000]+[{JA_CHARS}])", sentence):
            found.update(*(apps for _, apps in people))     # 名字の直後に名前が続くなら（資料にない別の人）名字だけでは引かない
    return found


def _continues(hit: dict) -> bool:
    """評価一覧のチャンクが、前の行の途中から始まるか（先頭の空でない行に応募番号がない）。
    最初のチャンク（chunk_id が _pages_0 で終わる）は、シートの見出しで始まるので、続きではない。"""
    if hit.get("kind") != EVALUATIONS or SHEET_HEAD.search(hit.get("chunk_id") or ""):
        return False
    first = next((ln for ln in (hit.get("chunk") or "").splitlines() if ln.strip()), "")
    return not APP.search(first)


def _owners(hit: dict) -> set[str]:
    """出典の資料の人。前の行の続きで始まる評価一覧のチャンクは、その人が分からないので空。
    applicants_of は候補の人数にも使うので変えず、ここだけで見る。"""
    return set() if _continues(hit) else applicants_of(hit)


def _marked(hit: dict) -> str:
    """要約に入れる本文。前の行の続きで始まる評価一覧のチャンクには、続きの前と、最初の応募番号の行の前に添え書きを入れる。"""
    text = hit.get("chunk") or ""
    if not _continues(hit):
        return text
    lines = text.splitlines()
    nxt = next((i for i, ln in enumerate(lines) if APP.search(ln)), None)
    out = [CONTINUED]
    for i, ln in enumerate(lines):
        if i == nxt:
            out.append(NEXT_ROW)
        out.append(ln)
    return "\n".join(out)


def drop_mismatched_citations(answer: str, evidence: list[dict], question: str = "") -> tuple[str, int]:
    """文に書いた人と、出典の資料の人が合わない [n] を外す。(直した答え, 外した数) を返す。言い方（資料にありません など）は見ない。

    文の人は、文の中の応募番号。なければ、資料の本文から作った名前の対応で引く（作れなければ名前は見ない）。
    その文の [n] が指す資料（evidence[n-1]）の人が空でなく、文の人と 1 人も重ならないとき、その [n] を外す。
    資料の人が空（求人票・前の行の途中から始まる評価一覧のチャンクなど）、n が範囲の外のときは外さない（範囲の外は check_citations が消す）。
    文に人がいないときは、同じ段落（空行まで。箇条書きの行は続き）の前の文に出てきた人を全部まとめて、その文の人とする。
    それもいなければ、質問に出てくる人。どちらもいなければ外さない。段落をまたいでは引き継がない。
    「姓 名さん」の形の名前があるのに名前の対応から引けない文は、だれの話か分からないので、外さない。
    """
    names = names_of(evidence)
    people = [_owners(h) for h in evidence]
    asked = _people_in(question, names) if question else set()
    removed = 0

    earlier: set[str] = set()      # いまの段落の、前の文に出てきた人

    def fix(m: re.Match) -> str:
        nonlocal removed
        sentence = m.group(0)
        own = _people_in(sentence, names)
        if own:
            mine = own
        elif NAME_LIKE.search(sentence):
            mine = set()
        else:
            mine = set(earlier) or asked
        earlier.update(own)
        if not mine:
            return sentence

        def one(c: re.Match) -> str:
            nonlocal removed
            k = int(c.group(1))
            if 1 <= k <= len(evidence) and people[k - 1] and not (people[k - 1] & mine):
                removed += 1
                return ""
            return c.group(0)

        return _CITE_ONE.sub(one, sentence)

    text = _LIST.sub(lambda m: "".join(f"[{x}]" for x in re.split(r"\s*[,、，]\s*", m.group(1))), answer)
    parts = PARAGRAPH_BREAK.split(text)          # 段落と、段落の間の空行が交互に入る
    for i in range(0, len(parts), 2):
        earlier.clear()
        parts[i] = _SENTENCE.sub(fix, parts[i])
    return "".join(parts), removed


def _only_not_in_docs(text: str) -> bool:
    """答えが「資料にありません」の型の文だけか（中身のある文が 1 つもないか）。"""
    sentences = [re.sub(r"[*_`]", "", x).strip() for x in _SENTENCE.findall(text)]    # 強調の記号は外して見る
    sentences = [x for x in sentences if re.sub(r"[。\s]", "", x)]
    return bool(sentences) and all(_NOT_IN_DOCS.search(x) for x in sentences)


def check_citations(answer: str, n: int) -> tuple[str, list[str]]:
    """[k] のうち 1..n の外を消す。[1, 2] は [1][2] に分ける。消した番号と、出典がないことを warnings に入れる。
    番号が 1 つもなくても、答えが「資料にありません」の型の文だけなら、出典がないとは注意しない。"""
    text = _LIST.sub(lambda m: "".join(f"[{x}]" for x in re.split(r"\s*[,、，]\s*", m.group(1))), answer)
    bad = sorted({int(k) for k in _ONE.findall(text) if not 1 <= int(k) <= n})
    text = _ONE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n else "", text)
    warnings = [f"答えに、見つけていない資料の番号がありました（{', '.join(map(str, bad))}）。消しました"] if bad else []
    if not _ONE.search(text) and not _only_not_in_docs(text):
        warnings.append(NO_CITATION)
    return text, warnings


def renumber(answer: str) -> tuple[str, list[int]]:
    """出典の番号を、答えに出てくる順に 1 から振り直す。(振り直した答え, 元の番号の並び) を返す。"""
    used = []
    for k in _ONE.findall(answer):
        if int(k) not in used:
            used.append(int(k))
    new = {old: i + 1 for i, old in enumerate(used)}
    return _ONE.sub(lambda m: f"[{new[int(m.group(1))]}]", answer), used


# ------------------------------------------------------------------ 1 問

def _call(llm, messages: list, tool_choice: str) -> dict:
    for attempt in range(RETRIES + 1):
        try:
            return llm(messages, TOOLS, tool_choice)
        except RateLimited:
            if attempt == RETRIES:
                raise
            time.sleep(RETRY_WAIT)


def ask(question: str, on_step: Callable[[Step], None], llm=None, searcher=search) -> dict:
    """1 問に答える。{run, answer, sources, warnings, tokens} を返す。sources は答えに使った資料（no は 1 から）。"""
    llm = llm or openai_llm
    run = Run(question)
    warnings = []
    tokens = {"input_tokens": 0, "output_tokens": 0}
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    answer = ""
    for n_call in range(MAX_LLM_CALLS + 1):
        choice = "none" if len(run.steps) >= MAX_STEPS or n_call >= MAX_LLM_CALLS else "auto"
        msg = _call(llm, messages, choice)
        for k in tokens:
            tokens[k] += msg["usage"].get(k, 0)
        if not msg["tool_calls"] or choice == "none":
            answer = msg["content"]
            break
        messages.append({"role": "assistant", "content": msg["content"] or None, "tool_calls": [
            {"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": t["arguments"]}} for t in msg["tool_calls"]]})
        for t in msg["tool_calls"]:
            if len(run.steps) >= MAX_STEPS:
                content = "段の上限に達したので、実行しませんでした。集めた資料で答えてください。"
            else:
                last = []

                def recording(*a):
                    last[:] = searcher(*a)
                    return last

                try:
                    args = json.loads(t["arguments"] or "{}")
                    step = run_tool(run, t["name"], args if isinstance(args, dict) else {}, recording)
                    on_step(step)
                    content = summary(run, step, [h["chunk_id"] for h in last], TOOL_KIND[t["name"]])
                except (config.SetupError, json.JSONDecodeError) as e:
                    warnings.append(f"道具 {t['name']} を実行できませんでした：{e}")
                    content = f"実行できませんでした：{e}"
            messages.append({"role": "tool", "tool_call_id": t["id"], "content": content})
    if not answer:
        warnings.append("答えが空でした")
    evidence = list(run.evidence.values())
    answer, _ = drop_mismatched_citations(answer, evidence, question)   # 外した数は画面に出さない
    text, cite_warnings = check_citations(answer, len(evidence))
    text, used = renumber(text)
    sources = [{"no": i + 1, **{k: evidence[old - 1].get(k) for k in SELECT}} for i, old in enumerate(used)]
    return {"run": run, "answer": text, "sources": sources, "warnings": warnings + cite_warnings, "tokens": tokens}
