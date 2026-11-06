# 基礎編：検索と RAG を自分の手で動かす

戦国武将のデータ（`data/sengoku/`）で、検索と RAG を一つずつ動かします。

LangChain は使いません。使うのは `azure-search-documents`、`openai`、`python-dotenv` だけです。

各スクリプトそのものが完成形です。上から順に実行し、画面に出る**中間結果**を読みながら進めます。
スクリプトは `# %%` で区切ったセルの形です。同じフォルダに同じ名前の Notebook（`.ipynb`）があり、どちらで動かしても同じ中身です。

## 前提

- Python 3.11 か 3.12。`python` が見つからないときは `py` に置き換えます（Windows）
- ライブラリ（最初に1回）：`pip install -r basic/requirements.txt`
- Azure の接続先とキーは、Repo 直下の `.env.local` に入っています。Repo 直下で `python tools/team.py env --role builder`（メンバーは `--role member`）を実行すると作れます。ほかの人に渡しません（Git にも入りません）
- 接続先とキーは、いつも `.env.local` の中身を使います（パソコンに残っている `AZURE_*` の環境変数は読みません）
- コマンドは PowerShell でも bash でも同じです。パスの区切りは `/` で書いてあります（PowerShell でも動きます）

## 構築する人とメンバー

チームは、自分たちの AI Search と Foundry を持ちます。インデックスの名前は固定です（武将は `sengoku`、同義語マップは `sengoku-synonyms`）。

- 構築する人（`--role builder`）：AI Search の管理者キーを使います。インデックスと同義語マップを作り、武将を登録します（01 の `create_index.py`・`upload.py`・`analyze.py`、02、03 の `embed.py`、`tools/reset.py`）
- メンバー（`--role member`）：検索だけのキーを使います。構築する人が作ったインデックスを検索できます（01 の `keyword_search.py`・`search_paraphrase.py`、03 の `vector_search.py`、04、05、06）
- メンバーの設定で、作る・変える・調べる手順を実行すると、不透明なエラーになる前に「この手順は構築する人の設定（--role builder）で実行します」と止まります

## スクリプトと Notebook

- スクリプト：トピックのフォルダで `python xxx.py`。VS Code では `# %%` のところに出る「Run Cell」で1セルずつ動かせます
- Notebook：同じ名前の `xxx.ipynb` を開き、上のセルから順に実行します。VS Code の Jupyter 拡張と、`requirements.txt` に入っている `ipykernel` を使います
- 質問や件数は、先頭近くの「変えてよい値」のセルで変えます。スクリプトでは引数でも変えられます（引数があれば引数、なければ変数）
- 前のトピックが終わっていないと、最初のセルで止まります。構築する人の設定なら、`REBUILD = True` にして実行し直すと、武将のインデックスを作り直してから進みます。作り直せたら `REBUILD = False` に戻します（`True` のままだと、実行のたびに作り直します）。メンバーの設定では、構築する人に実行してもらいます
- 中身を直すときは `.py` を直します。Notebook は `.py` から作ったものです（作る人用の `tools/make_notebooks.py`）

## トピックの一覧

番号の順に進めます。各トピックの README に、前提のトピック、実行するコマンド、見るところが書いてあります。
「発展」は、早く終わった人と持ち帰り用です。

- `topics/01-keyword-search`　キーワード検索：武将を読み込み、インデックスを作り、登録して、検索する
- `topics/02-analyzers-synonyms`　言い換えと日本語の分かれ方：Analyze API で分かれ方を見て、同義語マップに1行足す。発展は順位の調整（語の重み、欄の重み、除外の落とし穴）
- `topics/03-vector-search`　ベクトル検索：言い換えの質問で、キーワード検索が外れ、ベクトル検索が当たるのを見る
- `topics/04-hybrid-ranker`　ハイブリッド検索とセマンティックランカー：4つの方式の順位を並べる
- `topics/05-measure-search`　検索の良し悪しを数字で測る：60問×4方式の nDCG@10・再現率@10・1位の割合。自分の質問も足せる
- `topics/06-answer-from-results`　検索結果から答えを作る：プロンプトを組み、LLM に答えさせる

応用編のトピックは `applied/` にあります。

前提のトピックが終わっていないときは、最初のセルが止まって、先に実行するスクリプトか reset のコマンドを出します。

## 途中からの再開

トピックを始める直前の状態（武将のインデックス、登録済みのデータ、埋め込み）を、1コマンドで作り直せます（構築する人の設定で実行します）。

```
python basic/tools/reset.py --to 04
```

- 番号はトピックの番号です（`04-hybrid-ranker` のようにフォルダ名でもかまいません）
- 消すのは、武将のインデックス `sengoku` だけです。同じ AI Search の、ほかのインデックスには触りません
- 同義語マップ `sengoku-synonyms` は消しません（02 の最後で、武将のインデックスの欄から外します）
- 埋め込みは、既定では同梱の埋め込み済みファイル（`basic/embeddings/`）を使います。Azure OpenAI で埋め込み直すときは `--embed live`
- 先に何も変えずに見たいとき：`--dry-run`

## 困ったときに見る中間結果

答えがおかしいときは、最初に「いいえ」になった工程が、失敗した工程です。上から順に確かめます。

