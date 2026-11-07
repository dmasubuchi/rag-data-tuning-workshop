"""tools/spot_check.py（人が抜き取りで確かめる一覧を、1枚の HTML にする道具）の試験。

通信しない。人事・武将は Repo にある本物の質問とデータを読む。ホテルのデータは Repo に写していないので、
試験の中で作った小さな見本を使う。一時のファイルは一時フォルダーに書く。

ページの中の JavaScript の動き（チェックの排他・数の更新・書き出し・保存・コピー・再読み込みで戻る・localStorage が使えない環境）は、
この試験では確かめない（ブラウザがいる）。ブラウザ（Chromium、file:// で開く）で手で確かめた。ここで確かめるのは、
JavaScript に質問のデータが入っていないこと・HTML のエスケープ・外部の読み込みがないことなど、Python 側で決まる部分。
"""
import collections
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tools"))

import spot_check  # noqa: E402
from evallib import questions as ev  # noqa: E402

HR_QUESTIONS = ev.load_questions(ev.QUESTION_FILES["hr"])
HR_MANIFEST = ev.load_data("hr")
SENGOKU_QUESTIONS = ev.load_questions(ev.QUESTION_FILES["sengoku"])
SENGOKU_DATA = ev.load_data("sengoku")

EVIL = "<img src=x onerror=alert(1)>"


def hotel(hotel_id, name_ja, name_en, description_ja, rating=4.0, rooms=None):
    return {
        "HotelId": hotel_id, "HotelName": name_en, "HotelName_ja": name_ja,
        "Description": "An English description.", "Description_ja": description_ja,
        "Category": "Boutique", "Category_ja": "ブティック", "Tags": ["bar"], "Tags_ja": ["バー"],
        "ParkingIncluded": True, "IsDeleted": False, "LastRenovationDate": "2020-01-01T00:00:00Z", "Rating": rating,
        "Address": {"StreetAddress": "1 Main St", "City": "Seattle", "StateProvince": "WA", "PostalCode": "98101", "Country": "USA"},
        "Rooms": rooms if rooms is not None else [
            {"Description": "Budget Room", "Description_ja": "バジェットルーム", "Type": "Budget Room", "Type_ja": "バジェットルーム",
             "BaseRate": 80.0, "BedOptions": "1 King Bed", "SleepsCount": 2, "SmokingAllowed": False, "Tags": ["tv"]},
            {"Description": "Suite", "Description_ja": "スイート", "Type": "Suite", "Type_ja": "スイート",
             "BaseRate": 250.0, "BedOptions": "2 Queen Beds", "SleepsCount": 4, "SmokingAllowed": True, "Tags": ["jacuzzi tub"]},
        ],
    }


HOTELS = [
    hotel("1", "ひのでホテル", "Hinode Hotel", "海が見える静かな宿です。ペットも受け入れています。朝食は無料です。", 4.6),
    hotel("2", "つきのホテル", "Tsuki Hotel", "駅から歩いてすぐ。無料Wi-Fiがあります。", 3.9),
    hotel("3", "ほしのホテル", "Hoshi Hotel", "屋上のバーから街を一望できます。", 4.8),
]


def hotel_questions():
    kinds = ["paraphrase", "paraphrase", "proper-noun", "condition", "ja-en", "amenity", "condition", "amenity"]
    out = []
    for i, kind in enumerate(kinds, 1):
        q = {"qid": f"hotel-{i:02d}", "question": f"見本の質問 {i}", "type": kind, "answer_ids": ["1"], "why": "見本の理由"}
        if kind == "condition":
            q["condition"] = {"Rating": {"ge": 4.5}, "Rooms/BaseRate": {"le": 100}}
            q["answer_ids"] = ["1"]
        else:
            q["evidence"] = {"1": "ペットも受け入れています"}
        out.append(q)
    return out


def make(dataset, questions, data, n=10, seed=1, **kwargs):
    return spot_check.make_sheet(dataset, questions, data, n=n, seed=seed, **kwargs)


