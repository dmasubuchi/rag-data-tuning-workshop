# 手順書

研修を進めるための手順書です。仕組みの説明は[ハンズオン資料](../docs/lecture/md/index.md)（スライド）、トピックごとの手順は[基礎編](../basic/README.md)と[応用編](../applied/README.md)の README にあります。

## 呼び方

- 進行役：研修を進める人。組織の設定の値を渡し、Azure の権限を付ける
- 参加者：研修に出る人。チームで進める
- 構築する人：チームで1人。Azure のリソースを作り、データを入れる。`.env.local` は `--role builder` で作る
- メンバー：チームのほかの人。検索と読み取りをする。`.env.local` は `--role member` で作る

## 順番

1. [Windows PC の設定](setup/windows-pc.md)：Git・Python・az・VS Code を確かめる
2. [Azure の準備](setup/azure-setup.md)：チームの名前を決め、ポータルでリソースを作り、接続の設定 `.env.local` を作る
3. [ホテル](hotel.md)：ホテルのデータで、Azure AI Search をポータルで作って試す。Cosmos DB のベクトル検索も
4. [武将](sengoku.md)：基礎編（01〜06）。キーワード検索からベクトル検索、ハイブリッド、答えの生成まで
5. [応用（人事）](hr.md)：応用編（14〜20）と採用アシスタント。採用の文書で、業務の検索を見る
6. [検索デモ](search-demo.md)：条件を変えると結果が変わるのを、AI Search だけで見る
7. [進行役の手引き](facilitator.md)：開始前の準備、パートの順、各パートで見せるもの、つまずきやすい所

## 道具

- `python tools/team.py names`：チームの名前から、リソースの名前を表示する
- `python tools/team.py check-names`：作る前に、名前が使えるかを確かめる（何も作らない）
- `python tools/team.py health`：作ったものの状態を見る（読み取りだけ）
- `python tools/team.py env --role builder`（メンバーは `--role member`）：接続の設定 `.env.local` を作る
- `python tools/search_demo.py`：条件を変えると結果が変わるのを見る（[検索デモ](search-demo.md)）
- `python tools/hotel_vectors.py`：ホテルのデータにベクトルを足す（[ホテル](hotel.md)の 4 章）
