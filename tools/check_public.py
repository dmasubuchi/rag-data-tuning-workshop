#!/usr/bin/env python3
"""公開前の検査。

Repo に、秘密・禁止語・個人の絶対パス・メールアドレス・ID（GUID）が残っていないかを調べる。
Python 3.11 以上の標準ライブラリだけで動く。

使い方:
    python tools/check_public.py --banned PATH [--history] [--allow-skipped] [PATH ...]

- PATH を省略すると、いまのフォルダーを調べる。
- 調べるのは、ファイルの中身と、ファイル・フォルダのパス（調べる場所の下の名前）。
- Git の Repo の中では、Git が数えるファイル（追跡中のもの、まだ追跡していないが
  .gitignore の対象ではないもの）だけを調べる。.git/ や .gitignore の対象は調べない。
  Git の外のパスは、その下のファイルを全部調べる。
- 禁止語の照合の前に、本文・パス・禁止語を NFKC でそろえる（全角の英字、半角のカナも当たる）。
- Office の文書（.docx・.xlsx・.pptx など）は、中の XML から文字だけを取り出して調べる。
- テキストとして読めないファイル（バイナリ、UTF-8 でないもの、壊れた Office 文書）は、パスを1つずつ出す。
  飛ばしたファイルがあれば失敗（終了コード 1）。人が見て問題ないと確かめたときだけ --allow-skipped で通す。
- 禁止語のリストは Repo の外に置く（1行1語）。場所は --banned か、環境変数 PUBLIC_CHECK_BANNED で渡す（どちらも必須。
  ~ は展開する）。
- --history を付けると、Git の履歴にある全部のファイルの中身とパス（消したものも）に加えて、コミットの作成者・
  コミッターの名前とメール、コミットとタグのメッセージ、ブランチとタグの名前も調べる。

見つけた場所は「場所: [種類] 先頭の数文字…」で出す（ファイルの中身は「パス:行」）。値そのものは出さない。
禁止語や秘密がパスに入っているときは、出す場所の表記からも伏せる。

終了コード: 0=見つからなかった / 1=見つかった・または飛ばしたファイルがある /
2=検査できなかった（禁止語のリストがない・空、調べる場所がない、検査したファイルが 0 件、など）
"""

import argparse
import html
import io
import os
import re
import subprocess
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path
from typing import Iterator, NamedTuple

BANNED_ENV = "PUBLIC_CHECK_BANNED"
NO_BANNED_GIVEN = f"禁止語のリストの場所を --banned か {BANNED_ENV} で渡す"
# メールの例に使ってよいドメイン。RFC 2606 の予約名（example.com・.net・.org と、.example・.test・.invalid・.localhost で
# 終わるドメイン）と、日本の example.jp。example.com などは、ドメイン全体が一致するものだけ除く。
EXAMPLE_DOMAINS = {"example.com", "example.net", "example.org", "example.jp"}
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")
# 個人のメールではない noreply のアドレス。GitHub の noreply（<数字>+<名前>@users.noreply.github.com など）と、
# 共著者（Co-Authored-By）に書く AI のアドレス。ドメイン全体・アドレス全体が一致するものだけ除く。
NOREPLY_DOMAINS = {"users.noreply.github.com"}
NOREPLY_ADDRESSES = {"noreply@anthropic.com", "noreply@github.com"}

# 秘密らしい文字列の型。このファイル自身に引っかからないよう、リテラルの "=" は [=] と書く。
# 名前の規則（最後の型）は、AZURE_SEARCH_ADMIN_KEY、"primaryKey"、"key1"、Ocp-Apim-Subscription-Key のように、
# 名前に key・secret・token・password・connection string を含み、そのあとに 20 文字以上の値が続くものを拾う。
# \w{0,40}+ は、長い行で正規表現が遅くならないための「戻らない」繰り返し（Python 3.11 以上）。
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{32,}"),
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"SharedAccessSignature[=]|[?&]sig=[A-Za-z0-9%+/=]{20,}"),
    re.compile(r"""Authorization["']?\s*[:=]\s*["']?Bearer\s+[A-Za-z0-9+/_.=-]{20,}""", re.IGNORECASE),
    re.compile(
        r"""(?:key|secret|token|password|passwd|connection_?string)\w{0,40}+["']?\s*[:=]\s*["']?[A-Za-z0-9+/_.-]{20,}""",
        re.IGNORECASE,
    ),
]
# テナント・サブスクリプションなどの ID の形（ARM のリソース ID の /subscriptions/<ID>/ もこれで拾う）
GUID_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
ABS_PATH_PATTERN = re.compile(r"/Users/[A-Za-z0-9._-]+/")
# 先頭の (?<!...) は、英数字の長い連なりの途中から何度も探し直して遅くならないための印
EMAIL_PATTERN = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")

