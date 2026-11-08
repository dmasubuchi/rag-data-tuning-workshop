# 出どころとライセンスの注意

武将と人事のデータは、この Repo のために作ったもので、CC BY 4.0（`LICENSE-docs.md`）です。

## ホテルのデータ

研修で使うホテルのデータは、Microsoft の公式サンプルのデータ（Azure-Samples/azure-search-sample-data の hotels）を元にしています。
元のデータのライセンスは CDLA-Permissive 2.0（Community Data License Agreement - Permissive, Version 2.0）です。

- 元のデータ：<https://github.com/Azure-Samples/azure-search-sample-data>
- ライセンス：<https://cdla.dev/permissive-2-0/>

日本語を足した派生データは、この Repo ではなく別の Repo にあり、元の CDLA-Permissive 2.0 を引き継ぎます。
この Repo はそのデータを写して持たず、別の Repo を参照して使います。

## 武将のデータ

`basic/data/sengoku/` の武将のデータは、この研修のために作った説明用のデータです。戦国・三国志・幕末の人物 150 人の、一般に知られている事柄の要約と、質問 60 問です。

## 人事のデータ

`applied/data/` の人事のデータは、この研修のために作った架空のデータです。人物・会社・求人・メールは、すべて架空です。メールのアドレスには、予約済みのドメイン（`.example`）だけを使っています。

## スライドの操作（player.js）

`docs/lecture/player.js` と `site/lecture/player.js` は、slideplay 0.1.0 の `player/player.js` の写しです。

- 元：slideplay（<https://github.com/dmasubuchi/slideplay>、MIT License、Copyright (c) 2026 dmasubuchi）

## Mermaid

読む形のページ（`site/pages/`）の図は、ページを開いたブラウザが Mermaid（MIT License）を CDN（jsDelivr）から読んで描きます。この Repo は Mermaid を配りません。
