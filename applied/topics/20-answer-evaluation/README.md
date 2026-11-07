# 20 答えを評価する

19 で作った答え（10問 × ① 普通の検索 / ② エージェント型検索 × 3回）を、LLM に採点させます。採点の方法は2通りです。

- **自前の採点プロンプト**：採点の基準を日本語の文で書き、1〜5 で採点させる。観点は3つ（根拠への忠実さ・質問への答え・要点の網羅）
- **組み込みの評価器**：`azure-ai-evaluation` の `GroundednessEvaluator`（資料に基づいているか）と `RelevanceEvaluator`（質問に答えているか）。各 1〜5

同じ質問・同じ方式の答えを、別々に3回ずつ作ってあります。その3つの答えを1回ずつ採点して、**3回の最小・最大で点のぶれ**を見ます。
このぶれは、**答えの生成のぶれ**（同じ質問でも答えが少しずつ違う）と**採点のぶれ**（同じ答えでも点が少し変わる）を合わせたものです。
LLM が答えを作り、LLM が採点するので、1回だけ採点して「② が良い」と決めることはできません。

> 19 の質問の分解は、プレビューの API（`2026-08-01-preview`）です。20 の採点は、プレビューではありません
> （Azure OpenAI の通常の呼び出しと、`azure-ai-evaluation` の評価器です）。

## 何を学ぶか

- 「答えの良さ」は1つの数字では決まらない。観点（根拠・質問への答え・要点の網羅）を分けて見る
- 採点の基準は、プロンプトの文章として書ける。基準の文が違えば、同じ答えでも点が違う（自前と組み込みの比べ）
- 想定の要点（教材を作るときに資料から作る）と比べる「要点の網羅」は、今回使う2つの組み込みの評価器（Groundedness・Relevance）が比べない観点。資料に基づいていても、質問の答えとして足りないことは、groundedness では見えない
  - 組み込みには、正解の文章（`ground_truth`）と答えを比べて網羅を 1〜5 で採点する `ResponseCompletenessEvaluator` もある。1.18.10 で `from azure.ai.evaluation import ResponseCompletenessEvaluator` ができるのを確かめた。ただし実験的なクラス（仕様が変わることがある）で、この教材では使わない。自前の採点の「要点の網羅」が同じ見方をする
- 点には、答えの生成のぶれと、採点のぶれがある。方式の差が小さいときは、ぶれの範囲に埋もれる。採点だけのぶれは、同じ答えを繰り返し採点して見る（`score_one.py` を同じ答えで何回か実行する）
- 組み込みの評価器を使うときの落とし穴（下の「注意」）

## 前提

- 19 が動くこと（`pip install -r applied/requirements.txt`、知識ベース `hr-docs-kb`）
- 組み込みの評価器を使うとき：Repo 直下で一度だけ

```
pip install -r applied/requirements-eval.txt
```

  `applied/requirements.txt` に足して入れる `azure-ai-evaluation==1.18.10` です。**重い**（約 150MB、依存のライブラリが約 30 個増える。ネットワークが速ければ 10 秒ほど）ので、
  `requirements.txt` には入れず、20 だけの `requirements-eval.txt` に分けてあります。入れなくても、自前の採点は動きます。
  Python のホイールは OS を選ばない形（`py3-none-any`）で、Windows でも入ります（公式資料で確認。実機では未確認）。

## 実行

```
python score_one.py                         1つの答えを、2通りで採点する（メンバーも動かす）
python score_one.py --id q02 --method plain
python score_one.py --answer "自分で書いた答え"    答えを書き換えて、点がどう変わるか見る
python score_all.py                         （進行役）10問 × 2方式 × 3回を採点して、ぶれを見る
python score_all.py --summary               保存した採点を集計するだけ（LLM を呼ばない）
python score_all.py --summary --threshold 4 合格のしきい値を 4 にして、合否を数え直す（点は同じで、合格の数だけが変わる）
python score_all.py --no-builtin            自前の採点だけ
```

19 の保存（`applied/_work/19_answers.json`）がなければ、`score_all.py` が 19 の関数で先に作ります。

採点の保存（`applied/_work/20_scores.json`）は、**入力が同じものだけ**使い回します（質問・答え・渡した資料・想定の要点・採点の基準の文から決めた指紋で照合）。
19 を作り直したり、`OWN_SYSTEM` や `questions.json` の要点を直したりすると、その分を採点し直します。
自前だけで採点したあとに組み込みの評価器を使う（`--no-builtin` を外す）と、足りない組み込みの分だけを採点します。指紋のない古い保存は、採点し直します。

## 見るところ

- `score_one.py`
  - 自前の採点：観点ごとの点と理由。「要点の網羅」が低いとき、理由が足りない要点を挙げているか
  - 組み込みの評価器：点、しきい値（既定 3）、合否（pass / fail）、理由。出力の欄の名前の一覧
  - 「確認の質問」を答えとして採点する確かめ：groundedness が 3 点で **pass（合格）** になる。relevance は低い
- `score_all.py`
  - 方式ごとの平均点：① と ② の差は小さい（5つの観点で -0.2〜+0.1 点）。どちらかが必ず良いわけではない
  - 質問ごとの点の幅（3回の最小〜最大）：同じ質問・同じ方式の3回で、点が 1〜2 点動くものがある（groundedness と「根拠への忠実さ」は、10 問のうち 4 問で幅が 2 点以上）。
    （別々に作った 3 つの答えの幅なので、答えの生成と採点の両方のぶれ）差は、このぶれの範囲に収まるか。質問によっては方式で大きく違う（q03 は ② が良く、q07 は ① が良い）
  - groundedness の点の分布：3 点は 0 件。9 件が 2 点（fail）で、20 件が 4 点、31 件が 5 点
  - 自前と組み込みの一致：同じ点になるのは 3 割ほど、1 点以内で一致するのは 8 割ほど。基準の文が違えば、同じ観点でも点は同じにならない
  - 呼び出しとトークンの合計（最後の表）

