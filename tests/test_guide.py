"""手順書（guide/）と、tools/search_demo.py・tools/hotel_vectors.py の試験。通信しない（偽物の HTTP）。

手順書：相対リンクと見出しの飛び先がすべてある、書き方（山かっこの書き忘れ、呼び方、スクリーンショットなし）、
手順に出てくる道具とコマンドが本当にある、リソースの名前が team.py と同じ型、貼り付ける JSON が読める。
道具：.env.local だけを読む、メンバーの設定で動く、偽物の HTTP で送るものを確かめる。
"""

import ast
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parent.parent
GUIDE = REPO_DIR / "guide"
sys.path.insert(0, str(REPO_DIR / "tools"))

import check_questions  # noqa: E402
import eval_report  # noqa: E402
import eval_search  # noqa: E402
import hotel_vectors  # noqa: E402
import search_demo  # noqa: E402
import spot_check  # noqa: E402
import team  # noqa: E402
from evallib.methods import FETCH, METHODS  # noqa: E402
from evallib.questions import DATASETS  # noqa: E402
from githubmd import GithubSlugger, github_anchor  # noqa: E402
from teamlib.names import make_names  # noqa: E402

GUIDE_FILES = ["README.md", "setup/windows-pc.md", "setup/azure-setup.md", "hotel.md", "sengoku.md", "hr.md",
               "evaluation.md", "search-demo.md", "facilitator.md"]
FENCE = re.compile(r"^\s*(```|~~~)")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
EXTERNAL = re.compile(r"https?://[^\s/]+\.[^\s/]+(/\S*)?$")


# ------------------------------------------------------------------ Markdown の読み取り

def lines_outside_code(text):
    """コードのかたまり（```）の外の行を (行番号, 行) で返す。行の中のコード（`…`）は取り除く。"""
    for number, line in outside_fences(text):
        yield number, re.sub(r"`[^`]*`", "", line)


def code_blocks(text, language):
    """```language のかたまりの中身を返す。"""
    return re.findall(rf"^```{language}\n(.*?)^```", text, re.S | re.M)


def anchors_of(path: Path) -> set:
    slugger, found = GithubSlugger(), set()
    for _, line in outside_fences(path.read_text(encoding="utf-8")):
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            found.add(slugger.slug(m.group(1)))
    return found


def outside_fences(text):
    """コードのかたまり（```）の外の行を (行番号, 行) で返す（行の中はそのまま）。"""
    inside = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
        elif not inside:
            yield number, line


def shown(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_DIR))
    except ValueError:
        return path.name


def check_links(md: Path) -> list:
    """md の中の相対リンクと外部リンクを調べて、問題の一覧を返す（なければ空）。"""
    problems = []
    for number, line in lines_outside_code(md.read_text(encoding="utf-8")):
        for target in LINK.findall(line):
            where = f"{shown(md)}:{number} {target}"
            if re.match(r"https?://", target):
                if not EXTERNAL.match(target):
                    problems.append(f"{where}：外部の URL の形が違う")
                continue
            path, _, fragment = target.partition("#")
            dest = (md.parent / urllib.parse.unquote(path)).resolve() if path else md.resolve()
            if not dest.exists():
                problems.append(f"{where}：飛び先のファイルがない")
            elif fragment:
                if dest.is_dir():
                    problems.append(f"{where}：フォルダーに飛び先の見出しは付けられない")
                elif dest.suffix == ".md":
                    if urllib.parse.unquote(fragment) not in anchors_of(dest):
                        problems.append(f"{where}：飛び先の見出しがない")
                elif dest.suffix == ".html":
                    html = dest.read_text(encoding="utf-8")
                    if f'"id": "{fragment}"' not in html and f'id="{fragment}"' not in html:
                        problems.append(f"{where}：HTML に id がない")
    return problems


def guide_texts():
    return {name: (GUIDE / name).read_text(encoding="utf-8") for name in GUIDE_FILES}


# ------------------------------------------------------------------ 手順書

