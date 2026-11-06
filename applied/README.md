# 応用編：採用の文書で、業務の検索を体験する

架空の会社「サンプルテック」の採用の文書（求人票、職務経歴書、面接の評価、連絡メール、スキャンした書類）を使います。
基礎編で学んだ検索を、形式の違う文書・見せてよい人・更新と削除・関係・エージェント型検索・答えの評価といった、業務で起きる場面に広げます。

データはすべて研修用の架空データです（`data/README.md`）。

## 前提

- Azure の接続先とキーは、Repo 直下の `.env.local` に入っています。Repo 直下で `python tools/team.py env --role builder`（メンバーは `--role member`）を実行すると作れます。ほかの人に渡しません（Git にも入りません）
- 接続先とキーは、いつも `.env.local` の中身を使います（パソコンに残っている `AZURE_*` の環境変数は読みません）
- Python 3.11 か 3.12。仮想環境に、Repo 直下で一度だけ：

```
pip install -r applied/requirements.txt
```

- 20（答えを評価する）の組み込みの評価器を使うときだけ、追加で `pip install -r applied/requirements-eval.txt`（約 150MB。入れなくても自前の採点は動く）
- コマンドは PowerShell でも bash でも同じです。パスの区切りは `/` で書いてあります（PowerShell でも動きます）

## 構築する人とメンバー

チームは、自分たちの AI Search・Foundry・Storage を持ちます。人事の文書は、構築する人が1回だけ取り込みます（OCR を含むので、数分かかります）。名前は固定です。

- インデックス `hr-docs`（チャンク単位）
- データソース `hr-docs-ds`、スキルセット `hr-docs-ss`、インデクサー `hr-docs-ixr`
- 知識ソース `hr-docs-ks`、知識ベース `hr-docs-kb`（19・20）
- 文書の置き場：Storage の入れ物（`.env.local` の `AZURE_STORAGE_CONTAINER`、既定は `hr-docs`）。文書は manifest の相対パスのまま、入れ物の直下に置きます（例 `jobs/JOB-REQ042-v3.pdf`）

役割ごとに、できることが違います。

- 構築する人（`--role builder`）：AI Search の管理者キーと Storage の接続文字列を使います。次を動かせます
  - `tools/build_hr_index.py`：Storage に文書を置き、インデックスなどを作り、取り込む
  - `tools/build_hr_kb.py`：知識ソースと知識ベースを作る
  - 17（更新と削除）の3本：チームの本物の文書を直して、最後に元に戻す。**動かしているあいだ、チームの検索の結果も変わります**
- メンバー（`--role member`）：検索だけのキーを使います。Storage の接続文字列は持ちません。構築する人が作ったものを、検索して読みます（14・15・16・18・19・20）。17 は構築する人の画面で見ます
- メンバーの設定で、作る・変える・文書を直す手順を実行すると、不透明なエラーになる前に「この手順は構築する人の設定（--role builder）で実行します」と止まります
- Storage の項目が要るのは、`build_hr_index.py` と 17 だけです。ほかのスクリプトは、Storage の項目がなくても動きます

## スクリプトと Notebook

各トピックのフォルダで `python <スクリプト>.py` と実行します。スクリプトは `# %%` で区切ったセルの形で、同じフォルダに同じ名前の Notebook（`.ipynb`）があります。どちらで動かしても同じ中身です。
質問や役割は、先頭近くの「変えてよい値」のセルで変えます。スクリプトでは引数でも変えられます。
中身を直すときは `.py` を直します。Notebook は `.py` から作ったものです（教材を直す人用の `tools/make_notebooks.py`）。

## トピック

- `topics/14-mixed-documents/`：種類の違う文書をまとめて取り込む（手元の Python で読む。Azure は使わない）
  - `read_documents.py`
- `topics/15-azure-indexer/`：Azure の仕組みに置き換える（インデクサーとスキルセット、OCR）
  - `show_pipeline.py`：取り込みの設計図と結果を読む
  - `search_documents.py`：14 で当たらなかった語を、インデックス `hr-docs` で探す
- `topics/16-security-filter/`：見せてよい人で絞る
  - `search_by_role.py`：採用担当／面接官／一般社員で同じ質問を検索し、結果を並べる
  - `leak_demo.py`：悪い例。全部を LLM に渡してプロンプトで頼むだけだと漏れる（架空のデータ）
- `topics/17-update-delete/`：更新と削除（チームの本物の文書を直して、最後に元に戻す。構築する人の画面で見る）
  - `withdraw_application.py`：応募の取り下げ。blob を消すだけでは残る → 削除の印を付けて消す
  - `revise_job_posting.py`：求人票の改訂（v1 → v3）
  - `cleanup.py`：元に戻す（途中で止めたとき、`--keep` を付けたとき）
