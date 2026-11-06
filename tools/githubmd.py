"""GitHub が Markdown の見出しに付ける飛び先（アンカー）の作り方。

手順書のリンク（`#4-接続の設定を作る` のような）を GitHub と読む形のページの両方で効かせるため、
試験（tests/test_guide.py）とページの生成（tools/build_site.py）が同じ規則を使う。標準ライブラリだけ。
github-slugger をそのまま写したものではないので、丸数字（①）や絵文字などの珍しい文字では、GitHub の飛び先と違うことがある。
"""

import re
import unicodedata


def github_anchor(heading: str) -> str:
    """見出しの飛び先：小文字にして、文字・数字・ハイフン・下線・空白だけ残し、空白をハイフンにする。日本語はそのまま。"""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading).replace("`", "").strip().lower()
    kept = "".join(c for c in text
                   if c in " -_" or unicodedata.category(c)[0] in "LMN" or unicodedata.category(c) == "Pc")
    return kept.replace(" ", "-")


class GithubSlugger:
    """1つの文書の中で見出しの飛び先を作る。同じ飛び先が出たら `-1`・`-2` を付ける（github-slugger とほとんど同じ。違いは、冒頭の注記）。"""

    def __init__(self):
        self.occurrences = {}

    def slug(self, heading: str) -> str:
        slug = original = github_anchor(heading)
        while slug in self.occurrences:
            self.occurrences[original] += 1
            slug = f"{original}-{self.occurrences[original]}"
        self.occurrences[slug] = 0
        return slug
