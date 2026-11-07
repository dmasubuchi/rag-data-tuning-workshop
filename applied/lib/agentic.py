"""エージェント型検索（トピック 19）と答えの評価（トピック 20）が共通で使う部品。

エージェント型検索は、AI Search の「知識ベース」に質問を渡すと、LLM が質問を検索文に分解し、
複数の検索を走らせて、結果をまとめて返す仕組み。この Repo では次の2つを並べて試す。

  ① 普通の検索    質問をそのまま、ハイブリッド検索＋セマンティックランカーで1回探す
  ② エージェント型  知識ベース hr-docs-kb の retrieve（LLM が分解して、複数回探す）

どちらも、同じ絞り込み（見てよい人 allowed）と、同じ件数（TOP_N）の資料を、同じ答えのプロンプトで LLM に渡す。
違うのは「資料の選ばれ方」だけ。

【プレビューの API】LLM を使う機能（質問の分解、考える量 low・medium・auto）はプレビューの API。
low・medium は 2026-08-01-preview より前のプレビュー（2025-11-01-preview など）にもあり、2026-08-01-preview で足されたのが auto。
この教材は auto がある 2026-08-01-preview を使う。GA の版（2026-04-01）では、LLM を使わない minimal（質問をそのまま検索に使う）だけ。
プレビューは仕様が変わることがある。
API 版の文字列はこのファイルの API_VERSION の 1 か所だけ。

呼び出しは REST（requests）。ヘッダーは api-key（AI Search のキー）。知識ベースの LLM は、Azure OpenAI のキーを知識ベースに登録して使う
（マネージド ID やロールの割り当ては使わない）。登録は構築する人が tools/build_hr_kb.py で行う。メンバーは読むだけ。

エラーの表示にキーが出ないように、返ってきた文面は errors.redact を通す。
"""
import json
import re
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import APPLIED_DIR, acl, clients, config
from .errors import redact

# ------------------------------------------------------------------ 名前と版（ここだけ書き換える）

API_VERSION = "2026-08-01-preview"      # プレビュー。この教材は auto がある版を使う（LLM を使う機能は GA の 2026-04-01 にはない）
GA_API_VERSION = "2026-04-01"           # GA。minimal（LLM なし）だけ。retrievalReasoningEffort の欄自体がない
PREVIEW_NOTICE = (f"注意：エージェント型検索の LLM を使う機能は、プレビューの API です（この教材は auto がある {API_VERSION} を使います）。"
                  "仕様が変わることがあります。GA の版（" + GA_API_VERSION + "）は、LLM を使わない minimal だけです。")

KNOWLEDGE_SOURCE = "hr-docs-ks"             # 知識ソース（インデックス hr-docs を指す）
KNOWLEDGE_BASE = "hr-docs-kb"               # 知識ベース（知識ソースと LLM をまとめたもの）。LLM のモデル名は .env.local の AZURE_OPENAI_CHAT_MODEL
SOURCE_FIELDS = ("chunk_id", "title", "chunk", "kind", "req_id", "application_ids")   # 参照（references）に付ける欄

EFFORTS = ("minimal", "low", "medium", "auto")   # 考える量。auto は 2026-08-01-preview で足された（軽く探し、足りなければ medium まで進む）
DEFAULT_EFFORT = "low"                           # 何も指定しないときの既定（資料に明記）と同じ
TOP_N = 10                                       # 答えに渡す資料の件数（①②で同じ）

WORK_DIR = APPLIED_DIR / "_work"                 # 実行の途中のメモ（.gitignore 済み）
ANSWERS_JSON = WORK_DIR / "19_answers.json"
SCORES_JSON = WORK_DIR / "20_scores.json"
TOPIC_19_DIR = APPLIED_DIR / "topics" / "19-agentic-retrieval"
QUESTIONS_JSON = TOPIC_19_DIR / "questions.json"

METHODS = ("plain", "agentic")
METHOD_LABELS = {"plain": "① 普通の検索", "agentic": "② エージェント型検索"}


class SearchApiError(config.SetupError):
    """AI Search の REST が失敗した。メッセージはそのまま参加者に見せる（キーは伏せてある）。"""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status
        self.status_code = status


# ------------------------------------------------------------------ 呼んだ回数とトークンの記録