BINARY_SNIFF_BYTES = 8192
BATCH_BYTES = 64 * 1024 * 1024  # 履歴を読むとき、1回に git から受け取る量のめやす
OFFICE_SUFFIXES = (".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm", ".dotx", ".xltx", ".potx")
OFFICE_MAX_BYTES = 256 * 1024 * 1024  # 1つの文書の中身（展開後）の上限。超えたら読めないものとして扱う

# Office の XML から文字を取り出すときの決まり。
# タグは消す（Word は1語を複数の run に分けるので、つなげて調べる）。段落・セル・行・文書情報の項目の終わりは改行にする。
# 画像の代替テキスト・シート名・リンク先・作者のように、属性に入っている文字は、改行で区切って足す。
_XML_TAG = re.compile(r"<[^>]*>")
_XML_BLOCK_END = re.compile(
    r"</(?:\w+:)?(?:p|tc|tr|row|c|si|is|v|f|creator|lastModifiedBy|title|subject|description|keywords|category"
    r"|lpwstr|lpstr|Company|Manager|Application|Template)>|<(?:\w+:)?(?:br|tab|cr)\b[^>]*>"
)
_XML_TEXT_ATTR = re.compile(
    r"""\b(?:\w+:)?(?:descr|title|name|Target|author|initials)\s*=\s*(?:"([^"]*)"|'([^']*)')"""
)


class Finding(NamedTuple):
    path: str  # 場所の表記。line が 0 のときは、「何の名前か」まで含めた表記
    line: int  # ファイルの中身は 1 から。パス・コミットの作成者などの「名前」そのものは 0
    kind: str  # "secret" | "guid" | "banned" | "abs-path" | "email"
    excerpt: str  # 見つけた文字列の先頭の数文字だけ。あとは "…" で伏せる


class BannedListError(Exception):
    """禁止語のリストがない・読めない・空。"""


def _expand(path: Path) -> Path:
    try:
        return Path(path).expanduser()
    except RuntimeError:  # ホームフォルダーが分からない
        return Path(path)


def default_banned_path() -> Path | None:
    """環境変数 PUBLIC_CHECK_BANNED の場所（~ を展開したもの）。ない・空なら None。個人の置き場所を既定にはしない。"""
    value = os.environ.get(BANNED_ENV, "").strip()
    return _expand(Path(value)) if value else None


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


# ------------------------------------------------------------------ 文字列を調べる

