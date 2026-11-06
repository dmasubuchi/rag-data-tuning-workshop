"""スクリプトの main() を実行し、例外が出たら「何を確かめればよいか」を表示する。

各スクリプトの最後は次の形にそろえてある。
    if __name__ == "__main__":
        run(main)
"""
import atexit
import os
import sys
import time

from .config import SetupError, display_path, env_file_path, get_settings, reset_command


def _status(e) -> int:
    code = getattr(e, "status_code", None)
    if code is None:
        resp = getattr(e, "response", None)
        code = getattr(resp, "status_code", None)
    return code if isinstance(code, int) else 0


def _secret_values() -> list:
    """画面に出してはいけない値（AI Search と Azure OpenAI のキー、Storage の接続文字列）。

    設定が読めない場合も、環境変数と .env.local から集める。
    """
    vals = set()
    try:
        st = get_settings()
        vals.update([st.openai_key, st.search_key])
    except Exception:  # noqa: BLE001  設定が読めないときも、キーは消す
        pass
    for k in ("AZURE_OPENAI_API_KEY", "AZURE_SEARCH_API_KEY", "AZURE_STORAGE_CONNECTION_STRING"):
        vals.add(os.environ.get(k, ""))
    try:
        with open(env_file_path(), encoding="utf-8-sig") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k.endswith("_KEY") or k.endswith("CONNECTION_STRING"):
                    vals.add(v.strip().strip("'\""))
    except OSError:
        pass
    # 接続文字列の中のキー（AccountKey=… など）も、単独で消す
    for v in list(vals):
        for part in v.split(";"):
            name, _, secret = part.partition("=")
            if name.strip() in ("AccountKey", "SharedAccessSignature", "SharedAccessKey") and secret:
                vals.add(secret)
    return sorted((v for v in vals if v and len(v) >= 4), key=len, reverse=True)


def redact(text) -> str:
    """表示の前に、キーを *** に置き換える（切り詰めの前に呼ぶ）。"""
    text = str(text)
    for v in _secret_values():
        text = text.replace(v, "***")
    return text


def _is_query_key() -> bool:
    """いまの .env.local が、検索だけのキー（メンバー用）か。設定が読めなければ False。"""
    try:
        return get_settings().key_role == "query"
    except Exception:  # noqa: BLE001  設定が読めないときは、役割を決めつけない
        return False


def explain(e: BaseException) -> list:
    """例外から、参加者が確かめることの一覧を作る。"""
    name = type(e).__name__
    status = _status(e)
    text = str(e)
    tips: list = []

    if isinstance(e, SetupError):
        return []
    if isinstance(e, FileNotFoundError):
        name_ = getattr(e, "filename", "")
        tips.append(f"ファイルが見つかりません: {display_path(name_) if name_ else text}")
        tips.append("basic/data フォルダがあるか確かめてください（Repo を取得し直すと戻ります）。")
        return tips
    if name in ("ClientAuthenticationError",) or status in (401, 403):
        if _is_query_key():
            tips.append("いまの .env.local は、AI Search が検索だけのキー（メンバー用）です。作る・変える・調べる操作はできません。この手順は構築する人の設定（--role builder）で実行します。")
        tips.append("キーまたは権限の問題です。.env.local の AZURE_SEARCH_API_KEY（AI Search）または AZURE_OPENAI_API_KEY（Azure OpenAI）が、古くなっていないか確かめてください。")
        tips.append("キーが古いときは、.env.local を作り直せます。Repo 直下で `python tools/team.py env --role builder`（メンバーは `--role member`）を実行します。")
        tips.append("直らないときは、エラーの表示をそのまま進行役に見せてください。")
        return tips
    if name == "NotFoundError":
        tips.append("Azure OpenAI のデプロイが見つかりません。.env.local の AZURE_OPENAI_EMBEDDING_DEPLOYMENT と AZURE_OPENAI_CHAT_DEPLOYMENT（デプロイ名。モデル名とは限りません）を確かめてください。")
        tips.append("AZURE_OPENAI_ENDPOINT も確かめてください。")
        return tips
    if name == "ResourceNotFoundError" or status == 404:
        tips.append("インデックスなどが見つかりません。前の手順を実行したか確かめてください。")
        tips.append(f"困ったときは、そのトピックの開始の状態を作り直せます。例（トピック 04 の開始）：{reset_command('04')}")
        tips.append("インデックスの名前は固定です（武将は sengoku、同義語マップは sengoku-synonyms）。別のチームの AI Search につないでいないか、.env.local の AZURE_SEARCH_ENDPOINT も確かめてください。")
        return tips
    if name in ("RateLimitError",) or status == 429:
        tips.append("短い時間に呼びすぎました。1分ほど待って、もう一度実行してください。")
        return tips
    if name in ("APIConnectionError", "ServiceRequestError", "ConnectionError", "APITimeoutError", "ConnectTimeout") or "getaddrinfo" in text:
        tips.append("接続できません。.env.local の AZURE_SEARCH_ENDPOINT・AZURE_OPENAI_ENDPOINT が、書き換わっていないか確かめてください。")
        tips.append("ネットワーク（社内の回線、プロキシ、VPN）が止めていないかも確かめてください。")
        return tips
    if name == "BadRequestError" or status == 400:
        if "dimensions" in text.lower():
            tips.append("埋め込みの次元の指定が合いません。.env.local の EMBEDDING_DIMENSIONS と、使っている埋め込みモデルが対応する次元を確かめてください。")
        else:
            tips.append("送った内容が受け付けられませんでした。上のエラーの文を読んで、質問の文字列や設定の値を確かめてください。")
        return tips
    if name == "HttpResponseError":
        low = text.lower()
        if "semantic" in low:
            tips.append("セマンティックランカーが使えません。AI Search の料金プランがセマンティックランカーに対応しているか、月の無料枠を使い切っていないかを確かめてください。")
        elif "vector" in low or "dimension" in low:
            tips.append(f"ベクトルの項目の設定（次元）が合っていません。{reset_command('03')} のあと、03-vector-search の embed.py をもう一度実行してください。")
        else:
            tips.append("AI Search がエラーを返しました。上のエラーの文を読んでください。")
        return tips
    return tips


