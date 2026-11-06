"""chat() と openai_client() の呼び方を、偽のクライアントで確かめる（Azure には接続しない）。

実行（Repo 直下で）：python -m unittest discover -s basic/tests
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import clients, llm  # noqa: E402
from lib.config import SetupError, Settings  # noqa: E402

KEY = "SECRET-KEY-12345"


def settings(effort="", endpoint="https://example.cognitiveservices.azure.com/"):
    return Settings(search_endpoint="https://s", search_key="S-KEY-xyz", openai_endpoint=endpoint, openai_key=KEY,
                    api_version="", embedding_deployment="emb", chat_deployment="chat-dep", dimensions=1536,
                    env_file=".env.local", reasoning_effort=effort)


def response(text="こんにちは", finish="stop"):
    msg = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)], usage=None, model="m")


class FakeClient:
    def __init__(self, res):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._res = res

    def _create(self, **kw):
        self.calls.append(kw)
        return self._res


class ChatTest(unittest.TestCase):
    def run_chat(self, res, effort="", **kw):
        fake = FakeClient(res)
        with mock.patch.object(llm, "get_settings", return_value=settings(effort)), \
                mock.patch.object(llm, "openai_client", return_value=fake):
            out = io.StringIO()
            with redirect_stdout(out):
                try:
                    answer = llm.chat([{"role": "user", "content": "q"}], **kw)
                    err = None
                except SetupError as e:
                    answer, err = None, str(e)
        return fake.calls, answer, err, out.getvalue()

    def test_params(self):
        calls, answer, _, _ = self.run_chat(response(), effort="none", temperature=0.0, max_tokens=500)
        kw = calls[0]
        self.assertEqual(answer, "こんにちは")
        self.assertNotIn("temperature", kw)
        self.assertNotIn("max_tokens", kw)
        self.assertEqual(kw["max_completion_tokens"], 500)
        self.assertEqual(kw["reasoning_effort"], "none")
        self.assertEqual(kw["model"], "chat-dep")

    def test_sent_conditions_do_not_claim_temperature(self):
        with mock.patch.object(llm, "get_settings", return_value=settings("none")):
            c = llm.sent_conditions()
        self.assertIn("未指定", c["temperature"])
        self.assertNotEqual(c["temperature"], 0.0)
        self.assertEqual((c["reasoning_effort"], c["max_completion_tokens"]), ("none", 800))

    def test_no_effort_not_passed(self):
        calls, _, _, _ = self.run_chat(response())
        self.assertNotIn("reasoning_effort", calls[0])
        self.assertEqual(calls[0]["max_completion_tokens"], 800)

    def test_empty_and_length_stop(self):
        _, a, err, out = self.run_chat(response("", "stop"))
        self.assertIsNone(a)
        self.assertIn("空", err)
        _, a, err, out = self.run_chat(response("途中", "length"))
        self.assertIsNone(a)
        self.assertIn("finish_reason=length", err)
        self.assertNotIn(KEY, err + out)


class ClientTest(unittest.TestCase):
    def build(self, endpoint):
        clients.openai_client.cache_clear()
        with mock.patch.object(clients, "get_settings", return_value=settings(endpoint=endpoint)):
            c = clients.openai_client()
        clients.openai_client.cache_clear()
        return c

    def test_base_url_trailing_slash(self):
        for ep in ("https://x.cognitiveservices.azure.com/", "https://x.cognitiveservices.azure.com"):
            c = self.build(ep)
            self.assertEqual(str(c.base_url), "https://x.cognitiveservices.azure.com/openai/v1/")

    def test_key_not_in_repr(self):
        c = self.build("https://x.azure.com")
        self.assertNotIn(KEY, repr(c))


if __name__ == "__main__":
    unittest.main()