def qids(picked):
    return [q["qid"] for q in picked]


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = spot_check.main(list(args))
        except SystemExit as exit_:   # argparse の誤り
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class SelectionTest(unittest.TestCase):
    def test_same_seed_same_questions(self):
        first = spot_check.select_questions("hr", HR_QUESTIONS, 10, 1)
        second = spot_check.select_questions("hr", HR_QUESTIONS, 10, 1)
        self.assertEqual(qids(first), qids(second))
        self.assertEqual(len(first), 10)
        # 質問の並びが変わっても、同じ質問が選ばれる（質問の qid で決まる）
        shuffled = spot_check.select_questions("hr", list(reversed(HR_QUESTIONS)), 10, 1)
        self.assertEqual(sorted(qids(shuffled)), sorted(qids(first)))
        # 1枚の HTML も、同じ seed なら同じ
        self.assertEqual(make("hr", HR_QUESTIONS, HR_MANIFEST)[0], make("hr", HR_QUESTIONS, HR_MANIFEST)[0])

    def test_other_seed_other_questions(self):
        sets = {tuple(sorted(qids(spot_check.select_questions("hr", HR_QUESTIONS, 10, seed)))) for seed in range(1, 6)}
        self.assertGreater(len(sets), 1)

    def test_types_are_spread(self):
        picked = spot_check.select_questions("hr", HR_QUESTIONS, 10, 1)
        counts = collections.Counter(q["type"] for q in picked)
        self.assertEqual(set(counts), set(ev.TYPE_TARGETS["hr"]))
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        # 多い方の種類は、種類の並びの先頭から（paraphrase・proper-noun・numeric・multi-doc が 2 問、scan・permission が 1 問）
        self.assertEqual([counts[t] for t in ev.TYPE_TARGETS["hr"]], [2, 2, 2, 2, 1, 1])
        picked = spot_check.select_questions("hotel", hotel_questions(), 8, 1)
        counts = collections.Counter(q["type"] for q in picked)
        self.assertEqual([counts[t] for t in ("paraphrase", "proper-noun", "condition", "ja-en", "amenity")], [2, 1, 2, 1, 2])

    def test_fewer_than_types_takes_first_types_one_each(self):
        picked = spot_check.select_questions("hr", HR_QUESTIONS, 3, 1)
        self.assertEqual([q["type"] for q in picked], ["paraphrase", "proper-noun", "numeric"])

    def test_small_pool_gives_its_share_to_others(self):
        questions = [{"qid": "a1", "type": "paraphrase"}, {"qid": "n1", "type": "numeric"}, {"qid": "n2", "type": "numeric"},
                     {"qid": "n3", "type": "numeric"}]
        picked = spot_check.select_questions("hr", questions, 3, 1)
        self.assertEqual(collections.Counter(q["type"] for q in picked), {"paraphrase": 1, "numeric": 2})

    def test_n_larger_than_all_takes_all_in_type_order(self):
        picked = spot_check.select_questions("hr", HR_QUESTIONS, 500, 1)
        self.assertEqual(len(picked), 60)
        types = [q["type"] for q in picked]
        self.assertEqual(types, sorted(types, key=list(ev.TYPE_TARGETS["hr"]).index))

    def test_sengoku_uses_intent_as_type(self):
        picked = spot_check.select_questions("sengoku", SENGOKU_QUESTIONS, 10, 1)
        self.assertEqual(collections.Counter(q["type"] for q in picked), {t: 2 for t in ev.SENGOKU_TYPES})


class LocateTest(unittest.TestCase):
    def test_locate_ignores_whitespace_like_the_checker(self):
        text = "年収は 600万円\nから　800万円 です"
        start, end = spot_check.locate(text, "600万円から800万円")
        self.assertEqual(text[start:end], "600万円\nから　800万円")
        self.assertIsNone(spot_check.locate(text, "900万円"))
        self.assertIsNone(spot_check.locate(text, "   "))

    def test_excerpt_cuts_around_the_phrase(self):
        text = "あ" * 100 + "答えの語句" + "い" * 100
        exc = spot_check.excerpt(text, "答えの語句", 60)
        self.assertEqual((exc["before"], exc["hit"], exc["after"]), ("あ" * 60, "答えの語句", "い" * 60))
        self.assertTrue(exc["cut_before"] and exc["cut_after"])
        short = spot_check.excerpt("前の文。答えの語句。後の文。", "答えの語句", 60)
        self.assertFalse(short["cut_before"] or short["cut_after"])

    def test_every_hr_evidence_is_located_in_the_source_text(self):
        """確かめの道具（check_questions）が見つけられる語句は、一覧でも、かならず見つかる（強調できる）。"""
        files = {f["doc_id"]: f for f in HR_MANIFEST["files"]}
        checked = 0
        for q in HR_QUESTIONS:
            for doc_id, phrase in q["evidence"].items():
                text, _ = ev.hr_source_text(doc_id, files[doc_id], ev.HR_CONTENT_DIR)
                self.assertIsNotNone(spot_check.excerpt(text, phrase, 60), f"{q['qid']} {doc_id} {phrase}")
                checked += 1
        self.assertGreaterEqual(checked, 60)


class HrSheetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page, cls.picked, cls.warnings = make("hr", HR_QUESTIONS, HR_MANIFEST)

    def test_has_question_why_and_checks_for_each(self):
        for q in self.picked:
            self.assertIn(q["qid"], self.page)
            self.assertIn(q["question"], self.page)
        self.assertEqual(self.page.count('class="q"'), 10)
        self.assertEqual(self.page.count('type="checkbox"'), 20)       # 正しい・直す × 10 問
        self.assertEqual(self.page.count("<textarea"), 10 + 1)         # メモ × 10 ＋ 書き出し用の欄
        self.assertEqual(self.page.count('<p class="why">'), 10)

    def test_evidence_is_marked_in_the_text(self):
        picked = [q for q in HR_QUESTIONS if q["qid"] == "hr-01"]
        page = make("hr", picked, HR_MANIFEST, n=1)[0]
        self.assertIn("<mark>紹介手数料の手続きは、採用責任者の茂木から別途ご連絡いたします</mark>", page)
        self.assertIn("MAIL-09", page)

    def test_no_phrase_is_missing_in_the_real_data(self):
        self.assertEqual(self.warnings, [])
        self.assertNotIn("class=\"miss\"", self.page)

    def test_summary_shows_dataset_n_seed_and_type_counts(self):
        summary = self.page.split('<section class="summary">')[1].split("</section>")[0]
        self.assertIn("人事", summary)
        self.assertIn("全 60 問", summary)
        self.assertIn("seed", summary)
        self.assertIn(">1<", summary)
        for kind in ev.TYPE_TARGETS["hr"]:
            self.assertIn(kind, summary)

    def test_permission_shows_hidden_documents_apart(self):
        perm = [q for q in HR_QUESTIONS if q["qid"] == "hr-12"]
        page = make("hr", perm, HR_MANIFEST, n=1)[0]
        self.assertIn("見えないはず", page)
        self.assertIn("role:employee", page)
        self.assertEqual(page.count('class="doc hid"'), 2)       # CV-APP-0391・CV-APP-0603
        self.assertIn("<mark>AWS ソリューションアーキテクト アソシエイト</mark>", page)
        self.assertIn("正解の文書：なし", page)

    def card(self, qid):
        picked = [q for q in HR_QUESTIONS if q["qid"] == qid]
        return make("hr", picked, HR_MANIFEST, n=1)[0].split('<article class="q"')[1].split("</article>")[0]

    def test_scan_shows_the_description_the_phrase_line_and_a_link_to_the_image(self):
        page = self.card("hr-05")
        self.assertIn("内定承諾書。氏名の手書きと認印、会社の受付印", page)          # scans.json の what
        self.assertIn(spot_check.SCAN_CODE_LABEL, page)
        self.assertIn("<mark>2026年12月1日</mark>", page)
        self.assertIn("OCR", page)
        # make_scans.py の Python のコードは出さない（印字する文字だけ）
        for code in ("def make_", "d.text(", "Image.new", "fill=INK", "mincho"):
            self.assertNotIn(code, page)
        image = (ev.DATA_FILES["hr"].parent / "scans" / "SCAN-OFFER-APP-0386.pdf").resolve()
        self.assertTrue(image.is_file())
        self.assertIn(f'href="{image.as_uri()}"', page)
        self.assertIn("scans/SCAN-OFFER-APP-0386.pdf", page)

    def test_scan_phrase_labels_say_where_the_phrase_is(self):
        # 日付：画像の印字に合わせて道具が補った別の書き方（scans.json は 2026-10-26）
        page = self.card("hr-11")
        self.assertIn(spot_check.SCAN_DATES_LABEL, page)
        self.assertIn("<mark>2026.10.26</mark>", page)
        self.assertNotIn(spot_check.SCAN_CODE_LABEL, page)
        # scans.json の項目
        page = self.card("hr-55")
        self.assertIn(spot_check.SCAN_JSON_LABEL, page)
        self.assertIn("<mark>10:52</mark>", page)
        # 描く指示の文字（手書きのメモの中身）。1 行だけを、文字列のリテラルにして出す
        page = self.card("hr-56")
        self.assertIn(spot_check.SCAN_CODE_LABEL, page)
        self.assertIn("<mark>月1回の夜間当番</mark>", page)
        self.assertNotIn("def make_", page)
        # 印字する文字でなく、コードのコメントにだけある語句は、コードの行として出す（見つけたことが分かる）
        page = self.card("hr-35")
        self.assertIn(spot_check.SCAN_CODE_RAW_LABEL, page)
        self.assertIn("<mark>確認印</mark>", page)

    def test_scan_literals_drop_dict_keys_and_code(self):
        line = '("応募番号", f["application_id"]), ("入社予定日", "2026年12月1日")]'
        self.assertEqual(spot_check._literals(line), ["応募番号", "入社予定日", "2026年12月1日"])
        self.assertEqual(spot_check._literals("d.text((1, 2), f\"{x}年\", font=m)"), ["{x}年"])
        self.assertEqual(spot_check._literals("y = 860 + i * 84"), [])

    def test_mail_label_is_neutral_and_shows_the_subject(self):
        page = self.card("hr-01")                                  # MAIL-09（内定の知らせ）
        self.assertNotIn("面接の連絡メール", page)
        subject = next(m["subject"] for m in ev.read_json(ev.HR_CONTENT_DIR / "mail.json")["mails"] if m["id"] == "MAIL-09")
        self.assertIn('<span class="dt">メール</span>', page)
        self.assertIn(spot_check.e(subject), page)
        job = self.card("hr-03")
        self.assertIn("求人票", job)                                 # メール以外の札はそのまま

    def test_no_copy_of_value_at(self):
        self.assertFalse(hasattr(spot_check, "_value_at"))
        self.assertIs(spot_check.ev.value_at, ev.value_at)

    def test_scan_text_is_escaped_and_missing_image_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            content = data / "_build" / "content"
            content.mkdir(parents=True)
            (data / "scans").mkdir()
            (data / "scans" / "S1.pdf").write_bytes(b"%PDF")
            scans = {"scans": [
                {"id": "S1", "kind": "memo", "what": f"<b>what</b> {EVIL}", "form": "<u>form</u>"},
                {"id": "S2", "kind": "memo", "what": "画像がないスキャン"}]}
            (content / "scans.json").write_text(json.dumps(scans, ensure_ascii=False), encoding="utf-8")
            (data / "_build" / "make_scans.py").write_text(
                f'def make_memo():\n    d.text((1, 2), "{EVIL}", font=f)\n    d.text((3, 4), "二つ目", font=f)\n', encoding="utf-8")
            manifest = {"files": [{"doc_id": "S1", "kind": "scan", "path": "scans/S1.pdf", "ocr_required": True},
                                  {"doc_id": "S2", "kind": "scan", "path": "scans/none.pdf", "ocr_required": True}]}
            questions = [{"qid": "hr-01", "question": "q", "type": "scan", "answer_ids": ["S1", "S2"],
                          "evidence": {"S1": EVIL, "S2": "二つ目"}}]
            page, _, warnings = make("hr", questions, manifest, n=1, content_dir=content)
            link = (data / "scans" / "S1.pdf").resolve().as_uri()
        for raw in ("<img", "<b>", "<u>"):
            self.assertNotIn(raw, page, raw)
        self.assertIn("&lt;b&gt;what&lt;/b&gt;", page)
        self.assertIn("<mark>&lt;img src=x onerror=alert(1)&gt;</mark>", page)
        self.assertIn(f'href="{link}"', page)
        self.assertIn("スキャンのファイルが見つかりません（scans/none.pdf）", page)       # S2 は画像がない
        self.assertEqual(warnings, [])


