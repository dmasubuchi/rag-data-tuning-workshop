"""tools/eval_search.py（検索して採点する道具）と tools/evallib/{settings,rest,metrics,methods,datasets}.py の試験。

本物の Azure・ネットワーク・.env.local は使わない。HTTP は偽物（urllib.request.urlopen を差し替え、URL・ヘッダー・本文を確かめる）。
人事は、本物の manifest（applied/data/manifest.json）の文書の ID を使う。ホテルは tests/fixtures/hotels_mini.json（ID 1〜3）。
"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import random
import re
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))

import eval_search  # noqa: E402
import search_demo  # noqa: E402
from evallib import datasets, methods, metrics, rest, settings  # noqa: E402

HOTELS = REPO_DIR / "tests" / "fixtures" / "hotels_mini.json"
ENV = (
    "AZURE_SEARCH_ENDPOINT=https://srch-test.search.windows.net\n"
    "AZURE_SEARCH_API_KEY=query-key-from-the-file\n"
    "AZURE_SEARCH_KEY_ROLE=query\n"
    "AZURE_OPENAI_ENDPOINT=https://ai-test.openai.azure.com/\n"
    "AZURE_OPENAI_API_KEY=openai-key-from-the-file\n"
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small\n"
    "AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-5-mini\n"
    "EMBEDDING_DIMENSIONS=8\n"
)
DECOYS = {"AZURE_SEARCH_ENDPOINT": "https://decoy.search.windows.net", "AZURE_SEARCH_API_KEY": "decoy-key",
          "AZURE_OPENAI_ENDPOINT": "https://decoy.example", "AZURE_OPENAI_API_KEY": "decoy-openai-key"}
ALL_METHODS = ("keyword", "vector", "hybrid", "semantic")
SEARCH_URL = re.compile(r"^https://srch-test\.search\.windows\.net/indexes/([^/?]+)/docs/search\?api-version=2024-07-01$")


def respond(payload):
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def chunks(*doc_ids):
    """人事のチャンクの答え。1つ目の引数から順に、chunk_id と doc_id をもつ。"""
    return {"value": [{"chunk_id": f"c{i}", "doc_id": d} for i, d in enumerate(doc_ids, 1)]}


def hits(field, *ids):
    return {"value": [{field: i} for i in ids]}


class Seen:
    def __init__(self, req, body):
        self.url, self.method, self.body = req.full_url, req.get_method(), body
        self.headers = {k.lower(): v for k, v in req.header_items()}
        match = SEARCH_URL.match(self.url)
        self.index = match.group(1) if match else None
        self.is_embedding = self.url == "https://ai-test.openai.azure.com/openai/v1/embeddings"


class Fake:
    """偽物の Azure。search(index, body, seen) が答え（辞書）か HTTP の番号（整数）か例外を返す。"""

    def __init__(self, search, tokens=5):
        self.search, self.tokens, self.seen = search, tokens, []

    def __call__(self, req, timeout=None):
        seen = Seen(req, json.loads(req.data))
        seen.raw = req.data
        self.seen.append(seen)
        if seen.is_embedding:
            return respond({"data": [{"index": 0, "embedding": [0.25] * 8}],
                            "usage": {"prompt_tokens": self.tokens, "total_tokens": self.tokens}})
        answer = self.search(seen.index, seen.body, seen)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(seen.url, answer, "error", {}, io.BytesIO(b'{"error":{"message":"fake failure"}}'))
        if isinstance(answer, Exception):
            raise answer
        return respond(answer)

    def searches(self):
        return [s for s in self.seen if s.index]


class EvalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.env_file = self.dir / "member.env"
        self.env_file.write_text(ENV, encoding="utf-8")
        self.out_dir = self.dir / "out"

    def questions_file(self, questions):
        self.files = getattr(self, "files", 0) + 1
        path = self.dir / f"questions-{self.files}.json"
        path.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
        return path

    def run_eval(self, fake, argv, env_file=None):
        """eval_search.main を偽の HTTP で動かす。(終了コード, 標準出力, 標準エラー) を返す。"""
        out, err = io.StringIO(), io.StringIO()
        environ = {"WORKSHOP_ENV_FILE": str(env_file or self.env_file), **DECOYS}
        with mock.patch.dict(os.environ, environ), mock.patch("urllib.request.urlopen", side_effect=fake), \
                mock.patch("time.sleep") as sleep, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = eval_search.main([*argv, "--out", str(self.out_dir)])
        self.sleep = sleep
        return code, out.getvalue(), err.getvalue()

    def result(self):
        files = sorted(self.out_dir.glob("*.json"))
        self.assertEqual(len(files), 1, files)
        return json.loads(files[0].read_text(encoding="utf-8"))


class EvalSearchTest(EvalCase):
    # ---------------------------------------------------------------- 設定とキー

    def test_reads_env_local_and_uses_query_key_only(self):
        """.env.local（メンバーの検索だけのキー）の接続先とキーで、検索（docs/search）と埋め込みだけを呼ぶ。管理キーの API・端末の環境変数は使わない。"""
        qf = self.questions_file([{"qid": "q1", "question": "河越夜戦の大名", "answer_ids": ["b015"], "type": "keyword-wins"}])
        fake = Fake(lambda index, body, seen: hits("id", "b015", "b001"))
        code, out, err = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf)])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(fake.searches()), 4)
        for seen in fake.seen:
            self.assertEqual(seen.method, "POST")
            if seen.is_embedding:
                self.assertEqual(seen.headers["api-key"], "openai-key-from-the-file")
                self.assertEqual(seen.body, {"model": "text-embedding-3-small", "input": ["河越夜戦の大名"], "dimensions": 8})
            else:
                self.assertEqual(seen.index, "sengoku", seen.url)         # 検索の URL（docs/search）だけ
                self.assertEqual(seen.headers["api-key"], "query-key-from-the-file")
            for word in ("decoy", "/indexers", "/datasources", "/skillsets", "/synonymmaps", "/servicestats"):
                self.assertNotIn(word, seen.url)
        for text in (out, err, next(self.out_dir.glob("*.json")).read_text(encoding="utf-8")):
            for secret in ("query-key-from-the-file", "openai-key-from-the-file", "decoy"):
                self.assertNotIn(secret, text)

    def test_default_env_file_is_dot_env_local_in_the_repo(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("WORKSHOP_ENV_FILE", None)
            self.assertEqual(settings.env_path(), REPO_DIR / ".env.local")
        with mock.patch.dict(os.environ, {"WORKSHOP_ENV_FILE": "/somewhere/else.env"}):
            self.assertEqual(settings.env_path(), Path("/somewhere/else.env"))
        self.assertNotIn("query-key", repr(settings.load_settings(need_embedding=True, path=self.env_file)))

    def test_missing_settings_stop_before_any_request(self):
        fake = Fake(lambda index, body, seen: hits("id", "b015"))
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        code, out, _ = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf)], env_file=self.dir / "nothing.env")
        self.assertEqual(code, 1)
        self.assertIn("nothing.env が読めません", out)
        self.assertIn("team.py env", out)
        self.env_file.write_text(ENV.replace("EMBEDDING_DIMENSIONS=8\n", ""), encoding="utf-8")
        code, out, _ = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf)])
        self.assertEqual(code, 1)
        self.assertIn("EMBEDDING_DIMENSIONS", out)
        self.assertEqual(fake.seen, [])
        # キーワードだけなら、埋め込みの設定は要らない
        self.env_file.write_text("AZURE_SEARCH_ENDPOINT=https://srch-test.search.windows.net\nAZURE_SEARCH_API_KEY=k\n", encoding="utf-8")
        code, out, err = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf), "--methods", "keyword"])
        self.assertEqual(code, 0, out + err)
        self.assertFalse(any(s.is_embedding for s in fake.seen))

    def test_env_howto_matches_search_demo(self):
        self.assertEqual(settings.ENV_HOWTO, search_demo.ENV_HOWTO)

    # ---------------------------------------------------------------- 検索の本文

    def test_request_bodies_per_method(self):
        qf = self.questions_file([{"qid": "q1", "question": "河越夜戦の大名", "answer_ids": ["b015"]}])
        fake = Fake(lambda index, body, seen: hits("id", "b001"))
        code, out, err = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf)])
        self.assertEqual(code, 0, out + err)
        vector = [0.25] * 8
        base = {"top": 50, "select": "id"}
        vq = [{"kind": "vector", "vector": vector, "fields": "profile_vector", "k": 50}]
        self.assertEqual([s.body for s in fake.searches()], [
            {**base, "search": "河越夜戦の大名"},
            {**base, "vectorQueries": vq},
            {**base, "search": "河越夜戦の大名", "vectorQueries": vq},
            {**base, "search": "河越夜戦の大名", "vectorQueries": vq, "queryType": "semantic", "semanticConfiguration": "sengoku-semantic"},
        ])
        self.assertEqual(len([s for s in fake.seen if s.is_embedding]), 1)      # 質問の埋め込みは1回（方式で使い回す）

    def test_request_bodies_are_ascii_json_like_search_demo(self):
        qf = self.questions_file([{"qid": "q1", "question": "河越夜戦の大名", "answer_ids": ["b015"]}])
        fake = Fake(lambda index, body, seen: hits("id", "b015"))
        code, out, err = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf)])
        self.assertEqual(code, 0, out + err)
        for seen in fake.seen:                  # 検索の本文も、埋め込みの本文も、日本語を \uXXXX に直した ASCII（tools/search_demo.py と同じ）
            self.assertTrue(seen.raw.isascii(), seen.url)
        self.assertIn("\\u6cb3\\u8d8a", fake.searches()[0].raw.decode("ascii"))
        self.assertEqual(fake.searches()[0].body["search"], "河越夜戦の大名")       # 受け取る側が読むと、元の日本語に戻る

    def test_k_sets_the_scoring_depth_and_the_fetch_size(self):
        self.assertEqual([methods.fetch_count(k) for k in (1, 10, 11, 50)], [5, 50, 50, 50])
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        fake = Fake(lambda index, body, seen: hits("id", *[f"x{i}" for i in range(9)], "b015"))
        code, out, _ = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf), "--methods", "keyword", "--k", "5"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.searches()[0].body["top"], 25)
        r = self.result()["questions"][0]["results"]["keyword"]
        self.assertEqual((r["ndcg"], r["recall"], r["hit1"], r["first_rank"]), (0.0, 0.0, 0.0, 10))   # 10 位は k=5 の外

    # ---------------------------------------------------------------- 人事：文書単位

    def test_hr_chunks_are_ranked_by_document(self):
        """1つの文書が多くのチャンクに分かれても、同じ文書は1回だけ数える。文書の順位は、その文書の最初のチャンクの順位。"""
        qf = self.questions_file([{"qid": "h1", "question": "質問", "answer_ids": ["MAIL-09"], "type": "paraphrase"}])
        order = ("CV-APP-0391", "CV-APP-0391", "MAIL-09", "CV-APP-0391", "MAIL-09", "JOB-REQ042-v3", "CV-APP-0386")
        fake = Fake(lambda index, body, seen: chunks(*order))
        code, out, err = self.run_eval(fake, ["--dataset", "hr", "--file", str(qf), "--methods", "keyword"])
        self.assertEqual(code, 0, out + err)
        search = fake.searches()[0]
        self.assertEqual(search.index, "hr-docs")
        self.assertEqual(search.body["top"], 50)                      # k=10 の5倍までチャンクを取る
        self.assertEqual(search.body["select"], "doc_id,chunk_id")
        r = self.result()["questions"][0]["results"]["keyword"]
        self.assertEqual(r["ranked"], ["CV-APP-0391", "MAIL-09", "JOB-REQ042-v3", "CV-APP-0386"])
        self.assertEqual(r["first_rank"], 2)                           # チャンクの 3 番目ではなく、文書の 2 番目
        self.assertAlmostEqual(r["ndcg"], 1 / 1.5849625007211562, places=9)
        self.assertEqual((r["recall"], r["hit1"]), (1.0, 0.0))

    def test_documents_without_a_doc_id_are_still_counted(self):
        """doc_id が空のチャンクは、チャンクごとに別の文書として数える（漏れの点検から消えない）。"""
        response = {"value": [{"chunk_id": "c1", "doc_id": ""}, {"chunk_id": "c2", "doc_id": "MAIL-01"}, {"chunk_id": "c3"}]}
        self.assertEqual(methods.documents_in_order(datasets.SPECS["hr"], response), ["(chunk:c1)", "MAIL-01", "(chunk:c3)"])

    # ---------------------------------------------------------------- 飛ばす・止まる

    def hotel_questions(self):
        return self.questions_file([
            {"qid": "hotel-01", "question": "海の近くの宿", "type": "paraphrase", "answer_ids": ["1"]},
            {"qid": "hotel-02", "question": "評価が高く駐車場つき", "type": "condition", "answer_ids": ["2", "3"],
             "condition": {"Rating": {"ge": 4.5}, "ParkingIncluded": True}},
        ])

    def test_missing_index_skips_only_that_method(self):
        """hotels-cosmos がない：vector・hybrid（と +filter）だけ飛ばして理由を出し、keyword は最後まで測る。"""
        def search(index, body, seen):
            return 404 if index == "hotels-cosmos" else hits("HotelId", "1", "2")
        fake = Fake(search)
        code, out, err = self.run_eval(fake, ["--dataset", "hotel", "--file", str(self.hotel_questions()),
                                              "--hotel-data", str(HOTELS), "--methods", "keyword,vector,hybrid"])
        self.assertEqual(code, 0, out + err)
        data = self.result()
        self.assertEqual(sorted(data["skipped"]), ["hybrid", "hybrid+filter", "vector", "vector+filter"])
        for reason in data["skipped"].values():
            self.assertEqual(reason, "インデックス hotels-cosmos がありません（まだ作っていません）")
        self.assertEqual([sorted(q["results"]) for q in data["questions"]], [["keyword"], ["keyword", "keyword+filter"]])
        self.assertEqual(len([s for s in fake.searches() if s.index == "hotels-cosmos"]), 1)    # 同じインデックスは、もう頼まない
        self.assertEqual(out.count("飛ばす"), 1)
        self.assertIn("飛ばす  vector・hybrid・vector+filter・hybrid+filter：インデックス hotels-cosmos がありません", out)
        self.assertIn("keyword         nDCG", out)

    def test_missing_semantic_config_skips_only_semantic(self):
        """ホテルにセマンティックの設定がない（400）：semantic だけ飛ばす。ほかの方式は測る。"""
        def search(index, body, seen):
            return 400 if body.get("queryType") == "semantic" else hits("HotelId", "1")
        fake = Fake(search)
        code, out, err = self.run_eval(fake, ["--dataset", "hotel", "--file", str(self.hotel_questions()), "--hotel-data", str(HOTELS)])
        self.assertEqual(code, 0, out + err)
        data = self.result()
        self.assertEqual(sorted(data["skipped"]), ["semantic", "semantic+filter"])
        self.assertTrue(data["skipped"]["semantic"].startswith("セマンティックの設定（hotels-semantic）がありません（エラー 400："), data["skipped"])
        self.assertEqual(len([s for s in fake.searches() if s.body.get("queryType") == "semantic"]), 1)
        self.assertEqual(sorted(data["questions"][1]["results"]), ["hybrid", "hybrid+filter", "keyword", "keyword+filter", "vector", "vector+filter"])
        # ホテルの semantic は hotels-blob で、ベクトルのクエリを付けない
        semantic = [s for s in fake.searches() if s.body.get("queryType") == "semantic"][0]
        self.assertEqual((semantic.index, semantic.body["semanticConfiguration"], "vectorQueries" in semantic.body), ("hotels-blob", "hotels-semantic", False))

    def test_403_stops_with_hint_and_keeps_partial_results(self):
        """セマンティックが 403：無料枠かキーかを案内して止まり、そこまでの結果（途中の質問も）を保存する。"""
        qs = [{"qid": f"h{i}", "question": f"質問{i}", "answer_ids": ["MAIL-09"], "type": "paraphrase"} for i in (1, 2, 3)]
        count = {"semantic": 0}

        def search(index, body, seen):
            if body.get("queryType") == "semantic":
                count["semantic"] += 1
                if count["semantic"] == 2:
                    return 403
            return chunks("MAIL-09", "JOB-REQ042-v3")
        fake = Fake(search)
        code, out, _ = self.run_eval(fake, ["--dataset", "hr", "--file", str(self.questions_file(qs))])
        self.assertEqual(code, 1)
        self.assertIn("止まりました", out)
        self.assertIn("無料枠", out)
        self.assertIn("キーが合っているか", out)
        self.assertEqual(len(fake.searches()), 4 + 4)           # 1 問目の 4 方式 + 2 問目の 4 つ目（403）で止まる
        self.assertTrue(fake.seen[-1].body.get("queryType") == "semantic")
        data = self.result()
        self.assertIn("無料枠", data["stopped"])
        self.assertEqual([q["qid"] for q in data["questions"]], ["h1", "h2"])
        self.assertEqual(sorted(data["questions"][0]["results"]), sorted(ALL_METHODS))
        self.assertEqual(sorted(data["questions"][1]["results"]), ["hybrid", "keyword", "vector"])    # 2 問目は途中まで
        self.assertEqual(data["units"], {"search": 7, "semantic": 1, "embedding_tokens": 10})        # 403 の検索は数えない
        self.assertIn("ここまでの結果は", out)
        self.assertIn("[h2] nDCG@10  keyword 1.00  vector 1.00  hybrid 1.00\n", out)      # 途中の質問も、できた分を出す
        self.assertIn("nDCG", out)                                # 止まっても、平均は出す

    def test_403_on_a_plain_search_blames_the_key_not_the_free_tier(self):
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        for status in (401, 403):
            with self.subTest(status=status):
                fake = Fake(lambda index, body, seen, status=status: status)
                code, out, _ = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf), "--methods", "keyword"])
                self.assertEqual(code, 1)
                self.assertIn(f"エラー {status}：キーが合いません", out)
                self.assertNotIn("無料枠", out)
                self.assertEqual(len(fake.searches()), 1)
                for old in self.out_dir.glob("*.json"):
                    old.unlink()

    def test_network_failure_retries_once_then_stops(self):
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        failure = urllib.error.URLError("fake network down")
        state = {"n": 0}

        def flaky(index, body, seen):
            state["n"] += 1
            return failure if state["n"] == 1 else hits("id", "b015")
        code, out, err = self.run_eval(Fake(flaky), ["--dataset", "sengoku", "--file", str(qf), "--methods", "keyword"])
        self.assertEqual(code, 0, out + err)                  # 1 回目の失敗は、やり直して通る
        self.assertEqual(state["n"], 2)
        for old in self.out_dir.glob("*.json"):
            old.unlink()
        fake = Fake(lambda index, body, seen: failure)
        code, out, _ = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf), "--methods", "keyword"])
        self.assertEqual(code, 1)
        self.assertEqual(len(fake.seen), 2)                   # 1 回だけやり直す
        self.assertIn("つながりません：fake network down", out)
        self.assertEqual(self.result()["questions"][0]["results"], {})

    def test_busy_search_waits_and_retries(self):
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        state = {"n": 0}

        def busy(index, body, seen):
            state["n"] += 1
            return 429 if state["n"] <= 2 else hits("id", "b015")
        code, out, err = self.run_eval(Fake(busy), ["--dataset", "sengoku", "--file", str(qf), "--methods", "keyword"])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(state["n"], 3)
        self.assertEqual(self.sleep.call_count, 2)

    # ---------------------------------------------------------------- 権限と漏れ

    def test_permission_questions_count_leaks_not_recall(self):
        """正解のない質問は、再現率・nDCG の平均から外し、漏れ（その役割が見られない文書が上位 k 件に出た数。文書ごとに1）で数える。"""
        qs = [
            {"qid": "p1", "question": "石田さんの評価", "type": "permission", "answer_ids": [], "as_role": "role:employee",
             "hidden_ids": ["EVAL-INTERVIEWS-2026-10"]},
            {"qid": "n1", "question": "求人票の年収", "type": "numeric", "answer_ids": ["JOB-REQ042-v3"]},
        ]

        def search(index, body, seen):
            if "role:employee" in body.get("filter", ""):
                # 求人票（見える）、評価一覧（hidden_ids）、経歴書（求人票でないので漏れ）の順。評価一覧は2チャンク
                return chunks("JOB-REQ042-v3", "EVAL-INTERVIEWS-2026-10", "EVAL-INTERVIEWS-2026-10", "CV-APP-0391")
            return chunks("JOB-REQ042-v3", "CV-APP-0391")
        fake = Fake(search)
        code, out, err = self.run_eval(fake, ["--dataset", "hr", "--file", str(self.questions_file(qs)), "--methods", "keyword,hybrid"])
        self.assertEqual(code, 0, out + err)
        data = self.result()
        p1, n1 = (q["results"] for q in data["questions"])
        for method in ("keyword", "hybrid"):
            self.assertEqual(p1[method]["leaks"], 2, method)            # 評価一覧（2回出ても1）と経歴書。求人票は見える
            for key in ("ndcg", "recall", "hit1", "first_rank"):
                self.assertIsNone(p1[method][key], key)
            self.assertEqual(n1[method]["leaks"], 0)                    # 採用担当（既定）は全部見える：経歴書が出ても漏れでない
            self.assertEqual((n1[method]["ndcg"], n1[method]["recall"], n1[method]["hit1"]), (1.0, 1.0, 1.0))
        summary = metrics.summarize(data["questions"], "keyword")
        self.assertEqual((summary["questions"], summary["scored"], summary["ndcg"], summary["recall"]), (2, 1, 1.0, 1.0))
        self.assertEqual((summary["leak_questions"], summary["leaks"]), (1, 2))
        # 権限の絞り込み：as_role がなければ採用担当
        by_role = {("employee" in s.body["filter"]): s.body["filter"] for s in fake.searches()}
        self.assertEqual(by_role[True], "allowed/any(a: search.in(a, 'role:employee'))")
        self.assertEqual(by_role[False], "allowed/any(a: search.in(a, 'role:recruiter'))")
        self.assertIn("[p1] 漏れ  keyword 2  hybrid 2", out)
        self.assertIn("[n1] nDCG@10  keyword 1.00  hybrid 1.00", out)
        self.assertIn("漏れ 1/2問（50%）・文書 2件", out)
        self.assertIn("正解の文書がない質問（1問）は、平均に入れていません", out)

    def test_leak_rules(self):
        kinds = {"JOB-1": "job_posting", "CV-1": "resume", "MAIL-1": "mail"}
        vis = datasets.Visibility(kinds)
        self.assertEqual(vis.count("role:employee", [], ["JOB-1", "CV-1", "CV-1", "MAIL-1", "UNKNOWN"]), 3)   # 求人票以外・不明は漏れ
        self.assertEqual(vis.count("role:recruiter", ["CV-1"], ["JOB-1", "CV-1", "MAIL-1"]), 1)               # 採用担当でも hidden_ids は漏れ
        self.assertEqual(vis.count("role:interviewer", [], ["JOB-1", "CV-1"]), 0)                              # 面接官は hidden_ids だけで数える
        self.assertEqual(vis.count(None, ["CV-1"], ["CV-1"]), 0)                                              # 権限のないデータ
        with self.assertRaises(datasets.DataError):
            datasets.allowed_filter("employee")

    # ---------------------------------------------------------------- 条件の絞り込み

    def test_condition_adds_filter_variant(self):
        """condition のある質問だけ、各方式に絞り込みを足した <方式>+filter も測る。ベクトルの検索には vectorFilterMode を付ける。"""
        fake = Fake(lambda index, body, seen: hits("HotelId", "2", "3", "1"))
        code, out, err = self.run_eval(fake, ["--dataset", "hotel", "--file", str(self.hotel_questions()), "--hotel-data", str(HOTELS)])
        self.assertEqual(code, 0, out + err)
        data = self.result()
        self.assertEqual(data["methods"], list(ALL_METHODS) + [m + "+filter" for m in ALL_METHODS])
        q1, q2 = (q["results"] for q in data["questions"])
        self.assertEqual(sorted(q1), sorted(ALL_METHODS))                       # condition のない質問は、素の方式だけ
        self.assertEqual(sorted(q2), sorted(data["methods"]))
        flt = "Rating ge 4.5 and ParkingIncluded eq true"
        filtered = [s for s in fake.searches() if "filter" in s.body]
        self.assertEqual(len(filtered), 4)
        self.assertEqual({s.body["filter"] for s in filtered}, {flt})
        for s in filtered:
            self.assertEqual(s.body.get("vectorFilterMode"), "preFilter" if "vectorQueries" in s.body else None)
        self.assertEqual([s.index for s in filtered], ["hotels-blob", "hotels-cosmos", "hotels-cosmos", "hotels-blob"])
        plain = [s for s in fake.searches() if "filter" not in s.body]
        self.assertEqual(len(plain), 4 + 4)                                       # 1 問目の 4 + 2 問目の素の 4
        self.assertEqual(q2["keyword+filter"]["recall"], 1.0)
        self.assertEqual(q2["keyword+filter"]["ranked"], ["2", "3", "1"])
        self.assertIn("keyword+filter", out)

    def test_filter_variants_only_for_datasets_with_conditions(self):
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"], "condition": {"Rating": {"ge": 4}}}])
        fake = Fake(lambda index, body, seen: hits("id", "b015"))
        code, _, _ = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf), "--methods", "keyword"])
        self.assertEqual(code, 0)
        self.assertEqual(self.result()["methods"], ["keyword"])
        self.assertNotIn("filter", fake.searches()[0].body)

    def test_combine_filters(self):
        self.assertEqual(datasets.combine(None, None), None)
        self.assertEqual(datasets.combine("a eq 1", None), "a eq 1")
        self.assertEqual(datasets.combine("a eq 1 or b eq 2", "c eq 3"), "(a eq 1 or b eq 2) and (c eq 3)")

    # ---------------------------------------------------------------- 使った量

    def test_units_count_search_semantic_and_embedding_tokens(self):
        qs = [{"qid": f"h{i}", "question": f"質問{i}", "answer_ids": ["MAIL-09"]} for i in (1, 2)]
        fake = Fake(lambda index, body, seen: chunks("MAIL-09"), tokens=7)
        code, out, err = self.run_eval(fake, ["--dataset", "hr", "--file", str(self.questions_file(qs))])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.result()["units"], {"search": 8, "semantic": 2, "embedding_tokens": 14})    # 埋め込みは1問1回（vector・hybrid・semantic で共用）
        self.assertEqual(len([s for s in fake.seen if s.is_embedding]), 2)
        self.assertIn("使った量：検索 8 回（うちセマンティック ランカー 2 回）、質問の埋め込み 14 トークン", out)
        # keyword だけなら、埋め込みは頼まない
        for old in self.out_dir.glob("*.json"):
            old.unlink()
        fake = Fake(lambda index, body, seen: chunks("MAIL-09"))
        self.run_eval(fake, ["--dataset", "hr", "--file", str(self.questions_file(qs)), "--methods", "keyword"])
        self.assertEqual(self.result()["units"], {"search": 2, "semantic": 0, "embedding_tokens": 0})

    def test_embedding_falls_back_to_prompt_tokens_and_checks_length(self):
        s = settings.Settings("https://x", "k", "https://o", "ok", "dep", 8)
        answer = {"data": [{"index": 0, "embedding": [0.0] * 8}], "usage": {"prompt_tokens": 3}}
        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=None: respond(answer)):
            self.assertEqual(rest.embed(s, "質問"), ([0.0] * 8, 3))
        short = {"data": [{"index": 0, "embedding": [0.0] * 4}]}
        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=None: respond(short)):
            with self.assertRaises(rest.RestError):
                rest.embed(s, "質問")

    # ---------------------------------------------------------------- 結果のファイルと画面

    def test_result_file_shape_and_console(self):
        qs = [{"qid": f"h{i}", "question": f"質問{i}", "type": "paraphrase", "answer_ids": ["MAIL-09"]} for i in (1, 2, 3)]
        fake = Fake(lambda index, body, seen: chunks("JOB-REQ042-v3", "MAIL-09"))
        code, out, err = self.run_eval(fake, ["--dataset", "hr", "--file", str(self.questions_file(qs)), "--limit", "2"])
        self.assertEqual(code, 0, out + err)
        data = self.result()
        self.assertEqual(list(data), ["dataset", "started", "k", "methods", "skipped", "units", "stopped", "questions"])
        self.assertEqual((data["dataset"], data["k"], data["methods"], data["skipped"], data["stopped"]),
                         ("hr", 10, list(ALL_METHODS), {}, None))
        self.assertRegex(data["started"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertRegex(next(self.out_dir.glob("*.json")).name, r"^hr-\d{8}T\d{6}Z\.json$")
        self.assertEqual([q["qid"] for q in data["questions"]], ["h1", "h2"])          # --limit
        self.assertEqual(data["questions"][0]["type"], "paraphrase")
        self.assertEqual(list(data["questions"][0]["results"]["keyword"]), ["ranked", "ndcg", "recall", "hit1", "first_rank", "leaks"])
        self.assertIn("評価：hr（質問 2 問、上位 10 件で採点）", out)
        self.assertIn("[h1] nDCG@10  keyword 0.63  vector 0.63  hybrid 0.63  semantic 0.63", out)
        self.assertIn("keyword         nDCG 0.63  再現率 1.00  1位 0%  （2問）  漏れ 0/2問（0%）・文書 0件", out)
        self.assertIn("結果：", out)

    def test_quiet_prints_only_the_summary(self):
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        fake = Fake(lambda index, body, seen: hits("id", "b015"))
        code, out, _ = self.run_eval(fake, ["--dataset", "sengoku", "--file", str(qf), "--quiet"])
        self.assertEqual(code, 0)
        self.assertNotIn("[q1]", out)
        self.assertNotIn("評価：", out)
        self.assertIn("方式ごとの平均", out)
        self.assertIn("使った量：", out)

    # ---------------------------------------------------------------- 引数・質問の確かめ

    def test_bad_arguments_and_questions_exit_2_without_requests(self):
        good = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        cases = [
            (["--dataset", "sengoku", "--file", str(good), "--methods", "keyword,keyword+filter"], "--methods は"),
            (["--dataset", "sengoku", "--file", str(good), "--methods", "magic"], "--methods は"),
            (["--dataset", "sengoku", "--file", str(good), "--k", "0"], "--k は"),
            (["--dataset", "sengoku", "--file", str(good), "--k", "51"], "--k は"),
            (["--dataset", "sengoku", "--file", str(good), "--limit", "0"], "--limit は"),
            (["--dataset", "hr", "--hotel-data", str(HOTELS)], "--hotel-data は"),
            (["--dataset", "sengoku", "--file", str(self.dir / "none.json")], "none.json がありません"),
            (["--dataset", "hotel", "--hotel-data", str(self.dir / "none.json")], "none.json がありません"),
        ]
        bad = {
            "answer_ids の文書の ID がデータにない": ([{"qid": "q1", "question": "質問", "answer_ids": ["b999"]}], "b999"),
            "形が違う": ([{"qid": "q1", "answer_ids": ["b015"]}], "質問の形が違います"),
            "as_role の形": ([{"qid": "q1", "question": "質問", "answer_ids": [], "as_role": "employee"}], None),
            "質問が0問": ([], "質問が0問です"),
        }
        for name, (questions, expect) in bad.items():
            dataset = "hr" if "as_role" in name else "sengoku"
            cases.append((["--dataset", dataset, "--file", str(self.questions_file(questions))], expect or "role:… か user:…"))
        for argv, expect in cases:
            with self.subTest(argv=argv):
                fake = Fake(lambda index, body, seen: hits("id", "b015"))
                code, out, err = self.run_eval(fake, argv)
                self.assertEqual(code, 2, out + err)
                self.assertIn(expect, err)
                self.assertEqual(fake.seen, [])
        self.assertEqual(list(self.out_dir.glob("*.json")) if self.out_dir.exists() else [], [])

    def test_all_methods_skipped_exits_1(self):
        qf = self.questions_file([{"qid": "q1", "question": "質問", "answer_ids": ["b015"]}])
        code, out, _ = self.run_eval(Fake(lambda index, body, seen: 404), ["--dataset", "sengoku", "--file", str(qf)])
        self.assertEqual(code, 1)
        self.assertIn("測れた方式がありませんでした", out)
        self.assertIn("インデックス sengoku がありません", out)

    def test_real_question_files_run_with_a_fake_server(self):
        """本物の質問のファイル（武将60問・人事60問）を、偽のサーバーで最後まで走らせる。"""
        for dataset, count in (("sengoku", 60), ("hr", 60)):
            with self.subTest(dataset=dataset):
                for old in self.out_dir.glob("*.json") if self.out_dir.exists() else []:
                    old.unlink()
                field = "id" if dataset == "sengoku" else "doc_id"
                fake = Fake(lambda index, body, seen, field=field: {"value": [{field: "b015", "chunk_id": "c1"}]})
                code, out, err = self.run_eval(fake, ["--dataset", dataset, "--methods", "keyword", "--quiet"])
                self.assertEqual(code, 0, out + err)
                self.assertEqual(len(self.result()["questions"]), count)

    # ---------------------------------------------------------------- 名前が元のコードとずれていない

    def test_names_match_the_code_and_the_guide(self):
        basic = module_constants(REPO_DIR / "basic" / "lib" / "config.py")
        applied = module_constants(REPO_DIR / "applied" / "lib" / "config.py")
        sengoku, hr, hotel = (datasets.SPECS[n] for n in ("sengoku", "hr", "hotel"))
        for method in ALL_METHODS:
            self.assertEqual(sengoku.setups[method].index, basic["SENGOKU_INDEX"])
            self.assertEqual(hr.setups[method].index, applied["HR_INDEX"])
        for method in ("vector", "hybrid", "semantic"):
            self.assertEqual(sengoku.setups[method].vector_field, basic["SENGOKU_VECTOR_FIELD"])
            self.assertEqual(hr.setups[method].vector_field, applied["VECTOR_FIELD"])
        self.assertEqual(sengoku.setups["semantic"].semantic_config, basic["SENGOKU_SEMANTIC"])
        self.assertEqual(hr.setups["semantic"].semantic_config, applied["SEMANTIC_CONFIG"])
        guide = (REPO_DIR / "guide" / "hotel.md").read_text(encoding="utf-8")
        for name in (hotel.setups["keyword"].index, hotel.setups["vector"].index, hotel.setups["vector"].vector_field, hotel.id_field):
            self.assertIn(name, guide)
        self.assertEqual((hotel.setups["keyword"].index, hotel.setups["vector"].index), ("hotels-blob", "hotels-cosmos"))
        self.assertIn('"name":"HotelId","type":"Edm.String","key":true', guide)
        # ID の項目：武将は id、人事のチャンクは doc_id（キーは chunk_id）
        pipeline = (REPO_DIR / "applied" / "lib" / "pipeline.py").read_text(encoding="utf-8")
        for name in (hr.id_field, hr.fallback_id_field):
            self.assertIn(f'name="{name}"', pipeline)
        self.assertIn(sengoku.id_field, module_constants(REPO_DIR / "basic" / "lib" / "sengoku.py")["FIELDS"])

    def test_allowed_filter_matches_acl(self):
        acl = (REPO_DIR / "applied" / "lib" / "acl.py").read_text(encoding="utf-8")
        self.assertIn("""return f"allowed/any(a: search.in(a, '{','.join(items)}'))\"""", acl)
        self.assertEqual(datasets.allowed_filter("role:employee"), "allowed/any(a: search.in(a, 'role:employee'))")
        self.assertEqual(datasets.allowed_filter(["role:interviewer", "user:U-1006"]),
                         "allowed/any(a: search.in(a, 'role:interviewer,user:U-1006'))")
        acl_constants = module_constants(REPO_DIR / "applied" / "lib" / "acl.py")
        self.assertEqual(tuple(datasets.HR_PUBLIC_KINDS), acl_constants["PUBLIC_KINDS"])
        self.assertEqual(datasets.HR_RECRUITER, acl_constants["ROLE_RECRUITER"])
        self.assertEqual(datasets.PRINCIPAL.pattern, acl_constants_pattern(acl))

    def test_eval_modules_use_only_the_standard_library(self):
        allowed = set(sys.stdlib_module_names) | {"evallib"}
        files = [REPO_DIR / "tools" / "eval_search.py", REPO_DIR / "tools" / "eval_report.py",
                 *sorted((REPO_DIR / "tools" / "evallib").glob("*.py"))]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
            self.assertTrue(imported <= allowed, (path.name, imported - allowed))


