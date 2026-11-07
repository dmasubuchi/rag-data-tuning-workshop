"""答えの評価（トピック 20）の部品。19 の答えを、2通りの方法で採点する。

  ① 自前の採点プロンプト   採点の基準を日本語の文で書き、LLM に 1〜5 で採点させる。観点は3つ
                          根拠への忠実さ・質問への答え・要点の網羅（想定の要点は questions.json の expect）
  ② 組み込みの評価器       azure-ai-evaluation の GroundednessEvaluator（資料に基づいているか）と
                          RelevanceEvaluator（質問に答えているか）。どちらも 1〜5。採点の基準は評価器の中のプロンプト

LLM が答えを作り、LLM が採点するので、点のぶれには2つの元がある。
  - 答えの生成のぶれ：同じ質問・同じ方式でも、3回作ると答えが少しずつ違う（検索で選ばれる資料も、分解も変わる）
  - 採点のぶれ：同じ答えでも、採点のたびに点が少し変わる
この教材の「3回の最小・最大」は、別々に作った3つの答えを1回ずつ採点した点の幅なので、この2つを合わせたぶれ。
採点だけのぶれは、同じ答えを繰り返し採点して見る（score_one.py を同じ答えで何回か実行する）。

組み込みの評価器の注意（実際に動かして確かめたこと。azure-ai-evaluation 1.18.10）：
- 推論モデル（gpt-5 系）は is_reasoning_model=True が要る。付けないと max_tokens が使えないという 400 になる
- 出力の欄の名前は版で変わる。1.18.10 は groundedness・groundedness_result・groundedness_reason など（gpt_ 付きの欄はない。
  公式の古い例には gpt_groundedness がある）。トークン数は groundedness_properties の中に入っている。parse_builtin は両方の名前を読む
- しきい値の既定は 3 で、3 以上が合格。groundedness の 3 は「根拠にできる情報がない」（確認の質問・あいさつなど）の段なので、
  資料に基づいていない答えでも合格になることがある
- 1回の評価は LLM 1回の呼び出し

azure-ai-evaluation は重いので、applied/requirements-eval.txt に分けてある（20 だけで使う）。入っていなくても、自前の採点は動く。
"""
import hashlib
import json
import re
import time
from pathlib import Path

from . import agentic, config

# ------------------------------------------------------------------ 自前の採点プロンプト

OWN_METRICS = (
    ("faithfulness", "根拠への忠実さ"),
    ("answers_question", "質問への答え"),
    ("coverage", "要点の網羅"),
)

OWN_SYSTEM = """あなたは、採用の文書をもとに答える質問応答システムの採点者です。
質問、システムに渡した資料、想定の要点、システムの答えを読み、次の3つの観点を、それぞれ 1〜5 の整数で採点してください。
採点は、基準の文に最も近い点をつけます。資料と想定の要点だけを根拠にし、あなたの知識は使いません。

観点1 根拠への忠実さ（答えが、渡した資料に書いてあることだけでできているか）
- 5：答えのすべての記述が資料に書いてある。資料にないことは「資料にありません」と書いている
- 4：ほぼ資料のとおり。言い換えや軽い補足が混じるが、事実は変わらない
- 3：資料にある内容と、資料に書かれていない推測が、半々くらい
- 2：資料にない内容や、資料と食い違う内容がはっきり混じる
- 1：ほとんどが資料にない、または資料と食い違う
（資料に書いてあることを「資料にありません」と書いた場合は、事実に反するので 2 以下）

観点2 質問への答え（聞かれたことに答えているか）
- 5：聞かれたことのすべてに答えている。資料にない部分は、ないと答えている
- 4：ほぼ答えているが、1点だけ薄い
- 3：聞かれたことの半分くらいに答えている
- 2：質問とずれた内容が多い
- 1：質問に答えていない

観点3 要点の網羅（想定の要点が、正しく答えに入っているか）
- 5：すべての要点が、正しく入っている
- 4：ほぼ入っているが、1つが薄いか、細部が違う
- 3：要点の半分くらいが入っている
- 2：1つしか入っていないか、誤りが目立つ
- 1：ほとんど入っていない、または要点と逆のことを書いている
（要点に「資料にない」「確認できない」と書いてあるものは、答えが「資料にありません」などと書いていれば入っているとみなす。人や応募を取り違えていれば誤り）

次の形の JSON だけを返してください。reason は、点をつけた理由を日本語で1文。
{"faithfulness": {"score": 整数, "reason": "…"}, "answers_question": {"score": 整数, "reason": "…"}, "coverage": {"score": 整数, "reason": "…"}}"""


