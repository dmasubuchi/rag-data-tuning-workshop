# ハンズオン資料の原稿（検索と RAG の仕組み）

HTML のスライド（`site/lecture/`）と Markdown（`docs/lecture/md/`）の原稿と、作るための道具です。

- スライドは仕組みの説明（手法、Azure のリソース、検索の考え方）に集中する。検索の結果や順位は、各ページの下の「確かめる」が指すトピック（`basic/topics/…`、`applied/topics/…`）のスクリプトと Notebook で確かめる
- 進行は部の順（はじめに → 第1部 検索方法 → 第2部 取り込み → 第3部 関係とエージェント型検索 → 評価 → 比較と締め）。トピックの番号は、データと前提の順で、進行の順とは別

## ファイル

- `keywords.md`：キーワードのページ（全52ページ）。**本文を直すときはここを直す**
- `decks.json`：デッキ（部）の構成。ページの並び、節、各ページの「確かめる」トピック、新しく足したページ（はじめに、順位の調整、うまくいかない場面など）、トピックの表
- `deck.html`：描画のひな形。部品 `kw`（2段組みの3層の箇条書き。文字は枠に収まるよう 26px から 17px まで縮む）と `diagram`（図）、全ページ共通の「確かめる」の欄がある
- `player.js`：スライドのプレイヤー（slideplay の `player/player.js` の写し。MIT License。<https://github.com/dmasubuchi/slideplay>）
- `catalog.css`：目次のページの見た目
- `diagrams/`：図。`pNN.json`（題、キャプション、SVG、ノート）は `figures.py` が `figs_*.py` から書き出す。どのページにも図がある
- `tools/build.py`：`site/lecture/`（HTML のスライド）と `docs/lecture/md/`（Markdown）を作る
- `md/`：Markdown 版。部ごとの `.md`（節・ページ・本文・図・「確かめる」のリンク・ノート）と `index.md`、図の SVG（`img/pNN.svg`）。`build.py --md` が作る生成物なので、直接は直さない
- `tools/check.py`：全スライドを静止画にして、はみ出しと JS のエラーを調べる。プレイヤーの操作も確かめる
- `tools/svgparts.py`：図の部品（色、人・索引の箱・書棚・文書のアイコン、矢印、文字の大きさ）。どの図もこれだけを使う

「確かめる」が指すトピックのフォルダは、`decks.json` の `topics` に書いてある。基礎編は 01〜06、応用編は 14〜20。

## 図の描き方の決まり

- 図はスライドの真ん中の箱と矢印の部分だけを、SVG で描く。外枠、題、副題、線は描かない。段階ごとに出す部分に `data-step` を付ける
- 題はスライドの題に、副題はキャプションに、注はノートか本文に書く
- 色の数とアイコンの種類は、全部の図でそろえる（`tools/svgparts.py`）
- 中身は `keywords.md` の本文に合わせる。本文にない数字や機能名は足さない
- 図の中に「未確認」「TODO」「（下書き）」などの制作のメモを描かない
- 1枚の箱と矢印は6つまで、段階は4つまで。箇条は1ページ8つまで
- ノートには、段階ごとに話すことを書く（狙い／話すこと（段階ごと）／補足／注意）
- 図の中の文字は、画像にせず SVG の文字（text）として入れる

図を直すときは、`figs_*.py` を直して `python3 docs/lecture/diagrams/figures.py` で `pNN.json` を書き出し、`build.py` で作り直す（ページ番号を渡すと、そのページだけ書き出す）。

## 作り方

Repo の直下で実行します。`build.py` は Python 3.10 以上の標準ライブラリだけで動きます。確認の `check.py` には `playwright`（Chromium）が要ります（教材を直す人の道具で、参加者は要りません）。

```
python3 docs/lecture/tools/build.py
python3 docs/lecture/tools/build.py --md docs/lecture/md
python3 docs/lecture/tools/check.py --out <静止画の置き場>
```