def module_constants(path) -> dict:
    """モジュールの先頭にある NAME = 値（文字・タプルなどの書いた値）を読む。モジュールは動かさない。"""
    out = {}
    for node in ast.parse(Path(path).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def acl_constants_pattern(source) -> str:
    return re.search(r'^PRINCIPAL = re\.compile\(r"(.*?)"\)', source, re.M).group(1)


# ------------------------------------------------------------------ 指標は basic/lib/metrics.py と同じ式

class MetricsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("basic_metrics_from_file", REPO_DIR / "basic" / "lib" / "metrics.py")
        cls.basic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.basic)          # basic/lib/__init__.py を通さずに、ファイルから読む

    def test_metrics_match_basic_lib(self):
        rng = random.Random(20261107)
        pool = [f"D{i}" for i in range(30)]
        for _ in range(200):
            ranked = rng.sample(pool, rng.randint(0, 30))
            relevant = rng.sample(pool, rng.randint(0, 6))
            k = rng.randint(1, 12)
            self.assertEqual(metrics.ndcg_at_k(ranked, relevant, k), self.basic.ndcg_at_k(ranked, relevant, k))
            self.assertEqual(metrics.recall_at_k(ranked, relevant, k), self.basic.recall_at_k(ranked, relevant, k))
            self.assertEqual(metrics.hit_at_1(ranked, relevant), self.basic.hit_at_1(ranked, relevant))
            self.assertEqual(metrics.first_rank(ranked, relevant), self.basic.first_rank(ranked, relevant))
            if relevant:
                got, want = metrics.score(ranked, relevant, k), self.basic.evaluate(ranked, relevant, k)
                self.assertEqual((got["ndcg"], got["recall"], got["hit1"], got["first_rank"]),
                                 (want["ndcg"], want["recall"], want["hit1"], want["rank"]))
            else:
                self.assertEqual(metrics.score(ranked, relevant, k), {"ndcg": None, "recall": None, "hit1": None, "first_rank": None})

    def test_known_values(self):
        self.assertAlmostEqual(metrics.ndcg_at_k(["x", "a"], ["a"], 10), 0.6309297535714574)
        self.assertAlmostEqual(metrics.ndcg_at_k(["a", "x"], ["a", "b"], 10), 1 / (1 + 0.6309297535714574))
        self.assertEqual(metrics.first_rank(["x", "y"], ["a"]), None)

    def test_summarize_excludes_questions_without_answers(self):
        questions = [
            {"results": {"m": {"ndcg": 1.0, "recall": 1.0, "hit1": 1.0, "leaks": 0}}},
            {"results": {"m": {"ndcg": 0.0, "recall": 0.5, "hit1": 0.0, "leaks": 1}}},
            {"results": {"m": {"ndcg": None, "recall": None, "hit1": None, "leaks": 3}}},
            {"results": {}},
        ]
        s = metrics.summarize(questions, "m")
        self.assertEqual((s["questions"], s["scored"], s["ndcg"], s["recall"], s["hit1"]), (3, 2, 0.5, 0.75, 0.5))
        self.assertEqual((s["leak_questions"], s["leaks"]), (2, 4))
        self.assertEqual(metrics.summarize(questions, "none"), {"questions": 0, "scored": 0, "ndcg": None, "recall": None, "hit1": None,
                                                                 "leak_questions": 0, "leaks": 0})


if __name__ == "__main__":
    unittest.main()
