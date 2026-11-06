"""採用アシスタントの画面の、表示の判断（assistant/view.py）の試験。Streamlit は使わない。"""
import re
import sys
import unittest
from pathlib import Path

APPLIED = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APPLIED))
from assistant import engine, view  # noqa: E402


class ThinkingSlotTest(unittest.TestCase):
    def test_before_first_step_the_first_slot(self):
        self.assertEqual(view.thinking_slot(0, 6), 0)

    def test_after_each_step_the_next_slot(self):
        self.assertEqual(view.thinking_slot(1, 6), 1)
        self.assertEqual(view.thinking_slot(5, 6), 5)

    def test_no_slot_left_after_the_last_step(self):
        self.assertIsNone(view.thinking_slot(6, 6))


class SlotsToClearTest(unittest.TestCase):
    def test_unused_slots_are_cleared(self):
        self.assertEqual(view.slots_to_clear(2, 6), [2, 3, 4, 5])

    def test_nothing_drawn_clears_all(self):
        self.assertEqual(view.slots_to_clear(0, 3), [0, 1, 2])

    def test_all_used_clears_nothing(self):
        self.assertEqual(view.slots_to_clear(6, 6), [])


class ThinkingTextTest(unittest.TestCase):
    def test_one_notice_whatever_comes_next(self):
        """次が検索か答えかは、そのときにならないと分からない。待ちの文言は 1 つ。"""
        self.assertEqual(view.THINKING, "次の手を考えています…")
        self.assertFalse(hasattr(view, "WRITING"))


def source(no: int, chunk: str, application_ids: str = "", kind: str = "interview_evaluations", title: str = "EVAL-INTERVIEWS-2026-10.xlsx") -> dict:
    return {"no": no, "title": title, "kind": kind, "application_ids": application_ids, "chunk": chunk}


def one(s: dict, candidates=None) -> str:
    return view.source_headings([s], candidates)[0]


class SourceHeadingTest(unittest.TestCase):
    def test_people_in_the_chunk_are_added(self):
        s = source(1, "\tEV-001\tAPP-0417\t一次\n\tEV-002\tAPP-0439\t二次\n")
        self.assertEqual(one(s), "[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0417・APP-0439）")

    def test_three_people_are_shown_without_hoka(self):
        s = source(2, "APP-0001 a\nAPP-0002 b\nAPP-0003 c\n")
        self.assertEqual(one(s), "[2] EVAL-INTERVIEWS-2026-10.xlsx（APP-0001・APP-0002・APP-0003）")

    def test_more_than_three_people_end_with_hoka(self):
        s = source(2, "APP-0004 d\nAPP-0001 a\nAPP-0003 c\nAPP-0002 b\nAPP-0005 e\n")
        self.assertEqual(one(s), "[2] EVAL-INTERVIEWS-2026-10.xlsx（APP-0001・APP-0002・APP-0003 ほか）")

    def test_resume_uses_the_field_when_the_text_has_no_number(self):
        s = source(1, "職務経歴 …", application_ids="APP-0471", kind="resume")
        self.assertEqual(one(s), "[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0471）")

    def test_without_people_the_start_of_the_text(self):
        s = source(4, "求人票\n  募集の背景 夜間の運用を担う人を募集します。", application_ids="-", kind="job_posting")
        self.assertEqual(one(s), "[4] EVAL-INTERVIEWS-2026-10.xlsx（求人票 募集の背景 夜間の運用を…）")

    def test_short_text_has_no_ellipsis(self):
        self.assertEqual(one(source(1, "評価基準", kind="scan")), "[1] EVAL-INTERVIEWS-2026-10.xlsx（評価基準）")

    def test_nothing_to_add_keeps_the_plain_heading(self):
        self.assertEqual(one(source(1, "", kind="scan")), "[1] EVAL-INTERVIEWS-2026-10.xlsx")
        self.assertEqual(one(source(1, None, kind="scan")), "[1] EVAL-INTERVIEWS-2026-10.xlsx")

    def test_one_per_source_in_order(self):
        a, b = source(1, "APP-0417 a"), source(2, "APP-0439 b")
        self.assertEqual(view.source_headings([a, b], None), [one(a), one(b)])
        self.assertEqual(view.source_headings([], None), [])


