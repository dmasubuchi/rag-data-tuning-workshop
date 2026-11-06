# はじめに：研修の進め方

<!-- この Markdown は docs/lecture/tools/build.py --md が、keywords.md・decks.json・diagrams/ から作る。直すときは原稿を直す -->

チームの役割、clone から動かすまで、スクリプトと Notebook、部とトピックの対応

[目次に戻る](index.md)

## A　進め方

### スライドで仕組み、手元で振る舞いを確かめる

1. スライド：手法、Azure のリソース、検索の考え方を説明する
2. トピック：同じ仕組みを、スクリプトか Notebook で動かす
   - 検索の結果や順位は、スライドではなく手元で見る
3. 各ページの下の「確かめる」が、そのページのトピック
   - 例：確かめる　基礎 05 検索の良し悪しを数字で測る

<details>
<summary>ノート</summary>

言いたいこと：スライドは仕組みの説明に集中し、コードの結果と検索の振る舞いはトピックのスクリプトと Notebook で確かめる。

- スライドの各ページの下に「確かめる」の欄があり、対応するトピックのフォルダを示す。
- 結果の読み方は、Notebook のセルの間の説明に書いてある。

</details>

### RAG は、探してから答える仕組み

**準備**

**文書** →（切る）→ **チャンク** →（ベクトルにする）→ **埋め込み** →（入れる）→ **インデックス**

- **文書**：PDF や Word など
- **チャンク**：検索の単位に切った断片
- **埋め込み**：意味を数の並び（ベクトル）にしたもの
- **インデックス**：探せるように整理して置いた場所

**質問のとき**

**質問** → **検索** →（チャンクを渡す）→ **LLM** → **答え**

- **質問**：利用者が聞いたこと
- **検索**：近いチャンクをインデックスから探す
- **LLM**：大規模言語モデル。チャンクを読んで文章で答える
- **答え**：出典つきで返す

> 第1部：検索　／　第2部：準備（取り込み）　／　評価：検索と答えの良し悪し

<details>
<summary>ノート</summary>

言いたいこと：RAG は、先に文書をチャンクに切り、ベクトルにしてインデックスに入れておく。質問のときは、近いチャンクを探して LLM に渡し、文章で答えさせる。

- インデックス：検索できるように整理して置いた、チャンクの集まり。本の巻末の索引のようなもの。
- チャンク：文書を検索の単位に切った断片。大きすぎると答えがぼやけ、小さすぎると文脈が消える。
- 埋め込み：文を、意味が近いほど近くなる数の並び（ベクトル）にしたもの。ベクトル検索で使う。
- LLM：大規模言語モデル。渡されたチャンクを読んで、文章で答える。渡した文以外の知識も混ざることがある。
- このハンズオン資料は、検索（第1部）から入り、準備（第2部）、評価と進む。最後の p.48 で、この図に戻る。

</details>

### チームは、構築する人とメンバーで進める

#### 構築する人

- AI Search の管理者キーを使う
- インデックスと同義語マップを作り、データを入れる
- `--role builder` で、自分の .env.local を作る

#### メンバー

- 検索だけのキーを使う
- 構築する人が作ったインデックスを、検索して読む
- 構築する人から、member.local.env を受け取る

> チームごとに AI Search と Foundry を持つ。役ごとに、できることが決まっている

<details>
<summary>ノート</summary>

言いたいこと：チームは自分たちの AI Search と Foundry を持ち、構築する人とメンバーに役を分けて進める。

- 構築する人：AI Search の管理者キーで、インデックスと同義語マップを作り、データを登録する（基礎 01 の create_index.py・upload.py、03 の embed.py など）。
- メンバー：検索だけのキーで、構築する人が作ったインデックスを検索して、結果を読む。設定のファイルは、構築する人が `--role member --out member.local.env` で作って、チームの中だけで渡す。メンバーは、Repo の直下に .env.local という名前で置く。
- メンバーの設定で、作る・変える手順を実行すると、不透明なエラーになる前に「この手順は構築する人の設定で実行します」と止まる。その手順は、構築する人に実行してもらう。

</details>

## B　動かす準備

### clone して、.env.local を作れば動く

1. **Repo を clone する**：研修の Repo
   - `git clone <Repo の URL>`
2. **ライブラリを入れる**：基礎編のフォルダの requirements.txt
   - `pip install -r basic/requirements.txt`
3. **接続の設定 .env.local を作る**：構築する人が作る。メンバーは member.local.env を置く
   - `python tools/team.py env --team <チーム> --role builder`
4. **トピックのフォルダで実行する**：例：基礎 01 キーワード検索
   - `python load.py`

<details>
<summary>ノート</summary>

