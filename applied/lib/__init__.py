"""応用編の全スクリプトが共通で使う部品（設定、Azure への接続、文書の読み取り、表示、エラーの説明）。

各トピックのスクリプトの先頭で `import lib` と書くと、次のことが自動で行われる。
  1. 標準出力・標準エラーを UTF-8 にする（Windows の PowerShell でも日本語が化けないように）
  2. __pycache__ を作らない（フォルダを汚さない）
  3. エラーが出たら、キーを伏せて「何を確かめればよいか」を表示する（スクリプトでも Notebook でも）

設定は、Repo 直下の .env.local（Azure の接続先とキーなど）だけ。読む処理は config.py にある。
各トピックのスクリプトを読むときは、まずスクリプト本体を読めばよい。ここは「裏方」。
"""
import sys
from pathlib import Path

APPLIED_DIR = Path(__file__).resolve().parent.parent   # applied/
REPO_DIR = APPLIED_DIR.parent                          # Repo 直下（.env.local を置く場所）

sys.dont_write_bytecode = True   # __pycache__ を作らない

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except ValueError:      # Notebook の出力先など、変えられないもの
            pass

from .errors import install_error_handler  # noqa: E402

install_error_handler()