- `build.py --decks <JSON> --out <書き出し先>`：デッキの構成と書き出し先を変えられる
- `build.py --md docs/lecture/md`：同じ原稿から Markdown を作る（`--md` だけのときは HTML を作らない）。図は `img/pNN.svg` に、xmlns・字体・白い背景つきの1枚のファイルで書く（段ごとの `data-step` は外し、全部の段が見える）。両方を作り直すときは `build.py --out site/lecture --md docs/lecture/md`
- 原稿（`keywords.md`・`decks.json`・`diagrams/`）を直したら、`site/lecture/` と `docs/lecture/md/` を作り直して、いっしょにコミットする（試験が、作り直したものと同じかを確かめる）
- できたものは `site/lecture/index.html` をブラウザで開きます（目次 → カードを選ぶ。→ キーで進む、N でノート、H で目次）
- `check.py` は、`site/lecture/` を調べます。静止画の一覧（`contact.png`）は ffmpeg があるときだけ作ります
- 試験（通信なし）：Repo 直下で `.venv/bin/python -m unittest discover -s tests`（仮想環境の作り方は、Repo 直下の README の「教材を直す人へ」）

## 公開の出力に出さないもの

`site/lecture/` と `docs/lecture/md/` は参加者に公開します。次のものは `keywords.md`・`decks.json`・`diagrams/` に書きません（`build.py` も出しません）。

- 制作のメモ（未確認、記憶にもとづく、あったはず、確かめる必要がある）
- 内部の呼び名、別の講座や別の教材の名前
- 編集の履歴（「追加 ○ 枚」など）

作り直したあとの確認（図の中の文字は対象外）：

```
grep -rnE "未確認|記憶|あったはず|シリーズ|第[0-9]+回" site/lecture docs/lecture/md
```

## 本文の根拠にした Microsoft Learn（2026年11月に読んだ版）

- BM25・点数の変動：`azure/search/index-similarity-and-scoring`、`azure/search/index-ranking-similarity`
- RRF・ハイブリッド：`azure/search/hybrid-search-ranking`、`azure/search/hybrid-search-how-to-query`
- セマンティックランカー：`azure/search/semantic-search-overview`、`azure/search/semantic-how-to-enable-scoring-profiles`、`azure/search/semantic-how-to-enable-disable`、`azure/search/semantic-how-to-query-rewrite`
- アナライザー・同義語：`azure/search/search-analyzers`、`azure/search/index-add-language-analyzers`、`azure/search/search-synonyms`
- ベクトル：`azure/search/vector-search-ranking`、`azure/search/vector-search-how-to-create-index`、`azure/search/vector-search-how-to-query`、`azure/search/vector-search-filters`、`azure/search/vector-search-how-to-storage-options`、`azure/search/vector-search-how-to-quantization`
- スキル：`azure/search/cognitive-search-skill-document-intelligence-layout`、`azure/search/cognitive-search-skill-ocr`、`azure/search/cognitive-search-skill-textsplit`、`azure/search/search-how-to-semantic-chunking`
- インデクサー：`azure/search/search-how-to-index-azure-blob-changed-deleted`、`azure/search/search-blob-metadata-properties`、`azure/search/search-how-to-define-index-projections`
- エージェント型検索：`azure/search/agentic-retrieval-overview`、`azure/search/agentic-retrieval-how-to-set-retrieval-reasoning-effort`、`azure/search/agentic-knowledge-source-overview`、`azure/search/agentic-knowledge-source-how-to-web`、`azure/search/agentic-retrieval-how-to-retrieve`
- 権限：`azure/search/search-document-level-access-overview`
- 評価器：`python/api/azure-ai-evaluation/azure.ai.evaluation.<評価器名>`
- 上限・料金：`azure/search/search-limits-quotas-capacity`

（すべて `https://learn.microsoft.com/en-us/` の下）
