"""（作る人用）武将の埋め込み済みファイルを作る。参加者は実行しなくてよい。

実行（Repo 直下で）：python basic/tools/make_embeddings.py             武将の埋め込み済みファイルを作る
          python basic/tools/make_embeddings.py --check            いまのファイルが、いまの .env.local と合っているか確かめる（作らない）
できるファイル：
  basic/embeddings/sengoku.json   武将ごとの「名前。本文」の埋め込み
ファイルには、モデル名（Azure が返した名前）と次元を記録する。03-vector-search の embed.py --use-file と、tools/reset.py は、
記録がいまの設定と合わないファイルを使わずに、その場で埋め込む。
ベクトルは「埋め込んだ文字列の SHA-256」で探すので、武将の本文を書き換えたら、作り直す。
埋め込みには Azure OpenAI のキーが要る（.env.local。メンバーの設定でも埋め込める）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # basic/ を探索に加える（lib を使うため）
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import llm
from lib.config import SENGOKU_EMBEDDINGS, display_path, get_settings
from lib.data import embedding_text, load_bushou
from lib.runner import run
from lib.show import section, title
from lib.vectorstore import check_file, load_file, save_file, text_key


def sengoku_texts() -> list:
    return [embedding_text(p) for p in load_bushou()]


def build(path, texts: list, label: str) -> None:
    section(f"{label}：{len(texts)} 件を埋め込みます")
    vectors = llm.embed_texts(texts, label=label)
    save_file(path, texts, vectors, merge=False)
    size_mb = path.stat().st_size / 1_000_000
    data = load_file(path)
    print(f"  書きました：{display_path(path)}（{size_mb:.1f} MB）")
    print(f"  記録：モデル {data['model']}、次元 {data['dimensions']}、{len(data['vectors'])} 件、作成 {data['created_at']}")


def check(path, texts: list, label: str) -> None:
    data = load_file(path)
    ok, why = check_file(data, path)
    print(f"  {label}：{'使えます' if ok else '使えません'}（{why}）")
    if ok:
        have = sum(1 for t in texts if text_key(t) in data["vectors"])
        print(f"    いまのデータ {len(texts)} 件のうち、ファイルにあるもの：{have} 件" + ("" if have == len(texts) else "（足りない分は、その場で埋め込まれます。作り直してください）"))


def main() -> None:
    parser = argparse.ArgumentParser(description="埋め込み済みファイルを作る（作る人用）")
    parser.add_argument("--check", action="store_true", help="作らずに、いまのファイルを確かめる")
    args = parser.parse_args()
    s = get_settings()

    title("埋め込み済みファイル" + ("の確認" if args.check else "を作る"))
    print(f"いまの設定：デプロイ {s.embedding_deployment}、次元 {s.dimensions}")
    print(f"いまのモデル（Azure が返す名前）：{llm.embedding_model_name()}")

    if args.check:
        check(SENGOKU_EMBEDDINGS, sengoku_texts(), "武将")
    else:
        build(SENGOKU_EMBEDDINGS, sengoku_texts(), "武将")
        print("\nできました。確認：python basic/tools/make_embeddings.py --check")


if __name__ == "__main__":
    run(main)