教材を作ったときの測定の例（60 件。**実行のたびに少し変わります**。モデルが違えば、数字も変わります）：

- 平均点（① / ②）：根拠への忠実さ 3.67 / 3.73、質問への答え 4.47 / 4.23、要点の網羅 3.97 / 3.80、groundedness 4.27 / 4.17、relevance 4.10 / 4.17
- 点の幅の平均（①/②）：要点の網羅 0.9 / 1.1、groundedness 1.5 / 1.4、relevance 0.4 / 0.6
- 要点の網羅の平均の差は 0.17 点で、同じ方式の 3 回の幅（平均 1.1 点）より小さい。この採点だけで方式の勝ち負けは決められない

## 注意：組み込みの評価器を使うとき

実際に動かして確かめたことです（`azure-ai-evaluation` 1.18.10、gpt-5 系のモデル）。

- **groundedness の 3 は「根拠にできる情報がない」の段**です（確認の質問、あいさつなど）。ところが既定のしきい値が 3 で、**3 以上が合格**です。
  資料に基づいていない答えでも、3 点なら pass になります。合否だけで見ず、点そのものを見る。しきい値は自分で決める（`score_all.py --threshold 4` のように変えると、保存した点をその値で判定し直して数えます）
- **gpt-5 系のモデルは `is_reasoning_model=True` が要ります。** 付けないと「`max_tokens` はこのモデルで使えない」という 400 になります
  （評価器が `max_tokens` を送るため。`True` にすると `max_completion_tokens` に替わる）。公式の「審査役に使えるモデル」の一覧は gpt-4o-mini などで、gpt-5 系は載っていません
- **出力の欄の名前は版で変わります。** この版は `groundedness`・`groundedness_score`・`groundedness_result`（pass / fail）・`groundedness_passed`・
  `groundedness_reason`・`groundedness_status`・`groundedness_threshold`・`groundedness_properties`。公式の古い例にある `gpt_groundedness` のような `gpt_` 付きの欄はありません。
  トークン数は `groundedness_properties` の中（`prompt_tokens`・`completion_tokens`）です。`lib/evaluation.py` の `parse_builtin` は、両方の名前を読みます。版を固定してあるのは、このためです
- Groundedness に `query`（質問）も渡すと、質問なしのときと別の採点プロンプトが使われます（3 の意味も違う）。`context` は文字列で、複数の断片は `\n\n` でつなぎます
- 組み込みの評価器は、1回の評価で LLM を 1 回呼びます（出力の上限 800 トークンは、組み込みの評価器が自分で決めている値です。自前の採点の上限は 4000 で、考える分も数えます）
- 自前の採点も完全ではありません。たとえば、資料に書いてあることを「資料にありません」と答えた答えに、根拠への忠実さ 5 をつけることがありました（`score_one.py --answer "資料にありません。"` で試せる）。
  採点のプロンプトの基準は、実際の採点結果を読んで直していくもの。想定の要点（`questions.json`）も、同じように見直す
- 評価器の `model_config` は、`azure_endpoint`・`api_key`・`azure_deployment`（と任意の `api_version`）で、キーで渡します。マネージド ID は使いません

## 呼び出しの数

- `score_one.py` 1回：自前の採点 1 回、組み込みの評価器 2 回、確認の質問の確かめで 2 回。合計 LLM 5 回、約 1.5 万トークン。メンバーが同時に動かしても問題ない数
- `score_all.py`（進行役）：採点 60 件 × （自前 1 回 ＋ 組み込み 2 回）＝ LLM 180 回。19 の保存がないと、答えの生成 60 回と質問の分解 30 回も加わる
  - トークン：自前の採点が入力 21.4 万 / 出力 1.1 万、組み込みの評価器が入力 35.9 万 / 出力 1.4 万。採点だけで入力 57.3 万 / 出力 2.5 万（19 を含めると入力 75.6 万 / 出力 4.3 万）
  - 1件あたり 4〜5 秒、60 件で 5 分ほど。Azure OpenAI の「1分あたりのトークンの上限」（429）に当たると、組み込みの評価器は 30 秒待ってやり直します（実測で 1 回起きた）。
    同時に動かすときは、`score_all.py` は進行役だけが実行する

## ファイル

- `score_one.py`：1つの答えを、2通りで採点する
- `score_all.py`：10問 × 2方式 × 3回を採点して、ぶれを集計する（進行役）
- `../19-agentic-retrieval/questions.json`：質問と「想定の要点」（`expect`）。自前の採点の「要点の網羅」で使う
- `../../lib/evaluation.py`：自前の採点プロンプト（基準の文は `OWN_SYSTEM`）、組み込みの評価器の呼び出し、ぶれの計算
- 保存：`applied/_work/19_answers.json`（19 の答え）、`applied/_work/20_scores.json`（採点）。Git には入りません

## 公式資料

- 評価器（Python SDK）：https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/develop/evaluate-sdk
- GroundednessEvaluator：https://learn.microsoft.com/en-us/python/api/azure-ai-evaluation/azure.ai.evaluation.groundednessevaluator
- RelevanceEvaluator：https://learn.microsoft.com/en-us/python/api/azure-ai-evaluation/azure.ai.evaluation.relevanceevaluator
- RAG の評価器（採点の段の説明）：https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators
