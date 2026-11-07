# 検索の評価で使う質問

検索の方式を比べるための質問と、正解の文書の番号です。3つのデータ（武将・人事・ホテル）が、同じ形の質問を使います。質問の中身を足す・直すのは進行役か構築する人です。メンバーは、できあがった質問を読んで評価を動かすだけです。

## ファイル

- 武将：`basic/data/sengoku/questions.json`（既存の60問。直さない）
- 人事：`evaluation/hr_questions.json`（60問）
- ホテル：`evaluation/hotel_questions.json`（40問）

どれも質問の並び（JSON の配列）です。人事のファイルはできています。ホテルのファイルは、評価の準備の中で足します。

人事の60問は、種類をまぜて並べてあります（`hr-01` から順に、6問で6つの種類が1回ずつ）。先頭から何問かだけ取っても、種類がかたよりません。

## 1問の形

```json
{
  "qid": "hr-01",
  "question": "REQ-042 の今の求人票で、年収はいくらからいくらまでですか。",
  "type": "numeric",
  "answer_ids": ["JOB-REQ042-v3"],
  "why": "年収は JOB-REQ042-v3 の本文にある。"
}
```

（見本です。）

必ず書くもの：

- `qid`：質問の番号。ファイルの中で1つだけ。`hr-01` のように、データの名前と連番にします（空白は入れません）
- `question`：検索に使う質問の文
- `type`：質問の種類（下の「種類」）
- `answer_ids`：取ってくるべき文書の ID の並び。文書の ID は、武将は `bushou.json` の `id`、人事は `applied/data/manifest.json` の `files[].doc_id`、ホテルはホテルのデータの `HotelId`（文字列）。**空（`[]`）でよいのは `permission` だけ**です。答えの文書が1件もない質問で、`permission` の説明を見てください。ほかの種類で空だと、確かめの道具が問題にします

必要なときだけ書くもの：

- `why`：どの文書のどこに答えがあり、どの方式が得意・不得意になりそうか
- `note`：作る人のメモ
- `as_role`：だれとして聞くか（例 `"role:employee"`）。`permission` の質問に要ります
- `hidden_ids`：その人には見えてはいけない文書の ID の並び。`permission` の質問に要ります（1件以上）
- `condition`：ホテルの `condition` の質問で、答えの条件を表したもの。形はホテルの質問を作るときに決めます

ほかの項目（武将の `query_terms`・`avoid_terms`・`clues` など）があっても構いません。評価は読み飛ばします。

武将の既存の60問は、種類を `type` でなく `intent` と書いています。直さずに、`intent` を `type` として読みます（`load_questions` が読み替えます）。

## 種類

武将（既存の `intent`。数は確かめません）：

- `keyword-wins`：キーワード検索が上に出し、ベクトル検索は外す見込みの質問
- `vector-wins`：ベクトル検索が上に出し、キーワード検索は外す見込みの質問
- `hybrid-improves`：キーワードとベクトルを合わせる（ハイブリッド）と、どちらか一方より良くなる質問
- `hybrid-worsens`：ハイブリッドにすると、片方だけが1位にしていた正解が落ちる質問
- `climax`：キーワードもベクトルも正解を外し、セマンティック ランカー（意味での並べ直し）で上がる見込みの質問

人事（60問）：

- `paraphrase` 12：文書に出てこない言い換えの語で聞く
- `proper-noun` 10：応募番号・求人番号・人名・社名で聞く
- `numeric` 10：年収・日付・点数の条件で聞く
- `multi-doc` 10：答えが2つ以上の文書にまたがる
- `scan` 6：画像だけのスキャン（OCR が要る）に答えがある
- `permission` 12：聞く人に見せてはいけない文書がある（下の説明）

ホテル（40問）：

- `paraphrase` 10：文書に出てこない言い換えの語で聞く
- `proper-noun` 6：ホテル名・地名などの固有名詞で聞く
- `condition` 10：評価・駐車場・部屋の料金などの条件で絞る
- `ja-en` 6：日本語で聞いて英語の項目にしか答えがない（またはその逆）
- `amenity` 8：設備（`Tags`・`Tags_ja`・部屋の説明）で聞く

