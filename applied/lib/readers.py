"""手元の Python で、形式の違う文書を読む（トピック 14）。

形式ごとに使うライブラリと、チャンク（検索の単位）の切り方：
  PDF    pypdf        ページごとに1チャンク。文字の層がない（画像だけの）PDF は 0 文字になる
  Word   python-docx  見出しごとに1チャンク（見出しの段落から、次の見出しの手前まで）
  Excel  openpyxl     シートの1行を1チャンク。「列名: 値」の形にして、何の数字かが分かるようにする
  メール email         1通を1チャンク（件名・差出人・宛先・日時を本文の前に付ける）
  画像   （なし）      文字は取れない（0 文字）。画像の中の文字を読むには OCR が要る

Word の見出しは「見出し」スタイルではなく、太字の大きな文字で書かれていることが多い（このデータもそう）。
そのため、スタイル名ではなく書式（全部太字で、文字が 12pt 以上）で見出しを見分ける。
"""
import email
import email.policy
from dataclasses import dataclass, field
from pathlib import Path

from .config import DATA_DIR


@dataclass
class Chunk:
    text: str
    label: str = ""          # 何のまとまりか（ページ番号、見出し、シート名と行など）


@dataclass
class Document:
    path: Path
    format: str              # pdf / docx / xlsx / eml / png
    kind: str = ""           # manifest の種類（job_posting、resume など）
    kind_label: str = ""     # 求人票、職務経歴書 など
    doc_id: str = ""
    chunks: list = field(default_factory=list)
    note: str = ""           # 読めなかった理由など

    @property
    def chars(self) -> int:
        return sum(len(c.text) for c in self.chunks)

    @property
    def rel(self) -> str:
        return self.path.relative_to(DATA_DIR).as_posix()


def read_pdf(path: Path) -> list:
    from pypdf import PdfReader

    chunks = []
    for i, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            chunks.append(Chunk(text, f"{i}ページ"))
    return chunks


def _is_heading(p) -> bool:
    runs = [r for r in p.runs if r.text.strip()]
    if not runs or len(p.text.strip()) > 30:
        return False
    sizes = [r.font.size.pt for r in runs if r.font.size is not None]
    return all(r.bold for r in runs) and bool(sizes) and min(sizes) >= 12


def read_docx(path: Path) -> list:
    import docx

    d = docx.Document(str(path))
    chunks = []
    # 先頭の表（氏名・応募番号など）は、1つのチャンクにする
    for t in d.tables:
        rows = [" / ".join(c.text.strip() for c in r.cells) for r in t.rows]
        chunks.append(Chunk("\n".join(rows), "表"))
    heading, lines = "（冒頭）", []
    for p in d.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        if _is_heading(p):
            if lines:
                chunks.append(Chunk(f"{heading}\n" + "\n".join(lines), heading))
            heading, lines = text, []
        else:
            lines.append(text)
    if lines:
        chunks.append(Chunk(f"{heading}\n" + "\n".join(lines), heading))
    return chunks


def read_xlsx(path: Path) -> list:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    chunks = []
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
        if len(rows) < 2:
            continue
        header = [str(c) if c is not None else "" for c in rows[0]]
        if len([h for h in header if h]) < 2:       # 見出しの行がないシート（注記など）は、まとめて1チャンク
            chunks.append(Chunk("\n".join(" ".join(str(c) for c in r if c is not None) for r in rows), ws.title))
            continue
        for n, row in enumerate(rows[1:], start=2):
            pairs = [f"{h}: {v}" for h, v in zip(header, row) if h and v is not None and str(v).strip()]
            chunks.append(Chunk("\n".join(pairs), f"{ws.title} {n}行目"))
    return chunks


def read_eml(path: Path) -> list:
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content().strip() if body is not None else ""
    head = [f"件名: {msg['subject']}", f"差出人: {msg['from']}", f"宛先: {msg['to']}", f"日時: {msg['date']}"]
    return [Chunk("\n".join(head) + "\n\n" + text, "1通")]


def read_image(path: Path) -> list:
    if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"PNG の画像ではありません: {path.name}")
    return []           # 画像には文字の層がない。OCR をしないと文字は取れない


READERS = {".pdf": ("pdf", read_pdf), ".docx": ("docx", read_docx), ".xlsx": ("xlsx", read_xlsx),
           ".eml": ("eml", read_eml), ".png": ("png", read_image)}


def read_document(path: Path, meta: dict | None = None) -> Document:
    fmt, reader = READERS[path.suffix.lower()]
    meta = meta or {}
    doc = Document(path=path, format=fmt, kind=meta.get("kind", ""), kind_label=meta.get("kind_label", ""),
                   doc_id=meta.get("doc_id", ""))
    doc.chunks = reader(path)
    if not doc.chunks:
        doc.note = "文字が取れない（画像だけ）" if fmt in ("pdf", "png") else "空"
    return doc


def read_all(manifest_files: list) -> list:
    """manifest の順に、全ファイルを読む。"""
    return [read_document(DATA_DIR / f["path"], f) for f in manifest_files]
