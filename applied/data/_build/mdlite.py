"""この教材用の簡単な Markdown（見出し・段落・箇条書き・「キー: 値」の行）を読む。

形:
    # タイトル
    キー: 値            <- タイトルと最初の「## 」の間の「キー: 値」の行（メタ情報）
    ## 見出し2
    ### 見出し3         <- 職歴の「会社名｜期間」などに使う
    段落（空行で区切る。1 行続きなら 1 段落）
    - 箇条書き
    （研修用の架空データ）   <- 最後の「（」で始まる行は notice に入れる
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MdDoc:
    title: str = ""
    meta: list = field(default_factory=list)      # [(key, value)]
    blocks: list = field(default_factory=list)    # {'type': 'h2'|'h3'|'p'|'ul', 'text'|'items': ...}
    notice: str = ""


_KV = re.compile(r"^([^:：]{1,20})[:：]\s*(.+)$")


def parse_md(text: str) -> MdDoc:
    doc = MdDoc()
    seen_h2 = False
    para: list[str] = []
    items: list[str] = []

    def flush_para():
        if para:
            doc.blocks.append({"type": "p", "text": "".join(para)})
            para.clear()

    def flush_items():
        if items:
            doc.blocks.append({"type": "ul", "items": list(items)})
            items.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para(); flush_items()
            continue
        if line.startswith("# ") and not doc.title:
            doc.title = line[2:].strip()
        elif line.startswith("### "):
            flush_para(); flush_items()
            doc.blocks.append({"type": "h3", "text": line[4:].strip()})
        elif line.startswith("## "):
            flush_para(); flush_items()
            seen_h2 = True
            doc.blocks.append({"type": "h2", "text": line[3:].strip()})
        elif line.startswith("- "):
            flush_para()
            items.append(line[2:].strip())
        elif line.startswith("（研修用") and line.endswith("）"):
            flush_para(); flush_items()
            doc.notice = line.strip("（）")
        elif not seen_h2 and _KV.match(line):
            m = _KV.match(line)
            doc.meta.append((m.group(1).strip(), m.group(2).strip()))
        else:
            flush_items()
            para.append(line.strip())
    flush_para(); flush_items()
    return doc
