# 武将：検索の方式を動かす（基礎編 01〜06）

戦国武将のデータで、キーワード検索、ベクトル検索、ハイブリッド、答えの生成までを動かします。スクリプトとデータは [`basic/`](../basic/README.md) にあります。仕組みの説明は [ハンズオン資料 第1部](../docs/lecture/md/part1-search.md) です。

## 最初に1回

1. [ ] Repo 直下で、ライブラリを入れる：`pip install -r basic/requirements.txt`（Windows で `python` が見つからないときは `py`）
2. [ ] 接続の設定 `.env.local` を、Repo 直下に置く（[Azure の準備の 4](setup/azure-setup.md#4-接続の設定を作る)）
   - 構築する人：`python tools/team.py env --team <チーム> --role builder`（自分の `.env.local`。だれにも渡しません）
   - メンバー：構築する人から受け取った `member.local.env` を、Repo 直下に `.env.local` という名前で置く
3. [ ] 構築する人が、01 から順に進める。AI Search に、チームの武将のインデックス `sengoku` ができる（150件）

構築する人とメンバーで、できることが違います。

- 構築する人：インデックスと同義語マップを作り、武将を登録する（01 の `create_index.py`・`upload.py`・`analyze.py`、02、03 の `embed.py`、`basic/tools/reset.py`）
- メンバー：検索だけをする（01 の `keyword_search.py`・`search_paraphrase.py`、03 の `vector_search.py`、04、05、06）。構築する人が、そのトピックの登録などを先に終えてから始める
- 詳しくは [基礎編 README の「構築する人とメンバー」](../basic/README.md#構築する人とメンバー)

## 進め方

- 各トピックのフォルダで `python xxx.py`。VS Code では `# %%` の「Run Cell」で、1セルずつ動かせます
- 同じ名前の Notebook（`.ipynb`）でも、同じ中身です
- 質問は、先頭近くの「変えてよい値」のセルで変えます
- 前のトピックが終わっていないと、最初のセルで止まります。構築する人は、`REBUILD = True` にして実行し直し、終わったら `False` に戻します
- 途中から始めるときは、構築する人が `python basic/tools/reset.py --to 04` のように、トピックの開始の状態を作り直します

## トピック

各トピックの README に、実行するコマンドと見るところが書いてあります。

1. [ ] [01 キーワード検索](../basic/topics/01-keyword-search/README.md)：武将を読み込み、インデックスを作り、登録して、検索する
2. [ ] [02 言い換えと日本語の分かれ方](../basic/topics/02-analyzers-synonyms/README.md)：Analyze API で分かれ方を見て、同義語マップに1行足す
3. [ ] [03 ベクトル検索](../basic/topics/03-vector-search/README.md)：言い換えの質問で、キーワード検索が外れ、ベクトル検索が当たるのを見る
4. [ ] [04 ハイブリッドとランカー](../basic/topics/04-hybrid-ranker/README.md)：4つの方式の順位を並べる
5. [ ] [05 検索の良し悪しを数字で測る](../basic/topics/05-measure-search/README.md)：60問×4方式の nDCG@10・再現率@10・1位の割合
6. [ ] [06 検索結果から答えを作る](../basic/topics/06-answer-from-results/README.md)：プロンプトを組み、LLM に答えさせる

- 04・05・06 は、セマンティック ランカーを使います。月の無料枠は、チームの AI Search 全体で使います。05 の `measure_methods.py` は、質問の数（60回）だけ使うので、進行役が1回見せるだけにします（[基礎編 README](../basic/README.md#セマンティックランカーの使いすぎに注意)）

## 次の手順

[応用（人事）](hr.md)：採用の文書で、業務の検索を見る
