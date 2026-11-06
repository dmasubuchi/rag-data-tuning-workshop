"""（作る人用）セル形式（# %%）のスクリプトから、同じ名前の Notebook（.ipynb）を作る。参加者は実行しなくてよい。

実行（Repo 直下で）：python tools/make_notebooks.py            全部を作り直す
          python tools/make_notebooks.py --check    作り直さず、ずれているものを一覧にする（ずれがあれば終了コード 1）

対象：basic/topics/*/*.py と applied/topics/*/*.py のうち、`# %%` の行を含むもの。
      同じフォルダに、同じ名前の .ipynb ができる（例 basic/topics/01-keyword-search/keyword_search.ipynb）。
中身：jupytext（percent 形式）で変換する。出力は空、実行回数は null、メタデータは kernelspec（python3）だけ。
      セルの id は、セルの中身から決める。同じ .py からは、いつも同じバイト列ができる。
Notebook は .py から作るもの。Notebook の側は編集しない（.py を直して、このツールで作り直す）。
実行して出力が入った Notebook は、コミットしない（--check が「出力あり」と知らせる）。

--check が知らせるもの
  ない        .py はあるが、.ipynb がない
  ずれ        .py を直したのに、.ipynb を作り直していない
  出力あり    .ipynb に、実行した出力や実行回数が入っている
  余分        .ipynb はあるが、元になるセル形式の .py がない

終了コード：0 = 問題なし（作り直しの成功）／ 1 = --check でずれがあった／ 2 = jupytext が入っていない
jupytext は作る人の道具なので、basic/requirements.txt と applied/requirements.txt には入れない（requirements-dev.txt に入れる）。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOPIC_GLOBS = ("basic/topics/*/*.py", "applied/topics/*/*.py")
CELL_LINE = re.compile(r"^# %%", re.MULTILINE)
KERNELSPEC = {"display_name": "Python 3", "language": "python", "name": "python3"}


def cell_scripts() -> list:
    """セル形式（# %% を含む）のスクリプト。"""
    found = []
    for pattern in TOPIC_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            if path.name != "__init__.py" and CELL_LINE.search(path.read_text(encoding="utf-8")):
                found.append(path)
    return found


def rel(path: Path) -> str:
    return str(path.relative_to(REPO))


def to_notebook_text(py_text: str) -> str:
    """セル形式の .py の文字列から、Notebook の JSON の文字列を作る（同じ入力なら、同じ文字列）。"""
    import jupytext
    import nbformat

    nb = jupytext.reads(py_text, fmt="py:percent")
    nb.metadata = nbformat.from_dict({"kernelspec": dict(KERNELSPEC)})
    used = set()
    for i, cell in enumerate(nb.cells):
        cell.metadata = nbformat.from_dict({})
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
        cid = hashlib.sha1(cell.source.encode("utf-8")).hexdigest()[:8]
        if cid in used:                     # 中身が同じセルが2つあるときは、番号を足して区別する
            cid = f"{cid}-{i}"
        used.add(cid)
        cell.id = cid
    nbformat.validate(nb)
    text = nbformat.writes(nb)
    return text if text.endswith("\n") else text + "\n"


def strip_outputs(nb_json: dict) -> dict:
    """Notebook の JSON から、出力と実行回数を取り除いた写し。"""
    out = json.loads(json.dumps(nb_json))
    for cell in out.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    return out


def has_outputs(nb_json: dict) -> bool:
    return any(c.get("cell_type") == "code" and (c.get("outputs") or c.get("execution_count") is not None)
               for c in nb_json.get("cells", []))


def serialize(nb_json: dict) -> str:
    import nbformat

    nb = nbformat.from_dict(nb_json)
    text = nbformat.writes(nb)
    return text if text.endswith("\n") else text + "\n"


def check(scripts: list) -> list:
    """ずれの一覧 [(パス, 種類, 説明), ...]。"""
    problems = []
    wanted = {p.with_suffix(".ipynb") for p in scripts}
    for py in scripts:
        nb_path = py.with_suffix(".ipynb")
        if not nb_path.is_file():
            problems.append((rel(nb_path), "ない", "作り直してください（python tools/make_notebooks.py）"))
            continue
        expected = to_notebook_text(py.read_text(encoding="utf-8"))
        try:
            existing = json.loads(nb_path.read_text(encoding="utf-8"))
        except ValueError:
            problems.append((rel(nb_path), "ずれ", "Notebook として読めません。作り直してください"))
            continue
        if has_outputs(existing):
            problems.append((rel(nb_path), "出力あり", "実行した出力や実行回数が入っています。作り直してください"))
        if serialize(strip_outputs(existing)) != expected:
            problems.append((rel(nb_path), "ずれ", f"{py.name} と中身が違います。作り直してください"))
    for pattern in TOPIC_GLOBS:
        for nb_path in sorted(REPO.glob(pattern.replace(".py", ".ipynb"))):
            if nb_path not in wanted:
                problems.append((rel(nb_path), "余分", "元になるセル形式の .py がありません"))
    return problems


def build(scripts: list) -> None:
    """全部を作り直す。中身が変わらないものは書き直さない。"""
    made = changed = 0
    for py in scripts:
        nb_path = py.with_suffix(".ipynb")
        text = to_notebook_text(py.read_text(encoding="utf-8"))
        if nb_path.is_file() and nb_path.read_text(encoding="utf-8") == text:
            print(f"  変更なし  {rel(nb_path)}")
            continue
        status = "更新" if nb_path.is_file() else "作成"
        nb_path.write_text(text, encoding="utf-8", newline="\n")
        print(f"  {status}      {rel(nb_path)}")
        made += status == "作成"
        changed += status == "更新"
    print(f"\n{len(scripts)} 本のうち、作成 {made}、更新 {changed}、変更なし {len(scripts) - made - changed}。")


def main() -> int:
    parser = argparse.ArgumentParser(description="セル形式のスクリプトから Notebook を作る（作る人用）")
    parser.add_argument("--check", action="store_true", help="作り直さず、ずれているものを一覧にする（ずれがあれば終了コード 1）")
    args = parser.parse_args()

    try:
        import jupytext  # noqa: F401
    except ImportError:
        print("jupytext が入っていません。pip install -r requirements-dev.txt で入れてください（作る人の道具です。参加者の requirements.txt には入れません）。")
        return 2

    scripts = cell_scripts()
    if args.check:
        problems = check(scripts)
        if not problems:
            print(f"問題なし（セル形式のスクリプト {len(scripts)} 本と、Notebook が合っています）。")
            return 0
        print(f"ずれがあります（{len(problems)} 件）：")
        for path, kind, note in problems:
            print(f"  [{kind}] {path}　{note}")
        return 1
    build(scripts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
