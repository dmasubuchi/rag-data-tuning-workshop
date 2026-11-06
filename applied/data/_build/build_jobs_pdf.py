"""求人票（md）を A4 の PDF にする。reportlab の CID フォント（HeiseiKakuGo-W5 / HeiseiMin-W3）を使う。

骨組みは Qwen（qwen3-coder:30b）が書き、表の中身の Paragraph 化・列幅・見出しの縦線・ページ枠・
フッターを手で直した。
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from lib_common import CONTENT, DATA
from mdlite import parse_md

NAVY = colors.HexColor("#1F3A5F")
GRAY = colors.HexColor("#666666")
LABEL_BG = colors.HexColor("#E8ECF2")
GOTHIC, MINCHO = "HeiseiKakuGo-W5", "HeiseiMin-W3"
LEFT, RIGHT, TOP, BOTTOM = 20 * mm, 20 * mm, 12 * mm, 18 * mm
CONTENT_W = A4[0] - LEFT - RIGHT


def _style(name, font, size, **kw):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=size * 1.6, wordWrap="CJK", **kw)


def build(md_path: Path, out_path: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont(GOTHIC))
    pdfmetrics.registerFont(UnicodeCIDFont(MINCHO))
    doc = parse_md(md_path.read_text(encoding="utf-8"))
    meta = dict(doc.meta)
    notice = doc.notice

    body = _style("body", MINCHO, 10, spaceAfter=3)
    bullet = _style("bullet", MINCHO, 10, leftIndent=14, firstLineIndent=-10, spaceAfter=2)
    h2 = _style("h2", GOTHIC, 13, textColor=NAVY)
    label = _style("label", GOTHIC, 10, textColor=NAVY)
    value = _style("value", MINCHO, 10)
    band_small = _style("band_small", GOTHIC, 11, textColor=colors.white)
    band_title = _style("band_title", GOTHIC, 20, textColor=colors.white, alignment=TA_LEFT)
    note = _style("note", MINCHO, 9, textColor=GRAY)

    story = []
    band = Table([[Paragraph(escape(doc.title), band_small)], [Paragraph(escape(meta.get("職種", "")), band_title)]],
                 colWidths=[CONTENT_W])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                              ("TOPPADDING", (0, 0), (0, 0), 6), ("BOTTOMPADDING", (0, 1), (0, 1), 8)]))
    story += [band, Spacer(1, 8)]

    rows = [[Paragraph(escape(k), label), Paragraph(escape(v), value)] for k, v in doc.meta if k != "職種"]
    info = Table(rows, colWidths=[35 * mm, CONTENT_W - 35 * mm])
    info.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), LABEL_BG), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C0CC")),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [info]

    for block in doc.blocks:
        t = block["type"]
        if t == "h2":
            head = Table([[Paragraph(escape(block["text"]), h2)]], colWidths=[CONTENT_W], rowHeights=[22])
            head.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, 0), 4, NAVY), ("LEFTPADDING", (0, 0), (0, 0), 8),
                                      ("VALIGN", (0, 0), (0, 0), "MIDDLE"), ("TOPPADDING", (0, 0), (0, 0), 0),
                                      ("BOTTOMPADDING", (0, 0), (0, 0), 0)]))
            story += [Spacer(1, 8), head, Spacer(1, 3)]
        elif t == "p":
            story.append(Paragraph(escape(block["text"]), body))
        elif t == "ul":
            story += [Paragraph("・" + escape(item), bullet) for item in block["items"]]
    story += [Spacer(1, 12), Paragraph(f"※ この文書は{escape(notice)}です。実在の人物・企業とは関係ありません。", note)]

    footer_left = f"サンプルテック（架空の会社）｜求人票 {meta['求人番号']} {meta['版']}"

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#B8C0CC"))
        canvas.line(LEFT, 14 * mm, A4[0] - RIGHT, 14 * mm)
        canvas.setFont(MINCHO, 8)
        canvas.setFillColor(GRAY)
        canvas.drawString(LEFT, 9 * mm, footer_left)
        canvas.drawRightString(A4[0] - RIGHT, 9 * mm, f"{notice}｜{_doc.page}")
        canvas.restoreState()

    out = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT, topMargin=TOP,
                            bottomMargin=BOTTOM, invariant=1,
                            title=f"求人票 {meta['求人番号']} {meta['職種']} {meta['版']}",
                            author="サンプルテック 採用（研修用）", subject=notice, creator="サンプルテック 採用（研修用）")
    out.build(story, onFirstPage=footer, onLaterPages=footer)


# 入力のフォルダ -> 出力のフォルダ。
#   jobs     現行の版の求人票（manifest に入れる。build_hr_index.py が Storage に置く）
#   updates  旧い版の求人票（トピック 17「更新と削除」だけで使う。manifest に入れない。build_hr_index.py も Storage に置かない）
FOLDERS = ("jobs", "updates")


def main() -> None:
    for folder in FOLDERS:
        out_dir = DATA / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        for md_file in sorted((CONTENT / folder).glob("*.md")):
            out_file = out_dir / (md_file.stem + ".pdf")
            build(md_file, out_file)
            print(out_file.relative_to(DATA))


if __name__ == "__main__":
    main()
