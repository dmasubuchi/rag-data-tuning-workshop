"""applied/data の全ファイルを作り直す。

使い方（Repo の外に作った Python 3.12 の仮想環境で。requirements.txt を参照）:
    python _build/build_all.py            # 作り直して、manifest.json を書き、検査する
    python _build/build_all.py --verify   # 2 回作って、全ファイルが同じバイト列になることを確かめる

入力は _build/content/ だけ。時計・乱数（seed 固定）・ネットワークは使わない。
Azure には何も送らない。
"""
from __future__ import annotations

import hashlib
import shutil
import sys

import build_evaluations_xlsx
import build_jobs_pdf
import build_mail_eml
import build_resumes_docx
import check_all
import make_manifest
import make_scans
from lib_common import DATA

OUTPUT_DIRS = ["jobs", "updates", "resumes", "evaluations", "mail", "scans"]


def build() -> None:
    for name in OUTPUT_DIRS:
        shutil.rmtree(DATA / name, ignore_errors=True)
    for mod in (build_jobs_pdf, build_resumes_docx, build_evaluations_xlsx, build_mail_eml, make_scans):
        mod.main()
    make_manifest.main()


def digest() -> dict:
    out = {}
    for name in OUTPUT_DIRS:
        for p in sorted((DATA / name).rglob("*")):
            if p.is_file():
                out[str(p.relative_to(DATA))] = hashlib.sha256(p.read_bytes()).hexdigest()
    out["manifest.json"] = hashlib.sha256((DATA / "manifest.json").read_bytes()).hexdigest()
    return out


def main() -> int:
    build()
    if "--verify" in sys.argv:
        first = digest()
        build()
        second = digest()
        diff = [k for k in sorted(set(first) | set(second)) if first.get(k) != second.get(k)]
        if diff:
            print("同じ入力から違うバイト列ができたファイル:", *diff, sep="\n  ")
            return 1
        print(f"2 回作って {len(first)} ファイルがすべて同じバイト列でした。")
    return check_all.main()


if __name__ == "__main__":
    sys.exit(main())