class Usage:
    """呼んだ回数とトークンを種類ごとに数える（複数のスレッドから足されても数え間違えない）。

    kind の例：answer（答えの生成）、planning（知識ベースの質問の分解）、score_own（自前の採点）、score_builtin（組み込みの評価器）、
    retrieve（知識ベースの呼び出し）、search（普通の検索）、search_tokens（AI Search が数えた検索側のトークン）
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = Counter()
        self.input_tokens = Counter()
        self.output_tokens = Counter()

    def add(self, kind: str, calls: int = 1, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            self.calls[kind] += calls
            self.input_tokens[kind] += input_tokens
            self.output_tokens[kind] += output_tokens

    def snapshot(self) -> dict:
        with self._lock:
            kinds = sorted(set(self.calls) | set(self.input_tokens) | set(self.output_tokens))
            return {k: {"calls": self.calls[k], "input_tokens": self.input_tokens[k], "output_tokens": self.output_tokens[k]}
                    for k in kinds}

    def llm_tokens(self) -> tuple:
        """LLM に送った・返ってきたトークンの合計。検索側のトークン（search_tokens）は含めない。"""
        with self._lock:
            llm = [k for k in self.calls if k != "search_tokens"]
            return sum(self.input_tokens[k] for k in llm), sum(self.output_tokens[k] for k in llm)


USAGE = Usage()

USAGE_LABELS = {
    "answer": "答えの生成（Azure OpenAI）",
    "planning": "質問の分解（知識ベースが LLM を呼ぶ）",
    "score_own": "自前の採点（Azure OpenAI）",
    "score_builtin": "組み込みの評価器（Azure OpenAI）",
    "retrieve": "知識ベースの retrieve",
    "search": "普通の検索",
    "search_tokens": "検索側のトークン（reasoningTokens）",
}


def usage_rows(snapshot: dict = None) -> list:
    snap = snapshot if snapshot is not None else USAGE.snapshot()
    rows = []
    for kind, v in snap.items():
        tokens = (f"{v['input_tokens']:,} / {v['output_tokens']:,}" if (v["input_tokens"] or v["output_tokens"]) else None)
        rows.append([USAGE_LABELS.get(kind, kind), v["calls"], tokens])
    return rows


def usage_table(snapshot: dict = None) -> None:
    """呼んだ回数とトークン（入力 / 出力）の表。"""
    from . import show

    show.table(["何に", "回数", "トークン（入力 / 出力）"], usage_rows(snapshot))


# ------------------------------------------------------------------ 絞り込み

def allowed_filter(*principals: str) -> str:
    """principals（role:recruiter など）のだれかに見せてよいチャンクだけ。"""
    return acl.allowed_filter(principals or (acl.ROLE_RECRUITER,))


def search_filter() -> str:
    """採用担当（role:recruiter）として見るときの絞り込み。普通の検索にも、知識ベースの filterAddOn にも同じものを使う。"""
    return allowed_filter(acl.ROLE_RECRUITER)


# ------------------------------------------------------------------ REST

WRITE_METHODS = ("PUT", "DELETE", "PATCH")      # 知識ソース・知識ベースの作成・削除。retrieve（POST）と読み取り（GET）は含めない

def _url(path: str, version: str) -> str:
    return f"{config.get_settings().search_endpoint.rstrip('/')}{path}?api-version={version}"


def call(method: str, path: str, body: dict = None, version: str = None, ok: tuple = (200, 201, 204),
         timeout: int = 120, retries: int = 3, missing_ok: bool = False):
    """AI Search の REST を呼ぶ。429・502・503・504 は少し待ってやり直す。失敗は SearchApiError（キーは伏せる）。

    missing_ok=True のとき、404 は None を返す（あるか調べるときに使う）。
    """
    import requests

    if method.upper() in WRITE_METHODS:
        config.require_admin_key()      # 知識ソース・知識ベースを作る・消すのは、管理者キー（構築する人）だけ。メンバーは不透明な 403 の前に日本語で止まる
    headers = {"api-key": config.get_settings().search_key, "Content-Type": "application/json"}
    url = _url(path, version or API_VERSION)
    for attempt in range(retries + 1):
        try:
            res = requests.request(method, url, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            raise SearchApiError(f"AI Search に接続できませんでした（{method} {path}）：{redact(type(e).__name__)}。"
                                 "ネットワーク（社内の回線、プロキシ、VPN）が止めていないかを確かめてください。") from None
        if res.status_code in (429, 502, 503, 504) and attempt < retries:
            wait = 10
            try:
                wait = min(max(int(float(res.headers.get("retry-after", wait))), 3), 60)
            except ValueError:
                pass
            print(f"  AI Search が混み合っています（{res.status_code}）。{wait} 秒待って、もう一度送ります（{attempt + 1}/{retries}）。")
            time.sleep(wait)
            continue
        break
    if missing_ok and res.status_code == 404:
        return None
    if res.status_code not in ok:
        raise SearchApiError(f"AI Search が {res.status_code} を返しました（{method} {path}）。返ってきた文面：{_error_text(res)}",
                             res.status_code)
    if not res.content:
        return {}
    try:
        return res.json()
    except ValueError:
        raise SearchApiError(f"AI Search の返事を読めませんでした（{method} {path}）。", res.status_code) from None


def _error_text(res) -> str:
    """失敗した返事の文面（キーを伏せ、300 文字まで）。"""
    text = res.text
    try:
        j = res.json()
        text = (j.get("error") or {}).get("message") or text
    except ValueError:
        pass
    return redact(" ".join(str(text).split()))[:300]


# ------------------------------------------------------------------ 知識ソース・知識ベースの定義（構築する人のツールが作る）

def knowledge_source_definition() -> dict:
    """知識ソース：既存のインデックス hr-docs を指すだけ。参照に付ける欄（sourceDataFields）を決める。"""
    return {
        "name": KNOWLEDGE_SOURCE,
        "kind": "searchIndex",
        "description": "サンプルテック（架空の会社）の採用の文書。求人票・職務経歴書・面接の評価・連絡メール・スキャンした書類",
        "searchIndexParameters": {
            "searchIndexName": config.HR_INDEX,
            "semanticConfigurationName": config.SEMANTIC_CONFIG,
            "sourceDataFields": [{"name": n} for n in SOURCE_FIELDS],
        },
    }


def knowledge_base_definition(effort: str = DEFAULT_EFFORT) -> dict:
    """知識ベース：知識ソースと LLM をまとめる。LLM のモデル名は .env.local の AZURE_OPENAI_CHAT_MODEL、デプロイ名は AZURE_OPENAI_CHAT_DEPLOYMENT。
    LLM は Azure OpenAI のキーで呼ぶ（apiKey）。この中身は表示しない。"""
    s = config.get_settings()
    return {
        "name": KNOWLEDGE_BASE,
        "description": "採用の文書をまたいで探す。求人・応募・評価・メールのつながりを、質問から分解して探す",
        "knowledgeSources": [{"name": KNOWLEDGE_SOURCE}],
        "models": [{"kind": "azureOpenAI", "azureOpenAIParameters": {
            "resourceUri": s.openai_endpoint.rstrip("/"),
            "deploymentId": s.chat_deployment,
            "modelName": s.chat_model,
            "apiKey": s.openai_key,
        }}],
        "outputMode": "extractiveData",
        "retrievalReasoningEffort": {"kind": effort},
    }


# ------------------------------------------------------------------ retrieve の要求と、結果の読み取り

def retrieve_body(question: str, effort: str = DEFAULT_EFFORT, filter_expr: str = None, max_documents: int = TOP_N) -> dict:
    """知識ベースの retrieve に送る本文。

    - minimal は LLM を使わず、質問をそのまま検索文（intents）にする。messages は使えない（400 になる）。
    - low・medium・auto は messages に質問を入れる。LLM が検索文に分解する。
    - filterAddOn が絞り込み。普通の検索と同じものを渡す。
    - includeActivity で検索の記録（分解・回数・時間・トークン）、includeReferences で出典を返してもらう。
    - maxOutputDocuments で、渡す資料の件数を普通の検索と同じにそろえる。
    """
    if effort not in EFFORTS:
        raise config.SetupError(f"考える量は {', '.join(EFFORTS)} のどれかにしてください（今は {effort!r}）。")
    body = {
        "retrievalReasoningEffort": {"kind": effort},
        "outputMode": "extractiveData",
        "includeActivity": True,
        "maxOutputDocuments": max_documents,
        "knowledgeSourceParams": [{
            "kind": "searchIndex",
            "knowledgeSourceName": KNOWLEDGE_SOURCE,
            "filterAddOn": filter_expr or search_filter(),
            "includeReferences": True,
            "includeReferenceSourceData": True,
        }],
    }
    if effort == "minimal":
        body["intents"] = [{"type": "semantic", "search": question}]
    else:
        body["messages"] = [{"role": "user", "content": [{"type": "text", "text": question}]}]
    return body


def parse_activity(activity) -> dict:
    """activity（検索の記録）から、質問の分解・検索の回数・トークンを取り出す。

    - modelQueryPlanning：LLM が質問を分解した記録（使ったトークンと時間）。分解された文そのものはここにはない
    - searchIndex：実際に投げた検索1回ごとの記録。searchIndexArguments.search が検索文（分解された文）。この記録の数が検索の回数
    - agenticReasoning：reasoningTokens は AI Search が数えた検索側のトークン（LLM のトークンではない）
    - modelAnswerSynthesis：回答の合成のトークン（この Repo では使わない）
    """
    planning, searches, reasoning_tokens, synthesis = [], [], 0, {"input_tokens": 0, "output_tokens": 0}
    errors = []
    for a in activity or []:
        kind = a.get("type")
        if a.get("error"):
            errors.append(redact(json.dumps(a["error"], ensure_ascii=False))[:200])
        if kind == "modelQueryPlanning":
            planning.append({"input_tokens": int(a.get("inputTokens") or 0), "output_tokens": int(a.get("outputTokens") or 0),
                             "elapsed_ms": int(a.get("elapsedMs") or 0),
                             "model": (a.get("model") or {}).get("modelName")})
        elif kind == "searchIndex":
            args = a.get("searchIndexArguments") or {}
            searches.append({"id": a.get("id"), "source": a.get("knowledgeSourceName"), "query": args.get("search") or "",
                             "filter": args.get("filter"), "count": a.get("count"), "elapsed_ms": int(a.get("elapsedMs") or 0)})
        elif kind == "agenticReasoning":
            reasoning_tokens += int(a.get("reasoningTokens") or 0)
        elif kind == "modelAnswerSynthesis":
            synthesis["input_tokens"] += int(a.get("inputTokens") or 0)
            synthesis["output_tokens"] += int(a.get("outputTokens") or 0)
    queries = [s["query"] for s in searches]
    return {
        "planning": planning,
        "planning_calls": len(planning),
        "searches": searches,
        "search_count": len(searches),
        "queries": queries,
        "distinct_queries": list(dict.fromkeys(queries)),
        "input_tokens": sum(p["input_tokens"] for p in planning),
        "output_tokens": sum(p["output_tokens"] for p in planning),
        "planning_ms": sum(p["elapsed_ms"] for p in planning),
        "search_tokens": reasoning_tokens,
        "synthesis": synthesis,
        "errors": errors,
    }


def parse_references(references) -> list:
    """references（出典）から、番号・文書のキー・欄・点数・どの検索が出したか、を取り出す。

    id は引用用の番号で、索引の文書キーではない（キーは docKey）。activitySource は、その出典を出した検索の記録の id。
    """
    out = []
    for r in references or []:
        data = r.get("sourceData") or {}
        out.append({
            "ref_id": str(r.get("id")),
            "doc_key": r.get("docKey") or data.get("chunk_id") or "",
            "title": r.get("title") or data.get("title") or "",
            "kind": data.get("kind"),
            "score": r.get("rerankerScore"),
            "activity_source": r.get("activitySource"),
            "text": data.get("chunk") or "",
        })
    return out


def parse_response_items(response) -> list:
    """response[0].content[0].text（根拠の断片を JSON の文字列にしたもの）から、[{ref_id, title, content}] を取り出す。"""
    try:
        text = response[0]["content"][0]["text"]
        items = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def evidence_from_retrieval(items: list, references: list, limit: int = TOP_N) -> list:
    """知識ベースが返した断片を、答えに渡す資料（chunk_id・title・text・score）にする。同じチャンクは1件にまとめる。

    断片の ref_id と出典の id を突き合わせて、索引の文書キー（chunk_id）を付ける。
    """
    by_ref = {r["ref_id"]: r for r in references}
    out, seen = [], set()
    for item in items:
        ref = by_ref.get(str(item.get("ref_id")), {})
        key = ref.get("doc_key") or f"ref{item.get('ref_id')}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"chunk_id": key, "title": item.get("title") or ref.get("title") or "",
                    "text": item.get("content") or ref.get("text") or "", "score": ref.get("score")})
        if len(out) >= limit:
            break
    return out


def retrieve(question: str, effort: str = DEFAULT_EFFORT, filter_expr: str = None, max_documents: int = TOP_N) -> dict:
    """知識ベースに質問を渡す。分解・検索の回数・出典・時間・トークンをまとめて返す（JSON にできる辞書）。"""
    body = retrieve_body(question, effort, filter_expr, max_documents)
    started = time.time()
    res = call("POST", f"/knowledgebases/{KNOWLEDGE_BASE}/retrieve", body)
    elapsed = time.time() - started
    activity = parse_activity(res.get("activity"))
    if activity["errors"]:
        raise SearchApiError("知識ベースの検索で、記録にエラーが出ました：" + activity["errors"][0])
    references = parse_references(res.get("references"))
    evidence = evidence_from_retrieval(parse_response_items(res.get("response")), references, max_documents)
    USAGE.add("retrieve")
    if activity["planning_calls"]:
        USAGE.add("planning", calls=activity["planning_calls"], input_tokens=activity["input_tokens"],
                  output_tokens=activity["output_tokens"])
    USAGE.add("search_tokens", calls=0, input_tokens=activity["search_tokens"])
    return {"question": question, "effort": effort, "elapsed_s": round(elapsed, 2), "activity": activity,
            "references": references, "evidence": evidence}


def retrieve_ga(question: str, filter_expr: str = None) -> dict:
    """GA の API（2026-04-01）で retrieve する。LLM は使えない（minimal だけ）。質問をそのまま検索文（intents）にする。

    GA には retrievalReasoningEffort・outputMode・maxOutputDocuments の欄がない（付けると 400）。件数は上限なしで返る。
    """
    body = {
        "intents": [{"type": "semantic", "search": question}],
        "includeActivity": True,
        "knowledgeSourceParams": [{"kind": "searchIndex", "knowledgeSourceName": KNOWLEDGE_SOURCE,
                                   "filterAddOn": filter_expr or search_filter(),
                                   "includeReferences": True, "includeReferenceSourceData": True}],
    }
    started = time.time()
    res = call("POST", f"/knowledgebases/{KNOWLEDGE_BASE}/retrieve", body, version=GA_API_VERSION)
    elapsed = time.time() - started
    activity = parse_activity(res.get("activity"))
    references = parse_references(res.get("references"))
    evidence = evidence_from_retrieval(parse_response_items(res.get("response")), references, 1000)
    USAGE.add("retrieve")
    USAGE.add("search_tokens", calls=0, input_tokens=activity["search_tokens"])
    return {"question": question, "effort": "minimal（GA）", "elapsed_s": round(elapsed, 2), "activity": activity,
            "references": references, "evidence": evidence}


def require_knowledge_base() -> None:
    """知識ベースがあるか確かめる（読むだけ）。なければ構築する人に頼むよう案内して止まる。

    検索だけのキー（メンバー用）は、知識ベースの定義を読めないことがある（403）。そのときは確かめずに進む（retrieve が答える）。
    """
    try:
        found = call("GET", f"/knowledgebases/{KNOWLEDGE_BASE}", missing_ok=True)
    except SearchApiError as e:
        if e.status in (401, 403) and config.is_query_key():
            return
        raise
    if found is None:
        raise config.SetupError(
            f"知識ベース {KNOWLEDGE_BASE} がありません。構築する人に作ってもらってください。\n"
            "  （構築する人は applied/tools/build_hr_kb.py を実行します。メンバーのスクリプトでは作りません）")


# ------------------------------------------------------------------ 普通の検索（①）

def plain_search(question: str, top_n: int = TOP_N, filter_expr: str = None) -> list:
    """質問をそのまま、ハイブリッド（キーワード＋ベクトル）＋セマンティックランカーで1回探す。質問のベクトル化は AI Search が行う。"""
    from azure.search.documents.models import VectorizableTextQuery

    sc = clients.search_client(config.HR_INDEX)
    vq = VectorizableTextQuery(text=question, k_nearest_neighbors=50, fields=config.VECTOR_FIELD)
    hits = sc.search(question, vector_queries=[vq], query_type="semantic", semantic_configuration_name=config.SEMANTIC_CONFIG,
                     filter=filter_expr or search_filter(), top=top_n, select=["chunk_id", "title", "chunk", "kind"])
    USAGE.add("search")
    return [{"chunk_id": h["chunk_id"], "title": h.get("title") or "", "text": h.get("chunk") or "",
             "score": h.get("@search.reranker_score")} for h in hits]


# ------------------------------------------------------------------ 答えの生成（①②で同じプロンプト）

ANSWER_SYSTEM = (
    "あなたは採用担当を手伝うアシスタントです。渡された資料だけを根拠に、日本語で簡潔に答えてください。\n"
    "- 資料に書かれていないことは推測せず、「資料にありません」と書く。\n"
    "- 人や応募ごとに、分かったことと、分からないことを分けて書く。\n"
    "- 根拠にした資料の番号を、文の終わりに [1] のように付ける。"
)


def short_id(chunk_id: str, title: str = "") -> str:
    """チャンクの短い名前。ファイル名＋チャンクの番号（例 MAIL-09_REQ-043_APP-0386.eml#0）。画面に出すときに使う。"""
    m = re.search(r"_pages_(\d+)$", chunk_id or "")
    return f"{title}#{m.group(1)}" if m and title else (title or (chunk_id or "")[-14:])