class GuideTest(unittest.TestCase):
    def test_guide_files_exist_and_nothing_else_is_in_guide(self):
        found = sorted(str(p.relative_to(GUIDE)) for p in GUIDE.rglob("*") if p.is_file() and not p.name.startswith("."))
        self.assertEqual(found, sorted(GUIDE_FILES), "guide/ には、この9つの Markdown だけを置く（画像は置かない）")

    def test_guide_links_resolve(self):
        problems = []
        total = 0
        for name in GUIDE_FILES:
            md = GUIDE / name
            problems += check_links(md)
            total += sum(len(LINK.findall(line)) for _, line in lines_outside_code(md.read_text(encoding="utf-8")))
        self.assertEqual(problems, [])
        self.assertGreater(total, 60, "リンクを数えられていない")

    def test_link_checker_catches_broken_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "x.md"
            md.write_text("# 見出し\n\n[a](nothing.md) [b](#ない) [c](#見出し) [d](https://x) `[e](no.md)`\n"
                          "```\n[f](no.md)\n```\n", encoding="utf-8")
            problems = check_links(md)
        self.assertEqual(len(problems), 3, problems)   # a、b、d（c と、コードの中の e・f は問題にしない）

    def test_github_anchor_matches_known_cases(self):
        self.assertEqual(github_anchor("3-4. Cosmos DB（NoSQL）"), "3-4-cosmos-dbnosql")
        self.assertEqual(github_anchor("4. 武将をチームで作った AI Search と Foundry につなぐ"),
                         "4-武将をチームで作った-ai-search-と-foundry-につなぐ")
        self.assertEqual(github_anchor("5. 補助：az で作る"), "5-補助az-で作る")
        self.assertEqual(github_anchor("`.env.local` を作る"), "envlocal-を作る")

    def test_placeholders_are_in_code(self):
        """`<org>` のような山かっこは、コードの中にだけ書く（外に書くと HTML のタグとして消える）。"""
        for name, text in guide_texts().items():
            for number, line in lines_outside_code(text):
                self.assertIsNone(re.search(r"<[^\s>]+>", line), f"{name}:{number} {line}")

    def test_wording(self):
        """呼び方（進行役・参加者・ハンズオン資料）と、特定の研修の言葉・移植前の名前が残っていない。"""
        parts = [("講", "師"), ("受", "講"), ("講", "義"), ("持ち", "帰り"), ("宿", "題"), ("授", "業"), ("サポ", "ート"),
                 ("予", "行"), ("hotel", "_team"), ("set", "_group"), ("HANDSON", "_TEAM"), ("sthotel", ""), ("hotel-", "1105"),
                 ("work", "shop.env"), ("work", "shop.local.env"), ("team", "<team>"), ("local", "-env"), ("MicrosoftOfficial", "Repo")]
        pattern = re.compile("|".join(a + b for a, b in parts))
        group = re.compile("(?<![仕取番])" + "組" + "(?![みむんまめ織合成立])")   # 「組」（チームごとの名前の仕組み）
        for name, text in guide_texts().items():
            for number, line in enumerate(text.splitlines(), 1):
                self.assertIsNone(pattern.search(line), f"{name}:{number} {line}")
                self.assertIsNone(group.search(line), f"{name}:{number} {line}")

    def test_no_screenshots(self):
        for name, text in guide_texts().items():
            self.assertNotIn("![", text, f"{name} に画像がある")
            self.assertNotRegex(text, r"\]\([^)]*(?:img/|\.png|\.jpg|\.jpeg|\.gif)", f"{name} に画像のリンクがある")

    def test_no_environment_specific_values(self):
        """サブスクリプション ID・Repo の URL（ホテルのデータを除く）・日付が、手順書に出ていない。"""
        guid = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
        date = re.compile(r"\b20\d\d[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}/\d{1,2}\b")
        allowed_url = ("https://github.com/dmasubuchi/azure-search-sample-data-ja/blob/82c5f4a/",)
        for name, text in guide_texts().items():
            self.assertIsNone(guid.search(text), name)
            self.assertIsNone(date.search(re.sub(r"--model-version \S+", "", text)), f"{name} に日付がある")   # モデルの版は日付の形
            for url in re.findall(r"https://github\.com/\S+", text):
                self.assertTrue(url.startswith(allowed_url), f"{name}: {url}")

    def test_vector_paste_instructions_match_query_txt(self):
        """query.txt は [ から ] まで（4-4）。5-6 は、見本の [ここにベクトルの数を貼る] ごと、それに置き換える（[[…]] にしない）。"""
        text = guide_texts()["hotel.md"]
        self.assertEqual(text.count("`[ここにベクトルの数を貼る]` を"), 3)
        self.assertIn("4-4 でコピーしたベクトル（`[` から `]` まで）に置き換えます", text)
        self.assertNotIn("`[` と `]` の間", text)

    def test_hotel_data_is_pinned_to_the_commit(self):
        text = guide_texts()["hotel.md"]
        self.assertIn("https://github.com/dmasubuchi/azure-search-sample-data-ja/blob/82c5f4a/hotels/ja/HotelsData_toAzureBlobs_ja.json", text)
        self.assertNotIn("/blob/main/", text)

    def test_commands_in_the_guide_exist(self):
        subcommands = {"names", "check-names", "health", "env"}
        for name, text in guide_texts().items():
            for sub in re.findall(r"team\.py (\w[\w-]*)", text):
                self.assertIn(sub, subcommands, f"{name}: team.py {sub}")
            for role in re.findall(r"--role (\w+)", text):
                self.assertIn(role, {"builder", "member"}, f"{name}: --role {role}")
            for script in re.findall(r"python3? ((?:tools|basic/tools|applied/tools)/[\w./-]+\.py)", text):
                self.assertTrue((REPO_DIR / script).is_file(), f"{name}: {script}")
            for req in re.findall(r"pip install -r (\S+\.txt)", text):
                self.assertTrue((REPO_DIR / req).is_file(), f"{name}: {req}")

    def test_resource_names_follow_team_py(self):
        """手順に書いたリソースの名前の型が、team.py の決め方と同じ。"""
        names = make_names("orgx", "teamx")
        templates = [value.replace("orgx", "<org>").replace("teamx", "<team>")
                     for value in (names.resource_group, names.storage, names.search, names.cosmos, names.foundry)]
        self.assertEqual(templates, ["rg-<org>-<team>", "st<org><team>", "srch-<org>-<team>", "cosmos-<org>-<team>", "ai-<org>-<team>"])
        texts = guide_texts()
        for template in templates:
            self.assertIn(template, texts["setup/azure-setup.md"])
        for template in (templates[0], templates[1], templates[2]):
            self.assertIn(template, texts["hotel.md"])
        # 例の名前（組織 acme・チーム red）は、names の出力と同じ
        example = make_names("acme", "red")
        for value in (example.resource_group, example.storage, example.search, example.cosmos, example.foundry):
            self.assertIn(value, texts["setup/azure-setup.md"])

    def test_health_sample_matches_team_py(self):
        """azure-setup.md の health の例が、team.py の表示の形と同じ。"""
        n = make_names("acme", "red")
        rows = [team.Row(team.OK, f"リソース グループ {n.resource_group}", "Succeeded"),
                team.Row(team.OK, f"Storage {n.storage}", "Standard_LRS・StorageV2"),
                team.Row(team.OK, f"AI Search {n.search}", "running"),
                team.Row(team.OK, "AI Search 価格レベル", "Basic"),
                team.Row(team.OK, "AI Search セマンティック ランカー", "Free"),
                team.Row(team.OK, f"Foundry {n.foundry}"),
                team.Row(team.OK, "デプロイ text-embedding-3-small", "GlobalStandard・容量50・Succeeded"),
                team.Row(team.OK, "デプロイ gpt-5-mini", "GlobalStandard・容量20・Succeeded")]
        # 手順の3-7は、インデックスをまだ作っていない時点なので、文書の数は4つとも「まだない」
        counts = team.Counts(items=tuple(team.IndexCount(expect) for expect in team.INDEX_EXPECTS))
        shown, _ = team.health_text("red", rows, counts)
        self.assertIn(shown, guide_texts()["setup/azure-setup.md"])

    def test_evaluation_guide_commands_match_the_tools(self):
        """評価の手順書に書いたコマンドの引数（オプション・データ・方式）を、道具の本物の引数の定義と照らす。"""
        parsers = {"check_questions": check_questions, "eval_search": eval_search, "eval_report": eval_report,
                   "spot_check": spot_check}
        text = guide_texts()["evaluation.md"]
        seen = set()
        for name, module in parsers.items():
            accepted = set(module.build_parser()._option_string_actions)
            for rest in re.findall(rf"tools/{name}\.py([^`\n]*)", text):
                seen.add(name)
                for option in re.findall(r"(?<!\S)(--[a-z][\w-]*)", rest):
                    self.assertIn(option, accepted, f"{name}: {option}")
                for dataset in re.findall(r"--dataset (\w+)", rest):
                    self.assertIn(dataset, DATASETS, f"{name}: --dataset {dataset}")
                for methods in re.findall(r"--methods ([\w,+]+)", rest):
                    self.assertTrue(set(methods.split(",")) <= set(METHODS), f"{name}: --methods {methods}")
        self.assertEqual(seen, set(parsers), "4つの道具が、すべて手順書に出ている")
        # 評価の道具でない道具（応用編の build_hr_index.py など）のオプションは、その道具のソースの argparse にある
        for script, option in re.findall(r"python (applied/tools/\w+\.py) (--[a-z][\w-]*)", text):
            self.assertIn(f'"{option}"', (REPO_DIR / script).read_text(encoding="utf-8"), f"{script}: {option}")
        text = re.sub(r"python applied/tools/\w+\.py --[a-z][\w-]*", "", text)
        everywhere = set().union(*(set(m.build_parser()._option_string_actions) for m in parsers.values()))
        for option in set(re.findall(r"(?<![\w-])(--[a-z][\w-]*)", text)):   # 文の中のオプション（--limit など）も、どれかの道具にある
            self.assertIn(option, everywhere, option)

    def test_evaluation_guide_fetch_count_and_hr_status_step(self):
        """検索で取る件数（k によらず FETCH 件）と、人事の準備の「見てよい人」の確かめは、手順書に書いてある。"""
        text = guide_texts()["evaluation.md"]
        self.assertEqual(FETCH, eval_search.MAX_K)                       # k の上限と、1回に取る件数が同じ
        self.assertIn(f"`--k` によらず {FETCH} 件", text)
        self.assertIn("python applied/tools/build_hr_index.py --status", text)
        self.assertIn("見てよい人", text.split("## 2. 測る順番")[0])        # 準備（1 章）の中にある

    def test_evaluation_guide_matches_prices_example_and_health_targets(self):
        """単価の項目名は config/prices.example.json と、件数の目安は team.py の INDEX_EXPECTS と同じ。"""
        text = guide_texts()["evaluation.md"]
        example = json.loads((REPO_DIR / "config" / "prices.example.json").read_text(encoding="utf-8"))
        for field in ("currency", "checked", "semantic_per_1000", "embedding_per_1m_tokens", "search_per_1000"):
            self.assertIn(field, example, field)
            self.assertIn(f"`{field}`", text, field)
        for expect in team.INDEX_EXPECTS:
            self.assertIn(f"`{expect.index}` {expect.wanted}", text, expect.index)

    def test_evaluation_guide_permission_counts_match_the_questions(self):
        """人事の権限の質問の数（正解のない質問・正解のある質問）が、質問のファイルと同じ。"""
        text = guide_texts()["evaluation.md"]
        questions = json.loads((REPO_DIR / "evaluation" / "hr_questions.json").read_text(encoding="utf-8"))
        permission = [q for q in questions if q["type"] == "permission"]
        empty = sum(1 for q in permission if not q["answer_ids"])
        answered = len(permission) - empty
        self.assertIn(f"（種類 `permission`、{len(permission)}問）は、{empty}問に正解の文書がなく", text)
        self.assertIn(f"{answered}問は求人票が正解です", text)
        self.assertIn(f"正解のある{answered}問は、平均にも入れ", text)
        self.assertIn(f"正解のある{answered}問だけの平均になります（カッコの中も{answered}）", text)
        self.assertGreater(answered, 0)

    def test_evaluation_guide_edit_points_exist(self):
        """自分の組織のデータで動かすために変える場所として書いた名前が、コードに本当にある。"""
        text = guide_texts()["evaluation.md"]
        sources = {path: (REPO_DIR / path).read_text(encoding="utf-8") for path in
                   ("tools/evallib/datasets.py", "tools/evallib/questions.py", "tools/spot_check.py")}
        places = {"tools/evallib/datasets.py": ["SPECS"],
                  "tools/evallib/questions.py": ["DATASETS", "TYPE_TARGETS", "QUESTION_FILES", "DATA_FILES", "def ids_of", "def dataset_check"],
                  "tools/spot_check.py": ["DATASET_LABEL", "DOC_BUILDERS", "def build_context", "TYPE_LABEL"]}
        for path, names in places.items():
            self.assertIn(f"`{path}`", text, path)
            for name in names:
                self.assertIn(name, sources[path], f"{path}: {name}")
                self.assertIn(name.removeprefix("def "), text, f"{path}: {name}")

    def test_json_blocks_parse(self):
        """貼り付ける JSON が読める（ベクトルを貼る場所の見本は除く）。"""
        count = 0
        for name, text in guide_texts().items():
            for block in code_blocks(text, "json"):
                if "ここに" in block:
                    continue
                json.loads(block)
                count += 1
        self.assertGreaterEqual(count, 20)

    def test_hotel_indexes_cover_every_field_of_the_data(self):
        """インデックスの項目が、日本語版のホテルのデータ（コミット 82c5f4a）の全項目と、入れ子の中まで同じ。"""
        hotel = {"Address", "Category", "Category_ja", "Description", "Description_fr", "Description_ja", "HotelId",
                 "HotelName", "HotelName_ja", "IsDeleted", "LastRenovationDate", "Location", "ParkingIncluded", "Rating",
                 "Rooms", "Tags", "Tags_ja"}
        room = {"BaseRate", "BedOptions", "Description", "Description_fr", "Description_ja", "SleepsCount", "SmokingAllowed",
                "Tags", "Type", "Type_ja"}
        address = {"City", "Country", "PostalCode", "StateProvince", "StreetAddress"}
        indexes = {}
        for block in code_blocks(guide_texts()["hotel.md"], "json"):
            doc = json.loads(block) if "ここに" not in block else {}
            if "fields" in doc and "name" in doc:
                indexes[doc["name"]] = doc
        self.assertEqual(sorted(indexes), ["hotels-blob", "hotels-cosmos"])
        for name, doc in indexes.items():
            fields = {f["name"]: f for f in doc["fields"]}
            expected = hotel | ({"DescriptionVector"} if name == "hotels-cosmos" else set())
            self.assertEqual(set(fields), expected, name)
            self.assertEqual({f["name"] for f in fields["Rooms"]["fields"]}, room, name)
            self.assertEqual({f["name"] for f in fields["Address"]["fields"]}, address, name)
            self.assertTrue(fields["HotelId"]["key"], name)
        cosmos = {f["name"]: f for f in indexes["hotels-cosmos"]["fields"]}
        self.assertEqual(cosmos["DescriptionVector"]["dimensions"], 1536)
        self.assertEqual(cosmos["DescriptionVector"]["vectorSearchProfile"], indexes["hotels-cosmos"]["vectorSearch"]["profiles"][0]["name"])

    def test_hotel_queries_use_fields_that_exist(self):
        """3 章の検索クエリが、インデックス hotels-blob の項目（フィルター可・並べ替え可・集計可）だけを使う。"""
        text = guide_texts()["hotel.md"]
        index = next(json.loads(b) for b in code_blocks(text, "json") if '"name":"hotels-blob"' in b.replace(" ", ""))
        fields = {f["name"]: f for f in index["fields"]}
        rooms = {f["name"]: f for f in fields["Rooms"]["fields"]}
        section3 = text[text.index("## 3. 6つの機能を試す"):text.index("## 4. Cosmos DB のベクトル検索")]
        for block in code_blocks(section3, "json"):
            query = json.loads(block)
            for name in query.get("select", "").split(","):
                if name:
                    self.assertIn(name.split("/")[0], fields, name)
            orderby = query.get("orderby", "")
            for part in ([] if "geo.distance" in orderby else orderby.split(",")):   # 距離順は式なので、項目の確認から除く
                if part:
                    self.assertTrue(fields[part.split()[0]]["sortable"], part)
            for facet in query.get("facets", []):
                self.assertTrue(fields[facet.split(",")[0]]["facetable"], facet)
            for name in query.get("searchFields", "").split(","):
                if name:
                    self.assertTrue(fields[name]["searchable"], name)
            filter_text = query.get("filter", "")
            for name in re.findall(r"\b(Rating|MinRoomRate|HotelId)\b", filter_text):
                self.assertIn(name, fields)
            for name in re.findall(r"r/(\w+)", filter_text):
                self.assertTrue(rooms[name]["filterable"], name)


