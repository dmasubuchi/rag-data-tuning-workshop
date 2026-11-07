"""検索の評価で使う質問の形と、その確かめ（標準ライブラリだけ）。

質問は JSON の並びで、データごとのファイルに置く（形と種類の説明は evaluation/README.md）。
  load_questions(path)  質問のファイルを読む。武将の既存の質問の intent は、type として読む
  load_data(dataset)    質問が指す文書のデータ（武将・人事・ホテル）を読む
  ids_of(dataset, data) そのデータにある文書の ID の集合
  validate(...)         質問の形と中身を確かめる。問題の文の一覧を返す（空なら合格）

人事・ホテルに固有の確かめは、@dataset_check("hr") のように、このファイルの中に書いて、DATASET_CHECKS に足す
（別のモジュールに置くと、tools/check_questions.py から呼ばれない）。人事の確かめは check_hr、ホテルは check_hotel。
ホテルの condition（条件）は、condition_to_filter（検索の $filter の文字）と matches（データが条件に合うか）で扱う。
"""
import importlib.util
import json
import re
import sys
from datetime import datetime
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


def _read_items(path, key):
    """{key: [ ... ]} の形の JSON から、その並びを取り出す。一番上の形が違えば DataError。"""
    data = read_json(path)
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise DataError(f"{_show(path)} の一番上の形が違います（{{\"{key}\": [ ... ]}} の形で読みます）")
    return items


_SCAN_FACTS_CACHE = {}