言いたいこと：接続先やキーをコピーしたり書き換えたりする手順はない。clone して、ライブラリを入れて、team.py で .env.local を作れば動く。

- チームの名前は、--team か環境変数 WORKSHOP_TEAM で渡す。
- メンバー用のファイルは、構築する人が `--role member --out member.local.env` で作って渡す。メンバーは、Repo の直下に .env.local という名前で置く。構築する人の .env.local は、だれにも渡さない。
- スクリプトはトピックのフォルダで実行する。

注意：Windows では python が見つからないとき py に置き換える。

</details>

### 接続の設定は .env.local の1つだけ

#### 入っているもの

- AI Search の接続先とキー（構築する人は管理者キー、メンバーは検索だけのキー）
- Azure OpenAI（Foundry）の接続先とキーと、モデルの名前
- Storage の接続先（構築する人だけ。応用編で使う）

#### 気をつけること

- キーが入る。構築する人の .env.local は、だれにも渡さない（Git にも入らない）
- 端末の環境変数 `AZURE_*` ではなく、このファイルを読む
- 古くなったら、構築する人が `team.py env` で作り直し、member.local.env を渡し直す

> 全部のスクリプトと Notebook が、Repo の直下の .env.local を読む

<details>
<summary>ノート</summary>

言いたいこと：接続先とキーは Repo の直下の .env.local にまとめてあり、全部のスクリプトがここから読む。

- キーが入るので、Repo の外に写さない。構築する人の .env.local は、だれにも渡さない。Git にも入らない。
- メンバーには、構築する人が作った member.local.env を、チームの中だけで渡す。
- 端末に別の Azure の設定が残っていても、.env.local の値を使う。
- メンバーの .env.local には、AI Search の管理者キーと Storage の接続文字列は入らない。
- キーが古くなったときは、構築する人が team.py env で作り直し、member.local.env を渡し直す。

</details>

### スクリプトと Notebook は同じ中身

#### スクリプト

- python xxx.py で、上から順に動く
- 質問は --q "…" で変える
- 何度もやり直すのに向く

#### Notebook

- 1セルずつ動かして、結果を見る
- 質問はファイルの先頭の変数で変える
- セルの間に「どこを見るか」の説明

> スクリプトが正本。Notebook はスクリプトから作る

<details>
<summary>ノート</summary>

言いたいこと：スクリプトと Notebook は同じ処理で、どちらで動かしてもよい。

- スクリプトは引数で、Notebook は先頭の変数で質問を変える。引数があれば引数が優先する。
- Notebook はスクリプトから作るので、中身がずれない。

</details>

### 前のトピックの状態がなければ、止まって案内する

1. 各トピックの最初に、必要なインデックスがあるかを確かめる
2. なければ、先に動かすものを1行出して止まる
   - 思いがけない作り直しを防ぐ
3. 作り直すときは、reset のコマンドで状態をそろえる
   - 例：python basic/tools/reset.py --to 04（構築する人の設定で実行）

<details>
<summary>ノート</summary>

言いたいこと：トピックはどの順で動かしてもよいが、前提のインデックスがないときは止まって案内する。

- 案内に出たコマンドを、そのまま貼って実行すればよい。
- reset は、そのトピックを始める直前の状態を作り直す。埋め込み済みのファイルを使うので早い。
- メンバーの設定では、構築する人に実行してもらう。

</details>

### インデックスの名前は決まっていて、作るのは構築する人

| 担当 | 名前 | 使うトピック |
|---|---|---|
| 構築する人 | `sengoku`（インデックス） | 基礎 01〜06（武将） |
| 構築する人 | `sengoku-synonyms`（同義語マップ） | 基礎 02 |
| 構築する人 | `hr-docs`（インデックス） | 応用 14〜20（採用） |
| 構築する人 | `hr-docs-ds`・`hr-docs-ss`・`hr-docs-ixr` | 応用 15（データソース・スキルセット・インデクサー） |
| 構築する人 | `hr-docs-ks`・`hr-docs-kb` | 応用 19・20（知識ソース・知識ベース） |

<details>
<summary>ノート</summary>

言いたいこと：チームの AI Search に、インデックスなどが決まった名前で入る。名前が決まっているので、スクリプトは接続先だけで動く。

- 作るのは構築する人。武将は基礎 01〜03 のスクリプト、採用は applied/tools の build_hr_index.py と build_hr_kb.py。
- メンバーは、できあがったものを検索して読む。
- AI Search の Basic では、同義語マップはサービス全体で3つまで。ここで作るのは sengoku-synonyms の1つだけ。

</details>

### 使うデータは2つ