class HotelSheetTest(unittest.TestCase):
    def test_evidence_and_names_are_shown(self):
        page, picked, warnings = make("hotel", hotel_questions(), HOTELS, n=8)
        self.assertEqual(len(picked), 8)
        self.assertEqual(warnings, [])
        self.assertIn("ひのでホテル", page)
        self.assertIn("Hinode Hotel", page)
        self.assertIn("<mark>ペットも受け入れています</mark>", page)

    def test_condition_question_shows_the_values_not_evidence(self):
        cond = [q for q in hotel_questions() if q["type"] == "condition"][:1]
        page = make("hotel", cond, HOTELS, n=1)[0]
        self.assertIn("Rating ge 4.5 and Rooms/any(r: r/BaseRate le 100)", page)
        self.assertNotIn("<mark>", page)
        facts = page.split('class="facts"')[1].split("</dl>")[0]
        self.assertIn("4.6", facts)                 # Rating
        self.assertIn("80.0", facts)                # 条件に合う客室の料金（250.0 の客室は合わない）
        self.assertNotIn("250.0", facts)

    def test_phrase_not_in_the_data_is_flagged(self):
        questions = [{"qid": "hotel-01", "question": "見本", "type": "paraphrase", "answer_ids": ["1", "99"],
                      "evidence": {"1": "データにない語句", "99": "なにか"}}]
        page, _, warnings = make("hotel", questions, HOTELS, n=1)
        self.assertEqual(len(warnings), 2)
        self.assertIn("データにない語句", "".join(warnings))
        self.assertIn('class="miss"', page)

    def test_ja_en_phrase_is_marked_in_the_english_field(self):
        questions = [{"qid": "hotel-04", "question": "Hinode Hotel の朝食は", "type": "ja-en", "answer_ids": ["1"],
                      "evidence": {"1": ["Hinode Hotel", "朝食は無料です"]}}]
        page = make("hotel", questions, HOTELS, n=1)[0]
        self.assertIn("英語の項目", page)
        self.assertIn("<mark>Hinode Hotel</mark>", page)
        self.assertIn("<mark>朝食は無料です</mark>", page)