def _run_scan_facts(script):
    """make_scans.py を（その場で）読み込んで scan_facts() を呼ぶ。読めなければ (None, 理由)。"""
    name = "_evallib_make_scans"
    folder = str(script.parent)
    before = set(sys.modules)
    sys.path.insert(0, folder)
    try:
        spec = importlib.util.spec_from_file_location(name, script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        function = getattr(module, "scan_facts", None)
        if not callable(function):
            return None, "make_scans.py に scan_facts() がありません"
        facts = function()
        if not isinstance(facts, dict):
            return None, "scan_facts() の結果が {scan の id: {...}} の形ではありません"
        return facts, None
    except Exception as error:   # numpy・Pillow がない、台帳が読めない、など
        return None, f"{type(error).__name__}：{str(error)[:60]}"
    finally:
        if folder in sys.path:
            sys.path.remove(folder)
        for added in set(sys.modules) - before:   # 同じ置き場の lib_common・scan_effects も、次の読み込みに残さない
            module_file = getattr(sys.modules[added], "__file__", None)
            if added == name or (module_file and Path(module_file).resolve().parent == script.parent.resolve()):
                sys.modules.pop(added, None)


def _load_scan_facts(script):
    """scan_facts()（書類に書く事実。応募番号・受付印の日付など、画像に見える文字のもと）の結果と、読めなかった理由。"""
    try:
        stat = script.stat()
    except OSError:
        return None, "make_scans.py が読めません"
    key = (str(script), stat.st_mtime_ns, stat.st_size)
    if key not in _SCAN_FACTS_CACHE:
        _SCAN_FACTS_CACHE[key] = _run_scan_facts(script)
    return _SCAN_FACTS_CACHE[key]


def hr_content_available():
    """文書の本文のもと（HR_CONTENT_DIR）があるか。ないと、evidence の語句を探す確かめは飛ばされる。"""
    return Path(HR_CONTENT_DIR).is_dir()


def hr_source_text(doc_id, file, content_dir):
    """文書の本文のもとの文字（evidence の語句を探す先）と、その場所の名前を返す。

    求人票・経歴書は content/jobs・resumes の Markdown、メールは mail.json の件名と本文、
    面接の評価の一覧は evaluations.json と source_ats.json（選考状況・選考履歴のシートの元の台帳）、
    スキャンは scans.json の記述と、画像を描く make_scans.py の、そのスキャンを作る関数、
    書類に書く事実を台帳から引く scan_facts() の結果（応募番号・受付印の日付など、画像に見える文字）。
    numpy・Pillow がなく scan_facts() を呼べないときは、最初の2つだけを探す（その旨を場所の名前に書く）。
    読めない・見つからない・一番上の形が違うときは DataError。
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
        mails = _read_items(content_dir / "mail.json", "mails")
        mail = next((m for m in mails if isinstance(m, dict) and m.get("id") == doc_id), None)
        if mail is None:
            raise DataError(f"{doc_id} が mail.json にありません")
        return f"{mail.get('subject', '')}\n{mail.get('body', '')}", "mail.json"
    if kind == "interview_evaluations":
        text = "\n".join(_all_strings(read_json(content_dir / "evaluations.json")))
        text += "\n" + "\n".join(_all_strings(read_json(content_dir / "source_ats.json")))
        return text, "evaluations.json・source_ats.json"
    if kind == "scan":
        scans = _read_items(content_dir / "scans.json", "scans")
        scan = next((x for x in scans if isinstance(x, dict) and x.get("id") == doc_id), None)
        if scan is None:
            raise DataError(f"{doc_id} が scans.json にありません")
        text = "\n".join(_all_strings(scan))
        script = content_dir.parent / "make_scans.py"
        try:
            code = script.read_text(encoding="utf-8")
        except (OSError, ValueError):
            raise DataError(f"{doc_id} の画像を描くスクリプト {_show(script)} が読めません") from None
        scan_kind = scan.get("kind")
        match = re.search(rf"^def make_{re.escape(str(scan_kind))}\(.*?(?=^def |\Z)", code, re.S | re.M)
        notes = []
        if match:
            text += "\n" + match.group(0)
        else:
            notes.append(f"スキャンの種類「{scan_kind}」の make_{scan_kind} が make_scans.py にありません")
        facts, reason = _load_scan_facts(script)
        if facts is not None:
            text += "\n" + "\n".join(_all_strings(facts.get(doc_id)))
        else:
            notes.append(f"scan_facts() は読めませんでした（{reason}）")
        label = "scans.json・make_scans.py" + ("・scan_facts()" if facts is not None else "")
        return text, label + "".join(f" ※{note}" for note in notes)
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
    content_dir = HR_CONTENT_DIR if hr_content_available() else None
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


# ------------------------------------------------------------------ ホテルの condition（条件）

# condition に書ける項目と、値の種類。検索のインデックスで「絞り込める」項目（guide/hotel.md の hotels-blob）だけ。
# Rooms/… は客室の項目（どれかの客室が満たす）、Address/… は住所の項目。
CONDITION_FIELDS = {
    "HotelId": "text", "Category": "text", "Category_ja": "text",
    "ParkingIncluded": "bool", "IsDeleted": "bool", "LastRenovationDate": "datetime", "Rating": "number",
    "Address/City": "text", "Address/StateProvince": "text", "Address/PostalCode": "text", "Address/Country": "text",
    "Rooms/Type": "text", "Rooms/Type_ja": "text", "Rooms/BaseRate": "number", "Rooms/BedOptions": "text",
    "Rooms/SleepsCount": "number", "Rooms/SmokingAllowed": "bool",
}
CONDITION_OPS = ("eq", "ge", "le", "gt", "lt")
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _datetime(text):
    """ISO 8601 の日時の文字（例 2015-01-01T00:00:00Z）を日時にする。そうでなければ None。"""
    if not isinstance(text, str) or not _ISO_DATETIME.match(text):
        return None
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None


def _parse_ops(key, spec):
    """項目 1 つの条件（値だけ、または {演算: 値}）を [(演算, 値)] にする。形が違えば ValueError。"""
    kind = CONDITION_FIELDS[key]
    ops = list(spec.items()) if isinstance(spec, dict) else [("eq", spec)]
    if not ops:
        raise ValueError(f"「{key}」の条件が空です（値、または {{\"ge\": 4.5}} のように書きます）")
    for op, value in ops:
        if op not in CONDITION_OPS:
            raise ValueError(f"「{key}」の演算「{op}」は使えません（使える演算：{'・'.join(CONDITION_OPS)}）")
        if kind == "bool":
            ok = isinstance(value, bool) and op == "eq"
            how = "true か false（演算は eq だけ）"
        elif kind == "text":
            ok = isinstance(value, str) and bool(value) and op == "eq"
            how = "文字列（演算は eq だけ）"
        elif kind == "number":
            ok = _is_number(value)
            how = "数"
        else:
            ok = _datetime(value) is not None
            how = "日時の文字（例 \"2015-01-01T00:00:00Z\"）"
        if not ok:
            raise ValueError(f"「{key}」の {op} は {how} で書きます（今は {value!r}）")
    return ops


def _parse_condition(condition):
    """condition を、書いた順の部品にする。部品は ("field", 項目, 演算の並び)、または ("rooms", [(項目, 演算の並び), ...])。

    Rooms/… の条件は、いくつあっても 1 つの部品にまとめる（同じ客室が全部を満たす）。部品の位置は最初の Rooms/… の位置。
    形が違えば ValueError（理由は日本語）。
    """
    if not isinstance(condition, dict) or not condition:
        raise ValueError("condition は {項目: 値、または {演算: 値}} の形で、1 つ以上の条件を書きます")
    parts, rooms = [], None
    for key, spec in condition.items():
        if key not in CONDITION_FIELDS:
            raise ValueError(f"「{key}」は condition に使えません（使える項目：{'・'.join(CONDITION_FIELDS)}）")
        ops = _parse_ops(key, spec)
        if key.startswith("Rooms/"):
            if rooms is None:
                rooms = []
                parts.append(("rooms", rooms))
            rooms.append((key[len("Rooms/"):], ops))
        else:
            parts.append(("field", key, ops))
    return parts


def _odata_value(kind, value):
    if kind == "bool":
        return "true" if value else "false"
    if kind == "text":
        return "'" + value.replace("'", "''") + "'"
    if kind == "datetime":
        return value          # OData の日時は、引用符なし
    return str(value) if isinstance(value, int) else repr(value)


def condition_to_filter(condition):
    """condition を、検索の $filter の文字にする。

    {"Rating": {"ge": 4.5}, "ParkingIncluded": True} → "Rating ge 4.5 and ParkingIncluded eq true"
    {"Rooms/BaseRate": {"le": 100}} → "Rooms/any(r: r/BaseRate le 100)"
    項目の順は、書いた順のまま。Rooms/… は 1 つの any にまとめる（同じ客室が全部を満たす）。形が違えば ValueError。
    """
    clauses = []
    for part in _parse_condition(condition):
        if part[0] == "field":
            _, key, ops = part
            clauses += [f"{key} {op} {_odata_value(CONDITION_FIELDS[key], value)}" for op, value in ops]
        else:
            inner = [f"r/{field} {op} {_odata_value(CONDITION_FIELDS['Rooms/' + field], value)}"
                     for field, ops in part[1] for op, value in ops]
            clauses.append("Rooms/any(r: " + " and ".join(inner) + ")")
    return " and ".join(clauses)


def _holds(kind, found, op, wanted):
    """データの値 found が、条件（op と wanted）を満たすか。値がない・種類が違うときは満たさない（OData の null と同じ）。"""
    if found is None:
        return False
    if kind in ("bool", "text"):
        return isinstance(found, type(wanted)) and found == wanted
    if kind == "number":
        found, wanted = (found, wanted) if _is_number(found) else (None, None)
    else:
        found, wanted = _datetime(found), _datetime(wanted)
    if found is None:
        return False
    return {"eq": found == wanted, "ge": found >= wanted, "le": found <= wanted,
            "gt": found > wanted, "lt": found < wanted}[op]


def _value_at(item, path):
    for name in path.split("/"):
        item = item.get(name) if isinstance(item, dict) else None
    return item


def matches(hotel, condition):
    """ホテル（データの 1 件）が condition に合うか。Rooms/… は、どれかの客室が（まとめて）満たすこと。形が違えば ValueError。"""
    for part in _parse_condition(condition):
        if part[0] == "field":
            _, key, ops = part
            found = _value_at(hotel, key)
            if not all(_holds(CONDITION_FIELDS[key], found, op, value) for op, value in ops):
                return False
        else:
            rooms = hotel.get("Rooms") if isinstance(hotel, dict) else None
            rooms = rooms if isinstance(rooms, list) else []
            if not any(isinstance(room, dict)
                       and all(_holds(CONDITION_FIELDS["Rooms/" + field], room.get(field), op, value)
                               for field, ops in part[1] for op, value in ops)
                       for room in rooms):
                return False
    return True


# ------------------------------------------------------------------ ホテルに固有の確かめ

HOTEL_MAX_ANSWERS = 5             # condition でない質問の answer_ids の上限
HOTEL_MAX_CONDITION_ANSWERS = 20  # condition の質問で、条件に合うホテルの上限（0 件・これより多い条件は使わない）
_HOTEL_NON_TEXT = ("HotelId", "Location", "LastRenovationDate")   # 質問の根拠にしない項目
_JAPANESE_CHARS = re.compile("[ぁ-んァ-ヶ一-鿿]")
_OTHER_LANGUAGE = {"ja": "en", "en": "ja"}
_LANGUAGE_NAME = {"ja": "日本語", "en": "英語"}


def hotel_texts(hotel):
    """ホテル 1 件の文字を、{"en": 英語の項目の文字, "ja": 日本語の項目の文字} にする（evidence の語句を探す先）。

    日本語の項目は、名前が _ja で終わる項目（HotelName_ja・Description_ja・Category_ja・Tags_ja・客室の Description_ja・Type_ja）。
    フランス語（_fr）と、HotelId・Location・LastRenovationDate は含めない。
    それ以外はすべて英語の項目：HotelName・Description・Category・Tags、客室の Description・Type・BedOptions・Tags、住所（Address）。
    """
    found = {"en": [], "ja": []}

    def walk(value, language):
        if isinstance(value, str):
            found[language].append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in _HOTEL_NON_TEXT and not str(key).endswith("_fr"):
                    walk(item, "ja" if str(key).endswith("_ja") else "en")
        elif isinstance(value, list):
            for item in value:
                walk(item, language)

    walk(hotel, "en")
    return {language: "\n".join(parts) for language, parts in found.items()}


def question_language(text):
    """質問の言語。日本語の文字（ひらがな・カタカナ・漢字）があれば "ja"、なければ "en"。"""
    return "ja" if isinstance(text, str) and _JAPANESE_CHARS.search(text) else "en"


def _hotels(data):
    """ホテルの並びから、{HotelId: ホテル} にする。渡されていない・形が違うときは None。"""
    try:
        return {str(h["HotelId"]): h for h in data}
    except (KeyError, TypeError):
        return None


def _phrases(value):
    """evidence の値（語句、または語句の並び）を、語句の並びにする。形が違えば None。"""
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list) and value and all(isinstance(x, str) and x.strip() for x in value):
        return value
    return None


def _check_hotel_evidence(who, q, answers, hotels, texts):
    """ホテルの evidence（{HotelId: 語句、または語句の並び}）の確かめ。

    - condition でない質問は、answer_ids のホテルごとに要る（condition の質問は任意。あれば同じ確かめ）
    - ホテルのデータがあるときは、語句がそのホテルの文字（hotel_texts）にあること
    - ja-en は、質問の言語の項目になく、もう一方の言語の項目にだけある語句が、ホテルごとに 1 つ以上あること
    """
    evidence = q.get("evidence")
    required = "condition" not in q and q.get("type") != "condition"
    if evidence is None and not required:
        return []
    if not isinstance(evidence, dict):
        how = "（answer_ids のホテルごとに、そのホテルのデータにそのまま出る短い語句を {\"6\": \"無料Wi-Fi\"} の形で書きます）"
        return [f"{who}：evidence がありません{how}" if evidence is None
                else f"{who}：evidence は {{HotelId: 語句}} の形で書きます"]
    problems = []
    for hotel_id in answers:
        if hotel_id not in evidence and required:
            problems.append(f"{who}：evidence に「{hotel_id}」の語句がありません（answer_ids のホテルごとに 1 つ）")
    for hotel_id, value in evidence.items():
        if hotel_id not in answers:
            problems.append(f"{who}：evidence の「{hotel_id}」は answer_ids にありません")
            continue
        phrases = _phrases(value)
        if phrases is None:
            problems.append(f"{who}：evidence「{hotel_id}」は、語句か、語句の並び（空でない文字列）で書きます")
            continue
        if hotels is None or hotel_id not in hotels:
            continue
        if hotel_id not in texts:
            texts[hotel_id] = {language: _squash(text) for language, text in hotel_texts(hotels[hotel_id]).items()}
        both = texts[hotel_id]["en"] + "\n" + texts[hotel_id]["ja"]
        for phrase in phrases:
            if _squash(phrase) not in both:
                problems.append(f"{who}：evidence「{hotel_id}」の語句「{phrase}」が、そのホテルのデータ"
                                "（名前・説明・タグ・客室・住所）にありません")
        if q.get("type") == "ja-en":
            language = question_language(q.get("question"))
            other = _OTHER_LANGUAGE[language]
            if not any(_squash(p) in texts[hotel_id][other] and _squash(p) not in texts[hotel_id][language] for p in phrases):
                example = "。例：英語の名前（HotelName）、都市名・通りの名前（Address）" if language == "ja" else ""
                problems.append(
                    f"{who}：ja-en の evidence「{hotel_id}」に、{_LANGUAGE_NAME[other]}の項目にだけあって、"
                    f"{_LANGUAGE_NAME[language]}の項目にない語句がありません"
                    f"（{_LANGUAGE_NAME[language]}の質問の手がかりは、{_LANGUAGE_NAME[other]}の項目にだけある語句にします{example}）")
    return problems


def _check_hotel_condition(who, q, answers, hotels):
    """condition の確かめ。形が正しく、ホテルのデータがあるときは、answer_ids が「条件に合うホテル全部」と同じこと。"""
    if "condition" not in q:
        if q.get("type") == "condition":
            return [f"{who}：condition の質問には condition（答えの条件）が要ります"
                    "（例 {\"Rating\": {\"ge\": 4.5}, \"ParkingIncluded\": true}）"]
        return []
    try:
        _parse_condition(q["condition"])
    except ValueError as error:
        return [f"{who}：condition の形が違います（{error}）"]
    if hotels is None:
        return []
    matched = sorted((i for i, hotel in hotels.items() if matches(hotel, q["condition"])), key=lambda i: (len(i), i))
    problems = []
    if not matched or len(matched) > HOTEL_MAX_CONDITION_ANSWERS:
        problems.append(f"{who}：condition に合うホテルが {len(matched)} 件です（1〜{HOTEL_MAX_CONDITION_ANSWERS} 件になる条件にします）")
    if not matched:
        return problems
    missing = [i for i in matched if i not in answers]
    extra = [i for i in answers if i not in matched]
    if missing or extra:
        detail = "・".join(part for part in (f"足りない：{'・'.join(missing)}" if missing else "",
                                            f"条件に合わない：{'・'.join(extra)}" if extra else "") if part)
        problems.append(f"{who}：answer_ids が、condition に合うホテル（{len(matched)} 件：{'・'.join(matched)}）と違います"
                        f"（{detail}）。answer_ids は、条件に合うホテル全部にします")
    return problems


@dataset_check("hotel")
def check_hotel(questions, *, known_ids, data):
    """ホテルの質問に固有の確かめ（条件・答えの数・evidence）。

    - condition：種類 condition の質問には condition が要る。形（項目・演算・値の種類）が正しいこと。
      ホテルのデータがあるときは、answer_ids が「データのうち条件に合うホテル」と同じ集合で、1〜20 件であること
      （種類が condition でなくても、condition があれば同じ）
    - 答えの数：condition でない質問の answer_ids は 5 件まで
    - evidence：condition でない質問は、answer_ids のホテルごとに、そのホテルのデータにそのまま出る語句（または語句の並び）。
      ホテルのデータがあるときは、語句が hotel_texts にあること。ja-en は、質問の言語の項目にはなく、もう一方の言語の項目にだけある
      語句が、ホテルごとに 1 つ以上あること
    data はホテルの並び。None（validate を data なしで呼んだ）のときは、データを使う確かめ（condition の結果、語句の検索、ja-en の言語）は飛ばす。
    """
    hotels = _hotels(data)
    texts = {}
    problems = []
    for index, q in enumerate(questions, 1):
        who = label(q, index)
        answers = _strs(q.get("answer_ids"))
        has_condition = "condition" in q or q.get("type") == "condition"
        if not has_condition and len(answers) > HOTEL_MAX_ANSWERS:
            problems.append(f"{who}：{q.get('type')} の質問の answer_ids は {HOTEL_MAX_ANSWERS} 件までです（今は {len(answers)} 件。"
                            "多くのホテルが当てはまる質問は、条件（condition）にするか、絞り込みます）")
        problems += _check_hotel_condition(who, q, answers, hotels)
        problems += _check_hotel_evidence(who, q, answers, hotels, texts)
    return problems
