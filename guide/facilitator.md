# 進行役の手引き

研修を進める人（進行役）向けです。開始前の準備、パートの順、各パートで見せるもの、つまずきやすい所をまとめます。時刻は人数やパートの長さに合わせて組みます。5時間で進めるときの例は「[5時間で進めるとき（例）](#5時間で進めるとき例)」にあります。

## 人

- 進行役：全体を進める。組織の設定の値を渡し、Azure の権限を付ける。複数いるときは、チームごとに担当を決める
- チーム：構築する人（1人）と、メンバー（人数は自由）。構築する人が画面を操作し、ほかの人は手順を読み上げて確かめる
- チームの名前を決めたあとは、その名前（`<team>`）でチームを呼ぶ

流れ：パート1 PC、パート2 Azure、パート3 基礎編（ホテルと武将）、パート4 応用編（人事）、締め

## 5時間で進めるとき（例）

5時間で進めるときの例です。時刻はすべて例で、日時と相手が決まったら組み直します。

- 範囲：全チームが、ホテル（章1〜3）と武将 01〜06 までを終える。早いチームは、人事と評価に進む
- 最初の約30分は進行役が話し、残りは各チームが手順書を見て手を動かす。進行役は見て回る
- 「目安」は、その時刻までに見えていればよい数字

- 0:00–0:30　さわりとガイダンス（進行役が話す）
  - やること：検索の基盤のほかに、データの側（加工・運営・評価）があることを話す。進め方と、チームの役割を伝える
  - 映す：[はじめに](../site/lecture/intro/slides.html)のさわりの3枚と、進め方
- 0:30–1:15　パート1 PC とパート2 Azure（→ [パート1](#パート1-pc-の設定)、[パート2](#パート2-azure-の接続とリソース作成)）
  - やること：PC を整え、チームの名前を決めて、Azure のリソースを作り、`.env.local` を作る
  - 目安：`python tools/team.py health --team <team>` が `OK 8・まだ 0・NG 0`
- 1:15–2:10　ホテル 章1〜3（→ [ホテル](#ホテル)）
  - やること：Blob のホテルを AI Search に取り込み、6つの機能を試す
  - 映す：[p.16 取り込みの順番](../site/lecture/part2-ingestion/slides.html#p16)、[p.1 BM25](../site/lecture/part1-search/slides.html#p01)、[p.11 フィルターとファセット](../site/lecture/part1-search/slides.html#p11)
  - 目安：`hotels-blob` のドキュメント数が50。章3のキーワード検索で beach が4件
- 2:10–2:20　休憩
- 2:20–3:50　武将 01〜06（→ [武将](#武将)）
  - やること：構築する人が 01 から順に進め、メンバーは検索のスクリプトを動かす。05 の60問の測定は、進行役が1回見せる（チームでは動かさない）
  - 映す：[p.13 同義語マップ](../site/lecture/part1-search/slides.html#p13)、[p.2 ベクトル検索](../site/lecture/part1-search/slides.html#p02)、[p.3 ハイブリッド検索](../site/lecture/part1-search/slides.html#p03)、[p.42 NDCG と再現率](../site/lecture/part4-evaluation/slides.html#p42)、[p.50 ハルシネーション](../site/lecture/part5-wrapup/slides.html#p50)
  - 目安：01 で `sengoku` が150件。03 で、言い換えの質問のベクトル検索の1位が正解。06 で、検索ありの答えが正解
- 3:50–4:00　休憩
- 4:00–4:40　チームごとに分かれる
  - 早いチーム（武将 06 まで終わった）：[人事](hr.md) 14 → 15 → 16、その次に[評価](evaluation.md)（`--limit 6`）
  - 遅いチーム：武将の残り。進行役は遅いチームを回る
- 4:40–5:00　締め（→ [締め](#締め)）
  - やること：作り方の比較と料金を振り返る。続きの進め方（ホテルの章4〜5、人事 17〜20、評価の全部）を伝える。片付けを伝える（→ [終わったあと](#終わったあと)）
  - 映す：[p.46 作り方の比較](../site/lecture/part5-wrapup/slides.html#p46)、[p.52 料金の構造](../site/lecture/part5-wrapup/slides.html#p52)

人事に進むチームの前提：

- 人事を動かす全員（構築する人とメンバー）が、Repo 直下で `pip install -r applied/requirements.txt` を済ませる（武将のライブラリだけでは足りない）
- 構築する人が、[人事](hr.md)の「最初に1回」を済ませておく。`python applied/tools/build_hr_index.py` で `hr-docs` を取り込む（OCR を含むので、数分かかる）。武将の途中で始めておくと、待たない
- 取り込みが終わったら、`python applied/tools/build_hr_index.py --status` で状態を見る。メンバーは、取り込みが終わってから始める
- 14 は手元の Python だけで動く（Azure は使わない）。15・16 は、構築する人が作った `hr-docs` を検索する

パート4 の進行役のデモ（14〜20 と[採用アシスタント](../applied/assistant/README.md)）は、この時間割に入れていません。

### 遅れたとき・早く終わったとき

遅れたら、飛ばしてよい所：

- ホテルの 3-4 地理検索と 3-6 ソート：あとで、各チームで進める
- 武将 05 の60問の測定：チームでは動かさず、進行役が見せた数字を見る

判断の時刻の目安：

- 2:10 にホテルの章3が終わっていなければ、3-4 と 3-6 を飛ばして武将へ進む
- 3:50 に武将 06 まで来ていなければ、4:00–4:40 で続きを進める

早く終わったら、人事 14 → 15 → 16、そのあと評価へ進む：

- 評価の確かめ：`python tools/eval_search.py --dataset hr --limit 6`（先頭の6問だけ。セマンティック ランカーを6回使う）
- 全部の質問を測るのは、チームで1回にする（[評価](evaluation.md)）

## 開始前の準備

### 渡す値を決める

次の4つを決めて、参加者に伝えます（参加者は `workshop.config` に書きます）。

- [ ] Azure のサブスクリプション ID
- [ ] リソースを作る場所（例：`japaneast`）
- [ ] 組織の短い名前（小文字の英字と数字、3〜6文字、英字で始める）
- [ ] Azure のテナント

既存のリソース グループに作るときだけ、その名前も伝えます（`workshop.config` の `AZURE_RESOURCE_GROUP`。5つ目、任意）。

### Azure：招待と所有者の割り当て

進行役、または組織の管理者が行います。構築する人の数だけくり返します。

1. [ ] Entra 管理センター（`https://entra.microsoft.com`）に、テナントでサインインする
2. [ ] 左の「Entra ID」の「ユーザー」を開き、「新しいユーザー」の「外部ユーザーの招待」を選ぶ
3. [ ] 「電子メール」と「表示名」を入れ、「招待メッセージの送信」にチェックを入れて、「確認と招待」、「招待」を選ぶ
4. [ ] Azure ポータルで、使うサブスクリプションを開き、「アクセス制御 (IAM)」の「追加」から「ロールの割り当ての追加」を選ぶ
5. [ ] 「特権管理者ロール」の「所有者」を選び、「次へ」を選ぶ
6. [ ] 「メンバーの選択」で、招待した人を選び、「選択」、「次へ」を選ぶ
7. [ ] 「条件」タブでは、（推奨）の選択肢を選び、「次へ」を選ぶ
8. [ ] 「割り当ての種類」が出たら、「アクティブ」と「永続的」を選び、「次へ」を選ぶ
9. [ ] 「確認と割り当て」を選ぶ
10. [ ] 招待された人が、招待メールを承諾し、`https://portal.azure.com/<テナント>` でサインインし直して、サブスクリプションが見えることを確かめる

- 所有者にするのは、ロールの割り当て（AI Search にストレージを読む権限を付けるなど）を、構築する人が行うためです。研修のあとに、いつ外すかも決めておきます。

### GitHub：Repo の招待

Repo が非公開のときだけです。

1. [ ] 参加者の GitHub のアカウントを聞く
2. [ ] Repo の「Settings」の「Collaborators」で、「Add people」から招待する
3. [ ] 招待を承諾して、Repo を開けることを確かめる

### 進行役の PC

- [ ] Repo を clone し、`pip install -r basic/requirements.txt` を実行する
- [ ] `workshop.config` を書く（チームごとの状態確認に使う）
- [ ] az にサインインする：`az login --tenant <テナント>`、`az account show`
- [ ] Foundry のモデルの枠を確かめる：チームの数（デモ用のチームを作るなら、それも数える）だけ、埋め込み `text-embedding-3-small`（容量 50）と、チャット `gpt-5-mini`（容量 20）が、「グローバル標準（Global Standard）」で足りること
- [ ] 画面に映すもの（スライド）を開いておく：[ハンズオン資料](../site/lecture/intro/slides.html)

### 進行役のデモ用のチーム

パート3・4 のデモは、進行役が自分のデモ用のチーム（例 `demo`）の `.env.local` で動かします。始める前に、参加者と同じ手順で作っておきます。進行役が、そのチームの構築する人です。

1. [ ] [Azure の準備](setup/azure-setup.md)：チームの名前を決め、ポータルでリソースを作る
2. [ ] `python tools/team.py env --team <デモ用のチーム> --role builder`：進行役の `.env.local` を作る。`pip install -r applied/requirements.txt -r applied/assistant/requirements.txt` も入れておく
3. [ ] 基礎編 01〜03 を実行する（[武将](sengoku.md)）：インデックス `sengoku` とベクトルができる
4. [ ] `python applied/tools/build_hr_index.py` と `python applied/tools/build_hr_kb.py` を実行する（[応用（人事）](hr.md)）：人事の文書と、知識ベースができる

- デモ用のチームを作らないときは、どれかのチームの構築する人の画面を映して見せます。

## パート1 PC の設定

手順：[Windows PC の設定](setup/windows-pc.md)

- [ ] ネットワークにつなぐ
- [ ] 各 PC で、Git・Python・az・VS Code を確かめ、`pip install -r basic/requirements.txt` まで済ませる
- [ ] チームを分け、各チームの構築する人を決める
- 映す：[はじめに](../site/lecture/intro/slides.html)
- 確かめる：git・python・az・code のコマンドがすべて動く。VS Code の Markdown のプレビュー（`Ctrl+Shift+V`）に図が出る

## パート2 Azure の接続とリソース作成

手順：[Azure の準備](setup/azure-setup.md)

- [ ] 各チームが、チームの名前を決める（例 `red`）。小文字の英字と数字だけ、3〜8文字、英字で始める、`shared` で始めない。チームどうしで同じにしない
- [ ] 各チームが、`python tools/team.py check-names --team <team>` で確かめ、すべて「使える」になってから作り始める（既存のリソース グループを使うチームは、リソース グループだけ「既存のものを使う」になる）
- [ ] チームごとに、`names` の表示どおりに作る：リソース グループ（既存のものを使うときは作らない）、Storage、AI Search（Basic）、Cosmos DB、Foundry とモデル2つ
- [ ] 各チームの構築する人が、自分の `.env.local`（`python tools/team.py env --team <team> --role builder`）と、メンバー用の `member.local.env`（`--role member --out member.local.env`）を作り、`member.local.env` をチームの中だけでメンバーに渡す。メンバーは Repo 直下に `.env.local` という名前で置く
- 確かめる（進行役の PC で、チームごとに）：`python tools/team.py health --team <team>`。8行がすべて「OK」で、`OK 8・まだ 0・NG 0`
  - 「NG」は理由を読んで直す。「まだ」は、まだ作っていないもの
  - Cosmos DB は `health` が調べないので、ポータルで見る
  - 8行のあとに「インデックスの文書の数（参考）」が出る。判定には入らない。この時点は、4つとも「まだない」が正しい（取り込んだあとに実行し直すと、件数が出る）

## パート3 基礎編：ホテルと武将

### ホテル

手順：[ホテル](hotel.md)（章1〜3が中心。章4〜5は、Cosmos DB を使う続き）

- [ ] 章2：Blob のホテルを AI Search に取り込む（マネージド ID、Blob を読む権限、JSON を置く、インデックス、データソース、インデクサー、5分ごとの取り込み）
- [ ] 章3：6つの機能を検索エクスプローラーで試す（自動取り込み、キーワード、フィルター、地理、ファセット、並べ替え）
- 映す：[p.16 取り込みの順番](../site/lecture/part2-ingestion/slides.html#p16)、[p.27 インデクサーとスキルセット](../site/lecture/part2-ingestion/slides.html#p27)、[p.1 BM25](../site/lecture/part1-search/slides.html#p01)、[p.7 アナライザーと日本語の形態素解析](../site/lecture/part1-search/slides.html#p07)、[p.11 フィルターとファセット](../site/lecture/part1-search/slides.html#p11)、[p.29 差分の更新と削除の検出](../site/lecture/part2-ingestion/slides.html#p29)
- 確かめる（章2のあと、各チームのポータルで）：インデクサー `hotels-blob-indexer` の最初の実行が「成功」で、処理50・失敗0。インデックス `hotels-blob` のドキュメント数が50
- 確かめる（章3のあと）：beach 4件、pool 18件、wifi 22件。ビーチ・プールで日本語の名前のホテルが出る。ファセットの件数が出る。地理検索で近い順に3件

### 武将

手順：[武将](sengoku.md)（トピック 01〜06）

- [ ] 各チームの構築する人が、01 から順に進める。AI Search に `sengoku` ができる
- [ ] メンバーは、構築する人が進めたところまで、検索のスクリプトを動かす
- 確かめる：01 のあと、ポータルで `sengoku` のドキュメント数が 150
- 01・02：キーワード検索と、同義語で順位が変わるのを見る
  - 映す：[p.13 同義語マップ](../site/lecture/part1-search/slides.html#p13)
  - 確かめる：02 の同義語の1行で、q28 の順位が上がる
- 03：ベクトル検索で、言い換えの質問が当たるのを見る
  - 映す：[p.2 ベクトル検索](../site/lecture/part1-search/slides.html#p02)
  - 確かめる：言い換えの質問で、ベクトル検索の1位が正解
- 04：ハイブリッドとランカー
  - 映す：[p.3 ハイブリッド検索](../site/lecture/part1-search/slides.html#p03)、[p.4 RRF](../site/lecture/part1-search/slides.html#p04)、[p.5 セマンティックランカー](../site/lecture/part1-search/slides.html#p05)
  - 確かめる：4つの方式の順位が並ぶ。方式を変えれば必ず良くなるわけではない
- 05・06：測る、答えを作る
  - 映す：[p.42 NDCG と再現率](../site/lecture/part4-evaluation/slides.html#p42)、[p.48 RAG の基本の流れ](../site/lecture/part5-wrapup/slides.html#p48)、[p.50 ハルシネーション](../site/lecture/part5-wrapup/slides.html#p50)
  - 確かめる：05 の60問の測定は、進行役が、デモ用のチームの `.env.local` で1回見せる（チームで何度も実行しない）。06 で検索ありの答えが正解、検索なしは外れる

## パート4 応用編：人事

手順：[応用（人事）](hr.md)

- [ ] 構築する人が、`hr-docs` を取り込んでおく（数分。パート3の途中で始めておくと、待たない）
- [ ] 14〜20 を、進行役が、デモ用のチームの `.env.local`（構築する人の設定）で見せる（17 は本物の文書を直すので、進行役の画面だけで動かす）
- [ ] [採用アシスタント](../applied/assistant/README.md)を見せる（デモ用のチームの `.env.local` で。手元だけで開きます）
- 映す：[p.30 権限：誰に何を見せるか](../site/lecture/part2-ingestion/slides.html#p30)、[p.29 差分の更新と削除の検出](../site/lecture/part2-ingestion/slides.html#p29)、[p.31 文書同士の関係性を検索する](../site/lecture/part3-relations-agentic/slides.html#p31)、[p.32 エージェント型検索](../site/lecture/part3-relations-agentic/slides.html#p32)、[p.36 ナレッジソースとナレッジベース](../site/lecture/part3-relations-agentic/slides.html#p36)、[p.44 生成 AI による採点のぶれ](../site/lecture/part4-evaluation/slides.html#p44)
- 短く見せるとき：[検索デモ](search-demo.md)（AI Search だけ。5段で、絞る・見せてよい人・並べ直す）

## 締め

- [ ] 作り方の比較と料金を振り返る
  - 映す：[p.46 作り方の比較](../site/lecture/part5-wrapup/slides.html#p46)、[p.52 料金の構造](../site/lecture/part5-wrapup/slides.html#p52)
- [ ] 続きの手順を伝える：ホテルの章4〜5（Cosmos DB）、[評価](evaluation.md)（3つのデータを測り、精度と費用の釣り合いを決める）、ハンズオン資料と各トピックの README
- [ ] 質問の窓口を伝える（チャットなど、決めた場所）

## 終わったあと

- [ ] 各チームのリソース グループ `rg-<org>-<team>` を、残すか消すか決める
  - 続きの手順を進めるなら残す。AI Search の Basic は、残しているあいだ料金がかかる（料金は [Azure の料金ページ](https://azure.microsoft.com/ja-jp/pricing/details/search/)で確かめる）
  - 消すとき：ポータルでリソース グループを開き、「リソース グループの削除」を選ぶ。リソース グループの名前を入力して確認する
  - az では：`az group delete -n rg-<org>-<team>`（リソース グループの中身が全部消える）
  - 既存のリソース グループを使ったチーム（`AZURE_RESOURCE_GROUP`）は、グループを削除しない（ほかのものも入っている）。中のチームのリソース（`st<org><team>`・`srch-<org>-<team>`・`cosmos-<org>-<team>`・`ai-<org>-<team>`）だけを、1つずつ削除する
- [ ] 所有者の割り当てを、いつ外すか決める
- [ ] 試しに作ったリソースがあれば、消す

## つまずきやすい所

- モデルのデプロイで枠が足りない：「グローバル標準（Global Standard）」を選んでいるか、容量が 50・20 以下か確かめる
- チームの名前が使えない：`check-names` の「ほかで使われている」。名前を変える
- 「AZURE_RESOURCE_GROUP のリソース グループ … が見つかりません」：`workshop.config` の名前の綴りを直す（このツールは、グループを作らない）
- ロールの割り当てが効かない：付けた直後は、反映に時間がかかる。5分ほど待って、インデクサーの次の実行を見る
- 画面の名前が違う：Azure の画面は変わる。メニューの名前を探し、見つからなければ、進行役が確かめて伝える
- セマンティック ランカーの無料枠：チームの AI Search 全体で、月ごとに使う。05 の `measure_methods.py` は、1回の実行で質問の数（60回）使う
- 評価の `eval_search.py`：人事・武将は、全部の質問・4方式で、セマンティック ランカーを60回使う（[評価](evaluation.md)）。確かめは `--limit 6`、全部を測るのはチームで1回にする
- 17 は本物の文書を直す：動かしているあいだ、チームの検索の結果も変わる。メンバーが 15・16・18・19 を動かしていないときに、構築する人が実行する
- キーが古くなった：構築する人が `python tools/team.py env --team <チーム> --role builder`（自分の `.env.local`）と `--role member --out member.local.env`（メンバー用）を実行し直し、`member.local.env` をメンバーに渡し直す
- Azure OpenAI が「呼びすぎ（429）」と返す：自動で待って再試行する。続くときは、1分ほど待つ
