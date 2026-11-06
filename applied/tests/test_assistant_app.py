"""採用アシスタントの試験（通信なし）。
  ・合言葉と回数の上限、質問の並び（assistant/gate.py）
  ・画面（assistant/app.py）：Streamlit の AppTest で、画面が開く・質問すると段と答えと出典が出る・エラーを短く出す・合言葉で閉じる
    （ScreenTest。azure_io.ask は偽。streamlit が入っているときだけ動く）
  ・コンテナのイメージ（Dockerfile、.dockerignore）にキーを入れない約束
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

APPLIED = Path(__file__).resolve().parent.parent
REPO = APPLIED.parent
sys.path.insert(0, str(APPLIED))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from assistant import azure_io, engine, gate  # noqa: E402
from envcase import MEMBER, EnvCase  # noqa: E402


class AccessTest(unittest.TestCase):
    def test_no_code_set_means_open(self):
        self.assertTrue(gate.access_ok("x", None))
        self.assertTrue(gate.access_ok("", ""))

    def test_wrong_or_empty_code_is_refused(self):
        self.assertFalse(gate.access_ok("", "abc"))
        self.assertFalse(gate.access_ok("abd", "abc"))

    def test_right_code_is_accepted(self):
        self.assertTrue(gate.access_ok("abc", "abc"))
        self.assertTrue(gate.access_ok(" abc ", "abc"))


class LimitTest(unittest.TestCase):
    def test_under_limit(self):
        self.assertTrue(gate.under_limit(199, 200))
        self.assertFalse(gate.under_limit(200, 200))

    def test_limit_from_env(self):
        self.assertEqual(gate.max_questions({}), 200)
        self.assertEqual(gate.max_questions({"ASSISTANT_MAX_QUESTIONS": "30"}), 30)
        self.assertEqual(gate.max_questions({"ASSISTANT_MAX_QUESTIONS": "abc"}), 200)


class OrderTest(unittest.TestCase):
    def test_demo_questions_come_first_in_given_order(self):
        qs = [{"id": f"q{i:02d}"} for i in range(1, 6)]
        self.assertEqual([q["id"] for q in gate.order_questions(qs, ("q04", "q02"))], ["q04", "q02", "q01", "q03", "q05"])

    def test_unknown_ids_are_ignored(self):
        qs = [{"id": "q01"}, {"id": "q02"}]
        self.assertEqual([q["id"] for q in gate.order_questions(qs, ("q09",))], ["q01", "q02"])


def fake_ask(question, on_step):
    """azure_io.ask の代わり。Azure にも LLM にも行かず、1 段と答えと出典を返す。"""
    step = engine.Step(1, "欄で絞る", {"req_id": "REQ-042"}, None, 2, 5, ["CV-APP-0391.docx"])
    on_step(step)
    source = {"no": 1, "chunk_id": "CV-APP-0391-c0", "doc_id": "CV-APP-0391", "kind": "resume", "req_id": "REQ-042",
              "application_ids": "APP-0391", "title": "CV-APP-0391.docx", "chunk": "夜間の障害対応を担当"}
    return {"run": engine.Run(question, candidates={"APP-0391", "APP-0392"}, steps=[step]),
            "answer": "夜間の対応を担当しました [1]", "sources": [source], "warnings": [], "tokens": {"input_tokens": 1, "output_tokens": 1}}


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "pip install -r applied/assistant/requirements.txt で入る")
class ScreenTest(EnvCase):
    """Streamlit の AppTest で画面を動かす（app.py を、同じプロセスで実行する）。azure_io.ask は偽で、Azure には接続しない。
    設定は、試験用の一時の .env.local（メンバーの設定）。本物の .env.local は読まない。"""
    ENV_TEXT = MEMBER

    def start(self, code=None):
        import logging

        import streamlit as st
        from streamlit.testing.v1 import AppTest

        for name in list(logging.root.manager.loggerDict):
            if name.startswith("streamlit"):
                logger = logging.getLogger(name)
                self.addCleanup(logger.setLevel, logger.level)      # 試験のあとで、元の水準に戻す
                logger.setLevel(logging.ERROR)                      # 「missing ScriptRunContext」の注意を出さない
        st.cache_resource.clear()
        # 環境変数は、EnvCase が setUp で取った写し（tearDown で元に戻る）の中で変える。ここで別に patch しない
        os.environ["ASSISTANT_STEP_PAUSE"] = "0"
        if code is None:
            os.environ.pop("ASSISTANT_ACCESS_CODE", None)
        else:
            os.environ["ASSISTANT_ACCESS_CODE"] = code
        at = AppTest.from_file(str(APPLIED / "assistant" / "app.py"), default_timeout=30)
        return at.run()

    def test_screen_opens_with_the_ten_questions_and_the_demo_ones_first(self):
        at = self.start()
        self.assertEqual(list(at.exception), [])
        keys = [b.key for b in at.button if b.key]
        # 2 列に交互に並ぶ（左の列の上から、右の列の上から）。デモの質問（q07・q04・q10・q03）が、先頭の 4 つの位置
        self.assertEqual(sorted(keys), [f"q{i:02d}" for i in range(1, 11)])
        self.assertEqual((keys[0], keys[1], keys[5], keys[6]), ("q07", "q10", "q04", "q03"))

    def test_asking_shows_the_step_the_answer_and_the_sources(self):
        at = self.start()
        with mock.patch.object(azure_io, "ask", fake_ask):
            at.button(key="q10").click().run()
        self.assertEqual(list(at.exception), [])
        shown = " ".join(m.value for m in at.markdown)
        self.assertIn("夜間の対応を担当しました [1]", shown)
        self.assertIn("答えに使った資料 1 件", shown)
        self.assertIn("欄で絞る", shown)                    # 右の段のカード（やり方）
        self.assertIn("2 人", shown)                         # 段のカード（残った候補の人数）
        self.assertEqual([e.label for e in at.expander], ["[1] CV-APP-0391.docx（APP-0391）"])

    def test_an_error_from_the_search_is_shown_in_short_without_the_key(self):
        at = self.start()

        def broken(question, on_step):
            raise RuntimeError("接続できません key=FAKE-SRCH-d4e5f6")

        with mock.patch.object(azure_io, "ask", broken):
            at.button(key="q10").click().run()
        self.assertEqual(list(at.exception), [])
        shown = " ".join(e.value for e in at.error)
        self.assertIn("止まりました", shown)
        self.assertNotIn("FAKE-SRCH-d4e5f6", shown)      # キーは *** に伏せられる

    def test_access_code_closes_the_screen_until_it_is_typed(self):
        at = self.start(code="open-sesame")
        self.assertEqual([b.key for b in at.button if b.key], [])
        at.text_input[0].input("wrong").run()
        at.button[0].click().run()
        self.assertTrue(any("合言葉が違います" in e.value for e in at.error))
        self.assertEqual([b.key for b in at.button if b.key], [])
        at.text_input[0].input("open-sesame").run()
        at.button[0].click().run()
        self.assertEqual(len([b.key for b in at.button if b.key]), 10)


class ImageTest(unittest.TestCase):
    """コンテナのイメージに、接続先とキーを入れない約束（Docker は動かさない。ファイルの中身だけ見る）。"""

    def test_dockerignore_keeps_secrets_and_work_out_of_the_image(self):
        lines = {ln.strip() for ln in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()}
        old_name = "workshop" + ".local.env"       # 以前の設定ファイルの名前。この試験が禁止語の検査（test_layout）に当たらないように、2つに分けて書く
        for name in (".env.local", ".env", "*.local.env", "**/.env*", "**/*.local.env", "workshop.config", old_name,
                     ".venv", ".superpowers", ".git"):
            self.assertIn(name, lines)

    def test_dockerfile_reads_the_settings_from_a_mounted_file(self):
        text = (APPLIED / "assistant" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("WORKSHOP_ENV_FILE=/secrets/env.local", text)
        self.assertNotRegex(text, r"(?m)^\s*(COPY|ADD)\s.*\.env")
        for path in ("applied/lib", "applied/assistant", "applied/topics/19-agentic-retrieval/questions.json"):
            self.assertIn(path, text)
            self.assertTrue((REPO / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
