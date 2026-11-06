"""図（diagram のページ）を描く部品。どの図も、この色とアイコンだけを使う。

色（4色と、地の薄い青）
  BLUE    主役と、①②の流れ（質問する・探す）
  ORANGE  取ってくるもの、戻る流れ
  GREEN   答え・うまくいった
  GRAY    人（利用者）、なにもしないもの、下ごしらえ
  SOFT    箱の地（薄い青）
アイコン（4種類）：人、索引の箱、書棚、文書
文字：見出し 34px、本文 30px、補足 26px（図の横幅 1600 のとき。スライドの本文とほぼ同じ大きさ）
段階：<g data-step='n'> で囲む。0 は最初から見える。段階は 0〜3 の4つまで
"""
from html import escape

BLUE, ORANGE, GREEN, GRAY = "#1864ab", "#d9480f", "#2b8a3e", "#5b6675"
INK, SOFT, LINE = "#1d2733", "#e7f0fa", "#c9d6e6"
H, B, S = 34, 30, 26      # 文字の大きさ：見出し、本文、補足


def svg(width: int, height: int, *parts: str, top: int = 0) -> str:
    """top：上の余白を切るときの、描く範囲の上端"""
    return f"<svg viewBox='0 {top} {width} {height}'>" + "".join(parts) + "</svg>"


def step(n: int, *parts: str) -> str:
    return f"<g data-step='{n}'>" + "".join(parts) + "</g>"


def text(x, y, s, size=B, color=INK, bold=False, anchor="middle") -> str:
    w = " font-weight='700'" if bold else ""
    return f"<text x='{x}' y='{y}' font-size='{size}' fill='{color}'{w} text-anchor='{anchor}'>{escape(s)}</text>"


def lines(x, y, rows, size=B, color=INK, bold=False, anchor="middle", gap=None) -> str:
    """複数行の文字。y は1行目のベースライン。"""
    gap = gap or int(size * 1.4)
    return "".join(text(x, y + i * gap, r, size, color, bold, anchor) for i, r in enumerate(rows))


def box(x, y, w, h, stroke=GRAY, fill="#fff", width=4, dash=False) -> str:
    d = " stroke-dasharray='14 10'" if dash else ""
    return f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='10' fill='{fill}' stroke='{stroke}' stroke-width='{width}'{d}/>"


def person(x, y, color=GRAY, glasses=False) -> str:
    """人のアイコン。(x, y) は頭の中心。体は y+60 から y+160 まで。glasses=True はアプリ＋生成 AI（s06 のリサーチャー）"""
    s = (f"<circle cx='{x}' cy='{y}' r='38' fill='{color}'/>"
         f"<path d='M{x - 66} {y + 160} Q{x - 66} {y + 60} {x} {y + 60} Q{x + 66} {y + 60} {x + 66} {y + 160} Z' fill='{color}'/>")
    if glasses:
        s += (f"<circle cx='{x - 12}' cy='{y}' r='10' fill='none' stroke='#fff' stroke-width='4'/>"
              f"<circle cx='{x + 12}' cy='{y}' r='10' fill='none' stroke='#fff' stroke-width='4'/>"
              f"<line x1='{x - 2}' y1='{y}' x2='{x + 2}' y2='{y}' stroke='#fff' stroke-width='4'/>")
    return s


def index_box(x, y, w=300, color=BLUE) -> str:
    """索引の箱（引き出しが3段）。高さ 170"""
    s = box(x, y, w, 170, stroke=color, fill=SOFT)
    for i in range(3):
        s += box(x + 18, y + 16 + i * 50, w - 36, 42, stroke=color, width=3)
        s += f"<rect x='{x + w / 2 - 30}' y='{y + 32 + i * 50}' width='60' height='10' rx='5' fill='{color}'/>"
    return s


def shelf(x, y, w=300) -> str:
    """書棚（本が2段）。高さ 180"""
    s = box(x, y, w, 180, stroke=GRAY)
    s += f"<line x1='{x}' y1='{y + 90}' x2='{x + w}' y2='{y + 90}' stroke='{GRAY}' stroke-width='4'/>"
    tones = ["#a5c3e4", "#c9d6e6", "#8fb0d6", "#d3dae3"]
    n = int((w - 16) // 36)
    for row in range(2):
        for i in range(n):
            h = 64 + (i * 7) % 12
            s += f"<rect x='{x + 12 + i * 36}' y='{y + 86 + row * 90 - h}' width='28' height='{h}' fill='{tones[(i + row) % 4]}'/>"
    return s


def doc(x, y, w=90, h=116, color=GRAY) -> str:
    """文書（右上を折った紙）"""
    f = 26
    return (f"<path d='M{x} {y} H{x + w - f} L{x + w} {y + f} V{y + h} H{x} Z' fill='#fff' stroke='{color}' stroke-width='4'/>"
            f"<path d='M{x + w - f} {y} V{y + f} H{x + w}' fill='none' stroke='{color}' stroke-width='4'/>"
            + "".join(f"<line x1='{x + 14}' y1='{y + 44 + i * 18}' x2='{x + w - 14}' y2='{y + 44 + i * 18}' stroke='{LINE}' stroke-width='5'/>"
                      for i in range(4)))


def arrow(points, color=BLUE, width=7, dash=False) -> str:
    """折れ線の矢印。points は [(x, y), …]。最後の点が矢の先"""
    (x1, y1), (x2, y2) = points[-2], points[-1]
    dx, dy = x2 - x1, y2 - y1
    n = (dx * dx + dy * dy) ** 0.5 or 1
    ux, uy = dx / n, dy / n
    bx, by = x2 - ux * 22, y2 - uy * 22          # 矢じりの付け根
    d = " stroke-dasharray='16 12'" if dash else ""
    pts = points[:-1] + [(bx, by)]
    path = "M" + " L".join(f"{px:.0f} {py:.0f}" for px, py in pts)
    head = f"{x2:.0f},{y2:.0f} {bx - uy * 12:.0f},{by + ux * 12:.0f} {bx + uy * 12:.0f},{by - ux * 12:.0f}"
    return (f"<path d='{path}' fill='none' stroke='{color}' stroke-width='{width}' stroke-linejoin='round'{d}/>"
            f"<polygon points='{head}' fill='{color}'/>")
