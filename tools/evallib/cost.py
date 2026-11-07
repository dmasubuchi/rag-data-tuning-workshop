"""単価のファイルと、費用の見込み（使った回数 × 単価。標準ライブラリだけ）。

単価は、料金のページで確かめた値を、利用者が config/prices.json に写して書く（config/prices.example.json が見本。値は空）。
この道具は、値を推測で入れない。単価が書いていなければ、回数だけ出し、金額を作らない（0 円とも書かない）。

  費用 = 回数 × 単価
    セマンティック ランカー   semantic_per_1000 × セマンティックの回数 ÷ 1,000
    埋め込み                  embedding_per_1m_tokens × 埋め込みのトークン ÷ 1,000,000
    検索                      search_per_1000 × （検索の回数 − セマンティックの回数） ÷ 1,000

結果の JSON の units.search は、セマンティックの検索も含む（semantic は search の内数）。
セマンティックの検索は、セマンティックの単価で数え、検索の単価では重ねて数えない。

回数が 0 の項目は、単価が空でも金額は 0 なので、単価がなくても困らない（未設定とは数えない）。
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .questions import REPO_DIR

DEFAULT_PRICES = REPO_DIR / "config" / "prices.json"
EXAMPLE_PRICES = REPO_DIR / "config" / "prices.example.json"

# 費用の項目 → (単価の項目名, 単価の単位の回数)。表に出す順
PARTS = ("search", "semantic", "embedding")
PRICE_FIELDS = {"search": ("search_per_1000", 1_000), "semantic": ("semantic_per_1000", 1_000),
                "embedding": ("embedding_per_1m_tokens", 1_000_000)}
PART_LABELS = {"search": "検索", "semantic": "セマンティック", "embedding": "埋め込み"}


class PricesError(Exception):
    """単価のファイルが読めない・値が使えない（利用者に見せる日本語）。"""


@dataclass(frozen=True)
class Prices:
    currency: str = "JPY"
    checked: str = None             # 単価を確かめた日（利用者が書く）
    sources: tuple = ()
    values: dict = None             # 費用の項目 → 単価（None なら未設定）。None のとき全部未設定
    note: str = None
    found: bool = False             # 単価のファイルがあったか

    def price(self, part):
        return (self.values or {}).get(part)

    def unset_parts(self):
        return [part for part in PARTS if self.price(part) is None]


@dataclass(frozen=True)
class Estimate:
    """費用の見込み。amount は、単価のある項目だけを足した金額（足せる項目がなければ None）。"""
    amount: float
    added: tuple        # 足した項目
    unset: tuple        # 回数があるのに単価が未設定で、足せなかった項目

    @property
    def complete(self) -> bool:
        return self.amount is not None and not self.unset

    @property
    def partial(self) -> bool:
        return self.amount is not None and bool(self.unset)


def _number(value, name, path):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise PricesError(f"{path} の {name} は、0 以上の数か null で書きます（今は {value!r}）。")
    return float(value)


def load_prices(path=None) -> Prices:
    """単価のファイルを読む。ファイルがなければ、全部未設定の Prices（found=False）。形が違えば PricesError。"""
    path = Path(path) if path else DEFAULT_PRICES
    if not path.is_file():
        return Prices(found=False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PricesError(f"{path.name} が JSON として読めません（{error}）。config/prices.example.json の形で書きます。") from None
    if not isinstance(data, dict):
        raise PricesError(f"{path.name} は、{{ … }} の形で書きます（config/prices.example.json が見本）。")
    currency = data.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise PricesError(f"{path.name} の currency に、通貨の名前（例 JPY）を書きます。")
    checked = data.get("checked")
    if checked is not None and not isinstance(checked, str):
        raise PricesError(f"{path.name} の checked は、確かめた日の文字（例 2026-11-07）か null で書きます。")
    sources = data.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise PricesError(f"{path.name} の sources は、料金のページの URL の並びで書きます。")
    values = {part: _number(data.get(field), field, path.name) for part, (field, _) in PRICE_FIELDS.items()}
    note = data.get("note")
    return Prices(currency.strip(), checked.strip() if checked and checked.strip() else None, tuple(sources), values,
                  note if isinstance(note, str) else None, True)


def estimate(prices: Prices, search=0, semantic=0, embedding_tokens=0, parts=PARTS) -> Estimate:
    """回数 × 単価。search は、セマンティックを含む検索の回数（結果の units.search）。

    単価が未設定で、回数が 1 以上の項目は、足さずに unset へ入れる。回数が 0 の項目は、どちらにも入れない。
    """
    plain = max(search - semantic, 0)           # セマンティックの検索を、検索の単価で重ねて数えない
    counts = {"search": plain, "semantic": semantic, "embedding": embedding_tokens}
    amount, added, unset = None, [], []
    for part in PARTS:
        if part not in parts or not counts[part]:
            continue
        price = prices.price(part)
        if price is None:
            unset.append(part)
            continue
        amount = (amount or 0.0) + price * counts[part] / PRICE_FIELDS[part][1]
        added.append(part)
    return Estimate(amount, tuple(added), tuple(unset))


def format_amount(amount: float, currency: str) -> str:
    """金額の文字。日本円は「12.34円」、ほかは「12.34 USD」。0 より大きいのに 0.01 に満たないときは、0.00 と書かず「<0.01」。"""
    unit = "円" if currency.upper() == "JPY" else f" {currency}"
    if 0 < amount < 0.005:
        return f"<0.01{unit}"
    return f"{amount:,.2f}{unit}"