| データ | 中身 | トピック |
|---|---|---|
| 武将 | 戦国武将など150人の名前・別名・合戦・プロフィール、正解つきの質問60問 | 基礎 01〜06 |
| 採用 | 架空の会社の求人票・職務経歴書・面接の評価・メール・スキャン 23件 | 応用 14〜20 |

<details>
<summary>ノート</summary>

言いたいこと：基礎編は武将、応用編は採用のデータを使う。どちらも研修用に作ったデータで、採用は架空の会社の文書。

- 武将は、言い換えや固有名詞で検索方式の違いを見るのに使う。
- 採用は、形式の違う文書（PDF・Word・Excel・メール・スキャン）で、業務の場面を体験する。

</details>

## C　トピックの地図

### 基礎編：武将で検索の方式を学ぶ

| 番号 | トピック | データ | フォルダ |
|---|---|---|---|
| 基礎 01 | キーワード検索 | 武将 | [`basic/topics/01-keyword-search`](../../../basic/topics/01-keyword-search/README.md) |
| 基礎 02 | 言い換えと日本語の分かれ方 | 武将 | [`basic/topics/02-analyzers-synonyms`](../../../basic/topics/02-analyzers-synonyms/README.md) |
| 基礎 03 | ベクトル検索 | 武将 | [`basic/topics/03-vector-search`](../../../basic/topics/03-vector-search/README.md) |
| 基礎 04 | ハイブリッドとランカー | 武将 | [`basic/topics/04-hybrid-ranker`](../../../basic/topics/04-hybrid-ranker/README.md) |
| 基礎 05 | 検索の良し悪しを数字で測る | 武将 | [`basic/topics/05-measure-search`](../../../basic/topics/05-measure-search/README.md) |
| 基礎 06 | 検索結果から答えを作る | 武将 | [`basic/topics/06-answer-from-results`](../../../basic/topics/06-answer-from-results/README.md) |

<details>
<summary>ノート</summary>

トピックの一覧（基礎編）。番号はデータと前提の順で、この順なら必ず動く。各ページの「確かめる」のトピックを開く。

</details>

### 応用編：採用の文書で業務の場面を体験する

| 番号 | トピック | データ | フォルダ |
|---|---|---|---|
| 応用 14 | 種類の違う文書をまとめて取り込む | 採用 | [`applied/topics/14-mixed-documents`](../../../applied/topics/14-mixed-documents/README.md) |
| 応用 15 | Azure の仕組みに置き換える | 採用 | [`applied/topics/15-azure-indexer`](../../../applied/topics/15-azure-indexer/README.md) |
| 応用 16 | 見せてよい人で絞る | 採用 | [`applied/topics/16-security-filter`](../../../applied/topics/16-security-filter/README.md) |
| 応用 17 | 更新と削除 | 採用 | [`applied/topics/17-update-delete`](../../../applied/topics/17-update-delete/README.md) |
| 応用 18 | 関係で探す（紹介） | 採用 | [`applied/topics/18-relations`](../../../applied/topics/18-relations/README.md) |
| 応用 19 | エージェント型検索のデモ | 採用 | [`applied/topics/19-agentic-retrieval`](../../../applied/topics/19-agentic-retrieval/README.md) |
| 応用 20 | 答えを評価する | 採用 | [`applied/topics/20-answer-evaluation`](../../../applied/topics/20-answer-evaluation/README.md) |

07〜13 はこの Repo には入っていないので、応用編は 14 から始まる。フォルダ名や案内のコマンドに出る番号も、この数字のまま。

<details>
<summary>ノート</summary>

トピックの一覧（応用編）。応用編の番号は 14 から始まる（07〜13 はこの Repo にはない）。前提は、基礎編の検索と、構築する人が作った hr-docs。

</details>

### 部とトピックの対応

| 部 | ページ | 確かめるトピック |
|---|---|---|
| 第1部 検索方法 | p.1〜15 | 01・02・03・04 |
| 第2部 取り込み | p.16〜30 | 14・15・16・17 |
| 第3部 関係とエージェント型検索 | p.31〜38 | 18・19 |
| 評価 | p.39〜45 | 05・20 |
| 比較と締め | p.46〜52 | 06・19 |

<details>
<summary>ノート</summary>

進行は部の順。各部のページから、右の列のトピックを開いて振る舞いを確かめる。部の順とトピックの番号は別。

</details>

### 進め方のまとめ

- 部の順に進め、トピックで振る舞いを確かめる
- トピックの番号は、データと前提の順（この順なら必ず動く）
- 構築する人が作り、メンバーが検索して確かめる

<details>
<summary>ノート</summary>

言いたいこと：部の順とトピックの番号は別。番号はデータと前提の順で、どの順で来ても、前提がなければ止まって案内する。

</details>
