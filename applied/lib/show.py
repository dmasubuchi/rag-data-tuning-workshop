"""画面に出す文字列の整え方（見出し、切り詰め、表）。基礎編の show.py と同じ考え方。"""
import unicodedata


def title(text: str) -> None:
    print()
    print("=" * 64)
    print(text)
    print("=" * 64)


def section(text: str) -> None:
    print()
    print(f"--- {text} ---")


def one_line(text, limit: int = 60) -> str:
    """改行を空白に直して、limit 文字までに切り詰める。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[:limit] + "…"


def plain(value) -> str:
    """ライブラリの列挙型（SearchFieldDataType.STRING など）を、Azure での名前（Edm.String など）にする。"""
    return str(getattr(value, "value", value) or "")


def display_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - display_width(s))


def in_notebook() -> bool:
    try:
        from IPython import get_ipython

        shell = get_ipython()
        return shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell"
    except Exception:  # noqa: BLE001
        return False


def _cell(value) -> str:
    return "-" if value is None else str(value)


def table_text(headers: list, rows: list, indent: int = 2) -> str:
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
    """表を出す。スクリプトでは文字の表、Notebook では HTML の表。None のセルは「-」。"""
    if in_notebook():
        from IPython.display import HTML, display

        display(HTML(table_html(headers, rows)))
    else:
        print(table_text(headers, rows, indent))
