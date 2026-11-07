"""評価の結果（tools/eval_search.py が書いた JSON）を、比べやすい表にまとめる（標準ライブラリだけ。通信しない）。

出す表は2つ。
  方式ごと        質問の数・nDCG@k・再現率@k・1位の割合・（人事は）漏れ・検索の回数・セマンティックの回数・埋め込みのトークン・費用の見込み
  方式×質問の種類  質問の種類ごとの nDCG@k の平均（カッコは問の数）

使い方（Repo 直下で）：
  python tools/eval_report.py _work/eval/hr-20261107T010203Z.json
  python tools/eval_report.py _work/eval/hr-A.json _work/eval/hr-B.json --label 直す前 --label 直した後
  python tools/eval_report.py _work/eval/hr-*.json --prices config/prices.json --md _work/eval/report.md
  結果の JSON   1つ以上。複数を渡すと、同じ表の中で横に並べる（同じデータの結果だけ。違えば止める）
  --label       並べる結果の名前（結果の数だけ、渡した順に。省くと、結果のファイルの名前）
  --prices      単価のファイル（既定は config/prices.json。config/prices.example.json が見本）
  --md OUT      Markdown の表を OUT に書く（画面にも出す）

費用の見込み＝回数×単価（tools/evallib/cost.py）。単価は、料金のページで確かめた値を config/prices.json に写して書く。
ファイルがない・値が空のときは、回数だけ出して「単価が未設定」と書く（金額は作らない・0 円とも書かない）。

終了コード：0 = 出せた／1 = Markdown が書けない／2 = 結果・単価のファイル・引数が使えない
"""
import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from evallib import cost, metrics
from evallib.datasets import SPECS
from evallib.methods import METHODS, split_name
from evallib.questions import REPO_DIR

NO_TYPE = "（種類なし）"
ALL_ROW = "全体"
SKIPPED = "飛ばした"
UNSET = "単価が未設定"
MARK = "＊"                       # 一部の単価が未設定のとき、金額に付ける印（全角なので、端末で幅がぶれない。Markdown の * とも紛れない）
EMBEDDING_ROW = "埋め込み（共通）"
TOTAL_ROW = "合計"
PRICE_ORDER = ("semantic", "embedding", "search")       # 単価の行に出す順（単価のファイルの並び）
UNIT_TEXT = {"search": "1,000 回", "semantic": "1,000 回", "embedding": "100 万トークン"}


class ReportError(Exception):
    """表にできない理由（利用者に見せる日本語）。"""


# ------------------------------------------------------------------ 結果を読む

def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_score(value) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def result_problem(data):
    """結果の JSON が、この道具の読む形でなければ、その理由の文。使えるなら None。"""
    if not isinstance(data, dict):
        return "{ … } の形ではありません"
    for key, kind in (("dataset", str), ("methods", list), ("skipped", dict), ("units", dict), ("questions", list)):
        if not isinstance(data.get(key), kind):
            return f"{key} がありません"
    if not _is_count(data.get("k")) or data["k"] < 1:
        return "k（上位何件で採点したか）がありません"
    if not all(isinstance(m, str) for m in data["methods"]):
        return "methods の形が違います"
    if not all(_is_count(data["units"].get(key)) for key in ("search", "semantic", "embedding_tokens")):
        return "units（検索・semantic・embedding_tokens の回数）の形が違います"
    for index, q in enumerate(data["questions"], start=1):
        if not (isinstance(q, dict) and isinstance(q.get("results"), dict)):
            return f"{index} 番目の質問の形が違います（results がありません）"
        for method, r in q["results"].items():
            if not (isinstance(r, dict) and all(_is_score(r.get(key)) for key in ("ndcg", "recall", "hit1")) and _is_count(r.get("leaks"))):
                return f"{q.get('qid', index)} の {method} の点の形が違います（ndcg・recall・hit1・leaks）"
    return None


def load_result(path) -> dict:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ReportError(f"{path} が読めません（{error.strerror or error}）。") from None
    except ValueError:
        raise ReportError(f"{path.name} が JSON として読めません。tools/eval_search.py が書いた結果のファイルを渡します。") from None
    problem = result_problem(data)
    if problem:
        raise ReportError(f"{path.name} は、評価の結果の形ではありません：{problem}。tools/eval_search.py が書いた結果のファイルを渡します。")
    return data