class SengokuSheetTest(unittest.TestCase):
    def test_shows_the_first_120_characters_of_the_profile(self):
        picked = [q for q in SENGOKU_QUESTIONS if q["qid"] == "q01"]
        page = make("sengoku", picked, SENGOKU_DATA, n=1)[0]
        profile = next(b["profile"] for b in SENGOKU_DATA if b["id"] == "b015")
        self.assertIn(profile[:120], page)
        self.assertNotIn(profile[:121], page)
        self.assertIn("北条氏康", page)


class SafetyTest(unittest.TestCase):
    def evil_hotel_page(self):
        evil_hotel = hotel("1", EVIL + "ホテル", "Evil<b>Hotel", f"説明「{EVIL}」と\"><svg onload=alert(2)>です。")
        evil_hotel["Tags_ja"] = ["<script>alert('tag')</script>"]
        questions = [
            {"qid": '"><script>alert(0)</script>', "question": "<script>alert('q')</script>", "type": "paraphrase",
             "answer_ids": ["1"], "why": "<b>why</b>", "note": "<u>note</u>", "evidence": {"1": EVIL}},
            {"qid": "hotel-02", "question": "条件", "type": "condition", "answer_ids": ["1"],
             "condition": {"Category_ja": "ブティック"}, "why": "</p><i>x</i>"},
        ]
        return make("hotel", questions, [evil_hotel], n=2)[0]

    def test_html_escapes_text(self):
        page = self.evil_hotel_page()
        for raw in ("<img", "<svg", "<b>", "<u>", "<i>", "<script>alert", "\"><script", "</p><i>"):
            self.assertNotIn(raw, page, raw)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page)
        self.assertIn("<mark>&lt;img src=x onerror=alert(1)&gt;</mark>", page)
        self.assertIn("&lt;script&gt;alert(&#x27;q&#x27;)&lt;/script&gt;", page)
        self.assertEqual(page.count("<script"), 1)          # 一覧の自分のスクリプトだけ
        self.assertEqual(page.count("</script>"), 1)

    def test_html_escapes_hr_source_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            (content / "jobs").mkdir(parents=True)
            (content / "jobs" / "J1.md").write_text(f"# 求人票\n\n<script>alert('job')</script> と {EVIL} が本文にあります。", encoding="utf-8")
            manifest = {"files": [{"doc_id": "J1", "kind": "job_posting", "kind_label": "<b>求人票</b>"}]}
            questions = [{"qid": "hr-01", "question": "<i>q</i>", "type": "numeric", "answer_ids": ["J1"],
                          "evidence": {"J1": EVIL}, "why": "<b>w</b>"}]
            page = make("hr", questions, manifest, n=1, content_dir=content)[0]
        for raw in ("<img", "<b>", "<i>", "<script>alert"):
            self.assertNotIn(raw, page, raw)
        self.assertIn("<mark>&lt;img src=x onerror=alert(1)&gt;</mark>", page)
        self.assertIn("&lt;script&gt;alert(&#x27;job&#x27;)&lt;/script&gt;", page)
        self.assertIn("&lt;b&gt;求人票&lt;/b&gt;", page)

    def test_no_external_resources(self):
        page = make("hr", HR_QUESTIONS, HR_MANIFEST)[0]
        for raw in ("http://", "https://", "src=", "@import", "url(", "<link", "<iframe", "<img"):
            self.assertNotIn(raw, page, raw)
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn('<html lang="ja">', page)

    def test_export_works_from_the_dom_without_data_in_the_script(self):
        page = make("hr", HR_QUESTIONS, HR_MANIFEST)[0]
        script = page.split("<script>")[1].split("</script>")[0]
        self.assertNotIn("hr-01", script)
        self.assertIn("Blob", script)
        self.assertIn("localStorage", script)
        self.assertIn("try", script)