人事とホテルは、種類ごとの数が上の数と同じでなければ、確かめの道具が問題にします。文書が足りない種類は、数を減らして報告します。

### 種類の目標を変えるとき

文書が足りずに数を減らす（ほかの種類に回して合計を保つ）ときは、次の4か所をそろえます。

1. `tools/evallib/questions.py` の `TYPE_TARGETS`
2. この README の「種類」の数
3. `tests/test_questions.py` の `test_targets_match_the_brief`（人事は `HrQuestionsTest.test_hr_questions_pass` の数も）
4. 質問のファイル（新しい数に合わせて、質問を足す・直す）

そろえたら、下の「質問を確かめる」を実行します。

### 人事の決まり

人事は、種類ごとの決まりがあり、確かめの道具が見ます。

- 正解の文書の ID は、`applied/data/manifest.json` の23件。旧い版の求人票（`JOB-REQ042-v1`）は索引に入らないので、正解にしません
- 質問が文書の種類を限っている（「経歴書に」「メールで」「求人は」）ときは、その種類の文書だけを正解にします。同じことが評価一覧や面接メモにも書いてあっても、入れません
- `multi-doc`：`answer_ids` は2件以上で、どれか1件だけでは答えきれないこと
- `scan`：`answer_ids` に、OCR が要る文書（manifest の `ocr_required` が true。`SCAN-01`〜`SCAN-03`）を含むこと。スキャンにしか書いていないことを聞きます
- `permission`：次の節

## permission（見えてはいけない文書）

「一般社員として聞いたとき、求人票以外は出てこない」ことを確かめる質問です。

- `as_role` に聞く人の役割、`hidden_ids` にその人には見えてはいけない文書を書きます
- `answer_ids` は、その人に見える正解（なければ空）。`hidden_ids` と同じ ID は入れません
- 空の質問は、再現率の平均に入れません。`hidden_ids` の文書が結果に出た数（漏れ）を、別に数えます
- 人事では、`as_role` は `role:employee`（一般社員）だけを使います。一般社員に見えるのは求人票だけです（`applied/lib/acl.py`）
  - `hidden_ids`：求人票でない文書。その質問の答えが書いてある文書を入れます（求人票は見えるので入れません）
  - `answer_ids`：求人票だけ。求人票で答えられる部分がある質問は、その求人票を入れます。なければ空です

## 質問を確かめる

質問を足したり直したりしたら、Repo 直下で次を実行します。通信はしません。

```
python tools/check_questions.py --dataset sengoku
python tools/check_questions.py --dataset hr
python tools/check_questions.py --dataset hotel --hotel-data <ホテルのデータの JSON>
```

- 問題がなければ「問題なし（N 問）」と出して、終了コード 0 で終わります
- 問題があれば、1件ずつ出して終了コード 1 で終わります。次を見ます
  - 項目の形：`qid`・`question`・`type` は文字列、`answer_ids`・`hidden_ids` は ID の並び
  - qid の重複、使えない種類、文書にない ID
  - `answer_ids` と `hidden_ids` の重なり（同じ ID が両方にあってはいけません）
  - `answer_ids` が空の質問（`permission` 以外）
  - `permission` の `as_role` と `hidden_ids` の抜け
  - 種類ごとの数の違い
  - 人事は、上の「人事の決まり」（`permission`・`scan`・`multi-doc`）
- 質問やデータのファイルが読めないときは、理由を出して終了コード 2 で終わります。質問のファイルがないときは、次の手（`--file` で渡すか、質問を作ります）も出します
- `--file PATH` で質問のファイルを変えられます
- ホテルのデータは、このリポジトリに写していません。ダウンロードした `HotelsData_toAzureBlobs_ja.json` を `_work/hotel-vectors/` に置くか、`--hotel-data` で場所を渡します
