"""検索の評価で使う質問の形と、その確かめ（標準ライブラリだけ）。

質問は JSON の並びで、データごとのファイルに置く（形と種類の説明は evaluation/README.md）。
  load_questions(path)  質問のファイルを読む。武将の既存の質問の intent は、type として読む
  load_data(dataset)    質問が指す文書のデータ（武将・人事・ホテル）を読む
  ids_of(dataset, data) そのデータにある文書の ID の集合
  validate(...)         質問の形と中身を確かめる。問題の文の一覧を返す（空なら合格）

人事・ホテルに固有の確かめは、@dataset_check("hr") のように、このファイルの中に書いて、DATASET_CHECKS に足す
（別のモジュールに置くと、tools/check_questions.py から呼ばれない）。人事の確かめは check_hr。
"""
import json
import re
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]

DATASETS = ("sengoku", "hr", "hotel")

# 人事・ホテルは、種類ごとの目標の数（合計 60 問・40 問）。違えば validate が問題にする。
TYPE_TARGETS = {
    "hr": {"paraphrase": 12, "proper-noun": 10, "numeric": 10, "multi-doc": 10, "scan": 6, "permission": 12},
    "hotel": {"paraphrase": 10, "proper-noun": 6, "condition": 10, "ja-en": 6, "amenity": 8},
}
# 武将は既存の 60 問（basic/data/sengoku/questions.json の intent）。使える種類だけ決め、数は確かめない。
SENGOKU_TYPES = ("keyword-wins", "vector-wins", "hybrid-improves", "hybrid-worsens", "climax")

# 質問のファイルと、質問が指す文書のデータの置き場所（既定）。ホテルのデータは Repo に写さず、
# tools/hotel_vectors.py と同じ _work/hotel-vectors/ に置いたものを読む（別の場所は --hotel-data で渡す）。
QUESTION_FILES = {
    "sengoku": REPO_DIR / "basic" / "data" / "sengoku" / "questions.json",
    "hr": REPO_DIR / "evaluation" / "hr_questions.json",
    "hotel": REPO_DIR / "evaluation" / "hotel_questions.json",
}
DATA_FILES = {
    "sengoku": REPO_DIR / "basic" / "data" / "sengoku" / "bushou.json",
    "hr": REPO_DIR / "applied" / "data" / "manifest.json",
    "hotel": REPO_DIR / "_work" / "hotel-vectors" / "HotelsData_toAzureBlobs_ja.json",
}


class DataError(Exception):
    """利用者に見せる日本語の理由つきの失敗（ファイルがない・読めない・形が違う）。"""


def allowed_types(dataset):
    """そのデータで使える質問の種類（type）。"""
    return tuple(TYPE_TARGETS[dataset]) if dataset in TYPE_TARGETS else SENGOKU_TYPES


# ------------------------------------------------------------------ 読む

def _show(path):
    path = Path(path)
    try:
        return str(path.relative_to(REPO_DIR))
    except ValueError:
        return str(path)