- `topics/18-relations/`：関係で探す（紹介）
  - `trace_relations.py`：求人 → 応募 → 経歴書 → 面接評価を ID でたどる
- `topics/19-agentic-retrieval/`：エージェント型検索のデモ（LLM を使う機能はプレビューの API）
  - `compare_search.py`：普通の検索＋LLM と、エージェント型検索＋LLM を並べる
  - `effort_levels.py`：考える量（minimal・low・medium・auto）の違い
  - `make_answers.py`：（進行役）10問 × 2方式 × 3回の答えを作って保存する
- `topics/20-answer-evaluation/`：答えを評価する
  - `score_one.py`：1つの答えを、自前の採点と組み込みの評価器で採点する
  - `score_all.py`：（進行役）19 の答えをまとめて採点し、点のぶれを見る

- `assistant/`：採用アシスタント（Streamlit の画面。LLM が検索の道具を選んで、候補を段ごとに絞る。検索と LLM だけを使うので、メンバーの設定で動く。`assistant/README.md`）
  - 動かす：Repo 直下で `pip install -r applied/assistant/requirements.txt` のあと `streamlit run applied/assistant/app.py`

## 中身

- `data/`：採用の文書 23 ファイルと、その一覧（`manifest.json`）。`data/updates/` は 17 だけで使う求人票の旧版（v1）。`data/_build/` は、文書を作り直す道具（教材を直す人用。macOS の字体が要る。`data/README.md`）
- `lib/`：共通の部品
  - 設定と接続：`config.py`（`.env.local` の読み取りと、固定の名前）、`clients.py`
  - 文書の読み取り `readers.py`、取り込みの設計図 `pipeline.py`、見てよい人 `acl.py`
  - 17 の道具 `docops.py`（Storage の文書とインデックスを直す。元に戻す `restore`）
  - エージェント型検索 `agentic.py`、採点 `evaluation.py`、表示 `show.py`、エラーの表示 `errors.py`
- `tools/`：構築する人用（`build_hr_index.py`、`build_hr_kb.py`）
- `tests/`：通信しない試験（採用アシスタントの試験は `test_assistant_*.py`）
- `requirements.txt`、`requirements-eval.txt`（20 の組み込みの評価器だけ）

## 構築する人向け

Repo 直下で、構築する人の `.env.local` で実行します。

```
python applied/tools/build_hr_index.py             # 作る（あれば更新して実行し直す）
python applied/tools/build_hr_index.py --status    # いまの状態を見る（何も変えない）
python applied/tools/build_hr_index.py --recreate  # 全部消してから作り直す
python applied/tools/build_hr_index.py --delete    # 全部消す（Storage の入れ物の中の、manifest の文書も）

python applied/tools/build_hr_kb.py                # 知識ソースと知識ベースを作る（hr-docs が先に要る）
python applied/tools/build_hr_kb.py --status
python applied/tools/build_hr_kb.py --recreate
python applied/tools/build_hr_kb.py --delete
```

- `build_hr_index.py` が Storage に置くのは、manifest の 23 文書だけです。インデクサーの後に、全部のチャンクに「見てよい人」を付けます。取り込み直している間は、見てよい人が空になり、検索の結果が空になります
- `build_hr_kb.py` は、`.env.local` の `AZURE_OPENAI_CHAT_MODEL`（モデル名。既定 `gpt-5-mini`）と `AZURE_OPENAI_CHAT_DEPLOYMENT`（デプロイ名）を読んで、知識ベースの LLM にキーでつなぎます。プレビューの API（`2026-08-01-preview`）を使います。このモデルで動くかは、実機で確かめてください
- 17 が途中で止まったときは、`topics/17-update-delete/cleanup.py` で元に戻します（data/ のとおりにして、インデクサーを動かし、見てよい人を付け直します。何度実行しても同じです）

## 試験

通信しない試験です（偽の Azure）。仮想環境に入れて、applied フォルダで流します。

```
python3 -m venv .venv
.venv/bin/pip install -r applied/requirements.txt
cd applied
../.venv/bin/python -m unittest discover -s tests
```

Windows（PowerShell）では `.venv\Scripts\python` を使います。Notebook の試験（`tests/test_layout.py` の最後の1本）は、jupytext が入っているときだけ動きます（`requirements-dev.txt`）。
`azure-ai-evaluation`（`requirements-eval.txt`）が入っていないときは、1本が飛ばされます。
