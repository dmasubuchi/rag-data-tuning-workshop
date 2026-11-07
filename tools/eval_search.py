"""検索の方式を、質問のセットで測る（検索して採点する。標準ライブラリだけ）。

質問ごとに、キーワード（keyword）・ベクトル（vector）・ハイブリッド（hybrid）・セマンティック（semantic。ハイブリッド＋
セマンティック ランカー）で AI Search を検索し、正解の文書が上位 k 件に入ったかを、文書の単位で採点します。
質問に condition（ホテルの条件）があれば、各方式に絞り込みを足した <方式>+filter も測ります。
人事は、聞く人（質問の as_role。なければ role:recruiter）に見える分だけに絞って検索し、その人に見えてはいけない文書が
上位 k 件に出た数（漏れ）を数えます。漏れた質問の割合は、漏れうる質問（聞く人が採用担当でない、または hidden_ids がある質問）の
数で割ります。結果（問ごとの漏れた文書の ID も）と、使った量（検索・セマンティック・埋め込みの回数）は JSON に書きます（費用は別の道具で）。

使い方（Repo 直下で）：
  python tools/eval_search.py --dataset hr
  python tools/eval_search.py --dataset sengoku --methods keyword,hybrid --k 10 --limit 12
  python tools/eval_search.py --dataset hotel --hotel-data <ホテルのデータの JSON>
  --methods     測る方式（既定は4つ全部）。<方式>+filter は、質問の condition から自動で足す
  --k           上位何件で採点するか（既定 10。1〜50）。検索で取る件数は k によらず 50 で、文書にまとめてから上位 k 件を採点する
                （k を変えて比べても、取る範囲は同じ）
  --limit N     先頭の N 問だけ
  --file PATH   質問のファイルを変える
  --hotel-data  ホテルのデータの JSON。渡す（か _work/hotel-vectors/ に置く）と、質問の正解の ID がデータにあるかを先に確かめる
  --out DIR     結果の置き場所（既定 _work/eval。Git に入らない）
  --quiet       進み具合を出さず、最後のまとめだけ

接続先とキーは Repo 直下の .env.local（メンバーの検索だけのキーでよい。読むだけで、何も作らない・変えない）。
質問の埋め込みは、.env.local の埋め込みのデプロイで、質問ごとに1回だけ頼みます。
設定ファイルは、環境変数 WORKSHOP_ENV_FILE で別のものを指せる（試験用）。端末の AZURE_* の環境変数は読まない。

飛ばす・止まる：
  ・インデックスがない（404）・検索が通らない（400。セマンティックの設定がないときは、そう案内する）：その方式だけ飛ばして理由を出し、ほかの方式は最後まで測る
  ・キーが合わない（401・403）・セマンティック ランカーの無料枠の使い切り（403）・つながらない：止まって案内し、そこまでの結果は保存する

終了コード：0 = 測れた／1 = 止まった（設定・キー・つながらない。そこまでの結果は保存）か、測れた方式がなかった／2 = 質問・データ・引数が使えない
"""
import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evallib import metrics
from evallib.datasets import SPECS, Visibility, base_filter, combine, doc_kinds_of, leakable, role_of
from evallib.methods import FILTER_SUFFIX, METHODS, build_request, documents_in_order, needs_vector, split_name
from evallib.questions import (DATA_FILES, DATASETS, QUESTION_FILES, REPO_DIR, DataError, condition_to_filter, ids_of,
                               load_data, load_questions)
from evallib.rest import RestError, embed, search
from evallib.settings import ENV_HOWTO, SettingsError, load_settings

OUT_DIR = REPO_DIR / "_work" / "eval"
MAX_K = 50                # --k の上限（1回の検索で取る件数 FETCH と同じ）
FREE_TIER_HINT = ("エラー 403：キーが合っているか、セマンティック ランカーの無料枠（月ごと。チームの AI Search 全体で使う）を"
                  "使い切っていないかを確かめます。")


class Stop(Exception):
    """測るのをやめる理由（利用者に見せる日本語）。そこまでの結果は保存する。"""


# ------------------------------------------------------------------ 質問を整える

