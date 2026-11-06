"""図のページ（diagram）を作る。ページごとに diagrams/pNN.json（題、キャプション、SVG、ノート）を書き出し、build.py がそれを読む。

実行（Repo の直下で）：python3 docs/lecture/diagrams/figures.py [ページ番号 …]
- 図は部ごとのファイル figs_part1.py・figs_part2.py・figs_part3.py・figs_eval.py・figs_wrapup.py に書く
- 描き方の決まりは docs/lecture/README.md の「図の描き方の決まり」。部品は tools/svgparts.py だけを使う
"""
import importlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools")]
from _reg import FIGS  # noqa: E402

for f in sorted(HERE.glob("figs_*.py")):
    try:
        importlib.import_module(f.stem)
    except Exception as e:  # noqa: BLE001  書きかけのファイルがあっても、ほかの部の図は書き出す
        print(f"[飛ばした] {f.name}：{type(e).__name__}: {e}")


def main(argv):
    want = {int(a) for a in argv} or set(FIGS)
    for no, f in sorted(FIGS.items()):
        if no not in want:
            continue
        d = f()
        (HERE / f"p{no:02d}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"p.{no}：{d['title']}")


if __name__ == "__main__":
    main(sys.argv[1:])
