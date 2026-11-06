"""職務経歴書（md）を Word（.docx）にする。python-docx を使う。

骨組み（ページ設定、メタ情報の表、見出し・段落・箇条書きの書き出し）は Qwen（qwen3-coder:30b）が書き、
次を手で直した: 存在しない python-docx の API（見出しの罫線、PAGE フィールド）、表の空の先頭行、
glob の書き方、スタイル全体への東アジア用フォント指定、列幅、フッター。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from lib_common import CONTENT, DATA, FIXED_DT, NOTICE, normalize_zip
from mdlite import parse_md

FONT = "游明朝"
GRAY = RGBColor(100, 100, 100)
AUTHOR = "サンプルテック 採用（研修用）"


def set_font(run, size=None, bold=None, color=None):
    """run の日本語フォントと大きさを設定する（w:eastAsia にも同じ名前を入れる）。"""
    run.font.name = FONT
    rpr = run._element.get_or_add_rPr()
    rpr.rFonts.set(qn("w:eastAsia"), FONT)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def style_east_asia(style):
    style.font.name = FONT
    rpr = style.element.get_or_add_rPr()
    rpr.rFonts.set(qn("w:eastAsia"), FONT)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:eastAsia"), "ja-JP")


def shade(cell, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._element.get_or_add_tcPr().append(shd)


def bottom_border(paragraph, color="1F3A5F"):
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    paragraph._element.get_or_add_pPr().append(pbdr)


def add_page_field(paragraph, size=9):
    """複合フィールド（begin / instrText / end）でページ番号を入れる。"""
    for kind, text in (("begin", None), (None, " PAGE "), ("end", None)):
        run = paragraph.add_run()
        set_font(run, size=size, color=GRAY)
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._element.append(el)


def build(md_path: Path, out_path: Path) -> None:
    doc = parse_md(md_path.read_text(encoding="utf-8"))
    meta = dict(doc.meta)
    document = Document()

    sec = document.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Mm(20)
    for name in ("Normal", "List Bullet"):
        style_east_asia(document.styles[name])
    document.styles["Normal"].font.size = Pt(10.5)

    cp = document.core_properties
    cp.title = f"{doc.title} {meta['応募番号']} {meta['氏名']}"
    cp.author = cp.last_modified_by = AUTHOR
    cp.subject = doc.notice or NOTICE
    cp.created = cp.modified = FIXED_DT.replace(tzinfo=None)
    cp.comments = f"{NOTICE}。実在の人物・企業とは関係ありません。"

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(title.add_run(doc.title), size=18, bold=True)

    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for key, value in doc.meta:
        label_cell, value_cell = table.add_row().cells
        label_cell.width, value_cell.width = Mm(35), Mm(125)
        set_font(label_cell.paragraphs[0].add_run(key), size=10.5, bold=True)
        set_font(value_cell.paragraphs[0].add_run(value), size=10.5)
        shade(label_cell, "D9E2F3")

    table.columns[0].width, table.columns[1].width = Mm(35), Mm(125)

    for block in doc.blocks:
        t = block["type"]
        if t == "h2":
            p = document.add_paragraph()
            set_font(p.add_run(block["text"]), size=12, bold=True)
            bottom_border(p)
            p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(12), Pt(4)
            p.paragraph_format.keep_with_next = True
        elif t == "h3":
            left, _, right = block["text"].partition("｜")
            p = document.add_paragraph()
            set_font(p.add_run(left.strip()), size=10.5, bold=True)
            if right:
                p.paragraph_format.tab_stops.add_tab_stop(Mm(170), WD_TAB_ALIGNMENT.RIGHT)
                set_font(p.add_run("\t" + right.strip()), size=10.5)
            p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(6), Pt(2)
            p.paragraph_format.keep_with_next = True
        elif t == "p":
            p = document.add_paragraph()
            set_font(p.add_run(block["text"]), size=10.5)
            p.paragraph_format.line_spacing = 1.4
            p.paragraph_format.space_after = Pt(4)
        elif t == "ul":
            for item in block["items"]:
                p = document.add_paragraph(style="List Bullet")
                set_font(p.add_run(item), size=10.5)

    end = document.add_paragraph()
    end.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_font(end.add_run(f"（{doc.notice or NOTICE}）"), size=9, color=GRAY)

    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(footer.add_run(f"{doc.notice or NOTICE}｜ページ "), size=9, color=GRAY)
    add_page_field(footer)

    document.save(out_path)
    normalize_zip(out_path)


def main() -> None:
    out_dir = DATA / "resumes"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted((CONTENT / "resumes").glob("*.md")):
        out_path = out_dir / (path.stem + ".docx")
        build(path, out_path)
        print(out_path.relative_to(DATA))


if __name__ == "__main__":
    main()
