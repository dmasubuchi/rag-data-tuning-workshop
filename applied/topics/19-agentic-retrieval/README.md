# 19 エージェント型検索

同じ質問を、**普通の検索（1回）** と **エージェント型検索（LLM が質問を分解して、複数回探す）** で並べます。
どちらも同じ絞り込み・同じ件数の資料を、同じプロンプトで LLM に渡して答えさせます。違うのは「資料の選ばれ方」だけです。

> **プレビューの API です。** LLM を使う機能（質問の分解、考える量 low・medium・auto）はプレビューの API です。`low`・`medium` はそれより前のプレビューにもあり、
> `2026-08-01-preview` で足されたのが `auto` です。この教材は `auto` がある `2026-08-01-preview` を使います。
> 仕様が変わることがあります。GA の API 版（`2026-04-01`）で使えるのは、LLM を使わない minimal だけです。
> API 版の文字列は `lib/agentic.py` の `API_VERSION` の 1 か所だけです。

## 何を学ぶか

- 知識ベース（knowledge base）は、**知識ソース**（検索対象のインデックス）と**LLM**（質問を分解するモデル）をまとめた AI Search の部品
  - 知識ソース `hr-docs-ks`：インデックス `hr-docs` を指す
  - 知識ベース `hr-docs-kb`：知識ソースと LLM をまとめたもの（LLM は Azure OpenAI のキーで呼ぶ）。モデル名は `.env.local` の `AZURE_OPENAI_CHAT_MODEL`（既定 `gpt-5-mini`）、デプロイ名は `AZURE_OPENAI_CHAT_DEPLOYMENT` から読む
- 質問を渡すと、LLM が検索文に**分解**し、複数回探して、結果をまとめて返す。返事には3つが入る
  - `response`：根拠の断片（この Repo では、断片を取り出すだけの `extractiveData`。答えは別に LLM に作らせる）
  - `activity`：検索の記録。`modelQueryPlanning`（分解に使ったトークンと時間）、`searchIndex`（検索1回ごとの記録。検索文が入る）
  - `references`：出典。`docKey` が索引のチャンクのキー、`activitySource` がその出典を見つけた検索の記録の番号
- 分解された検索文は、`activity` の `searchIndex` の記録の `searchIndexArguments.search` にある。**検索の回数は、この記録の数**（回数そのものの欄はない）
- 考える量（`retrievalReasoningEffort`）で、どれだけ考えてから探すかが変わる
  - `minimal`：LLM を使わない。質問をそのまま検索文にする（`messages` でなく `intents` で渡す）
  - `low`：LLM が質問を分解する（何も指定しないときの既定）
  - `medium`：`low` のあと、結果を見て足りなければ、見直した計画でもう1回やり直す
  - `auto`：まず軽く探し、足りなければ `medium` まで上げる（`2026-08-01-preview` で足された。LLM を呼ぶ回数は質問ごとに変わる）
- 情報が欠けた人の扱い：データに書類がない人（たとえば面接の評価がない応募者）について、答えが「資料にありません」と書けるか

## 前提

- `pip install -r applied/requirements.txt`（Repo 直下で、仮想環境の中で）
- 構築する人がインデックス `hr-docs` と、知識ベース `hr-docs-kb` を作ってあること（なければ構築する人に聞く）。メンバーは読むだけで、何も作りません
- メンバーの設定（検索だけのキー、Storage なし）で動きます。ただし、知識ベースの retrieve が検索だけのキーで通るかは、実機で確かめていません（通らないときは、構築する人の設定で動かします）

## 実行

```
python compare_search.py                       ① と ② を並べる（既定の質問 q01）
python compare_search.py --id q07              用意した質問の別の1問
python compare_search.py --question "市川さんの二次面接はいつでしたか"     自分の質問
python compare_search.py --effort medium       ② の考える量を変える
python effort_levels.py                        考える量を変えて比べる（答えは作らない）
python effort_levels.py --id q02 --efforts minimal low
python make_answers.py                         （進行役）10問 × 2方式 × 3回の答えを作って保存する
```

## 見るところ

- `compare_search.py`
  - ② の「質問の分解」の表：元の質問に対して、LLM がどんな検索文に分けたか。検索の回数（`low` では3つ前後に分けることが多い）
  - ② の「出典」の表：答えに渡した資料と、「見つけた検索文」（どの検索文がどの資料を見つけたか）
  - 「方式の比べ」：検索の回数・分解（LLM）・時間・トークン。② は分解の分だけ増える
  - 「誰の資料が入ったか」：データにある書類（左）に対して、① ② の資料にその人の書類が入っているか。**書類がない人（評価の行が 0 など）は、入りようがない。答えが「資料にありません」と書けているかを、答えの文で確かめる**
  - ① と ② の答えを読み比べる。**② が必ず良いとは限らない**（資料の選ばれ方が変わるだけで、LLM の答え方のぶれもある）
