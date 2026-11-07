"""検索の評価で使う質問の形と、その確かめ（標準ライブラリだけ）。

質問は JSON の並びで、データごとのファイルに置く（形と種類の説明は evaluation/README.md）。
  load_questions(path)  質問のファイルを読む。武将の既存の質問の intent は、type として読む
  load_data(dataset)    質問が指す文書のデータ（武将・人事・ホテル）を読む
  ids_of(dataset, data) そのデータにある文書の ID の集合
  validate(...)         質問の形と中身を確かめる。問題の文の一覧を返す（空なら合格）

人事・ホテルに固有の確かめは、@dataset_check("hr") のように、この下の DATASET_CHECKS に足す。
"""
import json
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
    if not isinstance(qid, str) or not qid.strip():
        problems.append(f"{who}：qid がありません")
    elif qid != qid.strip() or any(ch.isspace() for ch in qid):
        problems.append(f"{who}：qid「{qid}」に空白があります")
    text = q.get("question")
    if not isinstance(text, str) or not text.strip():
        problems.append(f"{who}：question（質問の文）がありません")
    kind = q.get("type")
    if not isinstance(kind, str) or not kind:
        problems.append(f"{who}：type（種類）がありません")
    elif kind not in types:
        problems.append(f"{who}：type「{kind}」は使えません（使える種類：{'・'.join(types)}）")
    if "answer_ids" not in q:
        problems.append(f"{who}：answer_ids がありません（正解がなければ []）")
    else:
        problems += _check_ids("answer_ids", who, q["answer_ids"], known)
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

    共通の確かめ：qid が一意・question・type がそのデータで使える種類・answer_ids と hidden_ids が known_ids にある・
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