def own_messages(question: str, context: list, expect: list, answer: str) -> list:
    """自前の採点のために LLM に送る messages。資料は、答えを作ったときと同じ番号 [1]〜 で渡す。"""
    points = "\n".join(f"- {p}" for p in expect) or "（なし）"
    user = (f"質問：{question}\n\n資料（システムに渡したもの）：\n{agentic.context_text(context)}\n\n"
            f"想定の要点：\n{points}\n\nシステムの答え：\n{answer}")
    return [{"role": "system", "content": OWN_SYSTEM}, {"role": "user", "content": user}]


def parse_own_score(text: str) -> dict:
    """採点の返事（JSON）から {観点: {score, reason}} を取り出す。点は 1〜5 の整数でなければ ValueError。"""
    body = text.strip()
    m = re.search(r"\{.*\}", body, re.DOTALL)        # ```json … ``` で囲まれていても読む
    if not m:
        raise ValueError("JSON が見つかりません")
    data = json.loads(m.group(0))
    out = {}
    for key, _ in OWN_METRICS:
        entry = data.get(key)
        score = entry.get("score") if isinstance(entry, dict) else None
        if isinstance(score, str) and score.strip().isdigit():
            score = int(score.strip())
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            raise ValueError(f"{key} の点が 1〜5 の整数ではありません: {score!r}")
        out[key] = {"score": score, "reason": str(entry.get("reason") or "").strip()}
    return out


def score_own(question: str, context: list, expect: list, answer: str) -> dict:
    """自前の採点プロンプトで採点する（LLM 1回。形が違う返事なら1回だけやり直す）。

    {faithfulness: {score, reason}, answers_question: {...}, coverage: {...}, input_tokens, output_tokens}
    """
    messages = own_messages(question, context, expect, answer)
    total_in = total_out = 0
    for attempt in range(2):
        text, usage = agentic.chat(messages, "score_own", max_tokens=4000, json_mode=True)
        total_in += usage["input_tokens"]
        total_out += usage["output_tokens"]
        try:
            return {**parse_own_score(text), "input_tokens": total_in, "output_tokens": total_out}
        except (ValueError, json.JSONDecodeError) as e:
            last = e
    raise config.SetupError(f"自前の採点の返事を読めませんでした（{last}）。")


# ------------------------------------------------------------------ 組み込みの評価器（azure-ai-evaluation）

EVAL_PACKAGE = "azure-ai-evaluation==1.18.10"
BUILTIN_REASONING = True      # gpt-5 系は推論モデルなので is_reasoning_model=True（builtin_evaluators）
INSTALL_HINT = "  pip install -r applied/requirements-eval.txt     （Repo 直下で。azure-ai-evaluation が入る）"
BUILTIN_METRICS = (("groundedness", "資料に基づいているか（groundedness）"), ("relevance", "質問に答えているか（relevance）"))


def builtin_available() -> bool:
    try:
        import azure.ai.evaluation  # noqa: F401
    except ImportError:
        return False
    return True


def builtin_evaluators() -> dict:
    """{groundedness: GroundednessEvaluator, relevance: RelevanceEvaluator}。model_config は Azure OpenAI のキーで渡す。

    gpt-5 系は推論モデルなので is_reasoning_model=True が要る（付けないと 400）。
    """
    try:
        from azure.ai.evaluation import GroundednessEvaluator, RelevanceEvaluator
    except ImportError:
        raise config.SetupError("azure-ai-evaluation が入っていません。20 の組み込みの評価器には、次が要ります。\n" + INSTALL_HINT) from None
    s = config.get_settings()
    env = config.read_env_file(config.env_file_path())
    model_config = {"azure_endpoint": s.openai_endpoint.rstrip("/"), "api_key": s.openai_key, "azure_deployment": s.chat_deployment}
    if env.get("AZURE_OPENAI_API_VERSION"):
        model_config["api_version"] = env["AZURE_OPENAI_API_VERSION"]
    return {"groundedness": GroundednessEvaluator(model_config, is_reasoning_model=BUILTIN_REASONING),
            "relevance": RelevanceEvaluator(model_config, is_reasoning_model=BUILTIN_REASONING)}


