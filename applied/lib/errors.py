"""キーを伏せる処理と、エラーが出たときの説明。

スクリプトで実行したときも、Notebook で実行したときも、例外の表示の前にキーを *** に置き換え、
「何を確かめればよいか」を日本語で1〜3行出す。
"""
import os
import sys
import traceback


SECRET_NAME_ENDINGS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CONNECTION_STRING")


def _secret_values() -> list:
    """画面に出してはいけない値（AI Search・Azure OpenAI のキー、Storage の接続文字列とその中のキー）。

    .env.local は、設定を読むのと同じ python-dotenv で読む（値の後ろのコメント `KEY=値 # メモ` や引用符も、同じ扱いになる）。
    名前が KEY・SECRET・TOKEN・PASSWORD・CONNECTION_STRING で終わる項目の値を、すべて伏せる。
    """
    from .config import env_file_path, read_env_file

    vals = set()
    for k in ("AZURE_OPENAI_API_KEY", "AZURE_SEARCH_API_KEY", "AZURE_STORAGE_CONNECTION_STRING"):
        vals.add(os.environ.get(k, ""))
    try:
        for k, v in read_env_file(env_file_path()).items():
            if k.upper().endswith(SECRET_NAME_ENDINGS):
                vals.add(v)
    except Exception:  # noqa: BLE001  読めないときは、環境変数のぶんだけ伏せる（設定の読み取りの失敗は、別の説明で出る）
        pass
    for v in list(vals):
        for part in v.split(";"):
            name, _, secret = part.partition("=")
            if name.strip() in ("AccountKey", "SharedAccessSignature", "SharedAccessKey") and secret:
                vals.add(secret)
    return sorted((v for v in vals if v and len(v) >= 4), key=len, reverse=True)


def redact(text) -> str:
    """表示の前に、キーを *** に置き換える。"""
    text = str(text)
    for v in _secret_values():
        text = text.replace(v, "***")
    return text


def _status(e) -> int:
    code = getattr(e, "status_code", None)
    if code is None:
        code = getattr(getattr(e, "response", None), "status_code", None)
    return code if isinstance(code, int) else 0


def _query_key() -> bool:
    """いまの .env.local が、検索だけのキー（メンバー用）か。設定が読めなければ False（役割を決めつけない）。"""
    try:
        from .config import is_query_key

        return is_query_key()
    except Exception:  # noqa: BLE001
        return False


def explain(e: BaseException) -> list:
    """例外から、参加者が確かめることを日本語で返す。"""
    from .config import ENV_LOCAL_HOWTO, SetupError

    if isinstance(e, SetupError):
        return [str(e)]
    if isinstance(e, ModuleNotFoundError):
        return [f"ライブラリが入っていません（{e.name}）。Repo 直下で次を実行してください（仮想環境の中で）。",
                "  pip install -r applied/requirements.txt"]
    code = _status(e)
    name = type(e).__name__
    if code == 401 or code == 403:
        tips = []
        if _query_key():
            tips.append("いまの .env.local は、AI Search が検索だけのキー（メンバー用）です。作る・変える・調べる操作はできません。"
                        "この手順は構築する人の設定（--role builder）で実行します。")
        tips.append("Azure に断られました（キーが違う・使えない）。.env.local のキーが古くなっていないか確かめてください。")
        tips.append("  " + ENV_LOCAL_HOWTO)
        return tips
    if code == 404 or name == "ResourceNotFoundError":
        return ["Azure に目的のもの（インデックスなど）がありません。",
                "  インデックス hr-docs（と、19・20 の知識ベース hr-docs-kb）は、構築する人が applied/tools/build_hr_index.py"
                "（build_hr_kb.py）で作ります。まだなら構築する人に聞いてください。"]
    if code == 429:
        return ["Azure が混んでいます（回数の上限）。少し待ってから、もう一度実行してください。"]
    if name in ("ServiceRequestError", "ConnectionError", "ConnectError", "APIConnectionError"):
        return ["Azure に接続できません。.env.local の接続先（AZURE_SEARCH_ENDPOINT・AZURE_OPENAI_ENDPOINT）と、ネットワークを確かめてください。"]
    return [f"思わぬエラーです（{name}）。画面の内容を進行役に見せてください。"]


def _report(etype, value, tb) -> None:
    lines = [redact(line) for line in explain(value)]       # 説明の行（SetupError の本文を含む）も、表示の前にキーを伏せる
    detail = redact("".join(traceback.format_exception_only(etype, value))).strip()
    print("\n止まりました：" + lines[0], file=sys.stderr)
    for line in lines[1:]:
        print(line, file=sys.stderr)
    print("  （詳しく）" + detail[:600], file=sys.stderr)
    if os.environ.get("WORKSHOP_DEBUG"):
        print(redact("".join(traceback.format_tb(tb))), file=sys.stderr)


def install_error_handler() -> None:
    """スクリプトでは sys.excepthook、Notebook（IPython）では set_custom_exc で、上の表示に差し替える。"""
    def hook(etype, value, tb):
        if issubclass(etype, KeyboardInterrupt):
            sys.__excepthook__(etype, value, tb)
            return
        _report(etype, value, tb)

    sys.excepthook = hook
    try:
        from IPython import get_ipython  # type: ignore
        ip = get_ipython()
    except Exception:  # noqa: BLE001  IPython がなければスクリプトとして動いている
        ip = None
    if ip is not None:
        def custom(shell, etype, value, tb, tb_offset=None):
            _report(etype, value, tb)
        ip.set_custom_exc((Exception,), custom)