- `effort_levels.py`
  - 「考える量ごとの比べ」：検索文の数・検索の回数・LLM の呼び出し・時間・トークン
    - `minimal` は LLM の呼び出し 0 回・検索 1 回。`low` は LLM 1 回・検索 3 回前後。`medium` は結果を見てやり直すと、LLM 2 回・検索 6 回前後に増え、時間も長くなる（やり直さないこともある）
    - 「検索側のトークン」は AI Search が数えるトークン（`reasoningTokens`。LLM のトークンとは別）
  - 「同じ資料が選ばれたか」：考える量を上げると、選ばれる資料が変わる。変わっても答えが良くなるとは限らない（20 で点数にして確かめる）
  - 最後に GA の API（`2026-04-01`）で `minimal` を呼ぶ。LLM は 0 回
  - 分解は実行するたびに少しずつ変わる（LLM の出力だから）
- `make_answers.py`（進行役用）：方式ごとの平均（検索の回数・時間・トークン）と、質問ごとの分解

## 実際の数字の例

教材を作ったときの測定（答えに渡す資料 10 件）。**実行のたびに少し変わります**（分解は LLM の出力だから）。モデルが違えば、数字も変わります。

- 10 問 × 3 回（30 件ずつ）の平均（1件あたり）
  - ① 普通の検索：検索 1 回、2.2 秒、LLM のトークン 入力 2,596 / 出力 281（答えの生成だけ）
  - ② エージェント型検索：検索 3 回（質問の分解は 1 回）、3.3 秒、入力 3,509 / 出力 337（分解 約 960 / 60 ＋ 答えの生成）
  - `low` では、どの質問も検索文は 3 つに分かれた。「REQ-042 大西 明日香 一次面接 評価」「REQ-042 大西 明日香 職務経歴書」「大西 明日香」のように、質問の中の「聞きたいこと」ごとに分かれる
- `effort_levels.py`（q10 の例）

  - `minimal`：検索 1 回、LLM 0 回、0.3 秒
  - `low`：検索 3 回、LLM 1 回（入力 963 / 出力 64）、1.4 秒
  - `medium`：検索 6 回、LLM 2 回（入力 4,404 / 出力 249。2 回目は 1 回目の結果を読むので入力が増える）、3.8 秒
  - `auto`：検索 4 回、LLM 1 回、1.9 秒（最初に質問そのままで探し、そのあと分解した）
  - GA の API で `minimal`：検索 1 回、LLM 0 回。件数の上限がないので資料が 19 件返った
- 答えの良し悪しは、② が必ず良いわけではない。20 で採点すると、質問ごとに勝ち負けが入れ替わる（q03 は ②、q07 は ① が良い）

## 用意した質問（10問）

`questions.json` に、質問と「答えに入っているべき要点」（`expect`）があります。要点は教材を作るときに資料から作ったもので、20 の採点に使います。
複数の文書をまたぐ質問を中心にしています。

- q01 REQ-043 の最終面接に進んだ人の評価と、内定の連絡の日付は？（評価の Excel・選考履歴・連絡メール）
- q02 REQ-042 の応募者のうち、面接の評価がまだない人はいますか。いれば、今の段階も教えてください。（情報が欠けた人）
- q03 REQ-042 の大西 明日香さんの一次面接の評価と、職務経歴書の内容を教えてください。（評価は下書き、経歴書はない）
- q04 REQ-042 の二次面接を受けた人のうち、評価が高かった人と見送りになった人で、評価の中身はどう違いましたか。
- q05 市川 浩二さんは、REQ-042 の必須条件と歓迎条件を満たしていますか。経歴書と面接の評価から教えてください。
- q06 岩崎 俊介さん（APP-0417）は、REQ-042 の必須条件のうち、面接でまだ確認できていないものはありますか。
- q07 REQ-042 に応募している岩崎さんは2人います。それぞれ今どの段階で、次に何がありますか。（名前が似た2人）
- q08 石田 裕太さんの入社予定日と、内定承諾書の日付、承諾書の提出期限を教えてください。（スキャンの OCR とメール）
- q09 中島 美和さんの最終面接の候補日と、二次面接の評価を教えてください。
- q10 REQ-042 の応募者のうち、夜間の障害対応の経験がある人はだれですか。根拠になった書類も教えてください。（4種類の書類を人ごとに集める）

自分の質問は `--question "…"`（または各スクリプトの先頭の `QUESTION`）で試せます。質問に求人番号（REQ-042）や応募番号、人の名前を入れると探しやすくなります。

## 呼び出しの数（1問あたり）

メンバーが同時に動かしても困らない数にしてあります（Azure OpenAI の呼び出しは、`compare_search.py` で 3 回、`effort_levels.py` で 4 回）。
混み合って断られた（429）ときは、自動で少し待ってやり直します。