class CliTest(unittest.TestCase):
    def test_writes_one_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "deep" / "hr.html"
            code, stdout, stderr = run_cli("--dataset", "hr", "--n", "10", "--seed", "1", "--out", str(out))
            self.assertEqual((code, stderr), (0, ""), stderr)
            self.assertIn("10 問", stdout)
            self.assertTrue(out.read_text(encoding="utf-8").startswith("<!doctype html>"))
            again = Path(tmp) / "again.html"
            run_cli("--dataset", "hr", "--n", "10", "--seed", "1", "--out", str(again))
            self.assertEqual(out.read_text(encoding="utf-8"), again.read_text(encoding="utf-8"))

    def test_hotel_with_data_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, questions, out = Path(tmp) / "hotels.json", Path(tmp) / "q.json", Path(tmp) / "hotel.html"
            data.write_text(json.dumps(HOTELS, ensure_ascii=False), encoding="utf-8")
            questions.write_text(json.dumps(hotel_questions(), ensure_ascii=False), encoding="utf-8")
            code, _, stderr = run_cli("--dataset", "hotel", "--n", "8", "--seed", "1", "--hotel-data", str(data),
                                      "--file", str(questions), "--out", str(out))
            self.assertEqual((code, stderr), (0, ""), stderr)
            self.assertIn("ひのでホテル", out.read_text(encoding="utf-8"))

    def test_hotel_without_data_stops_with_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "none.json"
            code, _, stderr = run_cli("--dataset", "hotel", "--hotel-data", str(missing), "--out", str(Path(tmp) / "x.html"))
            self.assertEqual(code, 2)
            self.assertIn("NG", stderr)
            self.assertFalse((Path(tmp) / "x.html").exists())

    def test_bad_arguments_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "x.html")
            self.assertEqual(run_cli("--dataset", "hr", "--n", "0", "--out", out)[0], 2)
            self.assertEqual(run_cli("--dataset", "hr", "--hotel-data", "x.json", "--out", out)[0], 2)
            self.assertEqual(run_cli("--dataset", "nope", "--out", out)[0], 2)
            self.assertEqual(run_cli("--dataset", "hr", "--file", str(Path(tmp) / "none.json"), "--out", out)[0], 2)
            self.assertFalse(Path(out).exists())

    def test_warns_when_a_phrase_is_not_found_but_still_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, questions, out = Path(tmp) / "hotels.json", Path(tmp) / "q.json", Path(tmp) / "hotel.html"
            data.write_text(json.dumps(HOTELS, ensure_ascii=False), encoding="utf-8")
            questions.write_text(json.dumps([{"qid": "hotel-01", "question": "見本", "type": "paraphrase", "answer_ids": ["1"],
                                              "evidence": {"1": "ない語句"}}], ensure_ascii=False), encoding="utf-8")
            code, _, stderr = run_cli("--dataset", "hotel", "--n", "1", "--hotel-data", str(data), "--file", str(questions),
                                      "--out", str(out))
            self.assertEqual(code, 0)
            self.assertIn("注意", stderr)
            self.assertIn("ない語句", stderr)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
