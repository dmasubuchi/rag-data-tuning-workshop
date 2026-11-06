# 01 キーワード検索

## 学ぶこと

- 武将の JSON を、AI Search のインデックスに登録して、キーワード検索（BM25）で探す
- 日本語は分かち書きして検索する。質問と本文で同じ単語に分かれるかが、一致の分かれ目になる
- 質問を言い換えると、キーワード検索では正解が外れる

## 前提

- なし（最初のトピック）。Repo 直下に `.env.local` があること（なければ、Repo 直下で `python tools/team.py env --role builder`、メンバーは `--role member` で作る）
- `create_index.py` と `upload.py` は、AI Search の管理者キーが要るので、構築する人の設定（`--role builder`）で実行する。`analyze.py`（Analyze API）も管理者キーが要る。メンバーの設定（検索だけのキー）では、「構築する人の設定で実行します」と止まる。検索（`keyword_search.py`、`search_paraphrase.py`）は、メンバーの設定でもできる

## 実行するコマンド（このフォルダで）

必須（この順に）
- `python load.py`　武将の JSON の中身を見る（Azure には接続しない）
- `python create_index.py`　インデックスを作る（文字の項目だけ）
- `python upload.py`　武将を登録する
- `python keyword_search.py`　キーワード検索（既定は「桶狭間」）。`--q "姉川"` で検索語を変えられる
- `python analyze.py`　質問と本文が、どんな単語に分かれるか（Analyze API）
- `python search_paraphrase.py`　言い換えの質問をキーワード検索で実行する（正解が外れる）

Notebook でも、同じファイルを上から順にセルで実行できます。`--q` などの引数に当たるものは、先頭の「変えてよい値」のセルの変数（`QUERY`・`QUESTION`、`RECREATE = True` など）で指定します。
状態が足りないときは、スクリプトの先頭の `REBUILD = True`（スクリプトでは `--rebuild`）で、武将のインデックスを 01 が終わった状態に作り直せます。Notebook では、作り直したら `REBUILD = False` に戻します（`True` のままだと、実行のたびに作り直します）。

## 何を見ればよいか

- `keyword_search.py`：一致した武将の人数と、スコアの高い順。珍しい語を含むほどスコアが高い
- `analyze.py`：質問の単語ごとの「正解の項目」と「含む武将の人数」。共通の単語がないと、正解は上位に来にくい
- `search_paraphrase.py`：正解の武将の順位。言い方が違うと、上位に来ない

## 演習：先頭の値を書き換えて、もう一度実行する

- `keyword_search.py` の `SEARCH_FIELDS = None` を `["battles"]` にする：検索する項目を絞ると、一致する武将が変わる（`["name"]` だと 0 人）
- `search_paraphrase.py` の `QUESTION = None` を `"独眼竜と呼ばれた大名は誰ですか。"` にする：本文にある言葉を使うと、キーワード検索でも当たる
- 発展：`QUERY` を別の合戦名・地名・年号に変える

## 次のトピック

- `../03-vector-search`
