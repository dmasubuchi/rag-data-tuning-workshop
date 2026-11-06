"""セルの形（# %%）で書いたスクリプトの、共通の始まりと終わり。

セルの形のスクリプトは、上から順に実行する（main() を作らない）。Notebook では1セルずつ実行できる。

  start()        エラーの表示を参加者向けにする（runner.run と同じ表示。キーは伏せる）
                 スクリプトとして動かしたときは、最後に実行時間も出す。Notebook では、止まったセルの下に同じ表示を出す
  at_exit(func)  スクリプトとして動かしたとき、終わるとき（途中でエラーになったときも）に func を呼ぶ。後片付けに使う
                 Notebook では呼ばれないので、最後に後片付けのセルを置く
"""
import atexit
import os
import sys
import time

from .runner import friendly_errors, report_error
from .show import in_notebook


def start() -> None:
    """参加者向けのエラー表示を入れる。スクリプトとして動かしたときは、実行時間の表示も入れる。"""
    friendly_errors()
    if in_notebook():
        return
    t0 = time.time()
    atexit.register(lambda: print(f"\n（実行時間 {time.time() - t0:.1f} 秒）"))


def at_exit(func) -> None:
    """スクリプトとして動かしたときだけ、終わるときに func を呼ぶ（エラーで止まったときも）。

    func が失敗しても、ほかのエラーと同じ表示（キーを伏せる）にする。
    """
    if in_notebook():
        return

    def call():
        try:
            func()
        except (Exception, KeyboardInterrupt) as e:  # noqa: BLE001  後片付けの失敗も、参加者向けの表示にする
            print("\n[後片付けに失敗しました]")
            code = report_error(e)
            sys.stdout.flush()
            os._exit(code)      # 終了コードを失敗にする（atexit の中では sys.exit が効かない）

    atexit.register(call)