def report_error(e: BaseException) -> int:
    """例外を、参加者向けの形（何を確かめればよいか）で表示して、終了コードを返す。"""
    if isinstance(e, KeyboardInterrupt):
        print("\n中断しました。")
        return 130
    if isinstance(e, SetupError):
        print(f"\n[準備を確かめてください] {redact(e)}")
        return 2
    print(f"\n[エラー] {type(e).__name__}: {redact(e)[:600]}")
    tips = [redact(x) for x in explain(e)]
    print("確かめること:")
    if tips:
        for t in tips:
            print(f"  - {t}")
    else:
        print("  - 上のエラーの文を読み、前の手順を実行したかを確かめてください。")
        print("  - 直らないときは、このエラーの表示をそのまま進行役に見せてください。")
    return 1


def run(main) -> None:
    """main() を実行して、終了コードを決める。"""
    t0 = time.time()
    try:
        main()
    except SystemExit:
        raise
    except (KeyboardInterrupt, Exception) as e:  # noqa: BLE001  参加者向けに、種類ごとに確かめることを出す
        sys.exit(report_error(e))
    print(f"\n（実行時間 {time.time() - t0:.1f} 秒）")


def friendly_errors() -> None:
    """セル形式（# %%）のスクリプト用。スクリプトとして実行して途中で止まったとき、run() と同じ形で「何を確かめればよいか」を出す。

    セル形式のスクリプトは main() を持たず、上から順に実行する。そのため先頭のセルでこれを呼んでおく。
    Notebook の中では notebook_errors() と同じ（止まったセルの下に、キーを伏せた同じ形の表示を出す）。
    """
    from .show import in_notebook

    if in_notebook():
        notebook_errors()
        return

    def hook(kind, value, tb):
        if issubclass(kind, (Exception, KeyboardInterrupt)):
            code = report_error(value)
            atexit._run_exitfuncs()     # 後片付け（cells.at_exit）を先に済ませる。os._exit は atexit を呼ばない
            sys.stdout.flush()
            os._exit(code)      # sys.exit はフックの中では効かないので、ここで終える
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = hook


def notebook_errors() -> None:
    """Notebook 用。セルが止まったとき、元のトレースバックの代わりに report_error() の表示（キーを伏せる）を出す。

    例外の文には、接続先の応答がそのまま入り、キーが混じることがある。元のトレースバックはセルの出力に残るので出さない。
    """
    try:
        from IPython import get_ipython
    except ImportError:
        return
    shell = get_ipython()
    if shell is None:
        return

    def handler(self, etype, value, tb, tb_offset=None):
        report_error(value)
        return []

    shell.set_custom_exc((Exception,), handler)
