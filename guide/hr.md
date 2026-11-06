# 応用（人事）：採用の文書で、業務の検索を見る（応用編 14〜20）

架空の会社「サンプルテック」の採用の文書（求人票、職務経歴書、面接の評価、連絡メール、スキャンした書類）を使います。データはすべて研修用の架空データです。スクリプトとデータは [`applied/`](../applied/README.md) にあります。

仕組みの説明は、[ハンズオン資料の第2部](../docs/lecture/md/part2-ingestion.md)、[第3部](../docs/lecture/md/part3-relations-agentic.md)、[評価](../docs/lecture/md/part4-evaluation.md)です。

進行役がデモで見せることも、チームで動かすこともできます。デモは、進行役のデモ用のチームの `.env.local` で動かします（[進行役の手引き](facilitator.md#進行役のデモ用のチーム)）。

## 最初に1回

### 構築する人

人事の文書は、構築する人が1回だけ取り込みます。メンバーは、取り込みが終わってから始めます。

1. [ ] Repo 直下で、ライブラリを入れる：`pip install -r applied/requirements.txt`
2. [ ] 接続の設定 `.env.local` を、構築する人用で作る：`python tools/team.py env --team <チーム> --role builder`（[Azure の準備の 4](setup/azure-setup.md#4-接続の設定を作る)）
3. [ ] 文書を取り込む：`python applied/tools/build_hr_index.py`（OCR を含むので、数分かかります）
   - Storage の入れ物 `hr-docs` がなければ、この道具が作ります（非公開）
4. [ ] 状態を確かめる：`python applied/tools/build_hr_index.py --status`
5. [ ] 19・20 を動かすとき：`python applied/tools/build_hr_kb.py`（知識ソース `hr-docs-ks` と知識ベース `hr-docs-kb` を作ります）

### メンバー

1. [ ] Repo 直下で、ライブラリを入れる：`pip install -r applied/requirements.txt`
2. [ ] 構築する人から受け取った `member.local.env` を、Repo 直下に `.env.local` という名前で置く
3. [ ] 構築する人が、手順3（文書の取り込み）を終えている

構築する人とメンバーで、できることが違います。詳しくは [応用編 README の「構築する人とメンバー」](../applied/README.md#構築する人とメンバー)です。

## トピック

各トピックの README に、実行するコマンドと見るところが書いてあります。

- [14 種類の違う文書をまとめて取り込む](../applied/topics/14-mixed-documents/README.md)：手元の Python で読む（Azure は使わない）
- [15 Azure の仕組みに置き換える](../applied/topics/15-azure-indexer/README.md)：インデクサーとスキルセット、OCR
- [16 見せてよい人で絞る](../applied/topics/16-security-filter/README.md)：採用担当・面接官・一般社員で同じ質問を検索して並べる。プロンプトで頼むだけだと漏れる悪い例も
- [17 更新と削除](../applied/topics/17-update-delete/README.md)：応募の取り下げ、求人票の改訂。チームの本物の文書を直して、最後に元に戻す（構築する人の画面で見る）
- [18 関係で探す（紹介）](../applied/topics/18-relations/README.md)：求人、応募、経歴書、面接評価を ID でたどる
- [19 エージェント型検索のデモ](../applied/topics/19-agentic-retrieval/README.md)：普通の検索＋LLM と並べる。考える量の違い
- [20 答えを評価する](../applied/topics/20-answer-evaluation/README.md)：自前の採点と組み込みの評価器

- 17 は、動かしているあいだ、チームの検索の結果も変わります。ほかのメンバーが動かしていないときに、構築する人が実行します
- 19 の `make_answers.py` と、20 の `score_all.py` は、進行役が、デモ用のチームの `.env.local`（進行役が構築する人。[進行役の手引き](facilitator.md)）で見せます
- 20 の組み込みの評価器を使うときだけ、追加で `pip install -r applied/requirements-eval.txt`（約 150MB）

## 採用アシスタント（デモ）

採用の文書に、検索のやり方を変えながら候補を絞り込んで答える画面です。メンバーの設定で動きます。

1. [ ] Repo 直下で、ライブラリを入れる：`pip install -r applied/assistant/requirements.txt`
2. [ ] Repo 直下で、画面を開く：`streamlit run applied/assistant/app.py --server.address localhost`
   - この PC だけで開きます。人に見せるときは、`ASSISTANT_ACCESS_CODE` を設定します（[採用アシスタントの README](../applied/assistant/README.md#人に見せるときの設定任意)）

動かし方と仕組みは [採用アシスタントの README](../applied/assistant/README.md) です。

## 次の手順

[検索デモ](search-demo.md)：条件を変えると結果が変わるのを、AI Search だけで見る
