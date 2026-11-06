"""AI Search だけで、検索の条件を変えると結果が変わるのを見るデモ（人事のインデックス hr-docs）。

Python の標準ライブラリだけで動く（pip も az のサインインも要らない）。接続先とキーは Repo 直下の .env.local。
メンバーの設定（検索だけのキー）でよい。検索するだけで、何も作らない・変えない。
各段で、ポータルの検索エクスプローラー（JSON ビュー）に貼れる JSON も表示する。

使い方（Repo 直下で）：
  python tools/search_demo.py                     段ごとに Enter で進む
  python tools/search_demo.py --q "面接の評価"     自分の質問で
  python tools/search_demo.py --no-pause          止まらずに全部

インデックス hr-docs は、構築する人が applied/tools/build_hr_index.py で作ったもの。5 段目は、セマンティック ランカーを 1 回使う。
設定ファイルは、環境変数 WORKSHOP_ENV_FILE で別のものを指せる（試験用）。端末の AZURE_* の環境変数は読まない。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
INDEX = "hr-docs"
API = "2024-07-01"
SEMANTIC_CONFIG = "applied-semantic"
KINDS = {"job_posting": "求人票", "resume": "職務経歴書", "interview_evaluations": "面接の評価", "mail": "メール", "scan": "スキャン"}
ENV_HOWTO = "Repo 直下で `python tools/team.py env --role member`（構築する人は `--role builder`）を実行すると作れます。"


def env_path() -> Path:
    given = os.environ.get("WORKSHOP_ENV_FILE")
    return Path(given).expanduser() if given else REPO_DIR / ".env.local"


def read_env(path=None):
    """設定ファイルから、AI Search の接続先とキーを読む。ファイルが読めない・項目がないときは OSError か KeyError。"""
    env = {}
    for line in Path(path or env_path()).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("\"'")
    endpoint, key = env["AZURE_SEARCH_ENDPOINT"], env["AZURE_SEARCH_API_KEY"]
    if not endpoint or not key:
        raise KeyError("AZURE_SEARCH_ENDPOINT・AZURE_SEARCH_API_KEY")
    return endpoint.rstrip("/"), key


def search(endpoint, key, body):
    req = urllib.request.Request(f"{endpoint}/indexes/{INDEX}/docs/search?api-version={API}",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.load(res)


def steps(q):
    base = {"search": q, "top": 5, "count": True, "select": "title,kind,chunk"}
    return [
        ("1 キーワード検索", "質問の言葉が多く出てくる文書が上に来る", base),
        ("2 欄で絞る：職務経歴書だけ", "kind（文書の種類）の欄で絞る。件数が減る",
         {**base, "filter": "kind eq 'resume'"}),
        ("3 見せてよい人で絞る：採用担当", "allowed（見てよい人）の欄で絞る。採用担当は全部見える",
         {**base, "filter": "allowed/any(a: a eq 'role:recruiter')"}),
        ("4 見せてよい人で絞る：一般社員", "同じ質問でも、一般社員に見せてよいのは求人票だけ",
         {**base, "filter": "allowed/any(a: a eq 'role:employee')"}),
        ("5 並べ直す：セマンティック ランカー", "件数は1と同じ。意味の近さで並べ直すので、順番が変わる",
         {**base, "queryType": "semantic", "semanticConfiguration": SEMANTIC_CONFIG}),
    ]


def snippet(text, width=24):
    """チャンクの先頭を1行で。同じ文書のチャンクを見分ける手がかり。"""
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[:width] + "…"


def show(title, note, body, result):
    print(f"\n=== {title}")
    print(f"    {note}")
    print(f"    件数：{result.get('@odata.count')}件（上位5件）")
    if not result.get("value"):
        print("    該当なし")
    for i, d in enumerate(result.get("value", []), 1):
        score = d.get("@search.rerankerScore") or d.get("@search.score")
        score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "-"
        print(f"    {i}位  {d.get('title', ''):<22} {KINDS.get(d.get('kind'), d.get('kind', '')):<6}  点 {score_text}  {snippet(d.get('chunk'))}")
    print("    ポータルの検索エクスプローラー（JSON ビュー）に貼る：")
    print("    " + json.dumps(body, ensure_ascii=False))


def http_error_text(e: urllib.error.HTTPError, semantic: bool = False) -> str:
    """semantic は、セマンティック ランカーを使う段（5）。403 は、キーが合わないほかに、無料枠（月ごと）の使い切りでも出る。"""
    if e.code == 403 and semantic:
        return ("エラー 403：キーが合っているか、セマンティック ランカーの無料枠（月ごと。チームの AI Search 全体で使う）を"
                "使い切っていないかを確かめます。")
    if e.code in (401, 403):
        return f"エラー {e.code}：キーが合いません。{ENV_HOWTO}"
    if e.code == 404:
        return f"エラー 404：インデックス {INDEX} がありません。構築する人が `python applied/tools/build_hr_index.py` で作ります"
    return f"エラー {e.code}：{e.read().decode('utf-8', 'replace')[:200]}"


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="条件を変えると検索結果が変わるのを見る（AI Search だけ）")
    p.add_argument("--q", default="Python の経験", help="質問（既定：Python の経験）")
    p.add_argument("--no-pause", action="store_true", help="Enter で止まらずに全部表示する")
    args = p.parse_args(argv)
    try:
        endpoint, key = read_env()
    except (OSError, ValueError, KeyError):   # ファイルがない・読めない・項目がない
        print(f"{env_path().name} が読めません（AZURE_SEARCH_ENDPOINT と AZURE_SEARCH_API_KEY が要ります）。{ENV_HOWTO}")
        return 1
    print(f"インデックス {INDEX}（{endpoint}）に、「{args.q}」で検索します。")
    failed = False
    for i, (title, note, body) in enumerate(steps(args.q)):
        if i and not args.no_pause:
            input("\n（Enter で次へ）")
        try:
            show(title, note, body, search(endpoint, key, body))
        except urllib.error.HTTPError as e:
            failed = True
            print(f"\n=== {title}\n    {http_error_text(e, semantic='queryType' in body)}")
        except urllib.error.URLError as e:
            print(f"\n=== {title}\n    つながりません：{e.reason}")
            return 1
    if failed:
        return 1
    print("\n同じ質問でも、絞る欄・見せてよい人・並べ方で、出てくる文書と順番が変わります。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