def prepare(dataset, questions, known_ids):
    """質問の形を最低限確かめ、各質問に絞り込みの式（condition から）を足して返す。使えなければ DataError。"""
    prepared = []
    for index, q in enumerate(questions, start=1):
        if not (isinstance(q, dict) and isinstance(q.get("qid"), str) and isinstance(q.get("question"), str) and q["question"].strip()
                and isinstance(q.get("answer_ids"), list) and isinstance(q.get("hidden_ids", []), list)):
            raise DataError(f"{index} 番目の質問の形が違います（qid・question・answer_ids が要ります）。"
                            f"`python tools/check_questions.py --dataset {dataset.name}` で確かめます")
        base_filter(dataset, q)              # as_role の形を確かめる（人事だけ。形が違えば DataError）
        condition_filter = None
        if dataset.supports_condition and q.get("condition"):
            try:
                condition_filter = condition_to_filter(q["condition"])
            except ValueError as error:
                raise DataError(f"{q['qid']} の condition が使えません：{error}") from None
        if known_ids is not None:
            unknown = [str(i) for i in list(q["answer_ids"]) + list(q.get("hidden_ids", [])) if str(i) not in known_ids]
            if unknown:
                raise DataError(f"{q['qid']} の文書の ID がデータにありません：{'、'.join(unknown[:5])}"
                                f"（`python tools/check_questions.py --dataset {dataset.name}` で確かめます）")
        prepared.append({**q, "answer_ids": [str(i) for i in q["answer_ids"]], "hidden_ids": [str(i) for i in q.get("hidden_ids", [])],
                         "_condition_filter": condition_filter})
    return prepared


def parse_methods(text):
    names = [m.strip() for m in text.split(",") if m.strip()]
    unknown = [m for m in names if m not in METHODS]
    if unknown or not names:
        hint = "（絞り込みの方式 +filter は、質問の condition から自動で足します）" if any(FILTER_SUFFIX in m for m in unknown) else ""
        raise DataError(f"--methods は {'・'.join(METHODS)} から選びます（今は {text!r}）{hint}")
    return [m for m in METHODS if m in names]


# ------------------------------------------------------------------ 失敗の言い方

def server_message(detail, limit=160):
    """サービスの答えの文（JSON なら error.message）を、1行にして短くする。"""
    text = detail or ""
    try:
        text = json.loads(text)["error"]["message"] or text
    except (ValueError, KeyError, TypeError):
        pass
    return " ".join(str(text).split())[:limit]


SEMANTIC_WORDS = ("semantic", "セマンティック")


def bad_request_reason(semantic, config, detail):
    """検索が 400 になった方式を飛ばす理由。セマンティックの方式でも、サービスの答えの文に semantic・セマンティックが
    入るときだけ「設定がありません」と言う（ほかの 400 を、設定のせいにしない）。"""
    if semantic and any(word.lower() in detail.lower() for word in SEMANTIC_WORDS):
        return f"セマンティックの設定（{config}）がありません（エラー 400：{detail}）"
    return f"この方式は飛ばしました（HTTP 400：{detail}）"


def stop_text(error, *, semantic=False, embedding=False):
    if error.status is None:
        return f"つながりません：{error.detail}"
    if error.status == 403 and semantic:
        return FREE_TIER_HINT
    if error.status in (401, 403):
        return f"エラー {error.status}：キーが合いません。{ENV_HOWTO}"
    if error.status == 404 and embedding:
        return "エラー 404：埋め込みのデプロイが見つかりません（.env.local の AZURE_OPENAI_EMBEDDING_DEPLOYMENT）"
    return f"エラー {error.status}：{server_message(error.detail)}"


# ------------------------------------------------------------------ 測る

