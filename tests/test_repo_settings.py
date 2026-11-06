"""Repo 直下の設定ファイル（.streamlit/config.toml・.gitattributes）と、採用アシスタントの Dockerfile の先頭の例の試験。通信しない。"""

import subprocess
import tomllib
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


class StreamlitConfigTest(unittest.TestCase):
    def test_assistant_listens_on_localhost_by_default(self):
        """採用アシスタントは、既定では手元だけで開く（人に見せるときは ASSISTANT_ACCESS_CODE）。"""
        config = tomllib.loads((REPO_DIR / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["server"]["address"], "localhost")

    def test_dockerfile_example_publishes_to_localhost_and_mounts_the_member_file(self):
        head = (REPO_DIR / "applied" / "assistant" / "Dockerfile").read_text(encoding="utf-8").split("FROM ", 1)[0]
        self.assertIn("-p 127.0.0.1:8501:8501", head)
        self.assertIn("member.local.env:/secrets/env.local", head)
        self.assertNotIn("$PWD/.env.local", head)


class GitattributesTest(unittest.TestCase):
    def attr(self, name, which):
        done = subprocess.run(["git", "check-attr", which, "--", name], cwd=REPO_DIR, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.rsplit(": ", 1)[-1].strip()

    def test_text_files_are_lf_and_binary_files_are_left_alone(self):
        self.assertEqual(self.attr("README.md", "eol"), "lf")
        self.assertEqual(self.attr("README.md", "text"), "auto")
        for name in ("a.pdf", "a.png", "a.jpg", "a.docx", "a.xlsx"):
            with self.subTest(name=name):
                self.assertEqual(self.attr(name, "binary"), "set")

    def test_mail_files_keep_their_line_endings(self):
        self.assertEqual(self.attr("applied/data/mail/MAIL-01_REQ-042_APP-0417.eml", "text"), "unset")


if __name__ == "__main__":
    unittest.main()
