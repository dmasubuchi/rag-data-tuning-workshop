"""ホテルのデータに、説明の埋め込み（ベクトル）を足して、Cosmos DB に入れるファイルを作る（guide/hotel.md の 4 章）。

日本語版のホテルの JSON（HotelsData_toAzureBlobs_ja.json）には、ベクトルが入っていない。この道具が、各ホテルの
日本語の説明（Description_ja）を、チームの Foundry の埋め込みのモデルでベクトルにして、Cosmos DB 用のファイルを書く。
Cosmos DB の検索文に使うベクトル（検索文を埋め込んだもの）も作れる。

標準ライブラリだけで動く。接続先とキーは Repo 直下の .env.local の AZURE_OPENAI_ENDPOINT・AZURE_OPENAI_API_KEY・
AZURE_OPENAI_EMBEDDING_DEPLOYMENT・EMBEDDING_DIMENSIONS（メンバーの設定でもよい）。Azure OpenAI を呼ぶだけで、何も作らない。
書き出し先は _work/hotel-vectors/（Git に入らない）。

使い方（Repo 直下で）：
  python tools/hotel_vectors.py hotels
      _work/hotel-vectors/HotelsData_toAzureBlobs_ja.json（先にダウンロードして置く）を読み、
      _work/hotel-vectors/hotels_cosmos.json（各ホテルに id と DescriptionVector を足したもの。Cosmos DB の「Upload Items」で入れる）を書く
  python tools/hotel_vectors.py query "海の近くで、屋外プールのあるホテル"
      → _work/hotel-vectors/query.txt（検索文のベクトル。[ から ] まで。SQL や検索の JSON に貼る）
  --out DIR で置き場所と書き出し先を、--decimals N でベクトルの小数の桁（既定 6）を変えられる。
  hotels の入力のファイルは、hotels のあとに書いて変えられる（python tools/hotel_vectors.py hotels 別の場所/ホテル.json）。

設定ファイルは、環境変数 WORKSHOP_ENV_FILE で別のものを指せる（試験用）。端末の AZURE_* の環境変数は読まない。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_DIR / "_work" / "hotel-vectors"
HOTELS_FILE = "HotelsData_toAzureBlobs_ja.json"   # ダウンロードしたホテルの JSON の名前
BATCH = 25                      # 1回の呼び出しで埋め込む文の数
RETRY_LIMIT = 4                 # 「呼びすぎ（429）」と言われたときに、待って再試行する回数
MAX_BYTES = 1_900_000           # Cosmos DB の「Upload Items」は、1回の全ファイル合計が 2MB 未満
ENV_HOWTO = "Repo 直下で `python tools/team.py env --role builder`（メンバーは `--role member`）を実行すると作れます。"
REQUIRED = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "EMBEDDING_DIMENSIONS")


class ToolError(Exception):
    """利用者に見せる日本語の理由つきの失敗。"""


# ------------------------------------------------------------------ 設定

def env_path() -> Path:
    given = os.environ.get("WORKSHOP_ENV_FILE")
    return Path(given).expanduser() if given else REPO_DIR / ".env.local"


def read_settings(path=None) -> dict:
    path = Path(path or env_path())
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        raise ToolError(f"{path.name} が読めません。{ENV_HOWTO}") from None
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("\"'")
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise ToolError(f"{path.name} に、次の項目がありません：{'、'.join(missing)}。{ENV_HOWTO}")
    try:
        dims = int(env["EMBEDDING_DIMENSIONS"])
    except ValueError:
        raise ToolError(f"EMBEDDING_DIMENSIONS は整数で書いてください（今は {env['EMBEDDING_DIMENSIONS']!r}）。") from None
    return {"endpoint": env["AZURE_OPENAI_ENDPOINT"].rstrip("/"), "key": env["AZURE_OPENAI_API_KEY"],
            "deployment": env["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"], "dimensions": dims}


# ------------------------------------------------------------------ 埋め込み

def _post(settings, texts):
    body = {"model": settings["deployment"], "input": texts, "dimensions": settings["dimensions"]}
    req = urllib.request.Request(f"{settings['endpoint']}/openai/v1/embeddings",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"api-key": settings["key"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)


def embed(settings, texts) -> list:
    """文の一覧を埋め込み、同じ並びのベクトルの一覧を返す。429（呼びすぎ）は、待って再試行する。"""
    vectors = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start:start + BATCH]
        for attempt in range(RETRY_LIMIT + 1):
            try:
                answer = _post(settings, batch)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < RETRY_LIMIT:
                    wait = 15
                    try:
                        wait = min(max(int(float(e.headers.get("retry-after", wait))), 5), 60)
                    except (TypeError, ValueError):
                        pass
                    print(f"  Azure OpenAI が混み合っています。{wait} 秒待って、もう一度送ります（{attempt + 1}/{RETRY_LIMIT}）。")
                    time.sleep(wait)
                    continue
                if e.code in (401, 403):
                    raise ToolError(f"エラー {e.code}：キーが合いません。{ENV_HOWTO}") from None
                if e.code == 404:
                    raise ToolError("エラー 404：埋め込みのデプロイが見つかりません（.env.local の AZURE_OPENAI_EMBEDDING_DEPLOYMENT）") from None
                raise ToolError(f"エラー {e.code}：{e.read().decode('utf-8', 'replace')[:200]}") from None
            except urllib.error.URLError as e:
                raise ToolError(f"つながりません：{e.reason}") from None
        data = sorted(answer.get("data", []), key=lambda d: d.get("index", 0))
        if len(data) != len(batch):
            raise ToolError("埋め込みの答えの数が、送った文の数と合いません")
        for d in data:
            if len(d.get("embedding", [])) != settings["dimensions"]:
                raise ToolError(f"埋め込みの長さが {len(d.get('embedding', []))} でした（EMBEDDING_DIMENSIONS は {settings['dimensions']}）")
            vectors.append(d["embedding"])
        if len(texts) > BATCH:
            print(f"  埋め込み {min(start + BATCH, len(texts))}/{len(texts)} 件")
    return vectors


def _round(vector, decimals):
    return [round(x, decimals) for x in vector]


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _shown(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_DIR)).replace("\\", "/")
    except ValueError:
        return str(path)


# ------------------------------------------------------------------ コマンド

def make_hotels(settings, src: Path, out: Path, decimals: int) -> int:
    try:
        hotels = json.loads(src.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ToolError(f"{_shown(src)} が読めません。日本語版のホテルの JSON（HotelsData_toAzureBlobs_ja.json）をダウンロードして、"
                        "ここに置きます（別の場所に置いたときは、hotels のあとに場所を書きます）。") from None
    ok = isinstance(hotels, list) and hotels and all(
        isinstance(h, dict) and h.get("HotelId") and isinstance(h.get("Description_ja"), str) and h["Description_ja"].strip()
        for h in hotels)
    if not ok:
        raise ToolError(f"{src.name} は、日本語版のホテルの JSON（HotelId と Description_ja がある配列）ではありません。")
    print(f"{len(hotels)} 件のホテルの Description_ja を埋め込みます（{settings['deployment']}、{settings['dimensions']} 次元）。")
    vectors = embed(settings, [h["Description_ja"] for h in hotels])
    docs = [{"id": str(h["HotelId"]), **h, "DescriptionVector": _round(v, decimals)} for h, v in zip(hotels, vectors)]
    text = json.dumps(docs, ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(text.encode("utf-8"))
    if size >= MAX_BYTES:
        raise ToolError(f"ファイルが {size / 1e6:.1f} MB になり、Cosmos DB の「Upload Items」の上限（2MB 未満）を超えます。"
                        f"--decimals を小さくします（今は {decimals}）。")
    path = out / "hotels_cosmos.json"
    _write(path, text)
    print(f"OK    {_shown(path)} を作りました（{len(docs)} 件、約 {size / 1e6:.1f} MB）。各ホテルに id と DescriptionVector を足しています")
    return 0


def make_query(settings, text: str, out: Path, decimals: int, name: str) -> int:
    if not text.strip():
        raise ToolError("検索文が空です。")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ToolError("--name は、英数字・ハイフン・下線だけで書きます。")
    vector = _round(embed(settings, [text])[0], decimals)
    path = out / f"{name}.txt"
    _write(path, json.dumps(vector) + "\n")
    print(f"OK    {_shown(path)} を作りました（{len(vector)} 個の数。[ から ] まで）。中身を全部コピーして、SQL や検索の JSON に貼ります")
    return 0


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", type=Path, default=OUT_DIR, help="書き出し先のフォルダー（既定は _work/hotel-vectors）")
    common.add_argument("--decimals", type=int, default=6, help="ベクトルの小数の桁（既定 6）")
    p = argparse.ArgumentParser(description="ホテルの説明をベクトルにして、Cosmos DB に入れるファイルと検索文のベクトルを作る")
    sub = p.add_subparsers(dest="command", required=True)
    h = sub.add_parser("hotels", parents=[common], help="ホテルの JSON に id と DescriptionVector を足して、Cosmos DB 用のファイルを作る")
    h.add_argument("input", type=Path, nargs="?",
                   help="日本語版のホテルの JSON。省略すると、書き出し先のフォルダー（既定は _work/hotel-vectors）の HotelsData_toAzureBlobs_ja.json")
    q = sub.add_parser("query", parents=[common], help="検索文をベクトルにして、ファイルに書く")
    q.add_argument("text", help="検索文")
    q.add_argument("--name", default="query", help="ファイルの名前（既定 query。query.txt ができる）")
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if not 1 <= args.decimals <= 9:
        print("--decimals は 1〜9 です。", file=sys.stderr)
        return 2
    try:
        settings = read_settings()
        if args.command == "hotels":
            return make_hotels(settings, args.input or args.out / HOTELS_FILE, args.out, args.decimals)
        return make_query(settings, args.text, args.out, args.decimals, args.name)
    except ToolError as error:
        print(f"NG    {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