def read_json(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise DataError(f"{_show(path)} がありません") from None
    except (OSError, ValueError):
        raise DataError(f"{_show(path)} が読めません") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise DataError(f"{_show(path)} が JSON として読めません（{error.lineno} 行目：{error.msg}）") from None


def load_questions(path):
    """質問のファイルを読む。type がなく intent がある質問（武将の既存の60問）は、intent を type として読む。"""
    data = read_json(path)
    if not isinstance(data, list):
        raise DataError(f"{_show(path)} は質問の並び（[ ... ]）で書きます")
    return [{**q, "type": q["intent"]} if isinstance(q, dict) and "type" not in q and "intent" in q else q
            for q in data]


def ids_of(dataset, data):
    """データにある文書の ID の集合。武将は id、人事は manifest の files の doc_id、ホテルは HotelId。"""
    try:
        if dataset == "sengoku":
            return {str(item["id"]) for item in data}
        if dataset == "hr":
            return {str(item["doc_id"]) for item in data["files"]}
        if dataset == "hotel":
            return {str(item["HotelId"]) for item in data}
    except (KeyError, TypeError):
        pass
    raise DataError(f"{dataset} のデータの形が違います（ID が取り出せません）")


def load_data(dataset, path=None):
    """質問が指す文書のデータを読む。path を省くと DATA_FILES の既定の場所。形が違えば DataError。"""
    path = Path(path) if path else DATA_FILES[dataset]
    data = read_json(path)
    try:
        ids_of(dataset, data)
    except DataError:
        raise DataError(f"{_show(path)} は {dataset} のデータの形ではありません（ID が取り出せません）") from None
    return data


# ------------------------------------------------------------------ 確かめる

DATASET_CHECKS = {name: [] for name in DATASETS}


def dataset_check(dataset):
    """データ固有の確かめを足すデコレーター。

    確かめは check(questions, *, known_ids, data) -> list[str]（問題の文の一覧）で、共通の確かめのあとに
    呼ばれる。questions は、質問の形をなしているもの（辞書）だけ。
    置き場所：このファイル（tools/evallib/questions.py）の中。ほかのモジュールに置くと、読み込まれず、CLI から呼ばれない。
    data：validate に渡したもの（CLI は人事なら manifest、ホテルならホテルの並び）。validate を data なしで呼ぶと None
    なので、データを使う確かめは、None のときの扱い（飛ばす）を決めておく。
    """
    def register(check):
        DATASET_CHECKS[dataset].append(check)
        return check
    return register


def label(question, index=None):
    """問題の文の頭に付ける呼び名。qid があればそれ、なければ「3 番目」。"""
    qid = question.get("qid") if isinstance(question, dict) else None
    if isinstance(qid, str) and qid.strip():
        return qid
    return f"{index} 番目" if index else "?"


def _is_ids(value):
    return isinstance(value, list) and all(isinstance(x, str) and x for x in value)


def _check_ids(name, who, value, known):
    """ID の並びの形・重複・文書にあるかを確かめる。"""
    if not _is_ids(value):
        return [f"{who}：{name} は ID の並びで書きます（空は []）"]
    problems = []
    for dup in sorted({x for x in value if value.count(x) > 1}):
        problems.append(f"{who}：{name} に「{dup}」が 2 回あります")
    problems += [f"{who}：{name} の「{x}」は文書にありません" for x in dict.fromkeys(value) if x not in known]
    return problems


def _check_question(index, q, known, types):
    who = label(q, index)
    if not isinstance(q, dict):
        return [f"{who}：質問の形（{{ ... }}）ではありません"]
    problems = []
    qid = q.get("qid")
    if "qid" in q and not isinstance(qid, str):
        problems.append(f"{who}：qid は文字列で書きます（今は {type(qid).__name__}。例 \"hr-01\"）")
    elif not isinstance(qid, str) or not qid.strip():
        problems.append(f"{who}：qid がありません")
    elif qid != qid.strip() or any(ch.isspace() for ch in qid):
        problems.append(f"{who}：qid「{qid}」に空白があります")
    text = q.get("question")
    if "question" in q and not isinstance(text, str):
        problems.append(f"{who}：question は文字列で書きます（質問の文。今は {type(text).__name__}）")
    elif not isinstance(text, str) or not text.strip():
        problems.append(f"{who}：question（質問の文）がありません")
    kind = q.get("type")
    if "type" in q and not isinstance(kind, str):
        problems.append(f"{who}：type は文字列で書きます（種類の名前。今は {type(kind).__name__}）")
    elif not isinstance(kind, str) or not kind:
        problems.append(f"{who}：type（種類）がありません")
    elif kind not in types:
        problems.append(f"{who}：type「{kind}」は使えません（使える種類：{'・'.join(types)}）")
    if "answer_ids" not in q:
        problems.append(f"{who}：answer_ids がありません（正解がなければ []）")
    else:
        problems += _check_ids("answer_ids", who, q["answer_ids"], known)
        if isinstance(kind, str) and kind != "permission" and _is_ids(q["answer_ids"]) and not q["answer_ids"]:
            problems.append(f"{who}：{kind} の質問の answer_ids が空です（空でよいのは permission だけ。正解の文書を 1 件以上書きます）")
    for name in ("why", "note"):
        if name in q and not isinstance(q[name], str):
            problems.append(f"{who}：{name} は文字列で書きます")
    if "as_role" in q and (not isinstance(q["as_role"], str) or not q["as_role"].strip()):
        problems.append(f"{who}：as_role は役割の名前（文字列）で書きます")
    if "hidden_ids" in q:
        problems += _check_ids("hidden_ids", who, q["hidden_ids"], known)
        if _is_ids(q["hidden_ids"]) and _is_ids(q.get("answer_ids")):
            both = [x for x in q["hidden_ids"] if x in q["answer_ids"]]
            if both:
                problems.append(f"{who}：answer_ids と hidden_ids に同じ ID があります（{'・'.join(dict.fromkeys(both))}）")
    if kind == "permission":
        if not isinstance(q.get("as_role"), str) or not q["as_role"].strip():
            problems.append(f"{who}：permission の質問には as_role（だれとして聞くか）が要ります")
        if not _is_ids(q.get("hidden_ids")) or not q["hidden_ids"]:
            problems.append(f"{who}：permission の質問には hidden_ids（見えてはいけない文書）が 1 件以上要ります")
    return problems


def validate(dataset, questions, *, known_ids, data=None):
    """質問の形と中身を確かめて、問題の文の一覧を返す。空なら合格。

    共通の確かめ：項目の形（qid・question・type は文字列）・qid が一意・type がそのデータで使える種類・
    answer_ids と hidden_ids が known_ids にある・answer_ids と hidden_ids が重ならない・answer_ids が空なのは permission だけ・
    permission には as_role と hidden_ids。人事・ホテルは、種類ごとの数が TYPE_TARGETS と同じこと
    （武将は既存のデータなので、数は確かめない）。そのあとに DATASET_CHECKS のデータ固有の確かめを足す。
    data は、データ固有の確かめに渡す（人事は manifest、ホテルはホテルの並び）。
    """
    if dataset not in DATASETS:
        raise ValueError(f"dataset は {'・'.join(DATASETS)} のどれかです：{dataset!r}")
    if not isinstance(questions, list):
        return ["質問は並び（[ ... ]）で書きます"]
    known, types = set(known_ids), allowed_types(dataset)
    problems = []
    for index, q in enumerate(questions, 1):
        problems += _check_question(index, q, known, types)
    seen = {}
    for index, q in enumerate(questions, 1):
        qid = q.get("qid") if isinstance(q, dict) else None
        if isinstance(qid, str) and qid.strip():
            seen.setdefault(qid, []).append(index)
    for qid, places in seen.items():
        if len(places) > 1:
            problems.append(f"qid「{qid}」が重複しています（{'・'.join(map(str, places))} 番目）")
    for kind, target in TYPE_TARGETS.get(dataset, {}).items():
        count = sum(1 for q in questions if isinstance(q, dict) and q.get("type") == kind)
        if count != target:
            problems.append(f"種類 {kind} は {count} 問です（目標 {target} 問）")
    shaped = [q for q in questions if isinstance(q, dict)]
    for check in DATASET_CHECKS[dataset]:
        problems += check(shaped, known_ids=known, data=data)
    return problems


# ------------------------------------------------------------------ 人事に固有の確かめ

HR_PERMISSION_ROLE = "role:employee"   # 一般社員。applied/lib/acl.py：一般社員に見えるのは求人票（job_posting）だけ
HR_JOB_KIND = "job_posting"
# 文書の本文のもと（人事の evidence の語句を探す場所）。見つからない（フォルダーがない）ときは、語句を探す確かめだけ飛ばす
HR_CONTENT_DIR = REPO_DIR / "applied" / "data" / "_build" / "content"


def _strs(value):
    """ID の並びから、文字列だけを重複なしで取り出す（形の誤りは共通の確かめが言うので、ここでは読み飛ばす）。"""
    return list(dict.fromkeys(x for x in value if isinstance(x, str))) if isinstance(value, list) else []


def _hr_files(data):
    """manifest の files を {doc_id: 文書の記述} にする。manifest が渡されていない・形が違うときは None。"""
    try:
        return {str(f["doc_id"]): f for f in data["files"]}
    except (KeyError, TypeError):
        return None


def _squash(text):
    """空白（全角を含む）を全部取る。PDF や Word の折り返しがあっても、語句が見つかるように。"""
    return re.sub(r"\s+", "", text)


def _all_strings(value):
    """JSON の中の文字列を全部（入れ子も）。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def hr_source_text(doc_id, file, content_dir):
    """文書の本文のもとの文字（evidence の語句を探す先）と、その場所の名前を返す。

    求人票・経歴書は content/jobs・resumes の Markdown、メールは mail.json の件名と本文、
    面接の評価の一覧は evaluations.json と source_ats.json（選考状況・選考履歴のシートの元の台帳）、
    スキャンは scans.json の記述と、画像を描く make_scans.py の、そのスキャンを作る関数（画像の中の文字はここにある）。
    読めない・見つからないときは DataError。
    """
    content_dir = Path(content_dir)
    kind = file.get("kind")
    if kind in ("job_posting", "resume"):
        path = content_dir / ("jobs" if kind == "job_posting" else "resumes") / f"{doc_id}.md"
        try:
            return path.read_text(encoding="utf-8-sig"), f"{path.parent.name}/{path.name}"
        except (OSError, ValueError):
            raise DataError(f"{doc_id} の本文のもと {_show(path)} が読めません") from None
    if kind == "mail":
        mails = read_json(content_dir / "mail.json").get("mails", [])
        mail = next((m for m in mails if isinstance(m, dict) and m.get("id") == doc_id), None)
        if mail is None:
            raise DataError(f"{doc_id} が mail.json にありません")
        return f"{mail.get('subject', '')}\n{mail.get('body', '')}", "mail.json"
    if kind == "interview_evaluations":
        text = "\n".join(_all_strings(read_json(content_dir / "evaluations.json")))
        text += "\n" + "\n".join(_all_strings(read_json(content_dir / "source_ats.json")))
        return text, "evaluations.json・source_ats.json"
    if kind == "scan":
        scans = read_json(content_dir / "scans.json").get("scans", [])
        scan = next((x for x in scans if isinstance(x, dict) and x.get("id") == doc_id), None)
        if scan is None:
            raise DataError(f"{doc_id} が scans.json にありません")
        text = "\n".join(_all_strings(scan))
        script = content_dir.parent / "make_scans.py"
        try:
            code = script.read_text(encoding="utf-8")
        except (OSError, ValueError):
            raise DataError(f"{doc_id} の画像を描くスクリプト {_show(script)} が読めません") from None
        match = re.search(rf"^def make_{re.escape(str(scan.get('kind')))}\(.*?(?=^def |\Z)", code, re.S | re.M)
        if match:
            text += "\n" + match.group(0)
        return text, "scans.json・make_scans.py"
    raise DataError(f"{doc_id} の種類「{kind}」は本文のもとが決まっていません")


def _check_hr_evidence(who, q, ids, known_ids, files, content_dir, cache):
    """evidence（{文書の ID: 本文にそのまま出る語句}）の確かめ。文書にない ID は、共通の確かめが言うので、語句を求めない。"""
    problems = []
    evidence = q.get("evidence")
    if not isinstance(evidence, dict):
        how = "（answer_ids と hidden_ids の文書ごとに、本文にそのまま出る短い語句を {\"MAIL-01\": \"…\"} の形で書きます）"
        return [f"{who}：evidence がありません{how}" if evidence is None
                else f"{who}：evidence は {{文書の ID: 語句}} の形で書きます"]
    for doc_id in (i for i in ids if i in known_ids):
        phrase = evidence.get(doc_id)
        if not isinstance(phrase, str) or not phrase.strip():
            problems.append(f"{who}：evidence に「{doc_id}」の語句がありません（answer_ids・hidden_ids の文書ごとに 1 つ）")
    for doc_id in evidence:
        if doc_id not in ids:
            problems.append(f"{who}：evidence の「{doc_id}」は answer_ids にも hidden_ids にもありません")
    if files is None or content_dir is None:
        return problems
    for doc_id, phrase in evidence.items():
        if doc_id not in ids or doc_id not in files or not isinstance(phrase, str) or not phrase.strip():
            continue
        if doc_id not in cache:
            try:
                cache[doc_id] = hr_source_text(doc_id, files[doc_id], content_dir)
            except DataError as error:
                cache[doc_id] = error
        found = cache[doc_id]
        if isinstance(found, DataError):
            problems.append(f"{who}：evidence「{doc_id}」の語句を探せません（{found}）")
        elif _squash(phrase) not in _squash(found[0]):
            problems.append(f"{who}：evidence「{doc_id}」の語句「{phrase}」が、文書の本文のもと（{found[1]}）にありません")
    return problems


@dataset_check("hr")
def check_hr(questions, *, known_ids, data):
    """人事の質問に固有の確かめ（種類ごとの決まり、evidence）。

    - permission：as_role は role:employee だけ。hidden_ids は求人票でない文書（一般社員に見えない文書）。
      answer_ids は求人票だけ（なければ空）
    - scan：answer_ids に、OCR が要る文書（manifest の ocr_required が true）が 1 件以上ある
    - multi-doc：answer_ids が 2 件以上（どれか 1 件だけでは答えきれない）
    - evidence：answer_ids と hidden_ids の文書ごとに、本文にそのまま出る短い語句（{文書の ID: 語句}）。ない文書があれば問題。
      HR_CONTENT_DIR（文書の本文のもと）があるときは、語句が、その文書の本文のもと（hr_source_text）にあること
    answer_ids・hidden_ids が manifest にあることは、共通の確かめ（known_ids）が見る。
    data は manifest。None（validate を data なしで呼んだ）のときは、文書の種類・OCR・本文が分からないので、
    それを使う確かめ（permission の求人票、scan の OCR、evidence の語句の検索）は飛ばす。
    役割・multi-doc の数・evidence がそろっていることは、data なしでも確かめる。
    """
    files = _hr_files(data)
    content_dir = HR_CONTENT_DIR if Path(HR_CONTENT_DIR).is_dir() else None
    cache = {}
    problems = []
    for index, q in enumerate(questions, 1):
        who = label(q, index)
        kind = q.get("type")
        answers = _strs(q.get("answer_ids"))
        hidden = _strs(q.get("hidden_ids"))
        if kind == "permission":
            role = q.get("as_role")
            if isinstance(role, str) and role.strip() and role != HR_PERMISSION_ROLE:
                problems.append(f"{who}：permission の as_role は {HR_PERMISSION_ROLE} だけを使います（今は「{role}」。"
                                "一般社員には求人票だけが見える決まりです）")
            if files is not None:
                for doc_id in hidden:
                    if doc_id in files and files[doc_id].get("kind") == HR_JOB_KIND:
                        problems.append(f"{who}：hidden_ids の「{doc_id}」は求人票です（求人票は一般社員にも見えるので、"
                                        "hidden_ids には求人票でない文書を書きます）")
                for doc_id in answers:
                    if doc_id in files and files[doc_id].get("kind") != HR_JOB_KIND:
                        problems.append(f"{who}：permission の answer_ids の「{doc_id}」は求人票ではありません"
                                        "（一般社員に見える正解は求人票だけ。なければ空にして、hidden_ids に書きます）")
        elif kind == "scan" and files is not None:
            if not any(files.get(doc_id, {}).get("ocr_required") for doc_id in answers):
                problems.append(f"{who}：scan の質問の answer_ids には、OCR が要る文書（スキャン）を 1 件以上書きます")
        elif kind == "multi-doc":
            if len(answers) < 2:
                problems.append(f"{who}：multi-doc の質問の answer_ids は 2 件以上です（今は {len(answers)} 件。"
                                "どれか 1 件だけで答えられる質問は、ほかの種類にします）")
        problems += _check_hr_evidence(who, q, list(dict.fromkeys(answers + hidden)), known_ids, files, content_dir, cache)
    return problems