- `compare_search.py` 1回
  - AI Search：普通の検索 1 回、知識ベース 1 回（知識ベースの中で検索が 3 回前後）
  - Azure OpenAI：質問の分解 1 回（約 1,000 トークン）、答えの生成 2 回（約 2,700 トークンずつ）。合計 3 回、約 7,000 トークン
- `effort_levels.py` 1回（4つの考える量）
  - AI Search：知識ベース 4 回＋ GA の API で 1 回
  - Azure OpenAI：質問の分解だけ。`low` は 1 回、`medium` と `auto` は結果を見て続けるので回数が変わる（実測では `medium` 2 回、`auto` 1 回で、合計 4 回、約 7,000 トークン）。答えの生成はしない
- `make_answers.py`（進行役。10 問 × 3 回）
  - Azure OpenAI：答えの生成 60 回＋質問の分解 30 回。約 18 万入力 / 1.9 万出力トークン
  - AI Search：普通の検索 30 回、知識ベース 30 回
  - 参加者が動かすときは、`--only q01 q03`（質問を絞る）か `--runs 1` にする

## 仕組み（要求の形）

知識ベースの retrieve は REST で呼びます（`lib/agentic.py`。ヘッダーは `api-key`）。

```
POST {検索サービス}/knowledgebases/hr-docs-kb/retrieve?api-version=2026-08-01-preview
{
  "messages": [{"role": "user", "content": [{"type": "text", "text": "質問"}]}],   ← minimal のときは "intents": [{"type": "semantic", "search": "質問"}]
  "retrievalReasoningEffort": {"kind": "low"},
  "outputMode": "extractiveData",
  "includeActivity": true,
  "maxOutputDocuments": 10,
  "knowledgeSourceParams": [{
    "kind": "searchIndex", "knowledgeSourceName": "hr-docs-ks",
    "filterAddOn": "allowed/any(a: search.in(a, 'role:recruiter'))",
    "includeReferences": true, "includeReferenceSourceData": true
  }]
}
```

- `filterAddOn`：普通の検索の `filter` と同じ絞り込みを、知識ベースにも掛ける（16 で学んだ「見てよい人」の絞り込み）
- `maxOutputDocuments`：返す資料の件数。普通の検索の `top` とそろえる
- GA の API（`2026-04-01`）の retrieve は `intents` と `knowledgeSourceParams` と `includeActivity` だけ。`retrievalReasoningEffort`・`outputMode`・`maxOutputDocuments` を付けると 400 になる

## ファイル

- `compare_search.py`：同じ質問を ① 普通の検索と ② エージェント型検索で並べる（メンバーも動かす）
- `effort_levels.py`：考える量を変えて比べる（メンバーも動かす）
- `make_answers.py`：10問の答えを作って保存する（進行役）
- `questions.json`：用意した質問 10 問と、答えに入っているべき要点
- `../../lib/agentic.py`：知識ベースの定義、retrieve の要求と結果の読み取り、普通の検索、答えの生成、答えの保存
- `../../tools/build_hr_kb.py`：知識ソース・知識ベースを作る（構築する人）
- 保存：`applied/_work/19_answers.json`（質問・方式・回・答え・渡した資料。Git には入りません）

## 構築する人用

Repo 直下で、構築する人の `.env.local` で実行します。

```
python applied/tools/build_hr_kb.py             知識ソースと知識ベースを作る（あれば更新）。最後に動作確認（LLM 1 回）
python applied/tools/build_hr_kb.py --status    いまの状態を見る（何も変えない）
python applied/tools/build_hr_kb.py --recreate  消してから作り直す
python applied/tools/build_hr_kb.py --delete    消す
```

- 知識ベースの LLM は、`.env.local` の Azure OpenAI のキーを知識ベースに登録して呼びます（`azureOpenAIParameters.apiKey`）。マネージド ID やロールの割り当ては使いません
- モデル名（`modelName`）は `AZURE_OPENAI_CHAT_MODEL`、デプロイ名（`deploymentId`）は `AZURE_OPENAI_CHAT_DEPLOYMENT` から読みます。このモデルで知識ベースが動くかは、実機で確かめてください
- 扱うのは `hr-docs-ks` と `hr-docs-kb` だけです。インデックス・インデクサー・Storage には触りません
- 知識ソースの数・知識ベースの数は、AI Search 全体で各 15 まで（Basic）。この教材は 1 つずつ使います
- 前提：`hr-docs` の各チャンクに `allowed`（見てよい人）が付いていること。付いていないと、絞り込みで 1 件も返りません

## 公式資料

- エージェント型検索の概要：https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview
- 知識ベースを作る：https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-create-knowledge-base
- 知識ベースに質問する（retrieve）：https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-retrieve
- 考える量：https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-set-retrieval-reasoning-effort