@dataclass
class Run:
    label: str
    file: str               # 結果のファイルの名前（Markdown にはパスを書かない）
    data: dict

    @property
    def questions(self):
        return self.data["questions"]

    @property
    def k(self):
        return self.data["k"]


def load_runs(paths, labels) -> list:
    if labels and len(labels) != len(paths):
        raise ReportError(f"--label は結果の数（{len(paths)}）だけ、結果と同じ順に書きます（今は {len(labels)} 個）。")
    runs = []
    for index, path in enumerate(paths):
        runs.append(Run(labels[index].strip() if labels else Path(path).stem, Path(path).name, load_result(path)))
    if any(not run.label for run in runs):
        raise ReportError("--label が空です。")
    dup = sorted({run.label for run in runs if [r.label for r in runs].count(run.label) > 1})
    if dup:
        raise ReportError(f"並べる結果の名前が重なっています：{'・'.join(dup)}。--label で分けます。")
    datasets = {run.data["dataset"] for run in runs}
    if len(datasets) > 1:
        detail = "、".join(f"{run.label} は {run.data['dataset']}" for run in runs)
        raise ReportError(f"違うデータの結果は並べられません（{detail}）。同じデータの結果だけを渡します。")
    return runs


# ------------------------------------------------------------------ 表の部品

@dataclass
class Column:
    header: str
    group: str = None       # 結果の名前（複数の結果を横に並べるとき）
    align: str = "r"


@dataclass
class Table:
    columns: list
    rows: list


def display_width(text) -> int:
    """端末での幅。全角（東アジアの W・F）は 2、結合文字は 0。"""
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text, width, align) -> str:
    gap = " " * max(width - display_width(text), 0)
    return gap + text if align == "r" else text + gap


def render_text(table) -> list:
    """等幅の表。結果が複数のときは、1行目に結果の名前（その結果の列の上）を出す。"""
    cols = table.columns
    widths = [max([display_width(c.header)] + [display_width(row[i]) for row in table.rows]) for i, c in enumerate(cols)]
    spans, start = [], 0                    # 結果ごとの列の範囲 (始め, 終わり)
    for i in range(1, len(cols) + 1):
        if i == len(cols) or cols[i].group != cols[start].group:
            if cols[start].group is not None:
                spans.append((start, i))
            start = i

    def joiner(i):
        return "" if i == 0 else " | " if cols[i].group != cols[i - 1].group else "  "

    for begin, end in spans:                # 名前が列より長ければ、最後の列を広げる
        have = sum(widths[begin:end]) + 2 * (end - begin - 1)
        need = display_width(cols[begin].group)
        if need > have:
            widths[end - 1] += need - have

    def line(cells):
        return "".join(joiner(i) + pad(cell, widths[i], cols[i].align) for i, cell in enumerate(cells)).rstrip()

    out = []
    if spans:
        parts, i = [], 0
        while i < len(cols):
            span = next((s for s in spans if s[0] == i), None)
            if span:
                total = sum(widths[span[0]:span[1]]) + 2 * (span[1] - span[0] - 1)
                parts.append(joiner(i) + pad(cols[i].group, total, "l"))
                i = span[1]
            else:
                parts.append(joiner(i) + " " * widths[i])
                i += 1
        out.append("".join(parts).rstrip())
    header = line([c.header for c in cols])
    out += [header, "-" * max(display_width(x) for x in out + [header])] + [line(row) for row in table.rows]
    return out


def md_cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(table) -> list:
    heads = [f"{c.group}: {c.header}" if c.group else c.header for c in table.columns]
    lines = ["| " + " | ".join(md_cell(h) for h in heads) + " |",
             "| " + " | ".join("---:" if c.align == "r" else "---" for c in table.columns) + " |"]
    lines += ["| " + " | ".join(md_cell(cell) for cell in row) + " |" for row in table.rows]
    return lines


# ------------------------------------------------------------------ 表1：方式ごと