class SourceHeadingOrderTest(unittest.TestCase):
    CHUNK = "APP-0001 a\nAPP-0002 b\nAPP-0003 c\nAPP-0004 d\nAPP-0005 e\n"

    def test_remaining_candidates_come_first_then_by_number(self):
        s = source(1, self.CHUNK)
        self.assertEqual(one(s, {"APP-0005", "APP-0003"}), "[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0003・APP-0005・APP-0001 ほか）")

    def test_without_candidates_by_number(self):
        self.assertEqual(one(source(1, self.CHUNK), None), "[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0001・APP-0002・APP-0003 ほか）")
        self.assertEqual(one(source(1, self.CHUNK), set()), "[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0001・APP-0002・APP-0003 ほか）")

    def test_candidates_not_in_the_chunk_are_ignored(self):
        s = source(1, "APP-0002 b\nAPP-0001 a\n")
        self.assertEqual(one(s, {"APP-0999"}), "[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0001・APP-0002）")


class SourceHeadingTellApartTest(unittest.TestCase):
    """評価一覧の xlsx は 1 人が複数のチャンクに分かれ、経歴書の 2 つ目のチャンクは本文に番号がない。人だけでは同じ見出しになる。"""

    def test_same_person_in_two_evaluation_chunks_is_told_apart_by_the_evaluation_id(self):
        a = source(1, "\tEV-001\tAPP-0391\tC-120\t一次面接\n")
        b = source(3, "\tEV-003\tAPP-0391\tC-120\t二次面接\n")
        heads = view.source_headings([a, b], None)
        self.assertEqual(heads[0], "[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0391｜EV-001）")
        self.assertEqual(heads[1], "[3] EVAL-INTERVIEWS-2026-10.xlsx（APP-0391｜EV-003）")

    def test_several_evaluation_ids_in_a_chunk_are_shown_as_a_range(self):
        a = source(1, "\tEV-001\tAPP-0391\ta\n\tEV-002\tAPP-0391\tb\n\tEV-003\tAPP-0391\tc\n")
        b = source(2, "\tEV-004\tAPP-0391\td\n")
        heads = view.source_headings([a, b], None)
        self.assertTrue(heads[0].endswith("（APP-0391｜EV-001〜003）"), heads[0])
        self.assertTrue(heads[1].endswith("（APP-0391｜EV-004）"), heads[1])

    def test_resume_chunks_without_numbers_in_the_text_are_told_apart_by_the_start_of_the_text(self):
        a = source(1, "市川 浩二\n職務経歴 バックエンド", application_ids="APP-0391", kind="resume", title="CV-APP-0391.docx")
        b = source(2, "資格と研修\n基本情報技術者", application_ids="APP-0391", kind="resume", title="CV-APP-0391.docx")
        heads = view.source_headings([a, b], None)
        self.assertNotEqual(heads[0].split("] ", 1)[1], heads[1].split("] ", 1)[1])
        self.assertIn("市川 浩二 職務経歴 バック", heads[0])
        self.assertIn("資格と研修 基本情報技術者", heads[1])

    def test_headings_that_are_already_different_get_nothing_added(self):
        a = source(1, "\tEV-001\tAPP-0391\ta\n")
        b = source(2, "\tEV-009\tAPP-0603\tb\n")
        self.assertEqual(view.source_headings([a, b], None),
                         ["[1] EVAL-INTERVIEWS-2026-10.xlsx（APP-0391）", "[2] EVAL-INTERVIEWS-2026-10.xlsx（APP-0603）"])

    def test_only_the_overlapping_ones_get_something_added(self):
        a = source(1, "\tEV-001\tAPP-0391\ta\n")
        b = source(2, "\tEV-009\tAPP-0603\tb\n")
        c = source(3, "\tEV-002\tAPP-0391\tc\n")
        heads = view.source_headings([a, b, c], None)
        self.assertEqual(heads[1], "[2] EVAL-INTERVIEWS-2026-10.xlsx（APP-0603）")
        self.assertIn("EV-001", heads[0])
        self.assertIn("EV-002", heads[2])

    def test_same_evaluation_id_falls_back_to_the_start_of_the_text_too(self):
        a = source(1, "\tEV-001\tAPP-0391\t一次の評価\n")
        b = source(2, "\tEV-001\tAPP-0391\t二次の評価\n")
        heads = view.source_headings([a, b], None)
        self.assertNotEqual(heads[0].split("] ", 1)[1], heads[1].split("] ", 1)[1])


