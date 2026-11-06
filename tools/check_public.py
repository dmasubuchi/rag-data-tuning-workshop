#!/usr/bin/env python3
"""公開前の検査。

Repo に、秘密・禁止語・個人の絶対パス・メールアドレスが残っていないかを調べる。
Python 3.11 以上の標準ライブラリだけで動く。

使い方:
    python tools/check_public.py [--banned PATH] [--history] [PATH ...]

- PATH を省略すると、いまのフォルダーを調べる。
- Git の Repo の中では、Git が数えるファイル（追跡中のもの、まだ追跡していないが
  .gitignore の対象ではないもの）だけを調べる。.git/ や .gitignore の対象は調べない。
  Git の外のパスは、その下のファイルを全部調べる。
- テキストとして読めない（UTF-8 でない・バイナリ）ファイルは飛ばし、その数を最後に出す。
- 禁止語のリストは Repo の外に置く（1行1語）。--banned、環境変数 PUBLIC_CHECK_BANNED、
  ~/ai/runtime/public-check/banned.txt の順に探す。
- --history を付けると、Git の履歴にある全部のファイルの中身（消したものも）も調べる。

見つけた場所は「パス:行: [種類] 先頭の数文字…」で出す。値そのものは出さない。

終了コード: 0=見つからなかった / 1=見つかった / 2=検査できなかった（禁止語のリストがない・空、
調べる場所がない、など）
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterator, NamedTuple

BANNED_ENV = "PUBLIC_CHECK_BANNED"
BANNED_DEFAULT = "~/ai/runtime/public-check/banned.txt"
EXAMPLE_DOMAINS = {"example.com", "example.jp"}

# 秘密らしい文字列の型。このファイル自身に引っかからないよう、リテラルの "=" は [=] と書く。
# 名前の規則（最後の型）は、AZURE_SEARCH_ADMIN_KEY、"primaryKey"、"key1"、Ocp-Apim-Subscription-Key のように、
# 名前に key・secret・token・password・connection string を含み、そのあとに 20 文字以上の値が続くものを拾う。
# \w*+ は、長い行で正規表現が遅くならないための「戻らない」繰り返し（Python 3.11 以上）。
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{32,}"),
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"SharedAccessSignature[=]|[?&]sig=[A-Za-z0-9%+/=]{20,}"),
    re.compile(r"""Authorization["']?\s*[:=]\s*["']?Bearer\s+[A-Za-z0-9+/_.=-]{20,}""", re.IGNORECASE),
    re.compile(
        r"""(?:key|secret|token|password|passwd|connection_?string)\w*+["']?\s*[:=]\s*["']?[A-Za-z0-9+/_.-]{20,}""",
        re.IGNORECASE,
    ),
]
# テナント・サブスクリプションなどの ID の形（ARM のリソース ID の /subscriptions/<ID>/ もこれで拾う）
GUID_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
ABS_PATH_PATTERN = re.compile(r"/Users/[A-Za-z0-9._-]+/")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")

BINARY_SNIFF_BYTES = 8192
BATCH_BYTES = 64 * 1024 * 1024  # 履歴を読むとき、1回に git から受け取る量のめやす


class Finding(NamedTuple):
    path: str
    line: int
    kind: str  # "secret" | "guid" | "banned" | "abs-path" | "email"
    excerpt: str  # 見つけた文字列の先頭の数文字だけ。あとは "…" で伏せる


class BannedListError(Exception):
    """禁止語のリストがない・読めない・空。"""


def default_banned_path() -> Path:
    return Path(os.environ.get(BANNED_ENV) or BANNED_DEFAULT).expanduser()


def load_banned(path: Path) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise BannedListError(f"禁止語のリストがない（読めない）: {path}（{e.strerror or e}）") from e
    except UnicodeDecodeError as e:
        raise BannedListError(f"禁止語のリストが UTF-8 ではない: {path}") from e
    words = [line.strip() for line in text.split("\n")]
    words = [w for w in words if w]
    if not words:
        raise BannedListError(f"禁止語のリストが空: {path}")
    return words


