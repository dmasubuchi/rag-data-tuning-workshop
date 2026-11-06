"""基礎編の全スクリプトが共通で使う部品（設定、Azure への接続、検索、エラーの説明）。

各トピックのスクリプトの先頭で `import lib` と書くと、次のことが自動で行われる。
  1. 標準出力・標準エラーを UTF-8 にする（Windows の PowerShell でも日本語が化けないように）
  2. topics/ の下の各トピックのフォルダを import できるようにする
     （セル形式のスクリプトは、読み込むと上から順に動き出すので、スクリプトどうしでは import しない。
      トピックをまたいで使う関数は、lib/ に置く。スクリプトのファイル名は、全トピックを通して重ならないようにしてある）
  3. __pycache__ を作らない（フォルダを汚さない）

設定は、Repo 直下の .env.local（Azure の接続先とキーなど）だけ。読む処理は config.py にある。
Azure に接続する道具は clients.py、検索は search.py にある。
各トピックのスクリプトを読むときは、まずスクリプト本体を読めばよい。ここは「裏方」。
"""
import sys
from pathlib import Path

BASIC_DIR = Path(__file__).resolve().parent.parent   # basic/
REPO_DIR = BASIC_DIR.parent                          # Repo 直下（.env.local を置く場所）
TOPICS_DIR = BASIC_DIR / "topics"

sys.dont_write_bytecode = True   # __pycache__ を作らない

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# 実行するスクリプトの置き場所は、Python が自動で探す先頭に入る。ほかのトピックのフォルダは、最後に足す。
if TOPICS_DIR.is_dir():
    for _topic in sorted(p for p in TOPICS_DIR.iterdir() if p.is_dir()):
        if str(_topic) not in sys.path:
            sys.path.append(str(_topic))