class EscapeMarkdownTest(unittest.TestCase):
    def test_marks_that_markdown_reads_are_escaped(self):
        for ch in "*_$:[]#`~<>|&":
            self.assertEqual(view.escape_markdown(f"a{ch}b"), f"a\\{ch}b", ch)
        self.assertEqual(view.escape_markdown("a\\b"), "a\\\\b")

    def test_plain_text_is_kept(self):
        self.assertEqual(view.escape_markdown("夜間の運用 APP-0391 (v3).docx"), "夜間の運用 APP-0391 (v3).docx")

    def test_start_of_the_text_is_escaped_in_the_heading(self):
        s = source(1, "**重要** :red[注意] $x$ [a](b) `c` _d_ #e", application_ids="-", kind="job_posting")
        self.assertTrue(one(s).startswith("[1] EVAL-INTERVIEWS-2026-10.xlsx（\\*\\*重要\\*\\* \\:red\\[注意\\]"), one(s))

    def test_title_is_escaped_too(self):
        s = source(1, "APP-0391 a", title="CV_APP_0391_v3.docx")
        self.assertEqual(one(s), "[1] CV\\_APP\\_0391\\_v3.docx（APP-0391）")

    def test_text_added_to_tell_chunks_apart_is_escaped(self):
        a = source(1, "*強調* の経歴", application_ids="APP-0391", kind="resume")
        b = source(2, "_別_ の経歴", application_ids="APP-0391", kind="resume")
        heads = view.source_headings([a, b], None)
        self.assertIn("\\*強調\\*", heads[0])
        self.assertIn("\\_別\\_", heads[1])


class StepPauseTest(unittest.TestCase):
    def test_default_and_env(self):
        self.assertEqual(view.step_pause({}), 0.6)
        self.assertEqual(view.step_pause({"ASSISTANT_STEP_PAUSE": "1.5"}), 1.5)
        self.assertEqual(view.step_pause({"ASSISTANT_STEP_PAUSE": "0"}), 0.0)

    def test_too_long_a_pause_is_capped(self):
        self.assertEqual(view.step_pause({"ASSISTANT_STEP_PAUSE": "3"}), 3.0)
        self.assertEqual(view.step_pause({"ASSISTANT_STEP_PAUSE": "10"}), 3.0)

    def test_bad_values_fall_back(self):
        self.assertEqual(view.step_pause({"ASSISTANT_STEP_PAUSE": "abc"}), 0.6)
        self.assertEqual(view.step_pause({"ASSISTANT_STEP_PAUSE": "nan"}), 0.6)
        self.assertEqual(view.step_pause({"ASSISTANT_STEP_PAUSE": "-2"}), 0.0)


class WaitSecondsTest(unittest.TestCase):
    def test_nothing_drawn_yet_means_no_wait(self):
        self.assertEqual(view.wait_seconds(None, 10.0, 0.6), 0.0)

    def test_the_rest_of_the_pause_is_waited(self):
        self.assertAlmostEqual(view.wait_seconds(10.0, 10.2, 0.6), 0.4)

    def test_no_wait_when_enough_time_has_passed(self):
        self.assertEqual(view.wait_seconds(10.0, 18.0, 0.6), 0.0)

    def test_zero_pause_means_no_wait(self):
        self.assertEqual(view.wait_seconds(10.0, 10.0, 0.0), 0.0)


def step(no: int, method: str = "キーワード", args: dict | None = None, before=5, after=3, docs=8, titles=("a.docx", "b.docx"), note="") -> engine.Step:
    return engine.Step(no=no, method=method, args={"query": "夜間 障害対応"} if args is None else args, people_before=before,
                       people_after=after, docs_found=docs, top_titles=list(titles), note=note)


