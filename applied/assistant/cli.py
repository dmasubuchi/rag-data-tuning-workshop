"""採用アシスタントを端末で 1 問だけ動かす（確かめ用）。段と答えを順に出す。

実行（applied フォルダで）：
  python -m assistant.cli --id q10                       用意した質問（19 の questions.json）
  python -m assistant.cli --question "REQ-043 の …"      自分の質問
"""
import argparse
import json

import lib  # noqa: F401  （UTF-8 の出力と、キーを伏せたエラーの表示）
from lib import APPLIED_DIR

from . import azure_io

QUESTIONS = APPLIED_DIR / "topics" / "19-agentic-retrieval" / "questions.json"


def load_questions() -> list[dict]:
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data["questions"]


def show_step(step) -> None:
    before = "全員" if step.people_before is None else f"{step.people_before} 人"
    after = "全員" if step.people_after is None else f"{step.people_after} 人"
    args = "、".join(f"{k}={v}" for k, v in step.args.items())
    print(f"段 {step.no}  {step.method}  {args}")
    print(f"      候補 {before} → {after}（文書 {step.docs_found} 件）{('  ' + step.note) if step.note else ''}")
    for t in step.top_titles:
        print(f"      ・{t}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", help="用意した質問の番号（q01〜q10）")
    g.add_argument("--question", help="自分の質問")
    a = p.parse_args()
    question = a.question or next(q["question"] for q in load_questions() if q["id"] == a.id)
    print(f"質問：{question}\n")
    out = azure_io.ask(question, show_step)
    print(f"\n答え：\n{out['answer']}\n")
    for s in out["sources"]:
        print(f"[{s['no']}] {s['title']}（{s['kind']}）")
    for w in out["warnings"]:
        print(f"注意：{w}")
    print(f"\nLLM のトークン：入力 {out['tokens']['input_tokens']:,} / 出力 {out['tokens']['output_tokens']:,}")


if __name__ == "__main__":
    main()