1. 正解の武将は、検索の上位に入ったか（検索）：`04-hybrid-ranker/compare_methods.py`
2. 正解の武将は、実際に LLM に渡したプロンプトに入っているか（組み立て）：`06-answer-from-results/build_prompt.py`
3. 答えは、プロンプトの資料と、正解の武将に合っているか（回答生成）：`06-answer-from-results/generate_answer.py`

エラーが出たときは、画面の `確かめること:` を読みます。表示ではキーを `***` に伏せています。よくある原因：

- 「設定ファイルが見つかりません」「次の項目がありません」：Repo 直下で `python tools/team.py env --role builder`（メンバーは `--role member`）を実行したか
- 「この手順は構築する人の設定で実行します」：いまの `.env.local` が検索だけのキー（メンバー用）です。構築する人が実行するか、構築する人の `.env.local` で実行します
- 「キーまたは権限」：`.env.local` のキーが古くなっていないか。作り直せます
- 「インデックスがありません」：前のトピックのスクリプトを実行したか。構築する人は `reset.py` で作り直せる
- 「呼びすぎ（429）」：自動で待って再試行します。それでも続くときは1分ほど待つ
- セマンティックランカーが使えない：AI Search の料金プランが対応しているか、月の無料枠を使い切っていないか

## セマンティックランカーの使いすぎに注意

Free プランの無料枠には月ごとの上限があり、チームの AI Search 全体で使います。回数は料金ページ（https://azure.microsoft.com/ja-jp/pricing/details/search/）で確かめます。

- 1回の実行で各 1 回：`04-hybrid-ranker` の `ranker.py` と `compare_methods.py`、`06-answer-from-results` の `build_prompt.py` と `generate_answer.py`、`05-measure-search` の `ndcg_by_hand.py`
- 1回の実行で質問の数（60 回）：`05-measure-search` の `measure_methods.py`。チームで何度も実行しないようにします
- `compare_no_search.py` は、`generate_answer.py` が保存した答えを使えるとき（質問・検索の方式・件数が同じとき）だけ 0 回です。違うときや、`REBUILD = True`（`--rebuild`）で保存した答えが消えたあとは、検索し直すので 1 回使います。ほかのスクリプトはランカーを使いません（`METHOD = "hybrid_ranker"` に書き換えたときだけ使います）

## 自分の資料に差し替えるとき

- 武将の JSON → `data/sengoku/bushou.json`（項目 `id`、`name`、`aliases`、`battles`、`profile` など）。項目を変えるときは、`lib/sengoku.py` の `build_index()` と `FIELDS`、`lib/data.py` の `embedding_text()` を合わせる
- 質問と正解（任意）→ `data/sengoku/questions.json`。ないときは、正解の順位を省略して動きます
- 資料を差し替えたら、埋め込み済みファイルは作り直す（作る人用 `tools/make_embeddings.py`）。古い分は使われず、その場で埋め込まれる

## 作る人・進行役向け

- `python basic/tools/make_embeddings.py`：武将の埋め込み済みファイルを作る。`--check` で、いまの `.env.local` と合っているかを確かめる。本文を変えたら作り直す
- `python basic/tools/reset.py --to 04`：構築する人の設定で、トピックの開始の状態を作り直す
- `python tools/make_notebooks.py`：`.py` から Notebook を作り直す（出力は空）。`--check` で、ずれているものを一覧にする。jupytext が要る（`requirements-dev.txt`）
- 同義語マップ：Basic は AI Search 全体で 3 個まで。ここで作るのは `sengoku-synonyms` の 1 個だけ（作れないときは案内が出て止まる）。消すときは `lib.synonyms.delete_map()`
- テスト（通信なし）：仮想環境を作って流します

  ```
  python3 -m venv .venv
  .venv/bin/pip install -r basic/requirements.txt -r requirements-dev.txt
  .venv/bin/python -m unittest discover -s basic/tests
  ```

  Windows（PowerShell）では `.venv\Scripts\python` を使います
- 各スクリプトの実行時間は、スクリプトとして動かしたとき、最後に「（実行時間 n 秒）」と出ます

## フォルダ

- `topics/`：トピックごとのスクリプト・Notebook・README。スクリプトのファイル名は全トピックで重ならない。スクリプトは読み込むと動き出すので、スクリプトどうしでは import しない。トピックをまたいで使う関数は `lib/` にある
- `lib/`：スクリプトが共通で使う部品
  - 設定と接続：`config.py`（`.env.local` の読み取りと、固定の名前）、`clients.py`
  - 状態の確認と作り直し：`state.py`
  - 検索と表示：`search.py`、`show.py`、エラーの表示 `runner.py`、セルの形の始まりと終わり `cells.py`
  - 登録と埋め込み：`indexing.py`、`llm.py`（埋め込みと回答の生成）、埋め込み済みファイル `vectorstore.py`、前の結果のメモ `worklog.py`
  - データ：`data.py`、武将のインデックス `sengoku.py`
  - トピックの部品：同義語マップ `synonyms.py`、指標 `metrics.py`、検索結果からのプロンプト `rag_prompt.py`
- `data/`：武将の JSON と質問（`sengoku/`）
- `embeddings/`：埋め込み済みファイル（text-embedding-3-small、1536 次元。時間が足りないとき用）
- `tools/`：作る人用と再開用（`reset.py`、`make_embeddings.py`）
- `tests/`：通信なしのテスト
- `requirements.txt`