class StepLinesTest(unittest.TestCase):
    def test_three_short_lines(self):
        self.assertEqual(view.step_lines(step(2)), ("**2　キーワード**　`夜間 障害対応`", "候補 5 人 → **3 人**（文書 8 件）", "a.docx　b.docx"))

    def test_everyone_before_the_first_narrowing(self):
        _, count, _ = view.step_lines(step(1, before=None))
        self.assertEqual(count, "候補 全員 → **3 人**（文書 8 件）")

    def test_fields_args_are_named(self):
        head, _, _ = view.step_lines(step(1, "欄で絞る", {"req_id": "REQ-042", "kind": "resume"}))
        self.assertEqual(head, "**1　欄で絞る**　`req_id: REQ-042　kind: resume`")

    def test_list_args_are_joined_with_a_middle_dot_not_python_notation(self):
        head, _, _ = view.step_lines(step(1, "欄で絞る", {"req_id": "REQ-042", "applicant_ids": ["APP-0417", "APP-0439"]}))
        self.assertEqual(head, "**1　欄で絞る**　`req_id: REQ-042　applicant_ids: APP-0417・APP-0439`")
        self.assertNotIn("[", head)
        self.assertNotIn("'", head)

    def test_long_args_are_cut(self):
        head, _, _ = view.step_lines(step(1, "ID でたどる", {"候補": " ".join(f"APP-{i:04d}" for i in range(30))}))
        self.assertIn("…`", head)
        self.assertLess(len(head), 80)

    def test_long_id_list_is_cut_between_ids_not_inside_one(self):
        ids = [f"APP-{n:04d}" for n in (391, 392, 417, 439, 471, 603, 386)]
        for others in ({}, {"kind": "resume"}, {"req_id": "REQ-042"}, {"kind": "mail", "req_id": "REQ-042"}, {"req_id": "REQ-0420000"}):
            head, _, _ = view.step_lines(step(1, "欄で絞る", {**others, "applicant_ids": ids}))
            code = head.split("`")[1]
            self.assertTrue(code.endswith("…"), code)
            for m in re.finditer(r"APP-", code):
                self.assertRegex(code[m.start():], r"^APP-\d{4}(?:・|…)", code)

    def test_cut_between_ids_keeps_the_ids_before_it(self):
        ids = [f"APP-{n:04d}" for n in (391, 392, 417, 439, 471, 603, 386)]
        head, _, _ = view.step_lines(step(1, "欄で絞る", {"applicant_ids": ids}))
        self.assertEqual(head, "**1　欄で絞る**　`applicant_ids: APP-0391・APP-0392・APP-0417・APP-0439…`")

    def test_ids_separated_by_spaces_are_cut_between_ids_too(self):
        cand = " ".join(f"APP-{n:04d}" for n in (391, 392, 417, 439, 471, 603, 386))
        code = view.step_lines(step(1, "ID でたどる", {"候補": cand}))[0].split("`")[1]
        self.assertEqual(code, "候補: APP-0391 APP-0392 APP-0417 APP-0439 APP-0471…")

    def test_it_does_not_go_back_to_a_separator_in_the_first_half(self):
        """区切りまで戻るのは、上限の半分以上のとき。戻りすぎて「applicant_ids:…」のように値が 1 つも出ないのを避ける。"""
        ids = ",".join(f"APP-{n:04d}" for n in (391, 392, 417, 439, 471))
        code = view.step_lines(step(1, "欄で絞る", {"applicant_ids": ids}))[0].split("`")[1]
        self.assertEqual(code, "applicant_ids: APP-0391,APP-0392,APP-0417,APP-0439…")

    def test_it_goes_back_to_a_separator_in_the_second_half(self):
        text = "x" * 30 + " " + "y" * 30
        code = view.step_lines(step(1, args={"query": text}))[0].split("`")[1]
        self.assertEqual(code, "x" * 30 + "…")

    def test_text_without_a_separator_is_cut_hard(self):
        code = view.step_lines(step(1, args={"query": "あ" * 80}))[0].split("`")[1]
        self.assertEqual(code, "あ" * view.ARGS_CHARS + "…")

    def test_backtick_in_args_does_not_break_the_code_span(self):
        head, _, _ = view.step_lines(step(1, args={"query": "a`b"}))
        self.assertEqual(head.count("`"), 2)

    def test_note_goes_on_the_small_line(self):
        _, _, small = view.step_lines(step(1, note="0 人だったので絞らなかった"))
        self.assertIn("0 人だったので絞らなかった", small)
        self.assertIn("a.docx", small)

    def test_long_titles_are_left_out(self):
        titles = [f"CV-APP-{i:04d}-LONG-FILE-NAME.docx" for i in range(5)]
        _, _, small = view.step_lines(step(1, titles=titles))
        self.assertIn(titles[0], small)
        self.assertNotIn(titles[4], small)
        self.assertLessEqual(len(small), 70)

    def test_a_title_too_long_for_the_line_is_cut_not_dropped(self):
        long_title = "CV-APP-0391-" + "X" * 80 + ".docx"
        _, _, small = view.step_lines(step(1, titles=[long_title, "b.docx"]))
        self.assertTrue(small.startswith("CV-APP-0391-XXX"), small)
        self.assertTrue(small.endswith("…"), small)
        self.assertNotIn("b.docx", small)
        self.assertLessEqual(len(small), view.SMALL_CHARS)

    def test_a_cut_title_leaves_room_for_the_note(self):
        _, _, small = view.step_lines(step(1, titles=["X" * 90], note="0 人だったので絞らなかった"))
        self.assertIn("0 人だったので絞らなかった", small)
        self.assertIn("…", small)
        self.assertLessEqual(len(small), view.SMALL_CHARS + 2)

    def test_no_titles_no_small_line(self):
        self.assertEqual(view.step_lines(step(1, titles=(), docs=0))[2], "")

    def test_titles_are_escaped(self):
        self.assertIn("CV\\_APP\\_0391.docx", view.step_lines(step(1, titles=("CV_APP_0391.docx",)))[2])


