# データに着目した RAG の研修

A hands-on training on the data side of RAG: processing, operating and evaluating data on top of a search foundation (Azure AI Search).
The R in RAG is Retrieve: collect, rank, and search step by step. Keep it in mind from the day you build the foundation.
Everything is in Japanese: slides, step-by-step guides, scripts and sample data.

## 目的

検索の基盤（Azure AI Search）を作るだけでは、よい検索になりません。この研修では、基盤の上にある、データの加工・運営・評価を、手を動かして学びます。

- RAG の R は Retrieve（取ってくる）です。集める、順位を付ける、段階的に探す。この考え方を、基盤を作る段階から意識します
- 検索のしかたを変え、結果を数字で測り、直す。この繰り返しを、ホテル・戦国武将・採用の文書で体験します

## 対象

- Azure の SI パートナー（とくにインフラ寄りの人）
- 企業の情報システム部門、DX 推進
- データ・IR・BI・分析の担当

## 始め方

チームで進めます。1人が構築する人（Azure にリソースを作る）、ほかの人はメンバー（検索と読み取り）です。人数は自由です。研修を進める人を進行役、研修に出る人を参加者と呼びます。

要るもの：Azure のサブスクリプション、Python 3.11 か 3.12、Git、VS Code、az（Azure CLI）。

手順書は、[guide/README.md](guide/README.md) の順に進めます。

1. [Windows PC の設定](guide/setup/windows-pc.md)
2. [Azure の準備](guide/setup/azure-setup.md)
3. [ホテル](guide/hotel.md)
4. [武将](guide/sengoku.md)（基礎編）
5. [応用（人事）](guide/hr.md)（応用編）

2 の Azure の準備は、次の流れです。

1. `config/workshop.example.config` を `workshop.config` にコピーし、進行役から受け取った値を書く
2. `python tools/team.py names --team <team>`：チームの名前から、リソースの名前を表示する
3. `python tools/team.py check-names`：作る前に、名前が使えるかを確かめる
4. Azure のポータルで、表示された名前のとおりにリソースを作る
5. `python tools/team.py health`：作ったものの状態を見る
6. `python tools/team.py env --role builder`（メンバーは `--role member`）：接続の設定 `.env.local` を作る

## 構成

- `guide/`：手順書（Windows PC、Azure、ホテル、武将、応用、検索デモ、進行役の手引き）
- `basic/`：基礎編。トピック 01〜06。戦国武将のデータで、キーワード検索、同義語、ベクトル検索、ハイブリッド、測る、答えの生成
- `applied/`：応用編。トピック 14〜20。採用の文書で、形式の違う文書、インデクサー、見せてよい人、更新と削除、関係、エージェント型検索、答えの評価。採用アシスタント（`applied/assistant/`）
- `docs/lecture/`：ハンズオン資料（スライド）の原稿と、作る道具。読む形の Markdown は `docs/lecture/md/`
- `site/`：スライド（`site/lecture/`）と、読む形のページ（`site/pages/`）。入口は `site/index.html`
- `tools/`：チームの設定（`team.py`）、検索デモ、ページを作る道具、公開前の検査
- `config/`：接続の設定のひな形

トピックの番号は、基礎編が 01〜06、応用編が 14〜20 です。07〜13 はありません。

## ポータル

入口は [site/index.html](site/index.html) です。目的、始め方、スライド、基礎編・応用編のページへのリンクを1枚にまとめています。スライドは [site/lecture/index.html](site/lecture/index.html) から開きます。

GitHub Pages での公開を予定しています。いまは、Repo を手元に取り込み、ブラウザで開いてください。

## 教材を直す人へ

通信しない試験は、仮想環境を作って流します（Windows では `.venv\Scripts\python`）。

```
python3 -m venv .venv
.venv/bin/pip install -r basic/requirements.txt -r applied/requirements.txt -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m unittest discover -s basic/tests
cd applied && ../.venv/bin/python -m unittest discover -s tests
```

- README や手順書の Markdown を直したら、`.venv/bin/python tools/build_site.py` で `site/` を作り直して、いっしょにコミットします（試験が、作り直したものと同じかを確かめます）
- スライドの原稿の直し方は [docs/lecture/README.md](docs/lecture/README.md) にあります

## ライセンス

- コード：MIT License（[LICENSE](LICENSE)）
- 文書とこの Repo のために作ったデータ：CC BY 4.0（[LICENSE-docs.md](LICENSE-docs.md)）
- 第三者のデータ：[NOTICE.md](NOTICE.md)
