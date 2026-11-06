"""画面に出す文字列の整え方（見出し、切り詰め、順位の言い方）。"""
import unicodedata

MEASURED_TOP = 50  # 順位を測る範囲

METHOD_LABELS = {
    "keyword": "キーワード検索",
    "vector": "ベクトル検索",
    "hybrid": "ハイブリッド検索",
    "hybrid_ranker": "ハイブリッド＋ランカー",
}


def title(text: str) -> None:
    print()
    print("=" * 64)
    print(text)
    print("=" * 64)


def section(text: str) -> None:
    print()
    print(f"--- {text} ---")


def step(i: int, n: int, text: str) -> None:
    print(f"\n[{i}/{n}] {text}")


def one_line(text, limit: int = 60) -> str:
    """改行を空白に直して、limit 文字までに切り詰める。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[:limit] + "…"


def rank_label(rank, n_results: int, measured: int = MEASURED_TOP) -> str:
    """順位の言い方。上位 measured 件にないものは「圏外」、検索結果が0件のものは「未ヒット」。"""
    if rank is not None:
        return f"{rank}位"
    if n_results == 0:
        return "未ヒット"
    return f"圏外（上位{measured}件まで測定）"


def display_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, width: int) -> str:
    """全角を2文字分として、右側を空白で埋める。"""
    return s + " " * max(0, width - display_width(s))


def score_text(x) -> str:
    return "-" if x is None else f"{x:.4f}"


def api_calls_line(counts: dict) -> str:
    parts = []
    if counts.get("embedding"):
        parts.append(f"埋め込み {counts['embedding']} 回")
    if counts.get("chat"):
        parts.append(f"回答の生成 {counts['chat']} 回")
    if counts.get("analyze"):
        parts.append(f"Analyze {counts['analyze']} 回")
    return "Azure OpenAI の呼び出し：" + ("、".join(parts) if parts else "なし")


# ------------------------------------------------------------------ 検索結果の表示

def _scores(hit: dict) -> str:
    s = f"スコア {score_text(hit.get('@search.score'))}"
    if hit.get("@search.reranker_score") is not None:
        s += f"  ランカー {score_text(hit.get('@search.reranker_score'))}"
    return s


def print_bushou_hits(hits: list, limit: int = 5, answer_ids=None, extra: dict = None) -> None:
    """武将の検索結果を上から limit 件表示する。answer_ids に入る武将には「◀ 正解」を付ける。

    extra：{武将の id: 補足の文字列}。順位の移り変わりなどを添えたいとき用。
    """
    ids = set(answer_ids or [])
    if not hits:
        print("  （ヒットした武将はいません）")
        return
    for i, h in enumerate(hits[:limit], start=1):
        mark = "  ◀ 正解" if h.get("id") in ids else ""
        print(f" {i:>2}位  {h.get('name')}（{h.get('id')}）  {_scores(h)}{mark}")
        place = " / ".join(x for x in (h.get("province"), h.get("clan")) if x)
        battles = "、".join(h.get("battles") or [])
        print(f"        出身・家：{place}　合戦：{one_line(battles, 40)}")
        print(f"        {one_line(h.get('profile'), 56)}")
        if extra and h.get("id") in extra:
            print(f"        {extra[h.get('id')]}")


# ------------------------------------------------------------------ 表

def in_notebook() -> bool:
    """Jupyter の Notebook の中か（IPython が使え、画面に HTML を出せるか）。"""
    try:
        from IPython import get_ipython

        shell = get_ipython()
        return shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell"
    except Exception:  # noqa: BLE001  IPython がなければ、スクリプトとして扱う
        return False


def _cell(value) -> str:
    return "-" if value is None else str(value)


def table_text(headers: list, rows: list, indent: int = 2) -> str:
    """文字の表。全角を2文字分として桁をそろえる。値が None のセルは「-」と書く。"""
    body = [[_cell(c) for c in row] for row in rows]
    widths = [max(display_width(str(h)), *(display_width(r[i]) for r in body)) if body else display_width(str(h))
              for i, h in enumerate(headers)]
    gap = "  "
    lines = [" " * indent + gap.join(pad(str(h), w) for h, w in zip(headers, widths)).rstrip()]
    for r in body:
        lines.append(" " * indent + gap.join(pad(c, w) for c, w in zip(r, widths)).rstrip())
    return "\n".join(lines)


def table_html(headers: list, rows: list) -> str:
    import html

    head = "".join(f"<th style='text-align:left'>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(_cell(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def table(headers: list, rows: list, indent: int = 2) -> None:
    """表を出す。スクリプトでは文字の表、Notebook（IPython）では HTML の表。

    headers  見出しの文字列の一覧
    rows     行の一覧（各行はセルの値の一覧。None は「-」）
    """
    if in_notebook():
        from IPython.display import HTML, display

        display(HTML(table_html(headers, rows)))
    else:
        print(table_text(headers, rows, indent))