class ButtonLabelTest(unittest.TestCase):
    TITLES = {"q07": "岩崎さん2人の今の段階"}

    def test_demo_question_has_its_own_title(self):
        q = {"id": "q07", "question": "REQ-042 に応募している岩崎さんは2人います。"}
        self.assertEqual(view.button_label(q, self.TITLES, 18), "岩崎さん2人の今の段階")

    def test_others_are_cut_as_before(self):
        q = {"id": "q01", "question": "REQ-043 の最終面接に進んだ人の評価と、内定の連絡の日付は？"}
        self.assertEqual(view.button_label(q, self.TITLES, 18), "REQ-043 の最終面接に進んだ人…")


class FakeSlot:
    """st.empty の代わり。caption・empty・container が呼ばれたことを、枠の番号つきで log に残す。"""

    def __init__(self, name, log):
        self.name, self.log = name, log

    def caption(self, text):
        self.log.append((self.name, "caption", text))

    def empty(self):
        self.log.append((self.name, "empty"))

    def container(self, **kwargs):
        self.log.append((self.name, "container"))


def last_ops(log, names):
    """枠ごとの、最後に呼ばれたことと文言。"""
    out = {}
    for entry in log:
        out[entry[0]] = entry[1:]
    return {n: out.get(n) for n in names}


def draw(slot, step):
    slot.container(border=True)