def _mask(matched: str) -> str:
    """見つけた文字列の先頭の数文字だけを残して伏せる。"""
    return matched[: min(3, len(matched) // 2)] + "…"


def scan_text(path: str, text: str, banned: list[str]) -> list[Finding]:
    banned_patterns = [re.compile(re.escape(term), re.IGNORECASE) for term in banned if term]
    findings: list[Finding] = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        secret_spans: list[tuple[int, int]] = []
        for pattern in SECRET_PATTERNS:
            for m in pattern.finditer(line):
                if any(m.start() < end and start < m.end() for start, end in secret_spans):
                    continue  # 同じ場所を、別の型でも見つけた
                secret_spans.append(m.span())
                findings.append(Finding(path, lineno, "secret", _mask(m.group())))
        for m in GUID_PATTERN.finditer(line):
            if m.group().strip("0-") != "":  # すべて 0 の GUID は、空の値の印なので除く
                findings.append(Finding(path, lineno, "guid", _mask(m.group())))
        for m in ABS_PATH_PATTERN.finditer(line):
            findings.append(Finding(path, lineno, "abs-path", _mask(m.group())))
        for m in EMAIL_PATTERN.finditer(line):
            if m.group(1).lower() not in EXAMPLE_DOMAINS:
                findings.append(Finding(path, lineno, "email", _mask(m.group())))
        for pattern in banned_patterns:
            for m in pattern.finditer(line):
                findings.append(Finding(path, lineno, "banned", _mask(m.group())))
    return findings


class _Result:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.scanned = 0
        self.skipped = 0

    def add(self, label: str, text: str | None, banned: list[str]) -> None:
        if text is None:
            self.skipped += 1
            return
        self.scanned += 1
        self.findings.extend(scan_text(label, text, banned))


def _decode(data: bytes) -> str | None:
    """テキストとして読めればその文字列、読めなければ None。"""
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _read_file_text(path: Path) -> str | None:
    """ファイルの文字列。シンボリックリンクは辿らず、行き先の文字列を返す。"""
    try:
        if path.is_symlink():
            return os.readlink(path)
        if path.is_file():
            return _decode(path.read_bytes())
    except OSError:
        pass
    return None


def _git_files(directory: Path) -> list[str] | None:
    """directory の下で Git が数えるファイルの相対パス。Git の Repo の中でなければ None。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(directory), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    names = (os.fsdecode(raw) for raw in proc.stdout.split(b"\0") if raw)
    return list(dict.fromkeys(names))


def _walk_files(root: Path) -> Iterator[str]:
    """root の下のファイル全部の相対パス（.git/ だけは除く）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for d in sorted(dirnames):
            if d == ".git":
                continue
            if os.path.islink(os.path.join(dirpath, d)):
                filenames.append(d)  # フォルダーへのリンクは、辿らずにファイルとして扱う
            else:
                keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            if name != ".git":
                yield os.path.relpath(os.path.join(dirpath, name), root)


def _scan_tree(target: Path, banned: list[str], result: _Result) -> None:
    if not target.is_dir() or target.is_symlink():
        result.add(target.as_posix(), _read_file_text(target), banned)
        return
    names = _git_files(target)
    if names is None:
        names = list(_walk_files(target))
    for name in names:
        path = target / name
        if path.is_dir() and not path.is_symlink():
            continue  # サブモジュールなど
        if not os.path.lexists(path):
            continue  # 追跡中だが消してあるファイル
        result.add(path.as_posix(), _read_file_text(path), banned)


def _git_toplevel(path: Path) -> Path | None:
    directory = path if path.is_dir() else path.parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"], capture_output=True
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return Path(os.fsdecode(proc.stdout).strip())


def _git_run(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=True)
    return proc.stdout


def _history_blobs(repo: Path) -> Iterator[tuple[str, str, bytes]]:
    """履歴にある全部のファイルの中身を (オブジェクト名, パス, 中身) で返す。"""
    paths: dict[str, str] = {}
    for line in os.fsdecode(_git_run(repo, "rev-list", "--all", "--objects")).split("\n"):
        if line:
            sha, _, path = line.partition(" ")
            paths.setdefault(sha, path)
    if not paths:
        return
    listing = _git_run(repo, "cat-file", "--batch-check", stdin="\n".join(paths).encode() + b"\n")
    blobs: list[tuple[str, int]] = []
    for line in listing.decode().split("\n"):
        parts = line.split(" ")
        if len(parts) == 3 and parts[1] == "blob":
            blobs.append((parts[0], int(parts[2])))

    batch: list[str] = []
    total = 0
    for sha, size in blobs + [("", 0)]:  # 最後の "" は、残りを流すための印
        if batch and (not sha or total + size > BATCH_BYTES):
            yield from _read_blobs(repo, batch, paths)
            batch, total = [], 0
        if sha:
            batch.append(sha)
            total += size


def _read_blobs(repo: Path, shas: list[str], paths: dict[str, str]) -> Iterator[tuple[str, str, bytes]]:
    data = _git_run(repo, "cat-file", "--batch", stdin="\n".join(shas).encode() + b"\n")
    pos = 0
    while pos < len(data):
        eol = data.index(b"\n", pos)
        header = data[pos:eol].split(b" ")
        pos = eol + 1
        if len(header) != 3:
            continue  # "missing" など
        size = int(header[2])
        yield header[0].decode(), paths.get(header[0].decode(), ""), data[pos : pos + size]
        pos += size + 1


def _scan_history(repo: Path, banned: list[str], result: _Result) -> None:
    for sha, path, data in _history_blobs(repo):
        label = f"{path}@{sha[:7]}" if path else sha[:7]
        result.add(label, _decode(data), banned)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_public.py",
        description="公開前の検査：秘密・禁止語・個人の絶対パス・メールアドレスを探す",
    )
    parser.add_argument(
        "--banned",
        type=Path,
        help=f"禁止語のリスト（1行1語）。省略時は環境変数 {BANNED_ENV}、なければ {BANNED_DEFAULT}",
    )
    parser.add_argument("--history", action="store_true", help="Git の履歴にある全部のファイルの中身も調べる")
    parser.add_argument("paths", nargs="*", type=Path, help="調べる場所（省略時はいまのフォルダー）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    targets = args.paths or [Path(".")]

    try:
        banned = load_banned(args.banned or default_banned_path())
    except BannedListError as e:
        print(f"NG: {e}", file=sys.stderr)
        print(f"    --banned か環境変数 {BANNED_ENV} で指定する", file=sys.stderr)
        return 2

    for target in targets:
        if not (target.exists() or target.is_symlink()):
            print(f"NG: 調べる場所がない: {target}", file=sys.stderr)
            return 2

    result = _Result()
    for target in targets:
        _scan_tree(target, banned, result)

    if args.history:
        repos: dict[Path, None] = {}
        for target in targets:
            top = _git_toplevel(target)
            if top is None:
                print(f"NG: --history は Git の Repo の中でしか使えない: {target}", file=sys.stderr)
                return 2
            repos[top.resolve()] = None
        for repo in repos:
            try:
                _scan_history(repo, banned, result)
            except (subprocess.CalledProcessError, OSError) as e:
                print(f"NG: Git の履歴を読めなかった: {repo}（{e}）", file=sys.stderr)
                return 2

    for f in result.findings:
        print(f"{f.path}:{f.line}: [{f.kind}] {f.excerpt}")
    note = f"、テキストとして読めず飛ばした {result.skipped}" if result.skipped else ""
    if result.findings:
        print(f"NG: {len(result.findings)} 件見つかった（{result.scanned} ファイルを検査{note}）")
        return 1
    print(f"OK: 見つからなかった（{result.scanned} ファイルを検査{note}）")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