def context_text(evidence: list) -> str:
    """答えのプロンプトに入れる資料の部分。番号 [1]〜 を付ける。採点でも同じ文面を使う。"""
    blocks = []
    for i, e in enumerate(evidence, start=1):
        text = re.sub(r"\n{2,}", "\n", (e.get("text") or "").strip())
        blocks.append(f"[{i}] {e.get('title') or ''}\n{text}")
    return "\n\n".join(blocks)


def answer_messages(question: str, evidence: list) -> list:
    """答えを作るために LLM に送る messages。①②で同じ。"""
    user = f"資料：\n{context_text(evidence) or '（資料はありません）'}\n\n質問：{question}"
    return [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": user}]


def openai_client():
    """Azure OpenAI の v1 の接続先（基礎編と同じ）。キーで認証する。"""
    from openai import OpenAI

    s = config.get_settings()
    return OpenAI(base_url=s.openai_endpoint.rstrip("/") + "/openai/v1/", api_key=s.openai_key)


def chat(messages: list, kind: str, max_tokens: int = 4000, json_mode: bool = False) -> tuple:
    """LLM（.env.local のチャットのデプロイ）に messages を送る。(返事の文章, 使ったトークンの辞書) を返す。

    推論モデルは temperature を受け付けないので送らない。考える量は .env.local の AZURE_OPENAI_REASONING_EFFORT があれば渡す。
    呼びすぎ（429）は少し待ってやり直す。返事が空・途中で切れたときは原因を書いて止まる。
    """
    from openai import RateLimitError

    s = config.get_settings()
    kwargs = {"max_completion_tokens": max_tokens}
    if s.reasoning_effort:
        kwargs["reasoning_effort"] = s.reasoning_effort
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    for attempt in range(5):
        try:
            res = openai_client().chat.completions.create(model=s.chat_deployment, messages=messages, **kwargs)
            break
        except RateLimitError:
            if attempt == 4:
                raise
            print(f"  Azure OpenAI が混み合っています（呼びすぎの制限）。15 秒待って、もう一度送ります（{attempt + 1}/4）。")
            time.sleep(15)
    usage = {"input_tokens": getattr(res.usage, "prompt_tokens", 0) or 0, "output_tokens": getattr(res.usage, "completion_tokens", 0) or 0}
    USAGE.add(kind, **usage)
    choice = res.choices[0]
    text = (choice.message.content or "").strip()
    if choice.finish_reason == "length" or not text:
        raise config.SetupError("LLM の返事が空か、出力の上限（max_completion_tokens）で途中で切れました。"
                                f"終わり方 finish_reason={choice.finish_reason}")
    return text, usage


def make_answer(question: str, evidence: list) -> dict:
    """資料を渡して答えさせる。{answer, seconds, input_tokens, output_tokens}"""
    started = time.time()
    text, usage = chat(answer_messages(question, evidence), "answer")
    return {"answer": text, "seconds": round(time.time() - started, 2), **usage}


# ------------------------------------------------------------------ ①②の1回分

def run_plain(question: str, top_n: int = TOP_N, filter_expr: str = None) -> dict:
    """① 普通の検索1回 → 答え。"""
    started = time.time()
    t0 = time.time()
    evidence = plain_search(question, top_n, filter_expr)
    search_s = time.time() - t0
    ans = make_answer(question, evidence)
    return {"method": "plain", "question": question, "context": evidence, "answer": ans["answer"],
            "queries": [question], "search_count": 1, "planning_calls": 0, "search_seconds": round(search_s, 2),
            "answer_seconds": ans["seconds"], "total_seconds": round(time.time() - started, 2),
            "tokens": {"planning_input": 0, "planning_output": 0, "answer_input": ans["input_tokens"],
                       "answer_output": ans["output_tokens"], "search_side": 0}}


def run_agentic(question: str, effort: str = DEFAULT_EFFORT, top_n: int = TOP_N, filter_expr: str = None) -> dict:
    """② 知識ベースの retrieve（分解して複数回探す） → 同じプロンプトで答え。"""
    started = time.time()
    r = retrieve(question, effort, filter_expr, top_n)
    ans = make_answer(question, r["evidence"])
    a = r["activity"]
    return {"method": "agentic", "question": question, "effort": effort, "context": r["evidence"], "answer": ans["answer"],
            "queries": a["queries"], "search_count": a["search_count"], "planning_calls": a["planning_calls"],
            "search_seconds": r["elapsed_s"], "answer_seconds": ans["seconds"], "total_seconds": round(time.time() - started, 2),
            "retrieval": {"activity": a, "references": [{k: v for k, v in x.items() if k != "text"} for x in r["references"]]},
            "tokens": {"planning_input": a["input_tokens"], "planning_output": a["output_tokens"],
                       "answer_input": ans["input_tokens"], "answer_output": ans["output_tokens"], "search_side": a["search_tokens"]}}


def run_method(method: str, question: str, effort: str = DEFAULT_EFFORT, top_n: int = TOP_N, filter_expr: str = None) -> dict:
    if method == "plain":
        return run_plain(question, top_n, filter_expr)
    if method == "agentic":
        return run_agentic(question, effort, top_n, filter_expr)
    raise config.SetupError(f"方式は plain か agentic にしてください（今は {method!r}）。")


# ------------------------------------------------------------------ 用意した質問と、答えの保存（20 が使う）

def load_questions(path: Path = QUESTIONS_JSON) -> list:
    """用意した質問 10 問（id・question・focus・expect）。expect は資料から作った「答えに入るべき要点」。"""
    if not Path(path).is_file():
        raise config.SetupError(f"質問の一覧が見つかりません: {config.display_path(path)}")
    return json.loads(Path(path).read_text(encoding="utf-8"))["questions"]


def resolve_question(question: str = None, question_id: str = None) -> tuple:
    """(質問の番号, 質問の文)。自分の質問（question）があればそれ、なければ用意した質問の question_id（既定 q01）。"""
    if question:
        return "自分の質問", question
    qid = question_id or "q01"
    for q in load_questions():
        if q["id"] == qid:
            return q["id"], q["question"]
    raise config.SetupError(f"質問の番号 {qid!r} はありません。q01〜q10 のどれかにしてください。")


APP_ID = re.compile(r"APP-\d{4}")
DOC_KIND_LABELS = (("CV-", "経歴書"), ("EVAL-", "評価一覧"), ("MAIL-", "メール"), ("SCAN-", "スキャン"), ("JOB-", "求人票"))


def doc_kind_label(title: str) -> str:
    for prefix, label in DOC_KIND_LABELS:
        if (title or "").startswith(prefix):
            return label
    return "その他"


def application_coverage(evidence: list) -> dict:
    """渡した資料に、どの応募（APP-nnnn）の、どの種類の書類が何件入っているか。{応募番号: {書類の種類: 件数}}

    チャンクの本文に出てくる応募番号で数える（評価一覧のチャンクは複数の応募が入っているので、それぞれに数える）。
    """
    out = {}
    for e in evidence:
        label = doc_kind_label(e.get("title"))
        for app in set(APP_ID.findall(e.get("text") or "")):
            out.setdefault(app, Counter())[label] += 1
    return out


def coverage_text(counter) -> str:
    if not counter:
        return "（なし）"
    return " ".join(f"{k}{v}" for k, v in sorted(counter.items()))


def data_documents(app: dict) -> str:
    """データに実際にある書類（manifest の applications）。「ない」ことを確かめるのに使う。"""
    d = app.get("documents") or {}
    return (f"経歴書{len(d.get('resume') or [])} 評価の行{len(d.get('evaluation_ids') or [])} "
            f"メール{len(d.get('mail') or [])} スキャン{len(d.get('scans') or [])}")


def coverage_rows(plain_evidence: list, agentic_evidence: list) -> list:
    """応募ごとの表の行：[応募, 名前, データにある書類, ①に入った資料, ②に入った資料]。"""
    a, b = application_coverage(plain_evidence), application_coverage(agentic_evidence)
    rows = []
    for app in config.load_manifest()["applications"]:
        i = app["application_id"]
        rows.append([f"{i} {app['req_id']}", app["candidate_name"], data_documents(app), coverage_text(a.get(i)), coverage_text(b.get(i))])
    return rows


def write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_answers(path: Path = ANSWERS_JSON):
    """保存した答え。なければ None。"""
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def answer_key(item: dict) -> tuple:
    return (item["question_id"], item["method"], item["run"])


def make_answers(questions: list = None, runs: int = 3, effort: str = DEFAULT_EFFORT, top_n: int = TOP_N,
                 path: Path = ANSWERS_JSON, fresh: bool = False, progress=print) -> dict:
    """質問 × 方式（①②）× 回 の答えを作って保存する。保存があれば、できていない分だけ足す（途中で止まっても続きから）。

    保存先：applied/_work/19_answers.json。質問・方式・回・答え・渡した資料（chunk の ID と本文）を入れる。
    1回分は、①が検索1回＋答え1回、②が retrieve 1回（LLM が分解）＋答え1回。
    """
    questions = questions or load_questions()
    meta = {"api_version": API_VERSION, "effort": effort, "top_n": top_n, "runs": runs, "filter": search_filter(),
            "model": config.get_settings().chat_deployment, "created": datetime.now().isoformat(timespec="seconds")}
    data = None if fresh else load_answers(path)
    if data is not None:
        old = data.get("meta", {})
        if (old.get("effort"), old.get("top_n"), old.get("filter")) != (effort, top_n, meta["filter"]):
            raise config.SetupError(
                "保存してある答えは、考える量・件数・絞り込みが今の設定と違います。作り直すときは --fresh を付けてください。\n"
                f"  保存：effort={old.get('effort')} top_n={old.get('top_n')}　今：effort={effort} top_n={top_n}")
        data["meta"]["runs"] = max(runs, int(old.get("runs", 0)))
    else:
        data = {"meta": meta, "items": []}
    have = {answer_key(i) for i in data["items"]}
    todo = [(q, m, r) for q in questions for r in range(1, runs + 1) for m in METHODS if (q["id"], m, r) not in have]
    progress(f"  答えを作ります：{len(todo)} 件（質問 {len(questions)} × 方式 2 × {runs} 回のうち、まだのもの）")
    for n, (q, method, run) in enumerate(todo, start=1):
        result = run_method(method, q["question"], effort, top_n)
        item = {"question_id": q["id"], "question": q["question"], "method": method, "run": run, "answer": result["answer"],
                "context": [{"chunk_id": e["chunk_id"], "title": e["title"], "text": e["text"]} for e in result["context"]],
                "queries": result["queries"], "search_count": result["search_count"], "planning_calls": result["planning_calls"],
                "seconds": result["total_seconds"], "tokens": result["tokens"]}
        data["items"].append(item)
        data["usage"] = USAGE.snapshot()
        write_json(path, data)
        progress(f"  {n}/{len(todo)}  {q['id']} {METHOD_LABELS[method]} 第{run}回  検索 {result['search_count']} 回  {result['total_seconds']} 秒")
    return data


def ensure_answers(runs: int = 3, **kwargs) -> dict:
    """保存した答えがあればそれを返す。なければ（足りなければ）作る。20 が使う。"""
    return make_answers(runs=runs, **kwargs)
