"""トピックの開始に必要な状態（インデックス、登録済みのデータ、埋め込み）を、1コマンドで作り直す。

実行（Repo 直下で）：python basic/tools/reset.py --to 04
          python basic/tools/reset.py --to 04 --embed live   埋め込み済みファイルを使わず、Azure OpenAI で埋め込む
          python basic/tools/reset.py --to 01 --dry-run      何も変えず、消す対象と作る対象を見る
--to にトピックの番号（topics/ にあるフォルダの番号。03-vector-search のようにフォルダ名でもよい）を指定すると、
そのトピックを始める直前の状態（ハンズオン資料の流れで、それ以前のトピックが残す状態を全部）になる。例：
  01  何もない状態（武将のインデックスを削除）
  03  01 が終わった状態（武将のインデックス＋文字の項目の登録）
  04  03 が終わった状態（＋ベクトルの項目、埋め込み、セマンティックの設定）。05・06 も同じ
作る・消すのは、武将のインデックス sengoku だけ。同じ AI Search にある、ほかのインデックスと、同義語マップ sengoku-synonyms には触らない。
埋め込みは、既定では同梱の埋め込み済みファイルを使う（モデル名か次元が合わないファイルは使わず、その場で埋め込む）。
インデックスを消して作るので、AI Search の管理者キー（構築する人の設定。python tools/team.py env --role builder）が要る。
メンバーの設定（検索だけのキー）では、始めに「構築する人の設定で実行します」と止まる（--dry-run は読むだけなのでできる）。
中身は lib/state.py の rebuild_state(トピック)。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # basic/ を探索に加える（lib を使うため）
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import state
from lib.clients import index_exists, search_client
from lib.config import SetupError, index_names, require_admin_key
from lib.runner import run
from lib.show import section, title


def topic_folders() -> dict:
    """topics/ にあるトピックのフォルダ。{番号: フォルダ名}"""
    return {p.name.split("-")[0]: p.name for p in sorted(lib.TOPICS_DIR.iterdir()) if p.is_dir()}


def parse_args():
    parser = argparse.ArgumentParser(description="トピックの開始の状態を作り直す")
    parser.add_argument("--to", required=True, help="どのトピックの開始の状態にするか（番号。例 04）")
    parser.add_argument("--embed", choices=["auto", "live"], default="auto",
                        help="auto：埋め込み済みファイルを使う（合わなければその場で埋め込む）／live：必ず Azure OpenAI で埋め込む")
    parser.add_argument("--dry-run", action="store_true",
                        help="何も消さず、作らず、消す対象と作る対象に今あるかどうかだけを表示する（読み取りのみ）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    number = state.topic_number(args.to)
    folders = topic_folders()
    if number not in folders:
        raise SetupError(f"トピック {args.to} はありません。ある番号：{', '.join(folders)}")
    if not args.dry_run:
        require_admin_key()      # 何も表示しないうちに、メンバー用のキー（検索だけ）なら止める
    use_file = args.embed == "auto"
    t0 = time.time()

    title(f"トピック {folders[number]} の開始の状態を作ります")
    build = state.states_before(number)
    print(f"作るもの：{'、'.join(state.STATE_TITLES[s] for s in build) if build else '（なし）'}")
    print(f"消すインデックス（このハンズオンが作る{len(index_names())}つだけ）：{', '.join(index_names())}")
    if args.dry_run:
        section("--dry-run：今あるかどうか（読み取りのみ）")
        for name in index_names():
            print(f"  {name}：{'あり' if index_exists(name) else 'なし'}")
        print("\n何も消さず、何も作っていません。実行するときは --dry-run を外します。")
        return
    print("これを一度削除してから、作り直します（同じ AI Search の、ほかのインデックスと同義語マップには触りません）。")

    state.rebuild_state(number, use_file=use_file)

    section("できあがり")
    for name in index_names():
        print(f"  {name}：{search_client(name).get_document_count()} 件" if index_exists(name) else f"  {name}：なし")
    print(f"\n{folders[number]} を始められます。（所要 {time.time() - t0:.0f} 秒）")


if __name__ == "__main__":
    run(main)
