"""各チャンクに「見てよい人」（allowed）を付ける後処理（16 見せてよい人で絞る、で使う）。

立場は3つ。
  採用担当（role:recruiter）    全部見える
  面接官（role:interviewer）     求人票と、自分が担当する応募の文書だけ（user:U-1006 のように個人で持つ）
  一般社員（role:employee）      求人票だけ

決め方（文書の種類とチャンクの中身から決める）：
  求人票                         role:employee、role:interviewer、role:recruiter
  経歴書・メール・スキャン         role:recruiter と、その応募を担当する面接官（user:…）
  面接の評価一覧（Excel）          role:recruiter と、そのチャンクに出てくる応募を担当する面接官
                                  応募の出てこないチャンクは、評価基準・注記のシートの文章と確かめられたものだけ、
                                  面接官全員（role:interviewer）にも見せる。確かめられないもの（個別の評価の後半だけが
                                  切れて入ったものなど）は、安全側に倒して採用担当だけ
  現年収を含むチャンク             role:recruiter だけ（同じ文書でも、ほかのチャンクは面接官に見える）

面接官の割当ては、面接の評価一覧の「面接評価」シート（応募番号と面接官ID）から読む。

インデクサーは blob のメタデータから一覧（Collection）を作れないので、取り込みの後にここで付ける。
変更のあった文書は、インデクサーが取り込み直したチャンクの allowed が空に戻るので、インデクサーを動かしたあとは、
索引の全部のチャンクに付け直す（sync）。付いていないチャンクは、絞り込みでだれにも見えない（安全側）。
"""
import re
import time
from functools import lru_cache

from . import clients
from .config import DATA_DIR, HR_INDEX, SetupError

ROLE_RECRUITER = "role:recruiter"
ROLE_INTERVIEWER = "role:interviewer"
ROLE_EMPLOYEE = "role:employee"
PUBLIC_KINDS = ("job_posting",)
RECRUITER_ONLY_WORDS = ("現年収",)          # この語を含むチャンクは採用担当だけ
EVALUATION_BOOK = DATA_DIR / "evaluations" / "EVAL-INTERVIEWS-2026-10.xlsx"
BASIS_SHEETS = ("評価基準", "注記")        # 応募に関係なく、面接官全員に見せてよい、評価の Excel のシート
APP_ID = re.compile(r"APP-\d{4}")
PRINCIPAL = re.compile(r"(?:role|user):[A-Za-z0-9_-]+")     # 役割（role:…）か個人（user:…）の文字列の形

# 立場ごとの「検索する人が持っている印」。絞り込みは、チャンクの allowed とこの印が1つでも重なれば見える、という式にする。
# 面接官は、役割（role:interviewer）と個人（user:<面接官のID>）の両方を持つ。
VIEWER_RECRUITER = (ROLE_RECRUITER,)
VIEWER_EMPLOYEE = (ROLE_EMPLOYEE,)


def viewer_interviewer(user_id: str = "U-1006") -> tuple:
    return (ROLE_INTERVIEWER, f"user:{user_id}")


def allowed_filter(principals) -> str:
    """「見てよい人」で絞る式。例  allowed/any(a: search.in(a, 'role:interviewer,user:U-1006'))

    principals は、検索する人の印（role:… と user:…）の並び。式に埋め込むので、形（英数字・ハイフン・下線）を確かめる。
    """
    items = [principals] if isinstance(principals, str) else list(principals)
    if not items or any(not PRINCIPAL.fullmatch(str(x)) for x in items):
        raise SetupError(f"見てよい人の印は role:… か user:… の形で書いてください（今は {items!r}）。例 role:recruiter、user:U-1006")
    return f"allowed/any(a: search.in(a, '{','.join(items)}'))"


def scope_filter(principals) -> str:
    """検索する人（principals）に見える分だけに絞る式。見てよい人（allowed）だけで絞る。"""
    return allowed_filter(principals)


def interviewer_assignments(path=EVALUATION_BOOK) -> dict:
    """{応募番号: {面接官ID, …}}。面接の評価一覧の「面接評価」シートから読む。"""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    rows = list(wb["面接評価"].iter_rows(values_only=True))
    head = list(rows[0])
    ia, iu = head.index("応募番号"), head.index("面接官ID")
    out = {}
    for r in rows[1:]:
        if r[ia] and r[iu]:
            out.setdefault(str(r[ia]), set()).add(str(r[iu]))
    return out


def _squash(text) -> str:
    """空白（改行・全角の空白も）を全部取る。取り込みで切った文章と、シートの文章を、並べ方に関係なく比べるため。"""
    return re.sub(r"\s+", "", str(text))