class Run:
    def __init__(self, dataset, questions, methods, k, settings, visibility, say):
        self.dataset, self.questions, self.k = dataset, questions, k
        self.settings, self.visibility, self.say = settings, visibility, say
        self.names = list(methods)
        if dataset.supports_condition and any(q["_condition_filter"] for q in questions):
            self.names += [m + FILTER_SUFFIX for m in methods]
        self.skipped, self.units = {}, {"search": 0, "semantic": 0, "embedding_tokens": 0}
        self.results = []

    def skip(self, names, reason):
        """方式を飛ばす（理由を1回だけ出す）。飛ばしたものは、あとの質問でも検索しない。"""
        new = [n for n in names if n in self.names and n not in self.skipped]
        for n in new:
            self.skipped[n] = reason
        if new:
            self.say(f"飛ばす  {'・'.join(new)}：{reason}")

    def skip_index(self, index, reason):
        self.skip([n for n in self.names if self.dataset.setups[split_name(n)[0]].index == index], reason)

    def embed(self, text):
        try:
            vector, tokens = embed(self.settings, text)
        except RestError as error:
            raise Stop(stop_text(error, embedding=True)) from None
        self.units["embedding_tokens"] += tokens
        return vector

    def search(self, q, name, vector):
        """1問・1方式を検索して、結果（点つき）を返す。飛ばしたときは None。"""
        base, filtered = split_name(name)
        setup = self.dataset.setups[base]
        filter_text = base_filter(self.dataset, q)
        if filtered:
            filter_text = combine(filter_text, q["_condition_filter"])
        request = build_request(self.dataset, base, q["question"], vector, filter_text)
        try:
            response = search(self.settings, request.index, request.body)
        except RestError as error:
            detail = server_message(error.detail)
            if error.status == 404:
                self.skip_index(request.index, f"インデックス {request.index} がありません（まだ作っていません）")
            elif error.status == 400 and filtered:
                self.skip([name], f"絞り込みが通りません（エラー 400：{detail}）")
            elif error.status == 400:
                self.skip([name, name + FILTER_SUFFIX], bad_request_reason(request.semantic, setup.semantic_config, detail))
            else:
                raise Stop(stop_text(error, semantic=request.semantic)) from None
            return None
        self.units["search"] += 1
        self.units["semantic"] += 1 if request.semantic else 0
        ranked = documents_in_order(self.dataset, response)
        leaked = self.visibility.leaked_docs(role_of(self.dataset, q), q.get("hidden_ids"), ranked[:self.k])
        return {"ranked": ranked, **metrics.score(ranked, q["answer_ids"], self.k), "leaks": len(leaked), "leaked": leaked}

    def question(self, q):
        entry = {"qid": q["qid"], "type": q.get("type"), "leakable": leakable(self.dataset, q), "results": {}}
        self.results.append(entry)
        vector = None
        try:
            for name in self.names:
                base, filtered = split_name(name)
                if (filtered and not q["_condition_filter"]) or name in self.skipped:
                    continue
                if needs_vector(self.dataset, base) and vector is None:
                    vector = self.embed(q["question"])
                result = self.search(q, name, vector)
                if result is not None:
                    entry["results"][name] = result
        finally:
            self.say(progress_line(entry, self.k, bool(q["answer_ids"])))     # 途中で止まっても、そこまでの分を出す

    def go(self):
        """全部の質問を測る。止まった理由（なければ None）を返す。"""
        try:
            for q in self.questions:
                self.question(q)
        except Stop as stop:
            return str(stop)
        except KeyboardInterrupt:
            return "途中で止めました（Ctrl+C）"
        return None


def progress_line(entry, k, scored):
    """1問1行。正解のある質問は nDCG、正解のない質問（権限）は漏れの数。漏れがあれば、その方式を添える。"""
    results = entry["results"]
    if not results:
        return f"[{entry['qid']}] 測れた方式がありません"
    if scored:
        label, values = f"nDCG@{k}", {m: "-" if r["ndcg"] is None else f"{r['ndcg']:.2f}" for m, r in results.items()}
    else:
        label, values = "漏れ", {m: str(r["leaks"]) for m, r in results.items()}
    line = f"[{entry['qid']}] {label}  " + "  ".join(f"{m} {v}" for m, v in values.items())
    leaked = [f"{m} {r['leaks']}" for m, r in results.items() if r["leaks"] and scored]
    return line + (f"  漏れ {'・'.join(leaked)}" if leaked else "")


# ------------------------------------------------------------------ まとめと保存

def leak_text(s):
    """方式の行の最後の、漏れの数え方。割合は、漏れうる質問（権限の質問）の数で割る。"""
    if not s["leakable"]:
        return "漏れ：権限の質問がありません"
    return f"漏れ {s['leak_questions']}/{s['leakable']}問（{metrics.leak_rate(s) * 100:.0f}%、権限の問）・文書 {s['leaks']}件"


def summary_lines(result, dataset, k):
    questions, lines = result["questions"], []
    no_answer = sum(1 for q in questions if q["results"] and all(r["ndcg"] is None for r in q["results"].values()))
    lines.append(f"方式ごとの平均（nDCG・再現率は上位 {k} 件、文書の単位）")
    for name in result["methods"]:
        if name in result["skipped"]:
            lines.append(f"  {name:<16}飛ばしました：{result['skipped'][name]}")
            continue
        s = metrics.summarize(questions, name)
        if not s["questions"]:
            lines.append(f"  {name:<16}測っていません")
            continue
        text = f"  {name:<16}"
        if s["scored"]:
            text += f"nDCG {s['ndcg']:.2f}  再現率 {s['recall']:.2f}  1位 {s['hit1'] * 100:.0f}%  （{s['scored']}問）"
        else:
            text += "正解のある質問がありません"
        if dataset.permission:
            text += "  " + leak_text(s)
        lines.append(text)
    if no_answer:
        lines.append(f"  正解の文書がない質問（{no_answer}問）は、平均に入れていません。見えてはいけない文書が出た数（漏れ）で数えます。")
    return lines


def usage_line(units):
    return (f"使った量：検索 {units['search']} 回（うちセマンティック ランカー {units['semantic']} 回）、"
            f"質問の埋め込み {units['embedding_tokens']} トークン")