def parse_builtin(result: dict, name: str) -> dict:
    """評価器の出力から、点・合否・理由・トークン数を取り出す。欄の名前は版で変わるので、gpt_ 付きの古い名前も読む。

    1.18.10：groundedness、groundedness_result（pass/fail）、groundedness_passed、groundedness_reason、groundedness_properties
    古い例：gpt_groundedness、groundedness_reason
    """
    def pick(*keys):
        for k in keys:
            if k in result and result[k] is not None:
                return result[k]
        return None

    score = pick(name, f"{name}_score", f"gpt_{name}")
    props = pick(f"{name}_properties") or {}
    verdict = pick(f"{name}_result")
    passed = pick(f"{name}_passed")
    if passed is None and verdict in ("pass", "fail"):
        passed = verdict == "pass"
    return {"score": float(score) if isinstance(score, (int, float)) else None, "passed": passed, "result": verdict,
            "reason": str(pick(f"{name}_reason") or "").strip(), "status": pick(f"{name}_status"),
            "threshold": pick(f"{name}_threshold"),
            "input_tokens": int(props.get("prompt_tokens") or 0) if isinstance(props, dict) else 0,
            "output_tokens": int(props.get("completion_tokens") or 0) if isinstance(props, dict) else 0,
            "fields": sorted(result.keys())}


def score_builtin(evaluators: dict, question: str, context: list, answer: str) -> dict:
    """GroundednessEvaluator（query・response・context）と RelevanceEvaluator（query・response）で採点する。LLM を2回呼ぶ。"""
    context_str = "\n\n".join((c.get("text") or "").strip() for c in context)      # 断片は \n\n でつなぐ（公式の指示）
    out = {}
    for name, kwargs in (("groundedness", dict(query=question, response=answer, context=context_str)),
                         ("relevance", dict(query=question, response=answer))):
        raw = evaluators[name](**kwargs)
        out[name] = parse_builtin(raw, name)
        agentic.USAGE.add("score_builtin", input_tokens=out[name]["input_tokens"], output_tokens=out[name]["output_tokens"])
    return out


# ------------------------------------------------------------------ ぶれの計算

def spread(values: list) -> dict:
    """点の一覧から、最小・最大・平均・幅（最大−最小）。None は除く。"""
    xs = [v for v in values if v is not None]
    if not xs:
        return {"n": 0, "min": None, "max": None, "mean": None, "range": None}
    return {"n": len(xs), "min": min(xs), "max": max(xs), "mean": sum(xs) / len(xs), "range": max(xs) - min(xs)}


def range_text(sp: dict) -> str:
    """「3〜5」のような表示。最小と最大が同じなら「4」。"""
    if sp["n"] == 0:
        return "-"
    lo, hi = sp["min"], sp["max"]
    f = (lambda x: f"{x:g}")
    return f(lo) if lo == hi else f"{f(lo)}〜{f(hi)}"


def metric_value(record: dict, metric: str):
    """採点の1件分（own / builtin を持つ辞書）から、metric の点を取り出す。metric は own.faithfulness、builtin.groundedness の形。"""
    kind, name = metric.split(".", 1)
    entry = (record.get(kind) or {}).get(name)
    if entry is None:
        return None
    return entry.get("score") if isinstance(entry, dict) else entry


def group_spreads(records: list, metric: str) -> dict:
    """{(質問, 方式): spread}。同じ質問・方式の複数回（run）の点のぶれ。"""
    groups = {}
    for r in records:
        groups.setdefault((r["question_id"], r["method"]), []).append(metric_value(r, metric))
    return {k: spread(v) for k, v in groups.items()}


def method_means(records: list, metric: str) -> dict:
    """{方式: 平均点}（全質問・全回）。"""
    out = {}
    for method in agentic.METHODS:
        xs = [metric_value(r, metric) for r in records if r["method"] == method]
        sp = spread(xs)
        out[method] = sp["mean"]
    return out