def ordered_methods(runs) -> list:
    """全部の結果に出てくる方式。決まった順（keyword・vector・hybrid・semantic、そのあとに +filter）。"""
    names = []
    for run in runs:
        names += [m for m in run.data["methods"] if m not in names]

    def key(name):
        base, filtered = split_name(name)
        return (filtered, METHODS.index(base) if base in METHODS else len(METHODS), name)

    return sorted(names, key=key)


def method_units(run, name) -> dict:
    """1つの方式の使った量。結果にその方式の答えがある数＝成功した検索の回数（セマンティックの方式は、すべてセマンティック）。"""
    searches = sum(1 for q in run.questions if name in q["results"])
    return {"search": searches, "semantic": searches if split_name(name)[0] == "semantic" else 0}


def percent(value) -> str:
    return f"{value * 100:.0f}%"


@dataclass
class Notes:
    """表を作りながら集める、表の下に書くこと。"""
    unset: set = field(default_factory=set)       # 回数があるのに単価が未設定で、金額に入れなかった項目
    partial: set = field(default_factory=set)     # 一部の単価が未設定の金額に、足した項目
    has_partial: bool = False


class Report:
    def __init__(self, runs, prices, prices_label):
        self.runs, self.prices, self.prices_label = runs, prices, prices_label
        self.dataset = runs[0].data["dataset"]
        self.multi = len(runs) > 1
        self.methods = ordered_methods(runs)
        spec = SPECS.get(self.dataset)
        self.show_leaks = bool(spec and spec.permission) or any(
            r.get("leaks", 0) for run in runs for q in run.questions for r in q["results"].values())
        self.notes = Notes()

    def group(self, run):
        return run.label if self.multi else None

    # ---- 費用

    def cost_cell(self, parts, **units) -> str:
        est = cost.estimate(self.prices, parts=parts, **units)
        if est.complete:
            return cost.format_amount(est.amount, self.prices.currency)
        if est.partial:
            self.notes.has_partial = True
            self.notes.partial.update(est.added)
            self.notes.unset.update(est.unset)
            return cost.format_amount(est.amount, self.prices.currency) + MARK
        if est.unset:
            self.notes.unset.update(est.unset)
            return UNSET
        return "-"

    # ---- 表1

    def method_table(self) -> Table:
        columns = [Column("方式", None, "l")]
        for run in self.runs:
            g, k = self.group(run), run.k
            columns += [Column("問", g), Column(f"nDCG@{k}", g), Column(f"再現率@{k}", g), Column("1位", g)]
            if self.show_leaks:
                columns += [Column("漏れ問", g), Column("漏れ文書", g)]
            columns += [Column("検索", g), Column("セマンティック", g), Column("埋め込みトークン", g), Column("費用の見込み", g)]
        rows = [[name] + [cell for run in self.runs for cell in self.method_cells(run, name)] for name in self.methods]
        if any(run.data["units"]["embedding_tokens"] for run in self.runs):
            rows.append([EMBEDDING_ROW] + [cell for run in self.runs for cell in self.embedding_cells(run)])
        rows.append([TOTAL_ROW] + [cell for run in self.runs for cell in self.total_cells(run)])
        return Table(columns, rows)

    def quality_cells(self, run, name) -> list:
        width = 4 + (2 if self.show_leaks else 0)
        measured = name in run.data["methods"] and any(name in q["results"] for q in run.questions)
        if not measured:
            first = SKIPPED if name in run.data["skipped"] else "-"
            return ["-", first] + ["-"] * (width - 2)
        s = metrics.summarize(run.questions, name)
        count = str(s["scored"]) if s["scored"] == s["questions"] else f"{s['scored']}/{s['questions']}"
        cells = [count] + (["-"] * 3 if not s["scored"] else
                           [f"{s['ndcg']:.2f}", f"{s['recall']:.2f}", percent(s["hit1"])])
        if self.show_leaks:
            cells += [f"{s['leak_questions']}/{s['questions']}", str(s["leaks"])]
        return cells

    def method_cells(self, run, name) -> list:
        quality = self.quality_cells(run, name)
        if name not in run.data["methods"] or not any(name in q["results"] for q in run.questions):
            return quality + ["-", "-", "", "-"]
        units = method_units(run, name)
        # 埋め込みは質問ごとに1回を方式で共用するので、方式の行には入れない（「埋め込み（共通）」の行へ）
        return quality + [f"{units['search']:,}", f"{units['semantic']:,}", "",
                          self.cost_cell(("search", "semantic"), search=units["search"], semantic=units["semantic"])]

    def empty_quality(self) -> list:
        return [""] * (4 + (2 if self.show_leaks else 0))

    def embedding_cells(self, run) -> list:
        tokens = run.data["units"]["embedding_tokens"]
        return self.empty_quality() + ["", "", f"{tokens:,}", self.cost_cell(("embedding",), embedding_tokens=tokens)]

    def total_cells(self, run) -> list:
        u = run.data["units"]
        return self.empty_quality() + [f"{u['search']:,}", f"{u['semantic']:,}", f"{u['embedding_tokens']:,}",
                                       self.cost_cell(cost.PARTS, search=u["search"], semantic=u["semantic"],
                                                      embedding_tokens=u["embedding_tokens"])]

    # ---- 表2

    def types(self) -> list:
        names = []
        for run in self.runs:
            for q in run.questions:
                name = q.get("type") or NO_TYPE
                if name not in names:
                    names.append(name)
        return names

    def type_table(self) -> Table:
        columns = [Column("質問の種類", None, "l")] + [Column(name, self.group(run)) for run in self.runs for name in self.methods]
        rows = []
        for type_name in self.types() + [ALL_ROW]:
            row = [type_name]
            for run in self.runs:
                subset = run.questions if type_name == ALL_ROW else [q for q in run.questions if (q.get("type") or NO_TYPE) == type_name]
                for name in self.methods:
                    s = metrics.summarize(subset, name) if name in run.data["methods"] else None
                    row.append(f"{s['ndcg']:.2f} ({s['scored']})" if s and s["scored"] else "-")
            rows.append(row)
        return Table(columns, rows)

    def type_title(self) -> str:
        ks = [run.k for run in self.runs]
        if len(set(ks)) == 1:
            return f"方式×質問の種類（nDCG@{ks[0]} の平均。カッコは問の数）"
        return "方式×質問の種類（nDCG の平均。カッコは問の数。上位 k 件の k は " + "、".join(f"{r.label} は {r.k}" for r in self.runs) + "）"

    # ---- 表の下に書くこと

    def run_lines(self) -> list:
        lines = []
        for run in self.runs:
            started = run.data.get("started")
            detail = [f"開始 {started}"] if isinstance(started, str) and started else []
            lines.append(f"{run.label}：{run.file}（{'・'.join(detail + [f'上位 {run.k} 件', f'質問 {len(run.questions)} 問'])}）")
        return lines

    def price_lines(self) -> list:
        p = self.prices
        if not p.found:
            return [f"単価のファイル（{self.prices_label}）がありません。回数だけ出し、金額は出しません。"
                    f"config/prices.example.json を {self.prices_label} に写して、料金のページで確かめた値を書きます。"]
        items = []
        for part in PRICE_ORDER:
            price = p.price(part)
            items.append(f"{cost.PART_LABELS[part]} {UNIT_TEXT[part]} {UNSET if price is None else cost.format_amount(price, p.currency)}")
        checked = f"確かめた日 {p.checked}" if p.checked else "確かめた日が書いてありません"
        lines = [f"単価（{p.currency}、{checked}）：" + "、".join(items)]
        if p.sources:
            lines.append("単価の出どころ（料金のページ）：" + "・".join(p.sources))
        return lines

    def cost_notes(self) -> list:
        n, lines = self.notes, []
        if n.has_partial:
            added = "・".join(cost.PART_LABELS[x] for x in cost.PARTS if x in n.partial)
            lines.append(f"{MARK} 一部の単価が未設定です。足したのは {added} だけで、合計ではありません。")
        if n.unset and self.prices.found:
            names = "・".join(f"{cost.PART_LABELS[x]}（{cost.PRICE_FIELDS[x][0]}）" for x in cost.PARTS if x in n.unset)
            lines.append(f"{UNSET}：{names}。{self.prices_label} に、料金のページで確かめた値を書きます（無料なら 0）。")
        return lines

    def table_one_notes(self) -> list:
        lines = []
        for run in self.runs:
            if run.data.get("stopped"):
                lines.append(f"{run.label} は途中で止まった結果です：{run.data['stopped']}")
        for run in self.runs:
            for name, reason in run.data["skipped"].items():
                lines.append(f"飛ばした方式{f'（{run.label}）' if self.multi else ''}：{name}：{reason}")
        lines += self.cost_notes() + self.price_lines()
        lines.append("費用の見込み＝回数×単価（検索は、セマンティックを除いた回数）。埋め込みは方式で共用するので、「埋め込み（共通）」の行に分けます。")
        lines.append("nDCG・再現率・1位は、正解のある質問だけの平均。「問」は、平均に入れた数（測った数が違うときは 平均に入れた数/測った数）。")
        no_answer = [run for run in self.runs if any(q["results"] and all(r["ndcg"] is None for r in q["results"].values())
                                                     for q in run.questions)]
        if no_answer:
            lines.append("正解のない質問（人事の権限の質問のうち、見える文書がないもの）は平均に入れず、"
                         "見えてはいけない文書が上位 k 件に出た数（漏れ問・漏れ文書）で数えます。")
        return lines

    def table_two_notes(self) -> list:
        return ["「-」は、正解のない質問だけの種類か、その方式を測っていない種類です。"]