@lru_cache(maxsize=4)
def evaluation_basis_text(path=EVALUATION_BOOK) -> str:
    """評価の Excel の「評価基準」「注記」シートの文章を、空白を取って、つなげたもの。"""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    parts = []
    for name in BASIS_SHEETS:
        parts.append(_squash(name))
        parts += [_squash(c) for row in wb[name].iter_rows(values_only=True) for c in row if c is not None]
    return "".join(parts)


def is_evaluation_basis(text: str, basis: str) -> bool:
    """応募の番号が出てこない評価のチャンクが、評価基準・注記のシートの文章だけでできているか。

    切れ目は、基準の表の途中や、注記の途中でもよい（文章の一部が、基準・注記の文章の続きにあれば足りる）。
    1文字でも、基準・注記にない文章（個別の評価の後半など）が混ざっていたら、確かめられないので False。
    """
    body = _squash(text)
    return bool(body) and body in basis


def allowed_for(doc: dict, assignments: dict, basis: str = None) -> list:
    """1チャンク分（kind、application_ids、chunk の欄）から、見てよい人の一覧を返す。

    basis：評価基準・注記の文章（evaluation_basis_text）。省くと、評価の Excel から読む。
    """
    kind = doc.get("kind") or ""
    text = doc.get("chunk") or ""
    if kind in PUBLIC_KINDS:
        return [ROLE_EMPLOYEE, ROLE_INTERVIEWER, ROLE_RECRUITER]
    if any(w in text for w in RECRUITER_ONLY_WORDS):
        return [ROLE_RECRUITER]
    if kind == "interview_evaluations":
        apps = set(APP_ID.findall(text))
        if not apps:
            # 応募の出てこないチャンク。評価基準・注記と確かめられたときだけ、面接官全員に見せる。
            # Azure の分割は行を保証しないので、個別の評価の後半だけが、応募の番号なしで入ることがある（その場合は採用担当だけ）
            if is_evaluation_basis(text, evaluation_basis_text() if basis is None else basis):
                return [ROLE_INTERVIEWER, ROLE_RECRUITER]
            return [ROLE_RECRUITER]
    else:
        apps = set((doc.get("application_ids") or "").split())
    users = sorted({u for a in apps for u in assignments.get(a, ())})
    return [ROLE_RECRUITER] + [f"user:{u}" for u in users]


MERGE_TRIES = 3                 # 文書ごとの失敗（503 など）を、やり直す回数
MERGE_WAIT_SECONDS = 2


def _merge_all(sc, updates: list, wait: float = MERGE_WAIT_SECONDS) -> dict:
    """見てよい人の更新を、500 件ずつ送る。文書ごとの成否を見て、失敗したぶんは待ってやり直す。

    merge_documents は、要求が通っても、文書ごとに失敗を返すことがある（例外にならない）。
    - 404（その文書がもうない。インデクサーや後片付けが消した）は、付ける相手がいないので、数えるだけで、やり直さない
    - ほかの失敗は、やり直す。何回やっても残ったら、SetupError で止める（付いていないまま「付けた」と言わない）
    """
    pending, gone = list(updates), 0
    for attempt in range(MERGE_TRIES):
        failed = {}
        for i in range(0, len(pending), 500):
            for r in sc.merge_documents(pending[i:i + 500]):
                if r.succeeded:
                    continue
                if getattr(r, "status_code", None) == 404:
                    gone += 1
                else:
                    failed[r.key] = r
        pending = [u for u in pending if u["chunk_id"] in failed]
        if not pending:
            return {"done": len(updates) - gone, "gone": gone}
        if attempt < MERGE_TRIES - 1:
            time.sleep(wait * (attempt + 1))
    raise SetupError(f"見てよい人（allowed）を、{len(pending)} 件のチャンクに付けられませんでした（{MERGE_TRIES} 回試しました）。\n"
                     "  付いていないチャンクは、だれにも見えない状態です。少し待って、もう一度実行してください。")


def sync(index_name: str = HR_INDEX) -> dict:
    """インデックスの全部のチャンクに、見てよい人を付ける（付け直す）。数を返す。"""
    sc = clients.search_client(index_name)
    assignments = interviewer_assignments()
    basis = evaluation_basis_text()
    docs = list(sc.search("*", top=1000, select=["chunk_id", "kind", "application_ids", "chunk", "allowed"]))
    updates, stats = [], {"chunks": len(docs), "changed": 0, "recruiter_only": 0, "public": 0, "gone": 0}
    for d in docs:
        allowed = allowed_for(d, assignments, basis)
        if allowed == [ROLE_RECRUITER]:
            stats["recruiter_only"] += 1
        if ROLE_EMPLOYEE in allowed:
            stats["public"] += 1
        if list(d.get("allowed") or []) != allowed:
            updates.append({"chunk_id": d["chunk_id"], "allowed": allowed})
    merged = _merge_all(sc, updates)
    stats["changed"] = merged["done"]
    stats["gone"] = merged["gone"]
    return stats
