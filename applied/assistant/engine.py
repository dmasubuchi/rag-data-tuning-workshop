"""採用アシスタントの中心：候補（応募者）を、段ごとに絞り込む。

Azure も LLM も知らない。検索の結果（hits）を受け取り、候補と、答えの根拠（evidence）と、段の記録（steps）を更新する。

  候補      応募の番号（APP-0391 など）の集まり。最初は None（まだ絞っていない＝全員）
  絞る段    キーワード・ベクトル・欄で絞る。見つかった文書に出てくる人と、前の候補の共通部分を、新しい候補にする
            共通部分が 0 人なら、候補を変えない（人数は増えも消えもしない）
  たどる段  ID でたどる。候補の人の文書を集めるだけで、候補は変えない

人の数え方
  面接の評価一覧のチャンクは、欄 application_ids にシートの全員が入っている。人は本文の行から数える。
  1行は「評価ID・応募番号・…・求人番号・…」のように、応募番号と求人番号が同じ行に並ぶ。
  語（求人番号や検索の語）が分かっているときは、その語を含む行に出てくる人だけを数える。
"""
import re
from dataclasses import dataclass, field

APP_ID = re.compile(r"APP-\d{4}")
JA_CHARS = "\u3040-\u30ff\u3400-\u9fff\u3005"    # かな・漢字
_KANJI = "\u3400-\u9fff\u3005"
# 名前は「姓 名」。前に日本語の字が続くところからは始めない。メールは文の中に名前が出る（ご応募いただいた岩崎 俊介様）ので、漢字だけにして前の語を巻き込まない
_NAME = rf"(?<![{JA_CHARS}])(?P<sur>[{JA_CHARS}]{{1,6}})[ \u3000]+(?P<giv>[{JA_CHARS}]{{1,6}})"
_KANJI_NAME = rf"(?<![{_KANJI}])(?P<sur>[{_KANJI}]{{1,6}})[ \u3000]+(?P<giv>[{_KANJI}]{{1,6}})"
# 応募者の名前が応募番号と並んで出る 3 つの形（面接官など、ほかの人の名前は取らない）
NAME_FORMS = (
    re.compile(rf"(?P<app>APP-\d{{4}})\s+C-\d{{3}}\s+{_NAME}"),            # 評価一覧の行：APP-0391 C-120 市川 浩二
    re.compile(rf"氏名\s+{_NAME}\s+応募番号\s+(?P<app>APP-\d{{4}})"),       # 職務経歴書：氏名 市川 浩二 応募番号 APP-0391
    re.compile(rf"{_KANJI_NAME}様（応募番号\s*(?P<app>APP-\d{{4}})"),      # 連絡メール：市川 浩二様（応募番号 APP-0391
)
EVALUATIONS = "interview_evaluations"
METHODS = {"keyword": "キーワード", "vector": "ベクトル", "fields": "欄で絞る", "follow": "ID でたどる"}
MAX_STEPS = 6
TOP_TITLES = 3
NOT_NARROWED = "0 人だったので絞らなかった"


@dataclass
class Step:
    """1 段の記録。画面の右に 1 枚のカードで出す。people_before が None なら、まだ絞っていなかった（全員）。"""
    no: int
    method: str
    args: dict
    people_before: int | None
    people_after: int | None
    docs_found: int
    top_titles: list[str]
    note: str = ""


@dataclass
class Run:
    """1 つの質問の進み具合。evidence は chunk_id → 検索の結果の1件（入れた順を保つ）。"""
    question: str
    candidates: set[str] | None = None
    steps: list[Step] = field(default_factory=list)
    evidence: dict[str, dict] = field(default_factory=dict)


def applicants_of(hit: dict, terms: tuple = ()) -> set[str]:
    """1 件の検索結果に出てくる人（応募の番号）。

    本文の行のうち応募の番号を含む行から取る。terms があれば、その語を含む行だけ（どの行も含まなければ全部の行）。
    本文に番号がなければ、面接の評価一覧以外は欄 application_ids から取る（経歴書の1つ目のチャンクなど）。
    """
    lines = [ln for ln in (hit.get("chunk") or "").splitlines() if APP_ID.search(ln)]
    if terms:
        matched = [ln for ln in lines if any(t and t in ln for t in terms)]
        lines = matched or lines
    found = {m for ln in lines for m in APP_ID.findall(ln)}
    if found or hit.get("kind") == EVALUATIONS:
        return found
    return set(APP_ID.findall(hit.get("application_ids") or ""))


def names_of(hits: list[dict]) -> dict[str, set[str]]:
    """検索の結果の本文から、応募者の名前（姓 名）→ 応募番号の対応を作る。作れた名前だけ。"""
    names: dict[str, set[str]] = {}
    for h in hits:
        text = h.get("chunk") or ""
        for form in NAME_FORMS:
            for m in form.finditer(text):
                names.setdefault(f"{m['sur']} {m['giv']}", set()).add(m["app"])
    return names


def candidate_filter(candidates: set[str] | None) -> str | None:
    """候補の人の文書だけに絞る式。候補がまだなければ None。"""
    if candidates is None:
        return None
    return f"search.ismatch('{' '.join(sorted(candidates))}', 'application_ids', 'simple', 'any')"


def _terms(tool: str, args: dict) -> tuple:
    if tool == "fields" and args.get("req_id"):
        return (args["req_id"],)
    if tool == "keyword":
        return tuple((args.get("query") or "").split())
    return ()


def apply_step(run: Run, tool: str, args: dict, hits: list[dict], narrows: bool) -> Step:
    """検索の結果を run に入れ、1 段の記録を返す。"""
    before = None if run.candidates is None else len(run.candidates)
    for h in hits:
        run.evidence.setdefault(h["chunk_id"], h)
    note = ""
    if narrows:
        found = set().union(*(applicants_of(h, _terms(tool, args)) for h in hits)) if hits else set()
        if tool == "fields" and args.get("applicant_ids"):
            found &= set(args["applicant_ids"])   # 評価一覧のチャンクには、ほかの人の行も入っている
        if run.candidates is not None:
            found &= run.candidates
        if found:
            run.candidates = found
        else:
            note = NOT_NARROWED
    after = None if run.candidates is None else len(run.candidates)
    step = Step(no=len(run.steps) + 1, method=METHODS[tool], args=dict(args), people_before=before, people_after=after,
                docs_found=len(hits), top_titles=[h.get("title") or h.get("doc_id") or "" for h in hits[:TOP_TITLES]], note=note)
    run.steps.append(step)
    return step
