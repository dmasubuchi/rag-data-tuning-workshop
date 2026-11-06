# 15 Azure の仕組みに置き換える

14 で手元の Python がしたこと（文書を開く → 文字を取り出す → チャンクに切る）を、Azure AI Search の部品で行います。
構築する人が `applied/tools/build_hr_index.py` で1回だけ流して、インデックス `hr-docs` を作ってあります。メンバーは読んで、検索して確かめます。

## 何を学ぶか

- 取り込みの部品
  - データソース：どこの文書を読むか（Storage の入れ物の全体。接続文字列、削除の印）
  - インデクサー：文書を1つずつ開いて、文字と画像を取り出す
  - スキルセット：取り出したものに順に手を加える（OCR → 文字の結合 → 分割 → 埋め込み）
  - インデックスの射影：親の文書とチャンクの親子。チャンクを1件ずつ登録し、親の番号（parent_id）を持たせる
  - ベクトル化：検索するときの質問も、AI Search が Azure OpenAI でベクトルにする（統合ベクトル化）
- OCR を取り込みに入れると、14 で見つからなかった語（入社予定日）が見つかる
- Azure の分割は長さ（400 文字）で切る。Excel の1行や Word の見出しは考えない（14 との違い）

## 前提

- `pip install -r applied/requirements.txt`（Repo 直下で、仮想環境の中で）
- 構築する人がインデックス `hr-docs` を作ってあること（なければ構築する人に聞く）
- メンバーの設定（検索だけのキー、Storage なし）で動きます

## 実行

```
python show_pipeline.py      # 設計図と結果を読む（何も変えない）
python search_documents.py   # 14 で当たらなかった語を探す
python search_documents.py --term "夜間当番"
python search_documents.py --question "石田さんはいつから働き始めますか"
```

## 見るところ

- `show_pipeline.py`
  - スキルセットの表：前の段が出したもの（text、merged_content、pages）を、次の段が受け取っている
  - インデックスの欄：後のトピックで使う欄（allowed、req_id など）
  - 取り込みの結果：文書の種類ごとのチャンクの数に scan が入っている
- `search_documents.py`
  - 「入社予定日」の1位が scan（内定承諾書）。OCR で読んだ全文
  - 言い換えた質問（ハイブリッド検索）でも見つかる

## 設計図は手元のコードから読む

`show_pipeline.py` が表示するデータソース・スキルセット・インデックスの設計図は、`lib/pipeline.py` のコードから読みます
（構築する人の `build_hr_index.py` が Azure に送るものと同じ）。取り込みの結果は、インデックスの中を検索して数えます。
検索だけのキー（メンバー用）は、Azure にあるデータソースやスキルセットの定義を読めないので、手元のコードから読む作りにしてあります。
構築する人が、Azure にある定義や、インデクサーの実行の記録を見るときは、`python applied/tools/build_hr_index.py --status` を使います。

## 検索の絞り込みなし

このトピックの検索（`search_documents.py`）は、インデックス `hr-docs` の全部の文書を探します（見てよい人での絞り込みは 16 から）。
17 は、同じインデックスの文書を一時的に直しますが、最後に元に戻します。

## インデックスの欄（16〜20 で使う）

- `chunk`：本文（OCR で読んだ文字を含む）、`text_vector`：ベクトル
- `title`：ファイル名、`parent_id`：親の文書、`doc_id`：文書の番号、`kind`：文書の種類
- `req_id`・`application_ids`・`person_keys`：求人・応募・人の番号（18 関係で探す）
- `allowed`：見てよい人（role:recruiter、role:interviewer、role:employee、user:U-1006 など。16 見せてよい人で絞る）