def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _mask(matched: str) -> str:
    """見つけた文字列の先頭の数文字だけを残して伏せる。"""
    return matched[: min(3, len(matched) // 2)] + "…"


def _compile_banned(banned: list[str]) -> list[re.Pattern]:
    return [re.compile(re.escape(_nfkc(term)), re.IGNORECASE) for term in banned if term.strip()]


def _is_allowed_email(address: str, domain: str) -> bool:
    """検査から除くメールか（example・予約名のドメイン、GitHub と AI の noreply）。"""
    domain = domain.lower()
    return (domain in EXAMPLE_DOMAINS or domain.endswith(RESERVED_SUFFIXES)
            or domain in NOREPLY_DOMAINS or address.lower() in NOREPLY_ADDRESSES)


def _line_matches(line: str, banned_patterns: list[re.Pattern]) -> list[tuple[str, int, int]]:
    """NFKC でそろえた1行から、(種類, 開始, 終了) を全部。"""
    hits: list[tuple[str, int, int]] = []
    secret_spans: list[tuple[int, int]] = []
    for pattern in SECRET_PATTERNS:
        for m in pattern.finditer(line):
            if any(m.start() < end and start < m.end() for start, end in secret_spans):
                continue  # 同じ場所を、別の型でも見つけた
            secret_spans.append(m.span())
            hits.append(("secret", m.start(), m.end()))
    for m in GUID_PATTERN.finditer(line):
        if m.group().strip("0-") != "":  # すべて 0 の GUID は、空の値の印なので除く
            hits.append(("guid", m.start(), m.end()))
    for m in ABS_PATH_PATTERN.finditer(line):
        hits.append(("abs-path", m.start(), m.end()))
    for m in EMAIL_PATTERN.finditer(line):
        if not _is_allowed_email(m.group(), m.group(1)):
            hits.append(("email", m.start(), m.end()))
    for pattern in banned_patterns:
        for m in pattern.finditer(line):
            hits.append(("banned", m.start(), m.end()))
    return hits


def _scan_lines(path: str, text: str, banned_patterns: list[re.Pattern]) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = _nfkc(raw)
        for kind, start, end in _line_matches(line, banned_patterns):
            findings.append(Finding(path, lineno, kind, _mask(line[start:end])))
    return findings


def scan_text(path: str, text: str, banned: list[str]) -> list[Finding]:
    return _scan_lines(path, text, _compile_banned(banned))


def _redact(text: str, hits: list[tuple[str, int, int]]) -> str:
    """見つけた部分を、伏せた表記（先頭の数文字＋…）に置き換えた文字列。重なった部分は1つにまとめる。"""
    spans: list[list[int]] = []
    for _, start, end in sorted(hits, key=lambda h: (h[1], h[2])):
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    for start, end in reversed(spans):
        text = text[:start] + _mask(text[start:end]) + text[end:]
    return text


def _scan_value(label: str, value: str, banned_patterns: list[re.Pattern], show_value: bool = False) -> list[Finding]:
    """名前・メールのような1つの値を調べる。show_value なら、値そのもの（伏せたもの）を場所の表記に含める。"""
    norm = _nfkc(value)
    hits = _line_matches(norm, banned_patterns)
    if not hits:
        return []
    where = label.format(_redact(norm, hits)) if show_value else label
    return [Finding(where, 0, kind, _mask(norm[start:end])) for kind, start, end in hits]


# ------------------------------------------------------------------ ファイルを読む

class _Result:
    def __init__(self, banned: list[str]) -> None:
        self.patterns = _compile_banned(banned)
        self.findings: list[Finding] = []
        self.scanned = 0
        self.skipped: list[str] = []

    def add_file(self, prefix: str, name: str, suffix: str, text: str | None) -> None:
        """ファイル1つ。パスの名前（name）と、中身（text。読めなければ None）を調べる。

        場所の表記は prefix＋name＋suffix。name に禁止語・秘密が入っていれば、表記からも伏せる。
        """
        norm = _nfkc(name)
        hits = _line_matches(norm, self.patterns)
        shown = _redact(norm, hits) if hits else name
        label = prefix + shown + suffix
        for kind, start, end in hits:
            self.findings.append(Finding(f"{label}（パスの名前）", 0, kind, _mask(norm[start:end])))
        if text is None:
            self.skipped.append(label)
            return
        self.scanned += 1
        self.findings.extend(_scan_lines(label, text, self.patterns))

    def add_name(self, where: str, name: str) -> None:
        """履歴にあるパスの名前だけ（中身は別に調べる）。where の {} に、伏せたパスを入れる。"""
        self.findings.extend(_scan_value(where, name, self.patterns, show_value=True))

    def add_value(self, where: str, value: str) -> None:
        self.findings.extend(_scan_value(where, value, self.patterns))

    def add_message(self, where: str, message: str) -> None:
        self.findings.extend(_scan_lines(where, message, self.patterns))


def _decode(data: bytes) -> str | None:
    """テキストとして読めればその文字列、読めなければ None。"""
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _xml_to_text(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        xml = raw.decode("utf-16", errors="replace")
    else:
        xml = raw.decode("utf-8-sig", errors="replace")

    def replace(m: re.Match) -> str:
        tag = m.group()
        values = [a or b for a, b in _XML_TEXT_ATTR.findall(tag)]
        if values:
            return "\n" + "\n".join(values) + "\n"
        return "\n" if _XML_BLOCK_END.fullmatch(tag) else ""

    return html.unescape(_XML_TAG.sub(replace, xml))


def _office_text(data: bytes) -> str | None:
    """Office の文書（zip）の中の XML から取り出した文字。zip として読めなければ None。"""
    parts: list[str] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if not info.filename.lower().endswith((".xml", ".rels", ".vml")):
                    continue
                total += info.file_size
                if total > OFFICE_MAX_BYTES:
                    return None
                parts.append(_xml_to_text(archive.read(info)))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, zlib.error, EOFError,
            ValueError, OSError):
        return None
    return "\n".join(parts)


def _file_text(name: str, data: bytes) -> str | None:
    """ファイルの中身から調べる文字列を取る。名前（拡張子）で Office の文書かどうかを決める。読めなければ None。"""
    if name.lower().endswith(OFFICE_SUFFIXES):
        return _office_text(data)
    return _decode(data)


def _read_file_text(path: Path) -> str | None:
    """ファイルの文字列。シンボリックリンクは辿らず、行き先の文字列を返す。"""
    try:
        if path.is_symlink():
            return os.readlink(path)
        if path.is_file():
            return _file_text(path.name, path.read_bytes())
    except OSError:
        pass
    return None


def _git_files(directory: Path) -> list[str] | None:
    """directory の下で Git が数えるファイルの相対パス。Git の Repo の中でなければ None。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(directory), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
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


def _scan_tree(target: Path, result: _Result) -> None:
    if not target.is_dir() or target.is_symlink():
        # 1つのファイル。パスの名前は、ファイル名だけ（置き場所は調べる対象ではない）
        result.add_file(target.parent.as_posix() + "/" if target.parent != Path(".") else "", target.name, "",
                        _read_file_text(target))
        return
    names = _git_files(target)
    if names is None:
        names = list(_walk_files(target))
    prefix = "" if target == Path(".") else target.as_posix().rstrip("/") + "/"
    for name in names:
        path = target / name
        if path.is_dir() and not path.is_symlink():
            continue  # サブモジュールなど
        if not os.path.lexists(path):
            continue  # 追跡中だが消してあるファイル
        result.add_file(prefix, Path(name).as_posix(), "", _read_file_text(path))


def _git_toplevel(path: Path) -> Path | None:
    directory = path if path.is_dir() else path.parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return Path(os.fsdecode(proc.stdout).strip())


def _git_run(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    extra = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True, **extra)
    return proc.stdout


def _history_objects(repo: Path) -> list[tuple[str, str]]:
    """履歴にある全部のオブジェクトを (オブジェクト名, パス) で。パスがないもの（コミットなど）は ""。"""
    objects = []
    for line in os.fsdecode(_git_run(repo, "rev-list", "--all", "--objects")).split("\n"):
        if line:
            sha, _, path = line.partition(" ")
            objects.append((sha, path))
    return objects


def _history_blobs(repo: Path, objects: list[tuple[str, str]]) -> Iterator[tuple[str, str, bytes]]:
    """履歴にある全部のファイルの中身を (オブジェクト名, パス, 中身) で返す。"""
    paths: dict[str, str] = {}
    for sha, path in objects:
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


def _scan_history_info(repo: Path, result: _Result) -> None:
    """コミットの作成者・コミッター（名前とメール）とメッセージ、ブランチとタグの名前、注釈つきタグのメッセージ。"""
    log = _git_run(repo, "log", "--all", "-z", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B")
    for record in log.split(b"\0"):
        fields = record.decode("utf-8", errors="replace").lstrip("\n").split("\x1f", 5)
        if len(fields) != 6:
            continue
        sha, author, author_mail, committer, committer_mail, message = fields
        where = f"コミット {sha[:7]} の"
        result.add_value(where + "作成者の名前", author)
        result.add_value(where + "作成者のメール", author_mail)
        result.add_value(where + "コミッターの名前", committer)
        result.add_value(where + "コミッターのメール", committer_mail)
        result.add_message(where + "メッセージ", message)

    refs = _git_run(
        repo, "for-each-ref",
        "--format=%(objecttype)%1f%(objectname:short)%1f%(refname)%1f%(taggername)%1f%(taggeremail)%1f%(contents)%1e",
    )
    for record in refs.decode("utf-8", errors="replace").split("\x1e"):
        fields = record.lstrip("\n").split("\x1f", 5)
        if len(fields) != 6:
            continue
        kind, sha, refname, tagger, tagger_mail, contents = fields
        result.add_name("ブランチ・タグの名前 {}", refname)
        if kind == "tag":  # 注釈つきタグ（軽いタグの contents は、コミットのメッセージで調べ済み）
            where = f"タグ {sha} の"
            result.add_value(where + "作成者の名前", tagger)
            result.add_value(where + "作成者のメール", tagger_mail)
            result.add_message(where + "メッセージ", contents)


def _history_paths(repo: Path, objects: list[tuple[str, str]]) -> list[str]:
    """履歴にあるファイル・フォルダのパス（消したもの、名前を変える前のものも）。

    rev-list は同じ中身のファイルを1回しか数えないので、コミットごとの変更の一覧（名前の変更は追わない）も足す。
    """
    names = _git_run(repo, "log", "--all", "--name-only", "--no-renames", "--format=", "-z")
    from_log = (os.fsdecode(raw) for raw in names.split(b"\0") if raw)
    return list(dict.fromkeys([*(path for _, path in objects if path), *from_log]))


def _scan_history(repo: Path, result: _Result) -> None:
    objects = _history_objects(repo)
    for path in _history_paths(repo, objects):
        result.add_name("履歴にあるパス {}（パスの名前）", path)
    for sha, path, data in _history_blobs(repo, objects):
        name = path or sha[:7]
        norm = _nfkc(name)
        hits = _line_matches(norm, result.patterns)
        shown = _redact(norm, hits) if hits else name
        label = f"{shown}@{sha[:7]}" if path else sha[:7]
        text = _file_text(Path(name).name, data)
        if text is None:
            result.skipped.append(label)
        else:
            result.scanned += 1
            result.findings.extend(_scan_lines(label, text, result.patterns))
    _scan_history_info(repo, result)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_public.py",
        description="公開前の検査：秘密・禁止語・個人の絶対パス・メールアドレス・ID を探す",
    )
    parser.add_argument(
        "--banned",
        type=Path,
        help=f"禁止語のリスト（1行1語）。省略時は環境変数 {BANNED_ENV}。どちらもなければ検査できない",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Git の履歴にある全部のファイルの中身とパス、コミット・タグの情報、ブランチ・タグの名前も調べる",
    )
    parser.add_argument(
        "--allow-skipped",
        action="store_true",
        help="テキストとして読めず飛ばしたファイルがあっても、失敗にしない（人が見て確かめたときだけ）",
    )
    parser.add_argument("paths", nargs="*", type=Path, help="調べる場所（省略時はいまのフォルダー）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    targets = args.paths or [Path(".")]

    banned_path = _expand(args.banned) if args.banned else default_banned_path()
    if banned_path is None:
        print(f"NG: {NO_BANNED_GIVEN}", file=sys.stderr)
        return 2
    try:
        banned = load_banned(banned_path)
    except BannedListError as e:
        print(f"NG: {e}", file=sys.stderr)
        print(f"    --banned か環境変数 {BANNED_ENV} で指定する", file=sys.stderr)
        return 2

    for target in targets:
        if not (target.exists() or target.is_symlink()):
            print(f"NG: 調べる場所がない: {target}", file=sys.stderr)
            return 2

    result = _Result(banned)
    for target in targets:
        _scan_tree(target, result)

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
                _scan_history(repo, result)
            except (subprocess.CalledProcessError, OSError) as e:
                print(f"NG: Git の履歴を読めなかった: {repo}（{e}）", file=sys.stderr)
                return 2

    for f in result.findings:
        print(f"{f.path}:{f.line}: [{f.kind}] {f.excerpt}" if f.line else f"{f.path}: [{f.kind}] {f.excerpt}")
    for label in result.skipped:
        print(f"飛ばした（テキストとして読めない）: {label}")
    note = f"、テキストとして読めず飛ばした {len(result.skipped)}" if result.skipped else ""
    if result.findings:
        print(f"NG: {len(result.findings)} 件見つかった（{result.scanned} ファイルを検査{note}）")
        return 1
    if result.skipped and not args.allow_skipped:
        print(f"NG: テキストとして読めず飛ばしたファイルが {len(result.skipped)} 件ある。人が見て問題ないと確かめたときだけ --allow-skipped を付ける")
        return 1
    if result.scanned == 0:
        print(f"NG: 検査したファイルが 0 件（調べる場所を間違えていないか確かめる{note}）", file=sys.stderr)
        return 2
    print(f"OK: 見つからなかった（{result.scanned} ファイルを検査{note}）")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