def mean_range(spreads: dict, method: str):
    """方式ごとの、ぶれの幅（最大−最小）の平均。"""
    rs = [sp["range"] for (q, m), sp in spreads.items() if m == method and sp["range"] is not None]
    return sum(rs) / len(rs) if rs else None


def judge(score, threshold: float):
    """点がしきい値以上なら True（合格）、未満なら False。点がない（評価器がスキップした）ときは None。

    評価器は、自分の既定のしきい値（3）で pass / fail を返す。保存した合否は使わず、選んだしきい値で判定し直すときに使う。
    """
    return None if score is None else score >= threshold


def pass_counts(records: list, name: str, method: str, threshold: float) -> tuple:
    """(合格の数, 判定できた件数)。name は groundedness か relevance。選んだしきい値で判定し直す。"""
    verdicts = [judge(r["builtin"][name]["score"], threshold) for r in records if r["method"] == method and r.get("builtin")]
    verdicts = [v for v in verdicts if v is not None]
    return sum(1 for v in verdicts if v), len(verdicts)


def agreement_row(label: str, ag: dict) -> list:
    """一致の表の1行。比べられる点の対が0件（評価器が全部スキップなど）のときは、「比べる相手なし」にする。"""
    if not ag["n"]:
        return [label, 0, "比べる相手なし", "-", "-"]
    return [label, ag["n"], f"{ag['same'] * 100:.0f}%", f"{ag['within1'] * 100:.0f}%", f"{ag['mean_diff']:+.2f}"]


def agreement(records: list, metric_a: str, metric_b: str) -> dict:
    """2つの採点の一致：同じ点の割合、1点以内の割合、平均の差（a − b）。"""
    pairs = [(metric_value(r, metric_a), metric_value(r, metric_b)) for r in records]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    if not pairs:
        return {"n": 0, "same": None, "within1": None, "mean_diff": None}
    n = len(pairs)
    return {"n": n, "same": sum(1 for a, b in pairs if round(a) == round(b)) / n,
            "within1": sum(1 for a, b in pairs if abs(a - b) <= 1) / n, "mean_diff": sum(a - b for a, b in pairs) / n}


# ------------------------------------------------------------------ 採点の保存

def load_scores(path: Path = agentic.SCORES_JSON):
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def score_key(item: dict) -> tuple:
    return (item["question_id"], item["method"], item["run"])


def fingerprint(*parts) -> str:
    """入力の内容から決まる短い指紋（sha256 の先頭 16 文字）。同じ入力なら、いつも同じ文字列。"""
    text = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def own_fingerprint(item: dict, expect: list) -> str:
    """自前の採点の入力の指紋：質問・答え・渡した資料・想定の要点・採点の基準の文（OWN_SYSTEM）。どれかが変われば採点し直す。"""
    context = [[c.get("title"), c.get("text")] for c in item["context"]]
    return fingerprint("own", item["question"], item["answer"], context, list(expect), OWN_SYSTEM)


def builtin_fingerprint(item: dict) -> str:
    """組み込みの評価器の入力の指紋：質問・答え・渡した資料・評価器の版と設定。"""
    return fingerprint("builtin", item["question"], item["answer"], [c.get("text") for c in item["context"]],
                       EVAL_PACKAGE, BUILTIN_REASONING)


def stale_records(scores: dict, answers: dict, questions: list = None) -> list:
    """保存した採点のうち、今の答え・想定の要点・採点の基準と入力が違うもの（古い採点）のキー。--summary で警告するのに使う。"""
    questions = questions or agentic.load_questions()
    expect = {q["id"]: q.get("expect") or [] for q in questions}
    items = {score_key(i): i for i in answers["items"]}
    out = []
    for r in scores["records"]:
        item = items.get(score_key(r))
        if item is None or item["question_id"] not in expect:
            continue
        if r.get("own_hash") != own_fingerprint(item, expect[item["question_id"]]) or (
                r.get("builtin") and r.get("builtin_hash") != builtin_fingerprint(item)):
            out.append(score_key(r))
    return out


