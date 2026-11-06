"""（構築する人用）人事のインデックス hr-docs を、チームの AI Search に作る。メンバーは実行しない。

やること：
  1. Storage の入れ物（.env.local の AZURE_STORAGE_CONTAINER。既定 hr-docs）がなければ作り、applied/data/ の 23 ファイルを置く
     （blob のメタデータに文書ごとの情報を付ける。名前は manifest の相対パスのまま。例 jobs/JOB-REQ042-v3.pdf）
  2. データソース・インデックス・スキルセット・インデクサー（hr-docs-*）を作る（あれば更新）
  3. インデクサーを実行し、終わるまで待つ（数分）
  4. 各チャンクに「見てよい人」（allowed）を付ける（lib/acl.py。インデクサーを動かすたびに付け直す）
  5. 結果（文書の数、チャンクの数、失敗・警告）を表示する

実行：python applied/tools/build_hr_index.py             作る（あれば更新して実行し直す）
      python applied/tools/build_hr_index.py --status    いまの状態を見る（何も変えない）
      python applied/tools/build_hr_index.py --recreate  全部消してから作り直す
      python applied/tools/build_hr_index.py --delete    全部消す（Storage の入れ物の中の、manifest の文書も）

必要なもの：構築する人の .env.local（`python tools/team.py env --team <チーム> --role builder`。AI Search の管理者キーと Storage の接続文字列が入る）。
メンバーの設定では、始めに止まります。

扱うのは hr-docs-* と、入れ物の中の manifest の文書だけです。同じ AI Search の、ほかのインデックスや、入れ物のほかのファイルには触りません。
データソースは入れ物の全体を読みます。17（更新と削除）は、この入れ物の文書を直して、最後に元に戻します（lib/docops.py）。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import acl, clients, config, docops, pipeline, show  # noqa: E402
from lib.config import HR_DATASOURCE, HR_INDEX, HR_INDEXER, HR_SKILLSET  # noqa: E402


def upload():
    show.section("1. Storage に置く")
    if docops.ensure_container():
        print(f"  入れ物 {config.get_settings(need_storage=True).storage_container} を作りました（非公開）")
    # 全部を置き直す（上書き）。build_hr_index.py を実行し直すたびに、インデクサーが全部を取り込み直す。17 の元に戻す（restore）と、同じ docops.put_manifest
    put = docops.put_manifest(only_changed=False)
    print(f"  {len(put)} ファイルを置きました（入れ物 {config.get_settings(need_storage=True).storage_container}）")


def create_or_update():
    show.section("2. データソース・インデックス・スキルセット・インデクサーを作る")
    ixc, irc = clients.index_client(), clients.indexer_client()
    irc.create_or_update_data_source_connection(pipeline.datasource())
    print(f"  データソース {HR_DATASOURCE}")
    ixc.create_or_update_index(pipeline.index())
    print(f"  インデックス {HR_INDEX}")
    irc.create_or_update_skillset(pipeline.skillset())
    print(f"  スキルセット {HR_SKILLSET}")
    irc.create_or_update_indexer(pipeline.indexer())
    print(f"  インデクサー {HR_INDEXER}")


def run_and_wait():
    show.section("3. インデクサーを実行して、終わるまで待つ")
    # 作った直後の自動の実行が走っていると断られるので、待って頼み直す（docops.run_indexer）
    r = docops.run_indexer()
    print(f"  終わりました（{r['seconds']} 秒）　処理した文書 {r['items']} 件・失敗 {r['failed']} 件")


def set_allowed():
    show.section("4. 各チャンクに「見てよい人」を付ける")
    # インデクサーは、取り込み直したチャンクの allowed を空に戻すので、動かしたあとは、全部のチャンクに付け直す
    st = acl.sync()
    print(f"  チャンク {st['chunks']} 件のうち、付けた・付け直した {st['changed']} 件"
          f"（求人票で全員に見える {st['public']} 件、採用担当だけ {st['recruiter_only']} 件）")


def status():
    show.section("いまの状態")
    irc, ixc = clients.indexer_client(), clients.index_client()
    names = {
        "データソース": [d.name for d in irc.get_data_source_connections()],
        "スキルセット": [s.name for s in irc.get_skillsets()],
        "インデクサー": [x.name for x in irc.get_indexers()],
        "インデックス": list(ixc.list_index_names()),
    }
    for label, have in names.items():
        mine = [n for n in have if n.startswith(HR_INDEX)]
        print(f"  {label}：{', '.join(mine) or 'なし'}（AI Search 全体で {len(have)} 個。上限 15）")
    if HR_INDEXER in names["インデクサー"]:
        history = irc.get_indexer_status(HR_INDEXER).execution_history or []
        # 変化がなければ実行しても 0 件で終わる。実際に取り込んだ直近の実行を見せる
        last = next((x for x in history if x.item_count), history[0] if history else None)
        if last is not None:
            took = (last.end_time - last.start_time).total_seconds() if last.end_time else None
            print(f"  直近の取り込み：{show.plain(last.status)}　処理 {last.item_count} 件・失敗 {last.failed_item_count} 件"
                  f"　警告 {len(last.warnings or [])}　エラー {len(last.errors or [])}"
                  + (f"　{took:.1f} 秒" if took is not None else ""))
            for w in (last.warnings or [])[:5]:
                print(f"    警告：{show.one_line(lib.errors.redact(w.details or w.message), 90)}")
            for e in (last.errors or [])[:5]:
                print(f"    エラー：{show.one_line(lib.errors.redact(e.error_message), 90)}（{show.one_line(e.key, 40)}）")
    if HR_INDEX in names["インデックス"]:
        sc = clients.search_client(HR_INDEX)
        res = sc.search("*", facets=["kind,count:10"], top=0, include_total_count=True)
        kinds = res.get_facets().get("kind", [])
        print(f"  チャンク：{res.get_count()} 件（" + "、".join(f"{k['value']} {k['count']}" for k in kinds) + "）")
        res = sc.search("*", facets=["allowed,count:20"], top=0)
        allowed = res.get_facets().get("allowed", [])
        print("  見てよい人：" + ("、".join(f"{a['value']} {a['count']}" for a in allowed) or "まだ付いていない"))
    have = {b.name for b in docops.list_blobs()}
    wanted = {pipeline.blob_name(f["path"]) for f in config.manifest_files()}
    print(f"  Storage の入れ物：{len(have)} ファイル（manifest の {len(wanted)} 件のうち {len(wanted & have)} 件がある。"
          f"manifest にないもの {len(have - wanted)} 件）")


def delete_all():
    show.section("全部消す")
    irc, ixc = clients.indexer_client(), clients.index_client()
    for fn, name, label in [(irc.delete_indexer, HR_INDEXER, "インデクサー"),
                            (irc.delete_skillset, HR_SKILLSET, "スキルセット"),
                            (irc.delete_data_source_connection, HR_DATASOURCE, "データソース"),
                            (ixc.delete_index, HR_INDEX, "インデックス")]:
        try:
            fn(name)
            print(f"  {label} {name}：消しました")
        except Exception as e:  # noqa: BLE001
            if "ResourceNotFound" in type(e).__name__ or getattr(e, "status_code", 0) == 404:
                print(f"  {label} {name}：もともとありません")
            else:
                raise


def delete_blobs():
    # 消すのは、manifest の文書の名前だけ（入れ物のほかのファイルには触らない）
    cc = clients.container_client()
    have = {b.name for b in docops.list_blobs()}
    n = 0
    for f in config.manifest_files():
        name = pipeline.blob_name(f["path"])
        if name in have:
            cc.delete_blob(name)
            n += 1
    print(f"  Storage の入れ物：manifest の文書 {n} ファイルを消しました")


def main():
    parser = argparse.ArgumentParser(description="（構築する人用）人事のインデックスを作る")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true", help="いまの状態を見る（何も変えない）")
    g.add_argument("--recreate", action="store_true", help="全部消してから作り直す")
    g.add_argument("--delete", action="store_true", help="全部消す（Storage の入れ物の中の、manifest の文書も）")
    args, _ = parser.parse_known_args()
    config.require_admin_key()                  # メンバーの設定（検索だけのキー）なら、ここで日本語で止まる
    config.get_settings(need_storage=True)      # Storage の項目がなければ、ここで日本語で止まる
    show.title(f"（構築する人用）人事のインデックス {HR_INDEX}")
    if args.status:
        status()
        return
    if args.delete:
        delete_all()
        delete_blobs()
        return
    if args.recreate:
        delete_all()
    upload()
    create_or_update()
    run_and_wait()
    set_allowed()
    status()


if __name__ == "__main__":
    main()