# ------------------------------------------------------------------ 偽物の HTTP

class FakeResponse(io.BytesIO):
    pass


def respond(payload) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def write_env(directory: Path, text: str) -> Path:
    path = Path(directory) / "member.env"
    path.write_text(text, encoding="utf-8")
    return path


# メンバーの設定（検索だけのキー。Storage の項目なし）。キーの値は見本
MEMBER_ENV = (
    "AZURE_SEARCH_ENDPOINT=https://srch-test.search.windows.net\n"
    "AZURE_SEARCH_API_KEY=query-key-from-the-file\n"
    "AZURE_SEARCH_KEY_ROLE=query\n"
    "AZURE_OPENAI_ENDPOINT=https://ai-test.openai.azure.com/\n"
    "AZURE_OPENAI_API_KEY=openai-key-from-the-file\n"
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small\n"
    "AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-5-mini\n"
    "EMBEDDING_DIMENSIONS=8\n"
)


def run_tool(main, argv, env_file, decoys=None):
    """main(argv) を、WORKSHOP_ENV_FILE を env_file にして動かす。標準出力を文字で返す。decoys は端末の環境変数の見本。"""
    environ = {"WORKSHOP_ENV_FILE": str(env_file), **(decoys or {})}
    out = io.StringIO()
    with mock.patch.dict(os.environ, environ), contextlib.redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


class SearchDemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_file = write_env(self.tmp.name, MEMBER_ENV)
        self.requests = []

    def fake(self, status=200):
        def urlopen(req, timeout=None):
            self.requests.append(req)
            if status != 200:
                raise urllib.error.HTTPError(req.full_url, status, "error", {}, io.BytesIO(b"{}"))
            return respond({"@odata.count": 3, "value": [
                {"title": "JOB-REQ042-v3.pdf", "kind": "job_posting", "chunk": "求人票\n本文の先頭です", "@search.score": 1.5},
                {"title": "CV-APP-0471.docx", "kind": "resume", "chunk": "職務経歴", "@search.rerankerScore": 2.25}]})
        return urlopen

    def run_demo(self, argv=("--no-pause",), env_file=None, decoys=None):
        with mock.patch("urllib.request.urlopen", side_effect=self.fake()):
            return run_tool(search_demo.main, list(argv), env_file or self.env_file, decoys)

    def test_search_demo_reads_env_local(self):
        """.env.local（メンバーの検索だけのキー）の接続先とキーで、hr-docs に5回検索する。端末の環境変数は読まない。"""
        decoys = {"AZURE_SEARCH_ENDPOINT": "https://decoy.search.windows.net", "AZURE_SEARCH_API_KEY": "decoy-key"}
        code, out = self.run_demo(("--no-pause", "--q", "面接の評価"), decoys=decoys)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.requests), 5)
        for req in self.requests:
            self.assertTrue(req.full_url.startswith("https://srch-test.search.windows.net/indexes/hr-docs/docs/search?api-version="), req.full_url)
            self.assertEqual(req.get_header("Api-key"), "query-key-from-the-file")
            self.assertEqual(json.loads(req.data)["search"], "面接の評価")
        bodies = [json.loads(r.data) for r in self.requests]
        self.assertNotIn("filter", bodies[0])
        self.assertEqual(bodies[1]["filter"], "kind eq 'resume'")
        self.assertEqual(bodies[2]["filter"], "allowed/any(a: a eq 'role:recruiter')")
        self.assertEqual(bodies[3]["filter"], "allowed/any(a: a eq 'role:employee')")
        self.assertEqual((bodies[4]["queryType"], bodies[4]["semanticConfiguration"]), ("semantic", "applied-semantic"))
        self.assertNotIn("queryType", bodies[0])   # セマンティックは 5 段目だけ
        self.assertNotIn("decoy", out)
        self.assertNotIn("query-key-from-the-file", out)
        self.assertIn("3件", out)
        self.assertIn("1位  JOB-REQ042-v3.pdf", out)
        self.assertIn("求人票 本文の先頭です", out)   # チャンクの先頭が、1行で出る

    def test_search_demo_pauses_between_steps(self):
        with mock.patch("builtins.input", return_value="") as asked:
            code, _ = self.run_demo(argv=())
        self.assertEqual((code, asked.call_count), (0, 4))

    def test_search_demo_without_env_file_stops_with_guidance(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.fake()) as urlopen:
            code, out = run_tool(search_demo.main, ["--no-pause"], Path(self.tmp.name) / "nothing.env")
        self.assertEqual(code, 1)
        self.assertIn("team.py env", out)
        urlopen.assert_not_called()

    def test_search_demo_without_search_key_stops_with_guidance(self):
        broken = write_env(self.tmp.name, "AZURE_SEARCH_ENDPOINT=https://srch-test.search.windows.net\n")
        code, out = self.run_demo(env_file=broken)
        self.assertEqual(code, 1)
        self.assertIn("AZURE_SEARCH_API_KEY", out)
        self.assertEqual(self.requests, [])

    def test_search_demo_explains_missing_index(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.fake(status=404)):
            code, out = run_tool(search_demo.main, ["--no-pause"], self.env_file)
        self.assertEqual(code, 1)
        self.assertIn("build_hr_index.py", out)

    def test_search_demo_explains_403_by_step(self):
        """403 は、セマンティック ランカーの段（5）では、無料枠の使い切りも原因として言う。ほかの段ではキーだけ。"""
        def urlopen(req, timeout=None):
            self.requests.append(req)
            if json.loads(req.data).get("queryType") == "semantic":
                raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, io.BytesIO(b"{}"))
            return respond({"@odata.count": 0, "value": []})
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            code, out = run_tool(search_demo.main, ["--no-pause"], self.env_file)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.requests), 5)
        self.assertEqual(out.count("エラー 403"), 1)
        self.assertIn("無料枠", out)
        self.assertIn("キーが合っているか", out)
        with mock.patch("urllib.request.urlopen", side_effect=self.fake(status=403)):
            code, out = run_tool(search_demo.main, ["--no-pause"], self.env_file)
        self.assertEqual(out.count("エラー 403：キーが合いません"), 4)   # 1〜4 段は、キーだけを言う
        self.assertIn("無料枠", out)                                       # 5 段目は、無料枠も言う

    def test_default_env_file_is_dot_env_local_in_the_repo(self):
        """WORKSHOP_ENV_FILE がないときの設定ファイルは、Repo 直下の .env.local（中身は読まない）。"""
        for module in (search_demo, hotel_vectors):
            with mock.patch.dict(os.environ):
                os.environ.pop("WORKSHOP_ENV_FILE", None)
                self.assertEqual(module.env_path(), REPO_DIR / ".env.local", module.__name__)
            with mock.patch.dict(os.environ, {"WORKSHOP_ENV_FILE": "/somewhere/else.env"}):
                self.assertEqual(module.env_path(), Path("/somewhere/else.env"), module.__name__)

    def test_search_demo_uses_only_the_standard_library(self):
        tree = ast.parse((REPO_DIR / "tools" / "search_demo.py").read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertTrue(imported <= set(sys.stdlib_module_names), imported)


class HotelVectorsTest(unittest.TestCase):
    DIMS = 8

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.env_file = write_env(self.dir, MEMBER_ENV)
        self.out = self.dir / "out"
        self.requests = []

    def fake(self, fail_first=None):
        """入力の文の数だけ、決まった形のベクトルを返す。fail_first があれば、最初の呼び出しだけそのエラーにする。"""
        def urlopen(req, timeout=None):
            self.requests.append(req)
            if fail_first and len(self.requests) == 1:
                raise fail_first
            texts = json.loads(req.data)["input"]
            return respond({"data": [{"index": i, "embedding": [(len(t) + i + k) / 7 for k in range(self.DIMS)]}
                                     for i, t in enumerate(texts)]})
        return urlopen

    def hotels_file(self, count=30):
        hotels = [{"HotelId": str(i + 1), "HotelName": f"Hotel {i + 1}", "Description_ja": f"{i + 1} 番目のホテルの説明です。海が近い。",
                   "Rating": 3.5, "Rooms": [{"BaseRate": 99.5}], "Location": {"type": "Point", "coordinates": [1.0, 2.0]}}
                  for i in range(count)]
        path = self.dir / "hotels.json"
        path.write_text(json.dumps(hotels, ensure_ascii=False), encoding="utf-8")
        return path

    def run_tool(self, argv, env_file=None, **fake_options):
        with mock.patch("urllib.request.urlopen", side_effect=self.fake(**fake_options)), mock.patch("time.sleep") as sleep:
            code, out = run_tool(hotel_vectors.main, argv, env_file or self.env_file,
                                 {"AZURE_OPENAI_API_KEY": "decoy-key", "AZURE_OPENAI_ENDPOINT": "https://decoy.example"})
        self.sleep = sleep
        return code, out

    def test_hotels_adds_id_and_vector(self):
        path = self.hotels_file()
        code, out = self.run_tool(["hotels", str(path), "--out", str(self.out)])
        self.assertEqual(code, 0, out)
        written = json.loads((self.out / "hotels_cosmos.json").read_text(encoding="utf-8"))
        self.assertEqual(len(written), 30)
        original = json.loads(path.read_text(encoding="utf-8"))
        for doc, hotel in zip(written, original):
            self.assertEqual(doc["id"], hotel["HotelId"])           # Cosmos DB の id は HotelId と同じ
            self.assertEqual(len(doc["DescriptionVector"]), self.DIMS)
            self.assertEqual({k: v for k, v in doc.items() if k not in ("id", "DescriptionVector")}, hotel)   # 元の項目はそのまま
        self.assertTrue(all(len(str(x).split(".")[-1]) <= 6 for x in written[0]["DescriptionVector"]))   # 小数は6桁まで
        self.assertEqual(len(self.requests), 2)                     # 25件と5件の2回
        self.assertEqual([len(json.loads(r.data)["input"]) for r in self.requests], [25, 5])
        body = json.loads(self.requests[0].data)
        self.assertEqual((body["model"], body["dimensions"]), ("text-embedding-3-small", self.DIMS))
        self.assertEqual(json.loads(self.requests[0].data)["input"][0], original[0]["Description_ja"])
        for req in self.requests:
            self.assertEqual(req.full_url, "https://ai-test.openai.azure.com/openai/v1/embeddings")   # .env.local の接続先
            self.assertEqual(req.get_header("Api-key"), "openai-key-from-the-file")
        self.assertNotIn("openai-key-from-the-file", out)

    def test_hotels_reads_the_downloaded_file_from_the_output_folder_by_default(self):
        """入力を書かないと、書き出し先のフォルダーの HotelsData_toAzureBlobs_ja.json を読む（手順書の `hotels` だけの1行）。"""
        self.out.mkdir()
        (self.out / hotel_vectors.HOTELS_FILE).write_text(self.hotels_file(3).read_text(encoding="utf-8"), encoding="utf-8")
        code, out = self.run_tool(["hotels", "--out", str(self.out)])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(json.loads((self.out / "hotels_cosmos.json").read_text(encoding="utf-8"))), 3)

    def test_hotels_without_the_downloaded_file_says_where_to_put_it(self):
        code, out = self.run_tool(["hotels", "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn(hotel_vectors.HOTELS_FILE, out)
        self.assertEqual(self.requests, [])

    def test_hotels_file_is_small_enough_for_upload_items(self):
        """本物の次元（1536）でも、50件で約1MB。Upload Items の上限（2MB 未満）に収まる。"""
        import random
        rng = random.Random(1)
        hotels = json.loads(self.hotels_file(50).read_text(encoding="utf-8"))
        docs = [{"id": h["HotelId"], **h, "DescriptionVector": [round(rng.gauss(0, 0.0255), 6) for _ in range(1536)]} for h in hotels]
        size = len(json.dumps(docs, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertLess(size, hotel_vectors.MAX_BYTES)

    def test_hotels_stops_when_the_file_is_too_big(self):
        path = self.hotels_file(3)
        with mock.patch.object(hotel_vectors, "MAX_BYTES", 100):
            code, out = self.run_tool(["hotels", str(path), "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("--decimals", out)
        self.assertFalse((self.out / "hotels_cosmos.json").exists())

    def test_hotels_rejects_a_file_without_japanese_descriptions(self):
        path = self.dir / "english.json"
        path.write_text(json.dumps([{"HotelId": "1", "Description": "English only"}]), encoding="utf-8")
        code, out = self.run_tool(["hotels", str(path), "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("Description_ja", out)
        self.assertEqual(self.requests, [])

    def test_query_writes_a_vector_to_paste(self):
        code, out = self.run_tool(["query", "海の近くのホテル", "--out", str(self.out)])
        self.assertEqual(code, 0, out)
        vector = json.loads((self.out / "query.txt").read_text(encoding="utf-8"))
        self.assertEqual(len(vector), self.DIMS)
        self.assertEqual(json.loads(self.requests[0].data)["input"], ["海の近くのホテル"])
        code, _ = self.run_tool(["query", "町の中心", "--name", "city", "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "city.txt").is_file())

    def test_query_name_cannot_leave_the_folder(self):
        code, out = self.run_tool(["query", "海", "--name", "../x", "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertEqual(self.requests, [])

    def test_waits_and_retries_when_azure_openai_is_busy(self):
        busy = urllib.error.HTTPError("https://x", 429, "Too Many Requests", {"retry-after": "7"}, io.BytesIO(b"{}"))
        code, out = self.run_tool(["query", "海", "--out", str(self.out)], fail_first=busy)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.requests), 2)
        self.sleep.assert_called_once_with(7)

    def test_missing_settings_stop_with_guidance(self):
        code, out = self.run_tool(["query", "海"], env_file=self.dir / "nothing.env")
        self.assertEqual(code, 1)
        self.assertIn("team.py env", out)
        broken = write_env(self.dir, "AZURE_OPENAI_ENDPOINT=https://ai-test.openai.azure.com/\n")
        code, out = self.run_tool(["query", "海"], env_file=broken)
        self.assertEqual(code, 1)
        self.assertIn("AZURE_OPENAI_API_KEY", out)
        self.assertEqual(self.requests, [])

    def test_wrong_vector_length_is_reported(self):
        def short(req, timeout=None):
            return respond({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
        with mock.patch("urllib.request.urlopen", side_effect=short):
            code, out = run_tool(hotel_vectors.main, ["query", "海", "--out", str(self.out)], self.env_file)
        self.assertEqual(code, 1)
        self.assertIn("EMBEDDING_DIMENSIONS", out)

    def test_hotel_vectors_uses_only_the_standard_library(self):
        tree = ast.parse((REPO_DIR / "tools" / "hotel_vectors.py").read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertTrue(imported <= set(sys.stdlib_module_names), imported)


if __name__ == "__main__":
    unittest.main()