def result_json(result) -> str:
    """結果の JSON の文字。上の階層は1項目1行、質問は1問1行（読んで・差分を見やすいように）。"""
    head = {key: result[key] for key in ("dataset", "started", "k", "methods", "skipped", "units", "stopped")}
    lines = [json.dumps({key: value}, ensure_ascii=False, separators=(",", ":"))[1:-1] for key, value in head.items()]
    questions = ",\n".join(" " + json.dumps(q, ensure_ascii=False, separators=(",", ":")) for q in result["questions"])
    return "{\n" + ",\n".join(lines) + f',\n"questions":[\n{questions}\n]\n}}\n'


def write_result(result, out_dir, started):
    """結果を <データ>-<開始の時刻>.json に書く。同じ名前がすでにあれば（同じ秒に2つ始めたとき）、上書きせず -2・-3 を付ける。"""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem, text = f"{result['dataset']}-{started:%Y%m%dT%H%M%SZ}", result_json(result)
    for number in itertools.count(1):
        path = folder / (f"{stem}.json" if number == 1 else f"{stem}-{number}.json")
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as file:      # なければ作る形で開く（あれば FileExistsError）
                file.write(text)
        except FileExistsError:
            continue
        return path


def shown(path):
    try:
        return str(Path(path).resolve().relative_to(REPO_DIR))
    except ValueError:
        return str(path)


# ------------------------------------------------------------------ 入口

def load_known(dataset_name, hotel_data):
    """(文書の ID の集合 or None, 文書の種類 {ID: 種類})。ホテルのデータは、渡した（か既定の場所にある）ときだけ読む。"""
    if dataset_name == "hotel" and not hotel_data and not DATA_FILES["hotel"].exists():
        return None, {}
    data = load_data(dataset_name, hotel_data)
    return ids_of(dataset_name, data), (doc_kinds_of(data) if dataset_name == "hr" else {})


def build_parser():
    parser = argparse.ArgumentParser(description="検索の方式を、質問のセットで測る（検索して採点する）")
    parser.add_argument("--dataset", required=True, choices=DATASETS, help="測るデータ")
    parser.add_argument("--methods", default=",".join(METHODS), help="測る方式（カンマ区切り。既定は4つ全部）")
    parser.add_argument("--k", type=int, default=10, help="上位何件で採点するか（既定 10）")
    parser.add_argument("--limit", type=int, help="先頭の N 問だけ測る")
    parser.add_argument("--file", type=Path, help="質問のファイル（省くと、データごとの既定の場所）")
    parser.add_argument("--hotel-data", type=Path, help="ホテルのデータの JSON（--dataset hotel のときだけ）")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="結果の置き場所（既定 _work/eval）")
    parser.add_argument("--quiet", action="store_true", help="進み具合を出さず、最後のまとめだけ")
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    dataset = SPECS[args.dataset]
    try:
        if args.hotel_data and args.dataset != "hotel":
            raise DataError("--hotel-data は --dataset hotel のときだけ使えます。")
        if not 1 <= args.k <= MAX_K:
            raise DataError(f"--k は 1〜{MAX_K} で書きます（今は {args.k}）。")
        if args.limit is not None and args.limit < 1:
            raise DataError(f"--limit は 1 以上で書きます（今は {args.limit}）。")
        methods = parse_methods(args.methods)
        questions = load_questions(args.file or QUESTION_FILES[args.dataset])
        known_ids, doc_kinds = load_known(args.dataset, args.hotel_data)
        questions = prepare(dataset, questions[:args.limit] if args.limit else questions, known_ids)
    except DataError as error:
        print(f"NG    {error}", file=sys.stderr)
        return 2
    if not questions:
        print("NG    質問が0問です。", file=sys.stderr)
        return 2
    try:
        settings = load_settings(need_embedding=any(needs_vector(dataset, m) for m in methods))
    except SettingsError as error:
        print(f"NG    {error}")
        return 1
    say = (lambda text: None) if args.quiet else print
    started = datetime.now(timezone.utc).replace(microsecond=0)
    run = Run(dataset, questions, methods, args.k, settings, Visibility(doc_kinds), say)
    say(f"評価：{args.dataset}（質問 {len(questions)} 問、上位 {args.k} 件で採点）")
    say("方式：" + "・".join(run.names) + ("（condition のある質問は、各方式に絞り込みを足した +filter も測る）"
                                           if len(run.names) > len(methods) else ""))
    stopped = run.go()
    result = {"dataset": args.dataset, "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "k": args.k, "methods": run.names,
              "skipped": run.skipped, "questions": run.results, "units": run.units, "stopped": stopped}
    path = write_result(result, args.out, started)
    if stopped:
        print(f"NG    止まりました：{stopped}")
        print(f"      ここまでの結果は {shown(path)} に保存しました。")
    print()
    for line in summary_lines(result, dataset, args.k):
        print(line)
    print(usage_line(run.units))
    print(f"結果：{shown(path)}")
    if stopped:
        return 1
    if not any(q["results"] for q in run.results):
        print("NG    測れた方式がありませんでした。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
