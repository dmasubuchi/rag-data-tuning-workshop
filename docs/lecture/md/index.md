# 検索と RAG の仕組み

<!-- この Markdown は docs/lecture/tools/build.py --md が、keywords.md・decks.json・diagrams/ から作る。直すときは原稿を直す -->

スライドで仕組みを学び、スクリプトと Notebook で検索の振る舞いを確かめる

各ページの「確かめる」は、そのページのトピックの README へのリンクです。図は `img/` の SVG ファイルです。同じ原稿から作った HTML のスライドは `site/lecture/` にあります。

- [はじめに：研修の進め方](intro.md)：チームの役割、clone から動かすまで、スクリプトと Notebook、部とトピックの対応
- [第1部 検索方法](part1-search.md)：キーワード検索、ベクトル検索、ハイブリッド、ランカーと、その中の仕組み
- [第2部 取り込み](part2-ingestion.md)：読む、ばらす、切る、出典、索引の順番と、Azure の取り込みの仕組み
- [第3部 関係とエージェント型検索](part3-relations-agentic.md)：文書どうしの関係をたどる検索と、質問を分解して何度も検索するエージェント型検索
- [評価](part4-evaluation.md)：検索の評価と回答の評価を分けて測る
- [比較と締め](part5-wrapup.md)：作り方の比較、RAG の流れと出典、うまくいかない場面、プレビューと料金