def build_blocks(report) -> list:
    """(題, 表, 表の下の文) の並び。"""
    return [("方式ごと", report.method_table(), report.table_one_notes()),
            (report.type_title(), report.type_table(), report.table_two_notes())]


# ------------------------------------------------------------------ 出力

def text_lines(report, blocks) -> list:
    lines = [f"評価のまとめ：{report.dataset}（結果 {len(report.runs)} 件）"]
    lines += [f"  {line}" for line in report.run_lines()]
    for title, table, notes in blocks:
        lines += ["", title] + render_text(table) + [""] + [f"  {note}" for note in notes]
    return lines


def markdown_lines(report, blocks) -> list:
    lines = [f"# 検索の評価のまとめ：{report.dataset}", "", "## 結果", ""]
    lines += [f"- {line}" for line in report.run_lines()]
    for title, table, notes in blocks:
        lines += ["", f"## {title}", ""] + render_markdown(table) + [""] + [f"- {note}" for note in notes]
    return lines


# ------------------------------------------------------------------ 入口

def shown(path) -> str:
    """画面と Markdown に出す名前。Repo の中なら Repo 直下からの道、そうでなければファイルの名前だけ。"""
    try:
        return str(Path(path).resolve().relative_to(REPO_DIR))
    except ValueError:
        return Path(path).name


