"""検索の評価で使う質問の形を確かめる（標準ライブラリだけ。通信しない）。

質問のファイルを読み、qid の重複・使えない種類・文書にない ID・種類ごとの数（人事・ホテル）などを調べる。
質問の形と種類の説明は evaluation/README.md。

使い方（Repo 直下で）：
  python tools/check_questions.py --dataset sengoku     武将の既存の60問（basic/data/sengoku/questions.json）
  python tools/check_questions.py --dataset hr          人事（evaluation/hr_questions.json）
  python tools/check_questions.py --dataset hotel       ホテル（evaluation/hotel_questions.json）
  --file PATH         質問のファイルを変える
  --hotel-data PATH   ホテルのデータ（HotelsData_toAzureBlobs_ja.json）の場所。省くと _work/hotel-vectors/ の中

人事は、文書の本文のもと（applied/data/_build/content）がないと、evidence の語句を探す確かめを飛ばして、その旨を1行出す。

終了コード：0 = 問題なし／1 = 問題がある（一覧を出す）／2 = 質問かデータのファイルが読めない
"""
import argparse
import sys
from pathlib import Path

from evallib.questions import (DATASETS, QUESTION_FILES, DataError, hr_content_available, ids_of, load_data,
                               load_questions, validate)


def build_parser():
    parser = argparse.ArgumentParser(description="検索の評価で使う質問の形を確かめる")
    parser.add_argument("--dataset", required=True, choices=DATASETS, help="確かめる質問のデータ")
    parser.add_argument("--file", type=Path, help="質問のファイル（省くと、データごとの既定の場所）")
    parser.add_argument("--hotel-data", type=Path, help="ホテルのデータの JSON（--dataset hotel のときだけ）")
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.hotel_data and args.dataset != "hotel":
        print("--hotel-data は --dataset hotel のときだけ使えます。", file=sys.stderr)
        return 2
    question_file = args.file or QUESTION_FILES[args.dataset]
    try:
        questions = load_questions(question_file)
    except DataError as error:
        print(f"NG    {error}", file=sys.stderr)
        if not Path(question_file).exists():
            print("      質問のファイルは、--file で渡すか、質問を作ります（作り方は evaluation/README.md）。", file=sys.stderr)
        return 2
    try:
        data = load_data(args.dataset, args.hotel_data)
    except DataError as error:
        print(f"NG    {error}", file=sys.stderr)
        if args.dataset == "hotel" and not args.hotel_data:
            print("      ホテルのデータの JSON の場所は、--hotel-data で渡します。", file=sys.stderr)
        return 2
    if args.dataset == "hr" and not hr_content_available():
        print("注意  本文が見つからないので、evidence の照らし合わせを飛ばしました（applied/data/_build/content がありません）。",
              file=sys.stderr)
    try:
        problems = validate(args.dataset, questions, known_ids=ids_of(args.dataset, data), data=data)
    except DataError as error:
        print(f"NG    {error}", file=sys.stderr)
        return 2
    if not problems:
        print(f"問題なし（{len(questions)} 問）")
        return 0
    print(f"問題が {len(problems)} 件あります（{len(questions)} 問を確認）")
    for problem in problems:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
