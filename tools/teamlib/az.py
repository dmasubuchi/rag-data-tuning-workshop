"""Azure CLI（az）を呼ぶ。読み取りと、名前の空き確認だけを許す。

Azure に何かを作る・変える・消すコマンドは、このファイルに入っていない。
az に渡せるコマンドは READ_ONLY の一覧に限る。動かすのは Python の標準ライブラリだけ。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse

ARM = "https://management.azure.com"

# az に渡してよいコマンド（先頭が一致するもの）。az rest は Az.get（GET）と Az.post（名前の空き確認）だけ
READ_ONLY = (
    ("account", "show"),
    ("group", "exists"), ("group", "show"),
    ("resource", "list"),
    ("storage", "account", "check-name"), ("storage", "account", "show"), ("storage", "container-rm", "show"),
    ("storage", "account", "show-connection-string"),   # builder の .env.local だけ（資料を入れるため）
    ("cosmosdb", "check-name-exists"), ("cosmosdb", "show"),
    ("search", "service", "show"), ("search", "admin-key", "show"), ("search", "query-key", "list"),
    ("cognitiveservices", "account", "keys", "list"),
    ("role", "assignment", "list"),
    ("cognitiveservices", "account", "show"), ("cognitiveservices", "account", "deployment", "list"),
)


class CheckError(Exception):
    """kind：notfound（まだない）、denied（権限がない）、login（サインインしていない）、noaz（az がない）、other。"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail)
        self.kind, self.detail = kind, detail


LOGIN_HINTS = ("az login", "aadsts", "doesn't exist in cloud", "no subscriptions found", "interactive authentication",
               "refresh token has expired", "please run 'az login'")
DENIED_HINTS = ("authorizationfailed", "authorizationpermissionmismatch", "forbidden", "does not have authorization",
                "not authorized", "permissiondenied")
NOTFOUND_HINTS = ("notfound", "not found", "could not be found", "does not exist", "was not found")
SECRET = re.compile(r"(?i)(key|secret|password|token|connectionstring)(\s*[=:]\s*)\S+")


def classify(stderr: str) -> str:
    text = stderr.lower()
    for kind, hints in (("login", LOGIN_HINTS), ("denied", DENIED_HINTS), ("notfound", NOTFOUND_HINTS)):
        if any(h in text for h in hints):
            return kind
    return "other"


def short_error(stderr: str) -> str:
    """az のエラーから、見せてよい1行を取り出す（警告は除く。秘密らしい値は伏せる）。"""
    lines = [ln.strip() for ln in stderr.splitlines()
             if ln.strip() and not re.search(r"warning|pkg_resources|declare_namespace", ln, re.I)]
    line = next((ln for ln in lines if ln.startswith("ERROR")), lines[0] if lines else "az が失敗しました")
    return SECRET.sub(r"\1\2***", line)[:100]


def find_az() -> str | None:
    """az の場所。Windows では az.cmd（shutil.which が PATHEXT から見つける）。"""
    return shutil.which("az") or shutil.which("az.cmd")


class Az:
    """az を呼ぶ。すべて JSON で受け取る。読み取りと、名前の空き確認の post だけを許す。"""

    def __init__(self, exe=None, subscription=None, timeout=120):
        self.exe = exe or find_az()
        self.subscription, self.timeout = subscription, timeout
        if not self.exe:
            raise CheckError("noaz", "Azure CLI（az）が見つかりません")
        if not self.subscription:
            raise CheckError("other", "サブスクリプションが決まっていません")

    def _call(self, args, scoped=True):
        cmd = [self.exe, *args, "--only-show-errors", "-o", "json"]
        if scoped:
            cmd += ["--subscription", self.subscription]
        try:
            # stdin を空にして、az が入力を待って止まらないようにする（サインインの案内などで起きる）
            done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=self.timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise CheckError("other", "az が時間内に終わりません") from None
        except OSError:
            raise CheckError("other", "az を実行できません") from None
        if done.returncode != 0:
            raise CheckError(classify(done.stderr), short_error(done.stderr))
        out = done.stdout.strip()
        if not out:
            return None
        try:
            return json.loads(out)
        except ValueError:
            raise CheckError("other", "az の答えを読めません") from None

    def run(self, *args):
        if not any(tuple(args[:len(p)]) == p for p in READ_ONLY):
            raise CheckError("other", "許可していない az コマンドです")
        return self._call(args)

    def _own_url(self, url) -> bool:
        return url.startswith(f"{ARM}/subscriptions/{self.subscription}/")

    def get(self, url):
        if not self._own_url(url):
            raise CheckError("other", "許可していない URL です")
        return self._call(("rest", "--method", "get", "--url", url), scoped=False)

    def post(self, url, body):
        """名前の空き確認（checkNameAvailability、checkDomainAvailability）だけ。本文は一時ファイルで渡す（Windows の引用符を避ける）。"""
        path = urllib.parse.urlparse(url).path
        if not self._own_url(url) or not path.endswith(("/checkNameAvailability", "/checkDomainAvailability")):
            raise CheckError("other", "許可していない URL です")
        fd, tmp = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f)
            return self._call(("rest", "--method", "post", "--url", url, "--body", "@" + tmp), scoped=False)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