class FakeClock:
    def __init__(self):
        self.now, self.slept = 100.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class AskLiveTest(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.slots = [FakeSlot(i, self.log) for i in range(6)]
        self.tail = FakeSlot("tail", self.log)
        self.clock = FakeClock()

    def go(self, ask, tail=True, pause=0.0):
        return view.ask_live("q", self.slots, ask, draw, tail=self.tail if tail else None, pause=pause,
                             clock=self.clock, sleep=self.clock.sleep)

    def test_normal_run_thinks_after_each_step_and_clears_the_unused_slots(self):
        def ask(question, on_step):
            on_step(step(1))
            on_step(step(2, "ID でたどる"))
            return {"answer": "x"}

        self.assertEqual(self.go(ask), {"answer": "x"})
        self.assertEqual(self.log[:5], [(0, "caption", view.THINKING), (0, "container"), (1, "caption", view.THINKING),
                                         (1, "container"), (2, "caption", view.THINKING)])
        last = last_ops(self.log, range(6))
        self.assertEqual((last[0], last[1]), (("container",), ("container",)))
        self.assertTrue(all(last[i] == ("empty",) for i in (2, 3, 4, 5)))

    def test_error_in_the_middle_clears_the_thinking_caption_and_raises(self):
        def ask(question, on_step):
            on_step(step(1))
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.go(ask)
        last = last_ops(self.log, range(6))
        self.assertEqual(last[0], ("container",))
        self.assertTrue(all(last[i] == ("empty",) for i in range(1, 6)))

    def test_no_step_at_all_still_clears_every_slot(self):
        self.assertEqual(self.go(lambda question, on_step: {"answer": "x"}), {"answer": "x"})
        self.assertEqual(self.log[0], (0, "caption", view.THINKING))
        self.assertTrue(all(last_ops(self.log, range(6))[i] == ("empty",) for i in range(6)))

    def test_six_steps_write_the_answer_notice_in_the_tail_slot_and_clear_it(self):
        def ask(question, on_step):
            for n in range(1, 7):
                on_step(step(n))
            return {"answer": "x"}

        self.go(ask)
        self.assertIn(("tail", "caption", view.THINKING), self.log)
        self.assertEqual(last_ops(self.log, ["tail"])["tail"], ("empty",))
        self.assertTrue(all(last_ops(self.log, range(6))[i] == ("container",) for i in range(6)))

    def test_every_notice_is_the_same_one(self):
        def ask(question, on_step):
            for n in range(1, 7):
                on_step(step(n, "ID でたどる" if n == 3 else "キーワード"))
            return {}

        self.go(ask)
        self.assertEqual({e[2] for e in self.log if len(e) > 2}, {view.THINKING})

    def test_error_after_the_last_slot_clears_the_tail_notice(self):
        def ask(question, on_step):
            for n in range(1, 7):
                on_step(step(n))
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.go(ask)
        self.assertIn(("tail", "caption", view.THINKING), self.log)
        self.assertEqual(last_ops(self.log, ["tail"])["tail"], ("empty",))

    def test_error_in_render_leaves_no_notice_behind(self):
        def bad_render(slot, st):
            if st.no == 2:
                raise ValueError("render failed")
            slot.container(border=True)

        def ask(question, on_step):
            on_step(step(1))
            on_step(step(2))
            return {}

        with self.assertRaises(ValueError):
            view.ask_live("q", self.slots, ask, bad_render, tail=self.tail, pause=0.0, clock=self.clock, sleep=self.clock.sleep)
        last = last_ops(self.log, range(6))
        self.assertEqual(last[0], ("container",))
        self.assertTrue(all(last[i] == ("empty",) for i in range(1, 6)))

    def test_tail_slot_is_left_alone_when_not_used(self):
        self.go(lambda question, on_step: on_step(step(1)) or {"answer": "x"})
        self.assertFalse([e for e in self.log if e[0] == "tail"])

    def test_without_a_tail_slot_the_last_notice_is_just_skipped(self):
        def ask(question, on_step):
            for n in range(1, 7):
                on_step(step(n))
            return {}

        self.go(ask, tail=False)
        self.assertFalse([e for e in self.log if e[0] == "tail"])

    def test_steps_that_arrive_too_fast_are_drawn_a_pause_apart(self):
        def ask(question, on_step):
            on_step(step(1))
            self.clock.now += 0.2
            on_step(step(2))
            self.clock.now += 5.0
            on_step(step(3))
            return {}

        self.go(ask, pause=0.6)
        self.assertEqual(len(self.clock.slept), 1)
        self.assertAlmostEqual(self.clock.slept[0], 0.4)

    def test_each_step_is_drawn_at_least_a_pause_after_the_one_before(self):
        """待つのは描く前。描いた後ろで待つ作りだと、隣り合う描画の時刻が pause より近くなる。"""
        drawn_at = []

        def timed_render(slot, st):
            drawn_at.append(self.clock.now)
            slot.container(border=True)

        def ask(question, on_step):
            for n in range(1, 5):
                self.clock.now += 0.1       # 検索が 0.1 秒で次々に返る
                on_step(step(n))
            return {}

        view.ask_live("q", self.slots, ask, timed_render, tail=self.tail, pause=0.6, clock=self.clock, sleep=self.clock.sleep)
        self.assertEqual(len(drawn_at), 4)
        for before, after in zip(drawn_at, drawn_at[1:]):
            self.assertGreaterEqual(after - before, 0.6 - 1e-9)

    def test_zero_pause_never_sleeps(self):
        def ask(question, on_step):
            on_step(step(1))
            on_step(step(2))
            return {}

        self.go(ask, pause=0.0)
        self.assertEqual(self.clock.slept, [])


if __name__ == "__main__":
    unittest.main()
