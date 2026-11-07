# Azure の準備

チームの AI Search と Foundry などを、Azure に作ります。操作するのは、チームの構築する人（1人）です。ほかのメンバーは、手順を読み上げて確かめます。

画面の名前が書いてあるものと違うときは、進行役に聞きます（Azure の画面は変わることがあります）。

手順は、画面（ポータル）で作ることを中心に書いてあります。az のコマンドは、画面で作れないときや確かめるときの補助として、[5](#5-補助az-で作る) にまとめてあります。

## 作るもの

チームの名前を決めると、リソースの名前が決まります（`<org>` は組織の名前、`<team>` はチームの名前）。

- リソース グループ：`rg-<org>-<team>`
- ストレージ アカウント：`st<org><team>`
- AI Search：`srch-<org>-<team>`（価格レベルは Basic）
- Cosmos DB：`cosmos-<org>-<team>`（[ホテル](../hotel.md)の 4〜5 章だけで使う）
- Foundry：`ai-<org>-<team>` と、プロジェクト `proj-default`
- モデルのデプロイ：`text-embedding-3-small`（埋め込み）、`gpt-5-mini`（チャット）

例：組織が `acme`、チームが `red` のとき、`rg-acme-red`、`stacmered`、`srch-acme-red`、`cosmos-acme-red`、`ai-acme-red` です。

## 0. 進行役から受け取る値を書く

進行役から、次の4つの値を受け取ります。

- Azure のサブスクリプション ID
- リソースを作る場所（例：`japaneast`）
- 組織の短い名前（小文字の英字と数字、3〜6文字、英字で始める。例：`acme`）
- Azure のテナント（テナントのドメイン名か ID）

1. [ ] `config/workshop.example.config` をコピーして、Repo 直下に `workshop.config` という名前で置く
   - PowerShell：`Copy-Item config/workshop.example.config workshop.config`
2. [ ] `workshop.config` を VS Code で開き、4つの値を書いて保存する（引用符はつけない）
   - 既存のリソース グループに作るときだけ、5つ目の `AZURE_RESOURCE_GROUP` にその名前を書く（空なら `rg-<組織>-<チーム>` を作る）

- `workshop.config` は Git に入りません。ほかの人に渡す必要もありません（値は進行役が全員に伝えます）。
- 以降、`<テナント>` は `AZURE_TENANT` の値、`<サブスクリプション ID>` は `AZURE_SUBSCRIPTION_ID` の値、`<場所>` は `AZURE_LOCATION` の値、`<org>` は `WORKSHOP_ORG` の値に置き換えます。

## 1. Azure に入る

進行役（または組織の管理者）が、構築する人を Azure に招待し、サブスクリプションの「所有者」にしています。

1. [ ] 招待メールの「招待を承諾する」を選び、「承諾」を選ぶ
   - メールが届かないとき：`https://portal.azure.com/<テナント>` に、招待されたアドレスでサインインして承諾する
2. [ ] `https://portal.azure.com/<テナント>` を開いてサインインする
3. [ ] 上の検索ボックスに「サブスクリプション」と入れ、進行役に聞いたサブスクリプションが一覧にある
4. [ ] そのサブスクリプションを開き、「アクセス制御 (IAM)」の「アクセスの確認」で、自分が「所有者」になっている
   - 所有者でないとき：進行役に伝える

## 2. チームの名前を決める

リソースの名前は、すべて組織の名前とチームの名前から決まります。チームの名前は、小文字の英字と数字だけ、3〜8文字、英字で始めます。`shared` で始めてはいけません（例 `red`）。ほかのチームと同じにしません。

1. [ ] チームの名前を決める（以下、`<team>`）
2. [ ] PowerShell を開き、Repo のフォルダーに移って、Azure にサインインする（ブラウザが開く）
   - `az login --tenant <テナント>`
   - 「Select a subscription」と出たら、そのまま Enter を押す
3. [ ] 名前を表示する：`python tools/team.py names --team <team>`
4. [ ] 表示された `$env:WORKSHOP_TEAM = "<team>"` の行を、PowerShell に貼って実行する
   - このウィンドウの間だけ有効。PowerShell を開き直したら、もう一度貼る
   - 貼ったあとの `team.py` では、`--team` を省略できる
   - bash では、`export WORKSHOP_TEAM=<team>`
5. [ ] 名前が使えるかを確かめる（Azure には何も作りません）：`python tools/team.py check-names`
6. [ ] 5つの名前がすべて「使える」になる
   - 「ほかで使われている」が出たら、チームの名前を変えて 3 からやり直す
7. [ ] 3 で表示された名前のとおりに、次から作る

## 3. リソースを作る

作る順番：リソース グループ、ストレージ、AI Search、Cosmos DB、Foundry。

どの画面でも、「サブスクリプション」は 1 で確かめたものを選びます。「リージョン」は、`<場所>` に当たるものを選びます（`japaneast` なら「Japan East」）。

### 3-1. リソース グループ

1. 上の検索ボックスに `リソース グループ` と入れ、「リソース グループ」を選びます。
2. 「作成」を選びます。
3. 「サブスクリプション」を選びます。
4. 「リソース グループ」に `rg-<org>-<team>` と入れます。
5. 「リージョン」を選びます。
6. 「確認および作成（Review + create）」を選び、「作成」を選びます。

確認：

- [ ] リソース グループの一覧に `rg-<org>-<team>` がある。

### 3-2. ストレージ アカウント

1. 検索ボックスに `ストレージ アカウント` と入れ、「ストレージ アカウント」を選びます。
2. 「作成」を選びます。
3. 「サブスクリプション」を選びます。
4. 「リソース グループ」で `rg-<org>-<team>` を選びます。
5. 「ストレージ アカウント名」に `st<org><team>` と入れます。
6. 「リージョン」を選びます。
7. 「パフォーマンス」で「Standard」を選びます。
8. 「冗長性」で「ローカル冗長ストレージ (LRS)」を選びます。
9. ほかの項目は、そのままにします。
10. 「確認および作成（Review + create）」を選び、「作成」を選びます。
11. 完了したら「リソースに移動」を選びます。

- 文書を置く入れ物（コンテナー）は、使う手順で作ります。[ホテル](../hotel.md)は `hotels` を手順で作り、[応用（人事）](../hr.md)の `hr-docs` は取り込みの道具が作ります。

確認：

- [ ] 「概要」で、パフォーマンス（Performance）が「Standard」になっている。
- [ ] 「概要」で、レプリケーション（Replication）が「ローカル冗長ストレージ (LRS)」になっている。
- [ ] 「概要」で、アカウントの種類（Account kind）が「StorageV2」になっている。

### 3-3. AI Search

1. 検索ボックスに `Azure AI Search` と入れ、「Azure AI 検索（Azure AI Search）」を選びます。
2. 「作成」を選びます。
3. 「サブスクリプション」を選びます。
4. 「リソース グループ」で `rg-<org>-<team>` を選びます。
5. 「サービス名（Service name）」に `srch-<org>-<team>` と入れます。
6. 「場所（Location）」を選びます。
7. 「価格レベル（Pricing tier）」の「価格レベルを変更（Change pricing tier）」を選び、「価格レベルの選択」で「Basic」を選びます。
8. 「確認および作成（Review + create）」を選び、「作成」を選びます。
9. 完了したら「リソースに移動」を選びます。
10. 左メニューの「設定」の「セマンティック ランカー」（画面によっては「Premium features」）を開き、「Free」が選ばれていることを確かめます。違えば「Free」を選んで、保存します。

- 種類は「Search Service (Foundry IQ)」と表示されることがあります。
- Basic は、リソースがあるあいだ料金がかかります。料金は [Azure の料金ページ](https://azure.microsoft.com/ja-jp/pricing/details/search/)で確かめます。不要になったら、リソース グループごと削除します（[進行役の手引き](../facilitator.md)の「終わったあと」）。
- セマンティック ランカーの Free には、月ごとの上限があります。チームの AI Search 全体で使います（[基礎編 README](../../basic/README.md)）。

確認：

- [ ] `srch-<org>-<team>` が作られ、価格レベルが「Basic」になっている。
- [ ] 「セマンティック ランカー」が「Free」になっている。

### 3-4. Cosmos DB（NoSQL）

[ホテル](../hotel.md)の 4〜5 章（Cosmos DB のベクトル検索）を行わないときは、作らなくてもかまいません。

1. 検索ボックスに `Azure Cosmos DB` と入れ、「Azure Cosmos DB」を選びます。
2. 「作成」を選び、「Azure Cosmos DB for NoSQL」を選びます。
3. 「サブスクリプション」を選びます。
4. 「リソース グループ」で `rg-<org>-<team>` を選びます。
5. 「アカウント名」に `cosmos-<org>-<team>` と入れます。
6. 「場所」を選びます。
7. 「容量モード（Capacity mode）」で「プロビジョニング済みスループット（Provisioned throughput）」を選びます。
8. ほかの項目は、そのままにします。
9. 「レビュー + 作成（Review + create）」を選び、「作成」を選びます。

- ベクトル検索の機能は、ホテルの 4 章で有効にします。

確認：

- [ ] `cosmos-<org>-<team>` が作られた。

### 3-5. Foundry とプロジェクト

1. 検索ボックスに `Foundry` と入れ、「Foundry」を選びます。
2. 「作成」を選びます。
3. 「サブスクリプション」を選びます。
4. 「リソース グループ」で `rg-<org>-<team>` を選びます。
5. 「名前」に `ai-<org>-<team>` と入れます。
6. 「リージョン」を選びます。
7. プロジェクト名の欄があれば、`proj-default` と入れます。
8. 「確認および作成（Review + create）」を選び、「作成」を選びます。
9. 作成できたら、Foundry のポータル（`https://ai.azure.com`）を開き、「新しいファウンドリー（New Foundry）」のトグルがオンであることを確かめます。
10. プロジェクト `proj-default` があることを確認します。

- プロジェクトがないときは、Foundry のポータルで右上の「管理（Manage）」を選び、左の「リソースの詳細」の「プロジェクトの追加」で `proj-default` を作ります。

確認：

- [ ] `ai-<org>-<team>` とプロジェクト `proj-default` がある。

### 3-6. モデルのデプロイ

1. Foundry のポータルで、プロジェクト `proj-default` を開きます。
2. 右上の「検出（Discover）」を選び、左の「モデル（Models）」を選びます。
3. 埋め込みのモデル `text-embedding-3-small` を選びます。
4. 「デプロイ」の「カスタム設定」を選び、「デプロイの種類」で「グローバル標準（Global Standard）」を選びます。
5. 容量（1 分あたりのトークン数。千単位）を `50` にします。
6. 「デプロイ」を選びます。
7. もう一度「検出」の「モデル」を開き、チャットのモデル `gpt-5-mini` を選びます。
8. 「デプロイ」の「カスタム設定」を選び、「デプロイの種類」で「グローバル標準（Global Standard）」を選びます。
9. 容量を `20` にします。
10. 「デプロイ」を選びます。

- 「標準（Standard）」は、割り当ての枠が足りないことがあるので選びません。
- 埋め込みの容量は 50 以下にします。画面の初期値が 50 より大きいときは、50 に下げます。
- デプロイの画面が見つからないときは、進行役に聞きます。

確認：

- [ ] 右上の「ビルド（Build）」を選び、左の「モデル」の一覧で、`text-embedding-3-small` が「グローバル標準（Global Standard）」、状態が「成功（Succeeded）」になっている。
- [ ] 同じ一覧で、`gpt-5-mini` が「グローバル標準（Global Standard）」、容量 20、状態が「成功」になっている。

### 3-7. 確認

1. リソース グループ `rg-<org>-<team>` を開きます。
2. 「概要」の「リソース」を見ます。
3. PowerShell で、Repo のフォルダーから `python tools/team.py health` を実行します（読み取りだけで、何も変えません）。

確認：

- [ ] 「ストレージ アカウント」の `st<org><team>` がある。
- [ ] 「Search Service (Foundry IQ)」の `srch-<org>-<team>` がある。
- [ ] 「Azure Cosmos DB アカウント」の `cosmos-<org>-<team>` がある（ホテルの 4〜5 章を行うとき）。
- [ ] 「Foundry」の `ai-<org>-<team>` がある。
- [ ] 「Foundry プロジェクト」の `proj-default` がある。
- [ ] `health` の8行がすべて「OK」で、最後の行が `OK 8・まだ 0・NG 0` になっている。

`health` は、次のように表示します（容量などは、作ったとおりに出ます）。

```
チーム red の状態（読み取りだけ）
OK    リソース グループ rg-acme-red（Succeeded）
OK    Storage stacmered（Standard_LRS・StorageV2）
OK    AI Search srch-acme-red（running）
OK    AI Search 価格レベル（Basic）
OK    AI Search セマンティック ランカー（Free）
OK    Foundry ai-acme-red
OK    デプロイ text-embedding-3-small（GlobalStandard・容量50・Succeeded）
OK    デプロイ gpt-5-mini（GlobalStandard・容量20・Succeeded）
インデックスの文書の数（参考。下の OK・まだ・NG には入りません）：
  sengoku        まだない
  hr-docs        まだない
  hotels-blob    まだない
  hotels-cosmos  まだない
OK 8・まだ 0・NG 0
```

- 「OK」はそのままです。「NG」は、かっこの中の理由を読んで直します。「まだ」は、まだ作っていないものです。
- `health` は Cosmos DB を調べません。ポータルで確かめます。
- 「インデックスの文書の数」は参考で、OK・まだ・NG の数には入りません。ここではインデックスをまだ作っていないので、4つとも「まだない」で正しいです。ホテル・武将・人事の手順を進めたあとで実行し直すと、件数が出ます。件数が目安と違うときは、手順を見直してから[評価](../evaluation.md)に進みます。
- 文書の数は、AI Search の検索用のキー（クエリ キー）で数えます。管理者キーは読みません。検索用のキーがないときは、数えない理由が1行出ます（キーの作り方は、4 の「構築する人」の 2）。
- AI Search につながらない（接続の失敗・時間切れ）インデックスが1つあると、残りは問い合わせず「数えられません（つながりません）」と出ます。

## 4. 接続の設定を作る

`.env.local` は、チームの AI Search と Foundry の接続先とキーを書いたファイルです。すべてのスクリプトが、Repo 直下のこのファイルを読みます。キーが入るので、Git には入りません。

Azure に招かれるのは構築する人だけです。構築する人が、自分の `.env.local` と、メンバー用のファイル（`member.local.env`）を作ります。

### 構築する人

1. [ ] Repo 直下で、自分の `.env.local` を作る：`python tools/team.py env --team <team> --role builder`（`$env:WORKSHOP_TEAM` を設定してあれば `--team` は省けます）
   - AI Search の管理者キーと、Storage の接続文字列が入ります。この `.env.local` は、だれにも渡しません
   - Storage を作ってから実行します（接続文字列を読むため）
2. [ ] メンバーがいるとき：AI Search に、検索用のキー（クエリ キー）があることを確かめる
   - `srch-<org>-<team>` の「設定」の「キー」を開き、「クエリ キーの管理」にキーが1つ以上ある
   - ないとき：「追加」で作る
3. [ ] メンバー用のファイルを作る：`python tools/team.py env --team <team> --role member --out member.local.env`
   - 検索だけのキーが入ります。Storage の接続文字列は入りません
4. [ ] `member.local.env` を、チームの中だけで、メンバーに渡す（チームの外には渡しません）
5. [ ] つながることを確かめる：[武将](../sengoku.md)の 01 のフォルダー（`basic/topics/01-keyword-search`）で、`python create_index.py` を実行し、エラーが出ない

### メンバー

1. [ ] 構築する人から受け取った `member.local.env` を、Repo 直下に `.env.local` という名前で置く
2. [ ] つながることを確かめる：構築する人が[武将](../sengoku.md)の 01 の `upload.py` まで終えたあとで、`basic/topics/01-keyword-search` フォルダーで `python keyword_search.py` を実行し、エラーが出ない

### 古くなったとき

キーを作り直したときや、AI Search・Foundry を作り直したときは、構築する人が `team.py env` をもう一度実行します（自分の `.env.local` と、メンバー用の `member.local.env`）。メンバーには、作り直した `member.local.env` を渡します。

## 5. 補助：az で作る

画面で作れないときや、作ったものを確かめるときに使います。PowerShell で実行します。名前は、組織の名前（`workshop.config` の `WORKSHOP_ORG`）と、チームの名前（環境変数 `WORKSHOP_TEAM`）から組み立てます。

サインインと、名前の変数（PowerShell を開き直したら、もう一度）：

```powershell
az login --tenant <テナント>
az account set --subscription <サブスクリプション ID>
az account show --query name -o tsv
$org = "<org>"
$loc = "<場所>"
$t = $env:WORKSHOP_TEAM
$rg = "rg-$org-$t"   # 既存のリソース グループに作るときは、その名前（workshop.config の AZURE_RESOURCE_GROUP）
```

リソース グループと Storage：

```powershell
az group create -n $rg -l $loc
az storage account create -n "st$org$t" -g $rg -l $loc --sku Standard_LRS --kind StorageV2
```

AI Search（Basic、マネージド ID あり、セマンティック ランカー Free）：

```powershell
az search service create -n "srch-$org-$t" -g $rg -l $loc --sku basic --identity-type SystemAssigned --semantic-search free
```

Cosmos DB（NoSQL、ベクトル検索を有効に）：

```powershell
az cosmosdb create -n "cosmos-$org-$t" -g $rg --locations regionName=$loc --capabilities EnableNoSQLVectorSearch
```

Foundry：リソースとプロジェクトは画面で作ります（az では作れない部分があります）。モデルのデプロイは az でもできます。

```powershell
az cognitiveservices account deployment create -n "ai-$org-$t" -g $rg --deployment-name text-embedding-3-small --model-name text-embedding-3-small --model-version 1 --model-format OpenAI --sku-name GlobalStandard --sku-capacity 50
az cognitiveservices account deployment create -n "ai-$org-$t" -g $rg --deployment-name gpt-5-mini --model-name gpt-5-mini --model-version 2025-08-07 --model-format OpenAI --sku-name GlobalStandard --sku-capacity 20
```

メンバーに渡す検索用のキー（クエリ キー）を作る：

```powershell
az search query-key create --service-name "srch-$org-$t" -g $rg -n member
```

確かめる：

```powershell
az resource list -g $rg --query "[].{name:name,type:type}" -o table
python tools/team.py health
```

## 6. つまずいたとき

- 「ほかで使われている」と出る：チームの名前を変えて、2 からやり直します。
- `team.py` が「サブスクリプションが見えません」と出る：サインインしていないか、`workshop.config` の `AZURE_SUBSCRIPTION_ID` が違います。`az login --tenant <テナント>` を実行して、値を確かめます。
- モデルのデプロイで、枠が足りない：「グローバル標準（Global Standard）」を選んでいるか確かめます。容量を、決めた値以下にします。それでも足りないときは、進行役に伝えます。
- ポータルの画面の読み込みが遅い：待ち続けず、ページを読み込み直します。
- `health` に「NG」が出る：かっこの中の理由を読みます。「価格レベル」が Basic でなければ作り直し、「セマンティック ランカー」が Free でなければ 3-3 の 10 をやり直します。

## 次の手順

- [ホテル](../hotel.md)：Azure AI Search を、画面で作って試す
- [武将](../sengoku.md)：基礎編
- [応用（人事）](../hr.md)：応用編
