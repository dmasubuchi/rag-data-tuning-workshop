"""各ビルドスクリプトが共有する道具。固定の日時、フォント探し、zip の正規化。

作り直すには macOS の字体（ヒラギノ、Klee）が要る。macOS 以外では、描画に使う字体が見つからず、作り直せない。
文書そのものは、作り直さなくても Repo にある（作り直すのは、教材を直す人だけ）。
"""
from __future__ import annotations

import glob
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # applied/data/_build
DATA = ROOT.parent                              # applied/data
CONTENT = ROOT / "content"

JST = timezone(timedelta(hours=9))
FIXED_DT = datetime(2026, 10, 30, 10, 0, 0, tzinfo=JST)   # 文書のプロパティに入れる固定の日時
NOTICE = "研修用の架空データ"
ZIP_DATE = (2026, 10, 30, 10, 0, 0)


def load_json(name: str):
    with open(CONTENT / name, encoding="utf-8") as f:
        return json.load(f)


# フォント名 -> (候補パスのリスト, ttc の index)
_FONT_CANDIDATES = {
    "gothic": (["/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"], 0),
    "gothic_bold": (["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"], 0),
    "mincho": (["/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"], 0),
    "mincho_bold": (["/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"], 2),
    "maru": (["/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc"], 1),
    # 手書き風。macOS の Klee（ペン書き風）。無ければ丸ゴシックで代用する。
    "hand": (glob.glob("/System/Library/AssetsV2/com_apple_MobileAsset_Font8/*/AssetData/Klee.ttc"), 1),
}


def find_font(kind: str):
    """(path, index) を返す。Pillow の ImageFont.truetype(path, size, index=index) で使う。"""
    paths, index = _FONT_CANDIDATES[kind]
    for p in paths:
        if os.path.exists(p):
            return p, index
    if kind == "hand":
        return find_font("maru")
    raise FileNotFoundError(f"font not found: {kind}")


def normalize_zip(path: Path | str) -> None:
    """docx/xlsx（zip）の各エントリの更新日時を固定し、同じ入力から同じバイト列になるようにする。"""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "docProps/core.xml":   # openpyxl は保存時の現在時刻を modified に入れるので固定する
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                              rb"\g<1>2026-10-30T10:00:00Z\g<2>", data)
            zi = zipfile.ZipInfo(info.filename, date_time=ZIP_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            zout.writestr(zi, data)
    tmp.replace(path)