def score_answers(answers: dict, questions: list = None, builtin: bool = True, path: Path = agentic.SCORES_JSON,
                  fresh: bool = False, progress=print) -> dict:
    """19 の答え（answers）を採点して保存する。保存があれば、足りない分だけ採点する（途中で止まっても続きから）。

    保存した採点を使い回してよいのは、入力が同じときだけ。質問・答え・渡した資料・想定の要点・採点の基準が変わったら、その部分を採点し直す
    （入力の指紋 own_hash・builtin_hash で照合する。指紋のない古い保存は、採点し直す）。
    自前の採点と組み込みの評価器は、別々に数える。自前だけで採点したあとに builtin=True にすると、組み込みの分だけを足す。
    1件あたり LLM を、自前の採点で 1 回、組み込みの評価器で 2 回（groundedness・relevance）呼ぶ。
    """
    questions = questions or agentic.load_questions()
    expect = {q["id"]: q.get("expect") or [] for q in questions}
    data = None if fresh else load_scores(path)
    if data is None:
        data = {"meta": {"api_version": answers.get("meta", {}).get("api_version"), "model": config.get_settings().chat_deployment,
                         "package": EVAL_PACKAGE}, "records": []}
    index = {score_key(r): n for n, r in enumerate(data["records"])}
    plan = []                       # (答え, 前の記録, 自前を採点するか, 組み込みを採点するか, 自前の指紋, 組み込みの指紋)
    for item in answers["items"]:
        if item["question_id"] not in expect:
            continue
        old = data["records"][index[score_key(item)]] if score_key(item) in index else {}
        own_fp, builtin_fp = own_fingerprint(item, expect[item["question_id"]]), builtin_fingerprint(item)
        need_own = not old.get("own") or old.get("own_hash") != own_fp
        have_builtin = bool(old.get("builtin")) and old.get("builtin_hash") == builtin_fp
        need_builtin = builtin and not have_builtin
        if need_own or need_builtin or (old.get("builtin") and not have_builtin):
            plan.append((item, old, need_own, need_builtin, own_fp, builtin_fp))
    n_own, n_builtin = sum(1 for p in plan if p[2]), sum(1 for p in plan if p[3])
    evaluators = builtin_evaluators() if n_builtin else None
    progress(f"  採点します：自前 {n_own} 件（LLM {n_own} 回）、組み込み {n_builtin} 件（LLM {n_builtin * 2} 回）"
             + ("" if plan else "。保存した採点は、どれも入力が同じなので、そのまま使います"))
    for n, (item, old, need_own, need_builtin, own_fp, builtin_fp) in enumerate(plan, start=1):
        started = time.time()
        rec = {"question_id": item["question_id"], "method": item["method"], "run": item["run"]}
        if need_own:
            own = score_own(item["question"], item["context"], expect[item["question_id"]], item["answer"])
            rec["own"] = {k: {"score": own[k]["score"], "reason": own[k]["reason"]} for k, _ in OWN_METRICS}
            rec["own_tokens"] = {"input_tokens": own["input_tokens"], "output_tokens": own["output_tokens"]}
            rec["own_hash"] = own_fp
        else:
            rec.update({k: old[k] for k in ("own", "own_tokens", "own_hash")})
        if need_builtin:
            rec["builtin"] = score_builtin(evaluators, item["question"], item["context"], item["answer"])
            rec["builtin_hash"] = builtin_fp
        elif old.get("builtin") and old.get("builtin_hash") == builtin_fp:
            rec.update({k: old[k] for k in ("builtin", "builtin_hash")})       # 入力が同じ組み込みの点は残す
        # 入力が変わった古い組み込みの点は、捨てる（builtin=False のときも、古い点を残さない）
        key = score_key(item)
        if key in index:
            data["records"][index[key]] = rec
        else:
            index[key] = len(data["records"])
            data["records"].append(rec)
        data["usage"] = agentic.USAGE.snapshot()
        agentic.write_json(path, data)
        parts = ("自前" if need_own else "") + ("・" if need_own and need_builtin else "") + ("組み込み" if need_builtin else "")
        progress(f"  {n}/{len(plan)}  {item['question_id']} {agentic.METHOD_LABELS[item['method']]} 第{item['run']}回"
                 f"（{parts or '古い組み込みの点を外す'}）  {time.time() - started:.1f} 秒")
    return data
