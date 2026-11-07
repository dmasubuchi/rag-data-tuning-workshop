"""tools/eval_report.py（結果の JSON を表にまとめる道具）と tools/evallib/cost.py（単価・費用の見込み）の試験。

結果の JSON は、手で組んだもの（数字をはっきりさせる）と、tools/eval_search.py を偽の HTTP で動かして書かせたもの
（形が合っているか）の両方で作る。本物の Azure・ネットワーク・.env.local・config/prices.json は使わない
（単価は、いつも --prices で試験用のファイルを渡す）。
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))
sys.path.insert(0, str(REPO_DIR / "tests"))

import eval_report  # noqa: E402
import eval_search  # noqa: E402
from evallib import cost  # noqa: E402
from test_eval_search import ALL_METHODS, EvalCase, Fake, chunks  # noqa: E402

BASE = ("keyword", "vector", "hybrid", "semantic")


def scored(ndcg, recall=1.0, hit1=0.0, leaks=0):
    return {"ranked": ["D1"], "ndcg": ndcg, "recall": recall, "hit1": hit1, "first_rank": 1, "leaks": leaks}


def unscored(leaks=0):
    """正解のない質問（権限）の点。nDCG などは None、漏れだけを数える。"""
    return {"ranked": [], "ndcg": None, "recall": None, "hit1": None, "first_rank": None, "leaks": leaks}


def make_result(rows, dataset="hr", k=10, methods=BASE, skipped=None, units=None, stopped=None, started="2026-11-07T01:02:03Z"):
    """rows は (qid, 質問の種類, {方式: 点}) の並び。4つ目に leakable（漏れうる質問か）を書ける（省くと、種類が permission のとき真）。
    units を省くと、答えの数から合わせる（検索・セマンティック）。埋め込みは1問100トークン。"""
    questions = [{"qid": row[0], "type": row[1], "leakable": row[3] if len(row) > 3 else row[1] == "permission", "results": row[2]}
                 for row in rows]
    searches = sum(len(q["results"]) for q in questions)
    semantic = sum(1 for q in questions for name in q["results"] if name.split("+")[0] == "semantic")
    return {"dataset": dataset, "started": started, "k": k, "methods": list(methods), "skipped": skipped or {},
            "units": units or {"search": searches, "semantic": semantic, "embedding_tokens": 100 * len(questions)},
            "stopped": stopped, "questions": questions}


def hr_rows():
    """人事ふうの5問：正解のある3問（paraphrase 2・numeric 1）と、正解のない権限の2問。"""
    def all_methods(*points):
        return dict(zip(BASE, points))
    return [
        ("hr-01", "paraphrase", all_methods(scored(0.5), scored(0.63), scored(1.0, hit1=1.0), scored(1.0, hit1=1.0))),
        ("hr-02", "paraphrase", all_methods(scored(0.0, 0.0), scored(1.0, hit1=1.0), scored(1.0, hit1=1.0), scored(1.0, hit1=1.0))),
        ("hr-03", "numeric", all_methods(scored(1.0, hit1=1.0), scored(0.0, 0.0), scored(0.63), scored(1.0, hit1=1.0))),
        ("hr-04", "permission", all_methods(unscored(2), unscored(1), unscored(0), unscored(0))),
        ("hr-05", "permission", all_methods(unscored(0), unscored(0), unscored(0), unscored(0))),
    ]


def write_prices(directory, **values):
    path = Path(directory) / "prices.json"
    path.write_text(json.dumps({"currency": "JPY", "checked": "2026-11-07", "sources": ["https://example.invalid/prices"],
                                "semantic_per_1000": None, "embedding_per_1m_tokens": None, "search_per_1000": None,
                                "note": "試験用", **values}, ensure_ascii=False), encoding="utf-8")
    return path


def md_tables(text):
    """Markdown を、題 → (見出しの並び, 行の並び) にする（行は {見出し: 値}ではなく、値の並び）。"""
    tables, title, lines = {}, None, []
    for line in text.splitlines() + ["## end"]:
        if line.startswith("## "):
            if title and lines:
                cells = [[c.strip() for c in row.strip().strip("|").split(" | ")] for row in lines]
                tables[title] = (cells[0], cells[2:])
            title, lines = line[3:], []
        elif line.startswith("|"):
            lines.append(line)
    return tables


def method_table(text):
    head, rows = next(v for k, v in md_tables(text).items() if k == "方式ごと")
    return head, {row[0]: dict(zip(head, row)) for row in rows}


class ReportTools:
    """結果のファイルを作り、eval_report.main を動かす道具（self.dir が要る）。"""
    count = 0

    def result_file(self, result, name=None):
        self.count += 1
        path = self.dir / (name or f"result-{self.count}.json")
        path.write_text(eval_search.result_json(result), encoding="utf-8")
        return path

    def report(self, *argv, prices=None):
        """eval_report.main を動かす。(終了コード, 標準出力, 標準エラー, Markdown の文字)。単価は、渡さなければ「ファイルなし」。"""
        md = self.dir / f"report-{self.count}.md"
        args = [str(a) for a in argv]
        if "--prices" not in args:
            args += ["--prices", str(prices or self.dir / "no-such-prices.json")]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = eval_report.main([*args, "--md", str(md)])
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue(), md.read_text(encoding="utf-8") if md.exists() else ""


class ReportCase(ReportTools, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)


# ------------------------------------------------------------------ 単価のファイル

class PricesFileTest(unittest.TestCase):
    def test_example_has_no_values_and_only_the_official_pages(self):
        data = json.loads((REPO_DIR / "config" / "prices.example.json").read_text(encoding="utf-8"))
        self.assertEqual(list(data), ["currency", "checked", "sources", "semantic_per_1000", "embedding_per_1m_tokens",
                                      "search_per_1000", "note"])
        self.assertEqual(data["currency"], "JPY")
        for key in ("checked", "semantic_per_1000", "embedding_per_1m_tokens", "search_per_1000"):
            self.assertIsNone(data[key], key)               # 値を推測で入れない
        self.assertEqual(data["sources"], ["https://azure.microsoft.com/ja-jp/pricing/details/search/",
                                           "https://azure.microsoft.com/ja-jp/pricing/details/cognitive-services/openai-service/"])
        self.assertIn("config/prices.json", data["note"])
        for word in ("Basic の検索は時間課金なので search_per_1000 に 0 と書く", "null のままだと", "＊"):   # 時間課金の検索は 0 と書く（null だと合計に＊が付く）
            self.assertIn(word, data["note"], word)
        loaded = cost.load_prices(REPO_DIR / "config" / "prices.example.json")
        self.assertTrue(loaded.found)
        self.assertEqual(loaded.unset_parts(), list(cost.PARTS))

    def test_real_prices_file_is_ignored_by_git_and_is_the_default(self):
        self.assertEqual(cost.DEFAULT_PRICES, REPO_DIR / "config" / "prices.json")
        lines = (REPO_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("config/prices.json", lines)
        self.assertNotIn("config/prices.example.json", lines)

    def test_missing_file_is_all_unset_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = cost.load_prices(Path(tmp) / "none.json")
        self.assertFalse(loaded.found)
        self.assertEqual(loaded.unset_parts(), list(cost.PARTS))

    def test_values_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = cost.load_prices(write_prices(tmp, semantic_per_1000=500, embedding_per_1m_tokens=0.5, search_per_1000=0))
            self.assertEqual((good.price("semantic"), good.price("embedding"), good.price("search")), (500, 0.5, 0))
            self.assertEqual((good.currency, good.checked), ("JPY", "2026-11-07"))
            for field, bad in (("semantic_per_1000", -1), ("embedding_per_1m_tokens", "20"), ("search_per_1000", True),
                               ("semantic_per_1000", float("nan")), ("search_per_1000", [1])):
                with self.assertRaises(cost.PricesError, msg=(field, bad)):
                    cost.load_prices(write_prices(tmp, **{field: bad}))
            for text in ("{", "[]", '{"semantic_per_1000": 1}', '{"currency": ""}'):
                path = Path(tmp) / "bad.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(cost.PricesError, msg=text):
                    cost.load_prices(path)


class EstimateTest(unittest.TestCase):
    def prices(self, **values):
        with tempfile.TemporaryDirectory() as tmp:
            return cost.load_prices(write_prices(tmp, **values))

    def test_cost_is_units_times_prices(self):
        p = self.prices(semantic_per_1000=500, embedding_per_1m_tokens=20, search_per_1000=100)
        e = cost.estimate(p, search=20, semantic=5, embedding_tokens=50_000)
        # 検索は、セマンティックを除いた 15 回（100×15÷1000 = 1.50）。セマンティック 5 回は 500×5÷1000 = 2.50。埋め込みは 20×50000÷1000000 = 1.00
        self.assertAlmostEqual(e.amount, 1.50 + 2.50 + 1.00)
        self.assertTrue(e.complete)
        self.assertEqual((e.added, e.unset), (("search", "semantic", "embedding"), ()))

    def test_semantic_searches_are_not_counted_twice(self):
        p = self.prices(semantic_per_1000=0, search_per_1000=1000)
        self.assertAlmostEqual(cost.estimate(p, search=10, semantic=10).amount, 0.0)      # 全部セマンティック：検索の単価は掛けない
        self.assertAlmostEqual(cost.estimate(p, search=10, semantic=4).amount, 6.0)

    def test_unset_prices_make_no_amount(self):
        p = self.prices()
        e = cost.estimate(p, search=20, semantic=5, embedding_tokens=100)
        self.assertIsNone(e.amount)
        self.assertEqual(e.unset, ("search", "semantic", "embedding"))
        self.assertFalse(e.complete or e.partial)
        self.assertIsNone(cost.estimate(cost.Prices(), search=1).amount)               # 単価のファイルがないときも同じ

    def test_partial_prices_name_what_was_added(self):
        p = self.prices(embedding_per_1m_tokens=20)
        e = cost.estimate(p, search=20, semantic=5, embedding_tokens=50_000)
        self.assertAlmostEqual(e.amount, 1.0)
        self.assertTrue(e.partial)
        self.assertEqual((e.added, e.unset), (("embedding",), ("search", "semantic")))

    def test_zero_units_need_no_price(self):
        p = self.prices(search_per_1000=100)
        e = cost.estimate(p, search=5, semantic=0, embedding_tokens=0)       # セマンティックも埋め込みも使っていない
        self.assertTrue(e.complete)
        self.assertAlmostEqual(e.amount, 0.5)
        none = cost.estimate(self.prices(), search=0, semantic=0, embedding_tokens=0)
        self.assertEqual((none.amount, none.unset), (None, ()))                  # 何も使っていなければ、金額は作らない

    def test_format_amount(self):
        self.assertEqual(cost.format_amount(2.5, "JPY"), "2.50円")
        self.assertEqual(cost.format_amount(1234.567, "JPY"), "1,234.57円")
        self.assertEqual(cost.format_amount(0.001, "JPY"), "<0.01円")           # 0.00 とは書かない
        self.assertEqual(cost.format_amount(0.0, "JPY"), "0.00円")              # 単価が 0 と書いてあるときだけ
        self.assertEqual(cost.format_amount(3, "USD"), "3.00 USD")


# ------------------------------------------------------------------ 表

class ReportTest(ReportCase):
    def test_missing_prices_show_units_only(self):
        path = self.result_file(make_result(hr_rows(), units={"search": 20, "semantic": 5, "embedding_tokens": 50_000}))
        example = REPO_DIR / "config" / "prices.example.json"
        for label, prices in (("ファイルなし", None), ("値が空の見本", example)):
            with self.subTest(label):
                code, out, err, md = self.report(path, prices=prices)
                self.assertEqual((code, err), (0, ""), out)
                for text in (out, md):
                    self.assertIn("単価が未設定", text)
                    self.assertNotRegex(text, r"\d円", "金額を作らない")
                    self.assertNotIn("0円", text)
                head, rows = method_table(md)
                self.assertEqual(rows["合計"]["検索"], "20")                   # 回数は出す
                self.assertEqual(rows["合計"]["セマンティック"], "5")
                self.assertEqual(rows["合計"]["埋め込みトークン"], "50,000")
                self.assertEqual(rows["semantic"]["検索"], "5")
                for name in (*BASE, "合計", "埋め込み（共通）"):
                    self.assertEqual(rows[name]["費用の見込み"], "単価が未設定", name)
        _, out, _, _ = self.report(path)
        self.assertIn("単価のファイル", out)
        self.assertIn("がありません", out)
        self.assertIn("config/prices.example.json", out)
        _, out, _, _ = self.report(path, prices=example)
        self.assertIn("検索（search_per_1000）", out)               # 値が空の項目の名前を案内する

    def test_cost_uses_units_times_prices(self):
        path = self.result_file(make_result(hr_rows(), units={"search": 20, "semantic": 5, "embedding_tokens": 50_000}))
        prices = write_prices(self.dir, semantic_per_1000=500, embedding_per_1m_tokens=20, search_per_1000=100)
        code, out, err, md = self.report(path, prices=prices)
        self.assertEqual((code, err), (0, ""), out)
        head, rows = method_table(md)
        cost_of = {name: row["費用の見込み"] for name, row in rows.items()}
        self.assertEqual(cost_of, {"keyword": "0.50円", "vector": "0.50円", "hybrid": "0.50円", "semantic": "2.50円",
                                   "埋め込み（共通）": "1.00円", "合計": "5.00円"})
        self.assertEqual(rows["埋め込み（共通）"]["埋め込みトークン"], "50,000")
        # 方式の行と、埋め込みの行を足すと、合計になる（セマンティックの検索を、検索の単価で重ねて数えていない）
        self.assertAlmostEqual(sum(float(cost_of[n][:-1]) for n in (*BASE, "埋め込み（共通）")), float(cost_of["合計"][:-1]))
        self.assertNotIn("＊", md)
        self.assertNotIn("単価が未設定", md)
        self.assertIn("確かめた日 2026-11-07", md)
        self.assertIn("https://example.invalid/prices", md)         # 単価の出どころ
        self.assertIn("0.50円", out)

    def test_explicit_zero_prices_give_zero_amounts(self):
        path = self.result_file(make_result(hr_rows(), units={"search": 20, "semantic": 5, "embedding_tokens": 50_000}))
        prices = write_prices(self.dir, semantic_per_1000=0, embedding_per_1m_tokens=0, search_per_1000=0)
        _, _, _, md = self.report(path, prices=prices)
        _, rows = method_table(md)
        self.assertEqual(rows["合計"]["費用の見込み"], "0.00円")            # 単価が 0 と書いてあるので、0 円
        self.assertNotIn("単価が未設定", md)

    def test_partial_prices_name_what_was_added(self):
        path = self.result_file(make_result(hr_rows(), units={"search": 20, "semantic": 5, "embedding_tokens": 50_000}))
        prices = write_prices(self.dir, embedding_per_1m_tokens=20)
        _, out, _, md = self.report(path, prices=prices)
        _, rows = method_table(md)
        self.assertEqual(rows["埋め込み（共通）"]["費用の見込み"], "1.00円")
        self.assertEqual(rows["合計"]["費用の見込み"], "1.00円＊")            # 合計ではなく、足せたものだけ
        self.assertEqual(rows["keyword"]["費用の見込み"], "単価が未設定")
        for text in (out, md):
            self.assertIn("足したのは 埋め込み だけ", text)
            self.assertIn("合計ではありません", text)
            self.assertIn("検索（search_per_1000）", text)
            self.assertIn("セマンティック（semantic_per_1000）", text)

    def test_type_table_has_every_type_and_method(self):
        filtered = [m + "+filter" for m in BASE]

        def row(qid, kind, plain, with_filter=None):
            results = {m: scored(v) for m, v in zip(BASE, plain)}
            if with_filter:
                results.update({m: scored(v) for m, v in zip(filtered, with_filter)})
            return qid, kind, results

        rows = [row("h1", "paraphrase", (0.4, 0.8, 1.0, 1.0)),
                row("h2", "condition", (0.0, 0.5, 0.5, 1.0), (1.0, 1.0, 1.0, 1.0)),
                row("h3", "condition", (1.0, 0.0, 0.5, 1.0), (1.0, 1.0, 0.0, 1.0)),
                row("h4", "paraphrase", (0.6, 0.2, 0.0, 0.0)),
                row("h5", None, (0.2, 0.2, 0.2, 0.2)),
                row("h6", "ja-en", (0.0, 0.0, 0.0, 0.0))]
        path = self.result_file(make_result(rows, dataset="hotel", methods=(*BASE, *filtered)))
        code, out, err, md = self.report(path)
        self.assertEqual((code, err), (0, ""), out)
        title = next(t for t in md_tables(md) if t.startswith("方式×質問の種類"))
        self.assertIn("nDCG@10", title)
        head, body = md_tables(md)[title]
        self.assertEqual(head, ["質問の種類", *BASE, *filtered])            # 方式は全部。+filter は、基本の4つのあと
        self.assertEqual([r[0] for r in body], ["paraphrase", "condition", "（種類なし）", "ja-en", "全体"])   # 質問のある種類は全部（出てきた順）
        by_type = {r[0]: dict(zip(head[1:], r[1:])) for r in body}
        self.assertEqual(by_type["paraphrase"]["keyword"], "0.50 (2)")         # (0.4 + 0.6) / 2
        self.assertEqual(by_type["paraphrase"]["semantic"], "0.50 (2)")
        self.assertEqual(by_type["condition"]["keyword"], "0.50 (2)")
        self.assertEqual(by_type["condition"]["keyword+filter"], "1.00 (2)")
        self.assertEqual(by_type["condition"]["hybrid+filter"], "0.50 (2)")
        self.assertEqual(by_type["paraphrase"]["keyword+filter"], "-")         # condition のない種類に、絞り込みの方式はない
        self.assertEqual(by_type["（種類なし）"]["vector"], "0.20 (1)")
        self.assertEqual(by_type["ja-en"]["hybrid"], "0.00 (1)")
        self.assertEqual(by_type["全体"]["keyword"], "0.37 (6)")                # (0.4+0+1+0.6+0.2+0)/6
        # 方式ごとの表の nDCG と、種類の表の「全体」が一致する
        _, rows_by_method = method_table(md)
        for name in (*BASE, *filtered):
            self.assertEqual(f"{float(rows_by_method[name]['nDCG@10']):.2f}", by_type["全体"][name].split()[0], name)
        self.assertEqual(rows_by_method["keyword+filter"]["問"], "2")        # +filter は condition のある質問だけ
        for kind in ("paraphrase", "condition", "ja-en", "（種類なし）"):
            self.assertIn(kind, out)

    def test_questions_without_answers_keep_their_row_and_count_leaks(self):
        path = self.result_file(make_result(hr_rows()))
        _, out, _, md = self.report(path)
        head, rows = method_table(md)
        self.assertIn("漏れ問", head)
        self.assertIn("漏れ文書", head)
        # 割合の分母は、全部の質問（5）でなく、漏れうる質問（権限の2問）
        self.assertEqual((rows["keyword"]["漏れ問"], rows["keyword"]["漏れ文書"]), ("1/2 (50%)", "2"))
        self.assertEqual((rows["hybrid"]["漏れ問"], rows["hybrid"]["漏れ文書"]), ("0/2 (0%)", "0"))
        self.assertIn("漏れうる質問", md)                                # 分母の説明が、表の下にある
        self.assertEqual(rows["keyword"]["問"], "3/5")                    # 平均に入れたのは、正解のある3問
        self.assertEqual(rows["keyword"]["nDCG@10"], "0.50")             # (0.5 + 0 + 1) / 3
        self.assertEqual(rows["keyword"]["再現率@10"], "0.67")
        self.assertEqual(rows["keyword"]["1位"], "33%")
        title = next(t for t in md_tables(md) if t.startswith("方式×質問の種類"))
        by_type = {r[0]: r[1:] for r in md_tables(md)[title][1]}
        self.assertEqual(by_type["permission"], ["-", "-", "-", "-"])         # 行は残し、nDCG は決まらない
        self.assertIn("正解のない質問", md)

    def test_leak_rate_is_over_leakable_questions_and_old_results_still_read(self):
        """漏れの割合は、漏れうる質問で割る。leakable のない古い結果は、測った質問を全部漏れうる質問に数える。"""
        full = {m: unscored(1) for m in BASE}
        rows = [("p1", "permission", dict(full)), ("p2", "permission", dict(full))]
        rows += [(f"n{i}", "numeric", {m: scored(1.0) for m in BASE}) for i in range(1, 11)]
        result = make_result(rows)
        _, out, _, md = self.report(self.result_file(result))
        self.assertEqual(method_table(md)[1]["keyword"]["漏れ問"], "2/2 (100%)")      # 12 問のうち 2 問が漏れ。12 で割らない
        self.assertEqual(method_table(md)[1]["keyword"]["漏れ文書"], "2")
        self.assertIn("2/2 (100%)", out)
        for q in result["questions"]:
            del q["leakable"]
        _, _, _, md = self.report(self.result_file(result))
        self.assertEqual(method_table(md)[1]["keyword"]["漏れ問"], "2/12 (17%)")
        # 漏れうる質問がなければ、割合は出さない
        calm = make_result([("n1", "numeric", {m: scored(1.0) for m in BASE})], dataset="hr")
        self.assertEqual(method_table(self.report(self.result_file(calm))[3])[1]["keyword"]["漏れ問"], "-")

    def test_leakable_must_be_true_or_false(self):
        result = make_result(hr_rows())
        result["questions"][0]["leakable"] = "yes"
        code, _, err, _ = self.report(self.result_file(result))
        self.assertEqual(code, 2)
        self.assertIn("leakable", err)

    def test_leak_columns_only_where_leaks_make_sense(self):
        rows = [("s1", "keyword-wins", {m: scored(1.0) for m in BASE})]
        path = self.result_file(make_result(rows, dataset="sengoku"))
        head, _ = method_table(self.report(path)[3])
        self.assertNotIn("漏れ問", head)
        leaky = [("s1", "keyword-wins", {**{m: scored(1.0) for m in BASE}, "keyword": scored(1.0, leaks=1)})]
        head, _ = method_table(self.report(self.result_file(make_result(leaky, dataset="sengoku")))[3])
        self.assertIn("漏れ問", head)                                      # 漏れがあれば、どのデータでも出す

    def test_two_runs_side_by_side(self):
        before = make_result(hr_rows(), started="2026-11-07T01:02:03Z", units={"search": 20, "semantic": 5, "embedding_tokens": 50_000})
        after = make_result(hr_rows(), started="2026-11-08T01:02:03Z", k=5, units={"search": 20, "semantic": 5, "embedding_tokens": 51_000})
        for q in after["questions"]:
            for point in q["results"].values():
                if point["ndcg"] is not None:
                    point["ndcg"] = min(1.0, point["ndcg"] + 0.25)
        first, second = self.result_file(before, "hr-A.json"), self.result_file(after, "hr-B.json")
        prices = write_prices(self.dir, semantic_per_1000=500, embedding_per_1m_tokens=20, search_per_1000=0)
        code, out, err, md = self.report(first, second, "--label", "直す前", "--label", "直した後", prices=prices)
        self.assertEqual((code, err), (0, ""), out)
        head, rows = method_table(md)
        self.assertEqual(head.count("直す前: nDCG@10"), 1)
        self.assertEqual(head.count("直した後: nDCG@5"), 1)               # k が違えば、見出しの k も結果ごと
        self.assertEqual(head[0], "方式")
        keyword = rows["keyword"]
        self.assertEqual((keyword["直す前: nDCG@10"], keyword["直した後: nDCG@5"]), ("0.50", "0.67"))   # 同じ行に並ぶ
        self.assertEqual(rows["埋め込み（共通）"]["直す前: 埋め込みトークン"], "50,000")
        self.assertEqual(rows["埋め込み（共通）"]["直した後: 埋め込みトークン"], "51,000")
        self.assertEqual(rows["埋め込み（共通）"]["直す前: 費用の見込み"], "1.00円")
        self.assertEqual(rows["埋め込み（共通）"]["直した後: 費用の見込み"], "1.02円")
        title = next(t for t in md_tables(md) if t.startswith("方式×質問の種類"))
        self.assertIn("直す前 は 10", title)
        self.assertIn("直した後 は 5", title)
        type_head, type_rows = md_tables(md)[title]
        self.assertEqual(type_head[1:], [f"{g}: {m}" for g in ("直す前", "直した後") for m in BASE])
        self.assertEqual(dict(zip(type_head, type_rows[0]))["直した後: keyword"], "0.50 (2)")      # paraphrase：(0.75 + 0.25) / 2
        # 画面は、結果の名前を、その結果の列の上に出す（名前の行と見出しの行で、「 | 」の位置が同じ）
        lines = out.splitlines()
        group_line = next(l for l in lines if "直す前" in l and "直した後" in l and "|" in l)
        header_line = lines[lines.index(group_line) + 1]
        self.assertIn("nDCG@10", header_line)
        self.assertIn("nDCG@5", header_line)
        self.assertLess(group_line.index("直す前"), group_line.index("直した後"))

        def bars(line):
            return [eval_report.display_width(line[:i]) for i, c in enumerate(line) if c == "|"]

        self.assertEqual(bars(group_line), bars(header_line))
        self.assertEqual(len(bars(header_line)), 2)

    def test_two_runs_use_the_file_names_as_labels_by_default(self):
        a, b = self.result_file(make_result(hr_rows()), "hr-20261107T010203Z.json"), self.result_file(make_result(hr_rows()), "hr-20261108T010203Z.json")
        code, out, err, md = self.report(a, b)
        self.assertEqual((code, err), (0, ""))
        head, _ = method_table(md)
        self.assertIn("hr-20261107T010203Z: nDCG@10", head)
        self.assertIn("hr-20261108T010203Z: nDCG@10", head)

    def test_runs_must_be_the_same_dataset_with_distinct_labels(self):
        hr = self.result_file(make_result(hr_rows()), "hr.json")
        sengoku = self.result_file(make_result([("s1", "keyword-wins", {m: scored(1.0) for m in BASE})], dataset="sengoku"), "sengoku.json")
        code, out, err, md = self.report(hr, sengoku)
        self.assertEqual((code, out, md), (2, "", ""))
        self.assertIn("違うデータの結果は並べられません", err)
        self.assertIn("hr は hr", err)
        self.assertIn("sengoku は sengoku", err)
        code, _, err, _ = self.report(hr, hr)
        self.assertEqual(code, 2)
        self.assertIn("重なっています", err)
        code, _, err, _ = self.report(hr, hr, "--label", "A")
        self.assertEqual(code, 2)
        self.assertIn("--label は結果の数（2）", err)

    def test_skipped_methods_and_stopped_runs_are_explained_under_the_table(self):
        rows = [(f"h{i}", "paraphrase", {"keyword": scored(1.0), "hybrid": scored(0.5)}) for i in (1, 2)]
        reason = "インデックス hotels-cosmos がありません（まだ作っていません）"
        result = make_result(rows, dataset="hotel", methods=BASE, skipped={"vector": reason, "semantic": "セマンティックの設定がありません"},
                             stopped="エラー 403：キーが合っているか、セマンティック ランカーの無料枠を使い切っていないかを確かめます。")
        code, out, err, md = self.report(self.result_file(result))
        self.assertEqual((code, err), (0, ""))
        _, by_method = method_table(md)
        self.assertEqual(by_method["vector"]["nDCG@10"], "飛ばした")
        self.assertEqual(by_method["semantic"]["nDCG@10"], "飛ばした")
        self.assertEqual(by_method["hybrid"]["nDCG@10"], "0.50")                 # ほかの方式は表に出る
        for text in (out, md):
            self.assertIn(f"飛ばした方式：vector：{reason}", text)
            self.assertIn("途中で止まった結果です：エラー 403", text)

    def test_methods_missing_from_one_run_are_dashes(self):
        a = make_result([("q1", "t", {"keyword": scored(1.0), "hybrid": scored(0.5)})], methods=("keyword", "hybrid"))
        b = make_result([("q1", "t", {"keyword": scored(0.5), "vector": scored(0.25)})], methods=("keyword", "vector"))
        code, out, err, md = self.report(self.result_file(a, "a.json"), self.result_file(b, "b.json"))
        self.assertEqual((code, err), (0, ""))
        head, rows = method_table(md)
        self.assertEqual(list(rows)[:3], ["keyword", "vector", "hybrid"])      # 決まった順で、全部の結果の方式
        self.assertEqual(rows["vector"]["a: nDCG@10"], "-")
        self.assertEqual(rows["hybrid"]["b: nDCG@10"], "-")
        self.assertEqual(rows["vector"]["b: nDCG@10"], "0.25")

    def test_terminal_tables_are_aligned_by_display_width(self):
        a, b = self.result_file(make_result(hr_rows()), "a.json"), self.result_file(make_result(hr_rows()), "b.json")
        prices = write_prices(self.dir, semantic_per_1000=500, embedding_per_1m_tokens=20, search_per_1000=100)
        for files in ([a], [a, b]):
            code, out, err, _ = self.report(*files, prices=prices)
            self.assertEqual(code, 0)
            lines = out.splitlines()
            for start in [i for i, line in enumerate(lines) if set(line) == {"-"}]:       # 見出しの下の線が、表の幅
                width = eval_report.display_width(lines[start])
                end = start + 1
                while end < len(lines) and lines[end].strip():
                    end += 1
                for line in lines[start - 1:end]:
                    self.assertEqual(eval_report.display_width(line), width, line)
                for line in lines[start + 1:end]:              # 「 | 」の位置も同じ
                    self.assertEqual([eval_report.display_width(line[:i]) for i, c in enumerate(line) if c == "|"],
                                     [eval_report.display_width(lines[start - 1][:i]) for i, c in enumerate(lines[start - 1]) if c == "|"], line)

    def test_display_width_counts_full_width_as_two(self):
        self.assertEqual(eval_report.display_width("nDCG@10"), 7)
        self.assertEqual(eval_report.display_width("方式"), 4)
        self.assertEqual(eval_report.display_width("埋め込み（共通）"), 16)
        self.assertEqual(eval_report.pad("方式", 6, "r"), "  方式")
        self.assertEqual(eval_report.pad("ab", 4, "l"), "ab  ")

    def test_markdown_file_has_no_local_paths_and_escapes_cells(self):
        path = self.result_file(make_result(hr_rows()), "hr-X.json")
        code, out, err, md = self.report(path, self.result_file(make_result(hr_rows()), "hr-Y.json"), "--label", "A|B", "--label", "C")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("A\\|B: nDCG@10", md)                 # 名前の縦線で、列がずれない
        self.assertNotIn(str(self.dir), md)
        self.assertNotIn(str(Path.home()), md)
        self.assertIn("hr-X.json", md)
        self.assertTrue(md.startswith("# 検索の評価のまとめ：hr\n"))
        self.assertTrue(md.endswith("\n"))
        for table in md_tables(md).values():
            width = len(table[0])
            self.assertTrue(all(len(row) == width for row in table[1]))
        self.assertIn("Markdown：report-2.md", out)          # 画面にも、Repo の外のファイルはパスでなく名前だけ

    def test_md_is_created_inside_new_folders_and_overwritten(self):
        path = self.result_file(make_result(hr_rows()))
        target = self.dir / "new" / "dir" / "out.md"
        out, err = io.StringIO(), io.StringIO()
        for _ in range(2):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = eval_report.main([str(path), "--prices", str(self.dir / "none.json"), "--md", str(target)])
            self.assertEqual(code, 0)
        self.assertTrue(target.read_text(encoding="utf-8").startswith("# 検索の評価のまとめ"))
        blocked = self.dir / "file.txt"
        blocked.write_text("x", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = eval_report.main([str(path), "--prices", str(self.dir / "none.json"), "--md", str(blocked / "out.md")])
        self.assertEqual(code, 1)
        self.assertIn("Markdown を書けません", err.getvalue())

    def test_default_prices_file_is_used_when_not_given(self):
        path = self.result_file(make_result(hr_rows(), units={"search": 20, "semantic": 5, "embedding_tokens": 50_000}))
        prices = write_prices(self.dir, semantic_per_1000=500, embedding_per_1m_tokens=20, search_per_1000=100)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cost, "DEFAULT_PRICES", prices), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = eval_report.main([str(path)])
        self.assertEqual((code, err.getvalue()), (0, ""))
        self.assertIn("5.00円", out.getvalue())

    def test_bad_inputs_exit_2_with_a_reason(self):
        good = self.result_file(make_result(hr_rows()), "good.json")
        broken = {"not-json": "{", "list": "[]", "no-k": json.dumps({**make_result(hr_rows()), "k": None}),
                  "no-units": json.dumps({key: v for key, v in make_result(hr_rows()).items() if key != "units"}),
                  "bad-point": json.dumps(make_result([("q", "t", {"keyword": {"ndcg": "high", "recall": 1, "hit1": 1, "leaks": 0}})]))}
        for name, text in broken.items():
            path = self.dir / f"{name}.json"
            path.write_text(text, encoding="utf-8")
            code, out, err, md = self.report(path)
            self.assertEqual((code, out, md), (2, "", ""), name)
            self.assertIn("NG", err, name)
            self.assertIn(f"{name}.json", err, name)
        code, _, err, _ = self.report(self.dir / "missing.json")
        self.assertEqual(code, 2)
        self.assertIn("読めません", err)
        bad_prices = write_prices(self.dir, semantic_per_1000=-5)
        code, out, err, _ = self.report(good, prices=bad_prices)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("semantic_per_1000", err)
        self.assertEqual(self.report()[0], 2)                            # 結果を1つも渡さない（argparse）

    def test_runs_as_a_script_from_another_folder(self):
        path = self.result_file(make_result(hr_rows()))
        done = subprocess.run([sys.executable, str(REPO_DIR / "tools" / "eval_report.py"), str(path), "--prices", str(self.dir / "none.json")],
                              capture_output=True, text=True, encoding="utf-8", cwd=self.dir, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("方式ごと", done.stdout)
        self.assertIn("方式×質問の種類", done.stdout)


# ------------------------------------------------------------------ 本物の結果の形（eval_search.py が書いたもの）

class WithEvalSearchTest(ReportTools, EvalCase):
    def test_reads_what_eval_search_writes(self):
        qs = [{"qid": "h1", "question": "質問1", "type": "paraphrase", "answer_ids": ["MAIL-09"]},
              {"qid": "h2", "question": "質問2", "type": "numeric", "answer_ids": ["JOB-REQ042-v3"]},
              {"qid": "h3", "question": "質問3", "type": "permission", "answer_ids": [], "as_role": "role:employee",
               "hidden_ids": ["MAIL-09"]}]
        fake = Fake(lambda index, body, seen: chunks("MAIL-09", "MAIL-09", "JOB-REQ042-v3"), tokens=7)
        code, out, err = self.run_eval(fake, ["--dataset", "hr", "--file", str(self.questions_file(qs))])
        self.assertEqual(code, 0, out + err)
        result_path = next(self.out_dir.glob("*.json"))
        units = self.result()["units"]
        prices = write_prices(self.dir, semantic_per_1000=500, embedding_per_1m_tokens=20, search_per_1000=100)
        code, out, err, md = self.report(result_path, prices=prices)
        self.assertEqual((code, err), (0, ""), out)
        head, rows = method_table(md)
        # 方式ごとの検索の回数を足すと、使った量の合計と同じ（セマンティックは semantic の方式だけ）
        self.assertEqual(sum(int(rows[m]["検索"]) for m in ALL_METHODS), units["search"])
        self.assertEqual(sum(int(rows[m]["セマンティック"]) for m in ALL_METHODS), units["semantic"])
        self.assertEqual(rows["合計"]["検索"], str(units["search"]))
        self.assertEqual(rows["合計"]["埋め込みトークン"], f"{units['embedding_tokens']:,}")
        self.assertEqual(units, {"search": 12, "semantic": 3, "embedding_tokens": 21})
        # 費用：検索 9 回（セマンティックを除く）×100÷1000 + セマンティック 3 回×500÷1000 + 21 トークン×20÷1,000,000
        expected = 100 * 9 / 1000 + 500 * 3 / 1000 + 20 * 21 / 1_000_000
        self.assertEqual(rows["合計"]["費用の見込み"], cost.format_amount(expected, "JPY"))
        self.assertEqual(rows["埋め込み（共通）"]["費用の見込み"], "<0.01円")
        self.assertEqual(rows["keyword"]["漏れ問"], "1/1 (100%)")           # 一般社員に MAIL-09 が出た。漏れうる質問は一般社員の1問だけ（採用担当の2問は数えない）
        self.assertEqual(rows["keyword"]["問"], "2/3")
        # 画面と Markdown の両方に、種類の表がある
        self.assertIn("permission", md)
        self.assertIn("permission", out)


if __name__ == "__main__":
    unittest.main()