def build_parser():
    parser = argparse.ArgumentParser(description="評価の結果の JSON を、方式ごと・質問の種類ごとの表にまとめる（費用の見込みつき）")
    parser.add_argument("results", nargs="+", type=Path, help="tools/eval_search.py が書いた結果の JSON（複数なら横に並べる）")
    parser.add_argument("--label", action="append", help="並べる結果の名前（結果の数だけ、渡した順に）")
    parser.add_argument("--prices", type=Path, default=cost.DEFAULT_PRICES, help="単価のファイル（既定 config/prices.json）")
    parser.add_argument("--md", type=Path, metavar="OUT", help="Markdown の表を書くファイル")
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        runs = load_runs(args.results, args.label)
        prices = cost.load_prices(args.prices)
    except (ReportError, cost.PricesError) as error:
        print(f"NG    {error}", file=sys.stderr)
        return 2
    report = Report(runs, prices, shown(args.prices))
    blocks = build_blocks(report)
    for line in text_lines(report, blocks):
        print(line)
    if args.md:
        try:
            args.md.parent.mkdir(parents=True, exist_ok=True)
            args.md.write_text("\n".join(markdown_lines(report, blocks)) + "\n", encoding="utf-8", newline="\n")
        except OSError as error:
            print(f"NG    Markdown を書けません：{error.strerror or error}", file=sys.stderr)
            return 1
        print(f"\nMarkdown：{shown(args.md)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
