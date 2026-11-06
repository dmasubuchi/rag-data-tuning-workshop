"""前の操作の結果を、次の操作で並べて見せるための小さなメモ（basic/_work/ に書く）。

例：generate_answer.py の答えを覚えておき、compare_no_search.py で「検索なしの答え」と並べる。
ふだんは気にしなくてよい。消しても困らない（その操作が、もう一度計算し直すだけ）。
"""
import json
from datetime import datetime

from . import BASIC_DIR

WORK_DIR = BASIC_DIR / "_work"


def save(name: str, obj) -> None:
    WORK_DIR.mkdir(exist_ok=True)
    (WORK_DIR / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load(name: str):
    path = WORK_DIR / f"{name}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear() -> None:
    if WORK_DIR.is_dir():
        for p in WORK_DIR.glob("*.json"):
            p.unlink()


# ------------------------------------------------------------------ LLM に渡したプロンプトの保存
# 回答の生成に使った messages を、そのまま保存する。組み立て直さずに、これを表示できる。

PROMPT_NAMES = ("generate_answer",)   # 保存する側のスクリプト名（.py なし）


def prompt_record(script: str, question: str, settings: dict, chunk_ids: list, calls: list) -> dict:
    """保存する1件分。

    script    保存したスクリプトのファイル名
    question  質問
    settings  検索の方式、件数、温度など（どんな設定で渡したか）
    chunk_ids 渡した検索結果の chunk_id（武将のときは id）
    calls     生成の呼び出しごとの {"label": 呼び出しの名前, "messages": 渡した messages, "answers": 返ってきた答え}
    """
    return {
        "script": script,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "settings": settings,
        "chunk_ids": chunk_ids,
        "calls": calls,
    }


def latest_prompt(only: str = None):
    """保存されたプロンプトのうち、いちばん新しいもの（only を渡すと、そのスクリプトのもの）。なければ None。"""
    best = None
    for name in ([only] if only else PROMPT_NAMES):
        rec = load(name)
        if rec and rec.get("calls") and (best is None or rec.get("saved_at", "") > best.get("saved_at", "")):
            best = rec
    return best
