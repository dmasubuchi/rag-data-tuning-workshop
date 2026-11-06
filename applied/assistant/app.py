"""採用アシスタント（応用編のデモ）の画面。左に会話、右に検索の段の記録。

実行（Repo 直下で）：streamlit run applied/assistant/app.py
  ASSISTANT_ACCESS_CODE   合言葉。なければ合言葉なしで開く（自分の PC で動かすとき）
  ASSISTANT_MAX_QUESTIONS 1 日の質問の上限（既定 200）
  ASSISTANT_STEP_PAUSE    段を画面に描く最低の間隔（秒、既定 0.6、0 で間隔なし、上限 3）
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # applied/（lib と assistant を読むため）

import streamlit as st  # noqa: E402

import lib  # noqa: E402,F401
from lib.errors import explain, redact  # noqa: E402

from assistant import azure_io, gate, view  # noqa: E402
from assistant.cli import load_questions  # noqa: E402
from assistant.engine import MAX_STEPS  # noqa: E402

BUTTON_CHARS = 18
DEMO_FIRST = ("q07", "q04", "q10", "q03")   # デモで使う質問（候補が減る様子がよく見えるもの）。ボタンの先頭に並べる
DEMO_TITLES = {"q07": "岩崎さん2人の今の段階", "q04": "二次面接の評価の違い",   # 先頭の字では見分けにくいので、短い題を付ける
               "q10": "夜間の障害対応の経験", "q03": "大西さんの評価と経歴書"}

st.set_page_config(page_title="採用アシスタント", layout="wide")


@st.cache_resource
def counter() -> dict:
    """今日の質問の数（このアプリの中で数える）。"""
    return {"date": date.today(), "n": 0}


def count_one() -> bool:
    c = counter()
    if c["date"] != date.today():
        c["date"], c["n"] = date.today(), 0
    if not gate.under_limit(c["n"], gate.max_questions(os.environ)):
        return False
    c["n"] += 1
    return True


def render_step(slot, step) -> None:
    """1 段のカードを、段の番号の枠（st.empty）に描く。前の質問のカードは、同じ枠に描き直されて消える。3 行に収める（view.step_lines）。"""
    head, count, small = view.step_lines(step)
    card = slot.container(border=True)
    card.markdown(f"{head}  \n{count}")
    if small:
        card.caption(small)


def gatekeeper() -> bool:
    expected = os.environ.get("ASSISTANT_ACCESS_CODE")
    if st.session_state.get("ok") or gate.access_ok("", expected):
        return True
    code = st.text_input("合言葉", type="password")
    if st.button("開く"):
        if gate.access_ok(code, expected):
            st.session_state["ok"] = True
            st.rerun()
        st.error("合言葉が違います")
    return False


def main() -> None:
    st.markdown("### 採用アシスタント")
    st.caption("架空の会社の採用の文書（研修用のデータ）だけを根拠に、検索のやり方を変えながら候補を絞り込んで答えます")
    if not gatekeeper():
        return
    left, right = st.columns([6, 4], gap="large")
    questions = gate.order_questions(load_questions(), DEMO_FIRST)
    with left:
        cols = st.columns(2)
        for i, q in enumerate(questions):
            if cols[i % 2].button(view.button_label(q, DEMO_TITLES, BUTTON_CHARS), key=q["id"], use_container_width=True):
                st.session_state["question"] = q["question"]
                st.session_state["go"] = True
        typed = st.text_area("質問", value=st.session_state.get("question", ""), height=80)
        if st.button("質問する", type="primary"):
            st.session_state["question"] = typed
            st.session_state["go"] = True
    # 先に枠を置く。新しい質問を始めたとき、前の質問の段・答え・件数が、薄く残ったままにならないように
    answer_slot = left.empty()
    right.markdown("#### 検索の段")
    steps_box = right.container()
    slots = [steps_box.empty() for _ in range(MAX_STEPS)]
    total_slot = right.empty()
    if st.session_state.pop("go", False) and st.session_state.get("question", "").strip():
        st.session_state.pop("result", None)
        if not count_one():
            left.error("今日の質問の回数の上限に達しました")
            return
        try:
            out = view.ask_live(st.session_state["question"], slots, azure_io.ask, render_step, tail=total_slot,
                                pause=view.step_pause(os.environ))   # 待っている間は、右の枠に「次の手を考えています」が出る
            st.session_state["result"] = out
            st.session_state["live"] = True
        except Exception as e:  # noqa: BLE001  画面ごと落とさず、短い説明だけを出す
            left.error(redact("止まりました：" + " ".join(explain(e))))
            return
    out = st.session_state.get("result")
    if not out:
        return
    if not st.session_state.pop("live", False):
        for s in out["run"].steps:
            render_step(slots[s.no - 1], s)
    total_slot.markdown(f"**答えに使った資料 {len(out['sources'])} 件**")
    with answer_slot.container():
        st.markdown(f"**質問**　{out['run'].question}")
        st.markdown(out["answer"])
        for w in out["warnings"]:
            st.warning(w)
        if out["sources"]:
            st.markdown("**出典**")
        for s, heading in zip(out["sources"], view.source_headings(out["sources"], out["run"].candidates)):
            with st.expander(heading):
                st.text(s.get("chunk") or "")


main()
