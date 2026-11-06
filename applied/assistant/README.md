# 採用アシスタント

採用の文書について質問すると、LLM が検索のやり方を選びながら候補（応募者）を絞り込み、出典つきで答えます。
エージェント型 RAG の動きを見せるためのデモです。チームのだれかが動かし、ほかの人は画面を見ます。

検索と LLM だけを使います。メンバーの設定（検索だけのキー、Storage の項目なし）で動きます。

## 画面

- 左：用意した質問（19 の `questions.json` の 10 問）のボタンと、質問の入力欄。答えと、出典（開くと根拠の本文）
- 右：検索の段。1 段ごとに、やり方（キーワード・ベクトル・欄で絞る・ID でたどる）、検索の語や条件、残った候補の人数を出す

## 仕組み

- `engine.py`：候補の人（応募番号）を持ち、段ごとに絞る。2 段目からの検索は、前の段で残った人の文書だけが対象。0 人になる検索では絞らない
- `azure_io.py`：チームのインデックス `hr-docs` を、採用担当の役で検索する。LLM（`.env.local` のチャットのデプロイ）に 4 つの道具を渡し、どれを使うかを選ばせる。段は 6 まで。答えの出典の番号を確かめ（文に書いた人と、資料の人が合わない番号は外す）、1 から振り直す
- `app.py`：画面（Streamlit）。`gate.py` が合言葉と 1 日の回数の上限を見る。`view.py` が表示の判断（考えている間に次の段の枠へ「考えています」を出す・段のカードの3行・段を描く間隔・出典の見出しに人を添える・質問のボタンの題）を受け持つ
- `cli.py`：端末で 1 問だけ動かす（確かめ用）
- `Dockerfile`：コンテナで動かすときのイメージ（任意。使い方は先頭のコメント。手元だけで開く `127.0.0.1` に公開します）。Repo 直下の `.dockerignore` が `.env.local` などを除く

## 自分の PC で動かす

前提：Repo 直下の `.env.local`（メンバーは、構築する人から受け取った `member.local.env` をこの名前で置く。構築する人は、自分の `.env.local`）と、インデックス `hr-docs`（構築する人が作ったもの）。

```
pip install -r applied/assistant/requirements.txt
streamlit run applied/assistant/app.py --client.toolbarMode minimal --theme.primaryColor "#1864ab"
```

画面は、この PC だけで開きます（Repo 直下の `.streamlit/config.toml` が、`localhost` に決めています）。Streamlit は、実行したときのフォルダーの `.streamlit/` を読むので、起動は Repo 直下で行います。人に見せるときは、`ASSISTANT_ACCESS_CODE` を設定します（下）。

端末で 1 問だけ：`cd applied` のあと `python -m assistant.cli --id q10`

## 人に見せるときの設定（任意）

環境変数で変えられます。なければ、合言葉なし・既定の値で動きます。手元だけで開くあいだは、合言葉はなくてかまいません。ほかの PC から開かせるときは、起動に `--server.address 0.0.0.0` を付け、`ASSISTANT_ACCESS_CODE` を設定します。

- `ASSISTANT_ACCESS_CODE`：合言葉。決めると、画面を開くときに入力が要ります
- `ASSISTANT_MAX_QUESTIONS`：1 日の質問の上限（既定 200）
- `ASSISTANT_STEP_PAUSE`：段を画面に描く最低の間隔（秒、既定 0.6、0 で間隔なし、上限 3）。LLM が検索を続けて頼んだときも、段が 1 つずつ見えるようにします
- `ASSISTANT_REASONING_EFFORT`：LLM の考える量（`none`・`minimal`・`low`・`medium`・`high`。大文字小文字と前後の空白は問いません）。決めなければ `.env.local` の `AZURE_OPENAI_REASONING_EFFORT`、それも使える値でなければ `low`。`none` では、資料と人の取り違えが出たことがあります
