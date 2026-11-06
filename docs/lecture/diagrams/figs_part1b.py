"""第1部（検索方法）の図、p.9〜p.15。@fig(ページ番号) を付けた関数が、題・キャプション・SVG・ノートを返す。
描き方の決まりは docs/lecture/README.md の「図の描き方の決まり」。部品は tools/svgparts.py だけを使う。
"""
import math

from _reg import fig
from svgparts import (B, BLUE, GRAY, GREEN, H, INK, LINE, ORANGE, S, SOFT, arrow, box, doc, index_box, lines,  # noqa: F401
                      person, shelf, step, svg, text)


def _dot(x, y, color=GRAY, r=16) -> str:
    return f"<circle cx='{x}' cy='{y}' r='{r}' fill='{color}'/>"


def _ring(x, y, color, r=29, dash=False) -> str:
    d = " stroke-dasharray='10 8'" if dash else ""
    return f"<circle cx='{x}' cy='{y}' r='{r}' fill='none' stroke='{color}' stroke-width='6'{d}/>"


def _line(x1, y1, x2, y2, color=GRAY, width=3, dash=False) -> str:
    d = " stroke-dasharray='9 8'" if dash else ""
    return f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' stroke-width='{width}'{d}/>"


# ---------------------------------------------------------------- p.9 HNSW と全件検索
@fig(9)
def p09():
    # 左：全件検索（文書のベクトル 8 個を 4×2 に並べる）
    cols, rows = [260, 400, 540, 680], [230, 330]
    left = [(x, y) for y in rows for x in cols]
    pill = lambda x, y: box(x, y, 110, 46, stroke=BLUE, fill=BLUE) + text(x + 55, y + 33, "質問", S, "#fff", True)
    # 右：HNSW（下の層は 8 個。上へ行くほど少ない）
    bx = [1150 + 55 * i for i in range(8)]
    by = [356, 366, 348, 366, 348, 366, 350, 364]
    mid = {1: 1205, 3: 1315, 5: 1425, 7: 1535}
    top = {3: 1315, 7: 1535}
    ytop, ymid = 200, 278
    band = lambda y: box(880, y - 32, 680, 64, stroke=LINE, fill=SOFT, width=3)
    links = "".join(
        [_line(bx[i], by[i], bx[i + 1], by[i + 1]) for i in (0, 1, 2, 3, 4)] + [_line(bx[6], by[6], bx[7], by[7])]
        + [_line(1205, ymid, 1315, ymid), _line(1315, ymid, 1425, ymid), _line(1425, ymid, 1535, ymid), _line(1315, ytop, 1535, ytop)]
        + [_line(x, ytop, x, by[i], dash=True) for i, x in top.items()]
        + [_line(x, ymid, x, by[i], dash=True) for i, x in mid.items() if i not in top]
    )
    nodes = ("".join(_dot(bx[i], by[i]) for i in range(8)) + "".join(_dot(x, ymid) for x in mid.values())
             + "".join(_dot(x, ytop) for x in top.values()))
    body = svg(
        1600, 610,
        text(400, 44, "全件検索（厳密な KNN）", H, GRAY, True), text(400, 84, "質問とすべての文書を比べる", S, GRAY),
        text(1220, 44, "HNSW（近似）", H, BLUE, True), text(1220, 84, "つながりをたどって、近い所だけ比べる", S, GRAY),
        pill(60, 106), "".join(_dot(x, y) for x, y in left),
        pill(1260, 106),
        band(ytop), band(ymid), band(358),
        text(900, ytop + 9, "上の層（粗い）", S, GRAY, anchor="start"),
        text(900, ymid + 9, "中の層", S, GRAY, anchor="start"),
        text(900, 358 + 9, "下の層（細かい）", S, GRAY, anchor="start"),
        links, nodes,
        step(1, arrow([(115, 154), (115, 230), (680, 230), (680, 330), (282, 330)], BLUE),
             "".join(_dot(x, y, BLUE, 12) for x, y in left),
             text(400, 500, "① すべての文書と、1つずつ比べる", 28, BLUE, True),
             text(400, 538, "必ず見つかるが、件数が増えるほど遅い", S, GRAY)),
        step(2, arrow([(1315, 154), (1315, ytop), (1535, ytop), (1535, ymid), (1425, ymid), (1425, by[5] - 20)], BLUE),
             "".join(_dot(x, y, BLUE, 12) for x, y in [(1315, ytop), (1535, ytop), (1535, ymid), (1425, ymid), (bx[5], by[5])]),
             text(1220, 500, "② 上の層から下の層へ、つながりをたどる", 28, BLUE, True),
             text(1220, 538, "比べる点が少ないので、速い", S, GRAY)),
        step(3, _ring(540, 330, GREEN), text(540, 392, "一番近い点", S, GREEN, True),
             _ring(bx[5], by[5], GREEN), text(bx[5] - 12, 426, "見つけた点", S, GREEN, True),
             _ring(bx[6], by[6], ORANGE, dash=True), text(1566, 458, "本当に一番近い点", S, ORANGE, True, "end"),
             text(800, 592, "③ HNSW は速いが、本当に一番近い点を取りこぼすことがある", 28, ORANGE, True)),
    )
    return {
        "title": "HNSW は==近道で速く==探し、全件検索は==全部比べて==確かに探す",
        "caption": "HNSW は速いが取りこぼしがあり得る。全件検索は必ず見つかるが、件数が増えるほど遅くなる。点と網は説明用の例",
        "svg": body,
        "notes": "狙い：近いベクトルの探し方が2つあり、HNSW は速いが取りこぼしがあり得て、全件検索は遅いが必ず見つかる、と言える。\n"
                 "話すこと：\n"
                 "・段階0：左が全件検索（厳密な KNN）、右が HNSW（近似）。点は文書のベクトル（8個）。質問のベクトルに近いものを探す\n"
                 "・段階1：全件検索は、質問のベクトルをすべての文書のベクトルと1つずつ比べる。必ず一番近いものが見つかるが、"
                 "文書が増えるほど時間がかかる。件数が少ないときや、近似の結果と比べる基準を作るときに使う\n"
                 "・段階2：HNSW は、近いものどうしをつないだ網を、何層かに分けて作っておく。上の粗い層から下の細かい層へ、"
                 "つながりをたどって近いものを探す。比べる点が少ないので速い\n"
                 "・段階3：緑の輪が見つけた点。全件検索は一番近い点を必ず見つける。HNSW は、橙の点線の輪のように、"
                 "本当に一番近いものを取りこぼすことがある\n"
                 "補足：Azure AI Search では、アルゴリズムの設定で hnsw か exhaustiveKnn を選び、プロファイルでフィールドに結び付ける。"
                 "hnsw の調整は m（1つの点から何本つなぐか。既定は 4）、efConstruction（網を作るときに見る候補の数。既定は 400）、"
                 "efSearch（検索のときに見る候補の数。既定は 500）。hnsw のフィールドでも、ベクトルのクエリに exhaustive: true を付けると"
                 "全件で比べる。近似の結果と全件の結果を比べると、取りこぼしの程度が見える。exhaustiveKnn のフィールドは網を作らないので、保存の量が少ない\n"
                 "注意：図の網と点は説明用の例で、実際の HNSW の層の数や本数を表したものではない。"
                 "第1部の武将 150 人のデータは件数が少ないので、2つの方式の時間の差はほとんど出ない。先にそう言い、違いは結果の順位がそろうかどうかで見せる",
    }


# ---------------------------------------------------------------- p.10 類似度の測り方（例え話で説明する）
@fig(10)
def p10():
    ox, oy, k = 130, 560, 50                      # 原点と、1 目盛りの長さ。甘さ・辛さを (x, y) で 3×7 などと置く
    P = lambda x, y: (ox + k * x, oy - k * y)
    curry, mabo, dai = P(3, 7), P(2, 9), P(9, 1)

    def arc(r, a1, a2):                           # 原点から見た角度 a1 → a2（度）の円弧
        p = lambda a: (ox + r * math.cos(math.radians(a)), oy - r * math.sin(math.radians(a)))
        (x1, y1), (x2, y2) = p(a1), p(a2)
        return f"<path d='M{x1:.0f} {y1:.0f} A{r} {r} 0 0 0 {x2:.0f} {y2:.0f}' fill='none' stroke='{BLUE}' stroke-width='6'/>"

    a_c, a_m, a_d = (math.degrees(math.atan2(y, x)) for x, y in [(3, 7), (2, 9), (9, 1)])
    card_y = [56, 222, 388]

    cards = [("①  コサイン類似度", BLUE, "矢印の向きの近さ。長さは見ない", "麻婆豆腐 0.98　大福 0.49　（1 に近いほど近い）"),
             ("②  内積", ORANGE, "向きの近さ × 2本の長さ。長さも効く", "麻婆豆腐 69　大福 34　（大きいほど近い）"),
             ("③  ユークリッド距離", GREEN, "矢印の先どうしの距離。小さいほど近い", "麻婆豆腐 2.2　大福 8.5　（ほかの2つと向きが逆）")]
    static = [text(860, 36, "カレーとの近さ", S, GRAY, True, "start")]
    steps = {1: [], 2: [], 3: []}
    for i, (head, color, desc, result) in enumerate(cards):
        y = card_y[i]
        static += [box(860, y, 700, 150, stroke=GRAY, width=3), text(890, y + 46, head, H, color, True, "start"),
                   text(890, y + 92, desc, B, INK, anchor="start")]
        steps[i + 1] += [f"<rect x='860' y='{y}' width='700' height='150' rx='10' fill='none' stroke='{color}' stroke-width='8'/>",
                         text(890, y + 132, result, S, color, True, "start")]
    body = svg(
        1600, 640,
        arrow([(ox, oy), (ox + 560, oy)], GRAY, 4), text(ox + 578, oy + 12, "甘い", B, GRAY, anchor="start"),
        arrow([(ox, oy), (ox, 40)], GRAY, 4), text(ox, 26, "辛い", B, GRAY),
        arrow([(ox, oy), curry], INK, 8), text(curry[0] + 16, curry[1] - 6, "カレー", H, INK, True, "start"),
        arrow([(ox, oy), mabo], INK, 8), text(mabo[0] + 18, mabo[1] + 12, "麻婆豆腐", H, INK, True, "start"),
        arrow([(ox, oy), dai], INK, 8), text(dai[0] + 18, dai[1] + 14, "大福", H, INK, True, "start"),
        *static,
        step(1, arc(280, a_c, a_m), text(ox + 124, oy - 222, "約11度", 28, BLUE, True, "start"),
             arc(140, a_d, a_c), text(ox + 168, oy - 124, "約60度", 28, BLUE, True, "start"), *steps[1]),
        step(2, _line(ox, oy + 36, dai[0], oy + 36, ORANGE, 6),
             _line(ox, oy + 26, ox, oy + 46, ORANGE, 6), _line(dai[0], oy + 26, dai[0], oy + 46, ORANGE, 6),
             text((ox + dai[0]) // 2, oy + 74, "大福の矢印の長さ", 28, ORANGE, True), *steps[2]),
        step(3, _line(curry[0], curry[1], mabo[0], mabo[1], GREEN, 6, True),
             _line(curry[0], curry[1], dai[0], dai[1], GREEN, 6, True), *steps[3],
             text(1210, 610, "長さを1にそろえると、3つとも順位は同じになる", 28, INK, True)),
    )
    return {
        "title": "近さの測り方は、==向き==か、==向きと長さ==か、==先どうしの距離==か",
        "caption": "料理を「甘い」「辛い」の2軸で矢印にした例え話。料理が文、矢印がベクトル、軸が次元に当たる。座標と値は説明用の例",
        "svg": body,
        "notes": "狙い：コサイン類似度、内積、ユークリッド距離は、矢印の向き・長さ・先の位置のどこを見るかの違いだと言える。\n"
                 "話すこと：\n"
                 "・段階0：料理を「甘い」「辛い」の2軸の矢印にする例え話。料理が文、矢印が文のベクトル。"
                 "カレー（甘さ 3、辛さ 7）、麻婆豆腐（2、9）、大福（9、1）。右の3つが、近さの測り方\n"
                 "・段階1：① コサイン類似度は、向きの近さ。長さは見ない。カレーと麻婆豆腐は向きが約11度ずれて 0.98、カレーと大福は約60度ずれて 0.49。"
                 "値は -1 から 1 で、1 に近いほど近い\n"
                 "・段階2：② 内積は、向きの近さに2本の長さを掛けた値。長さも効く（カレーと麻婆豆腐は 3×2 + 7×9 = 69、カレーと大福は 3×9 + 7×1 = 34）。大きいほど近い\n"
                 "・段階3：③ ユークリッド距離は、矢印の先どうしの距離（カレーと麻婆豆腐は約 2.2、カレーと大福は約 8.5）。"
                 "小さいほど近いので、ほかの2つと向きが逆。長さを1にそろえたベクトルでは、3つとも順位が同じになる\n"
                 "補足：Azure AI Search では、ベクトル検索のアルゴリズムの設定の metric で cosine、dotProduct、euclidean、hamming から選ぶ"
                 "（hamming はバイナリのベクトル用）。埋め込みモデルの説明に書かれている測り方に合わせる。"
                 "Azure OpenAI の text-embedding 系統は長さを1にそろえた出力を返す（OpenAI の説明）ので、dotProduct は cosine と同じ順位になり、少し速く動く。"
                 "@search.score は、類似度そのものではなく、大きいほど近い値に直した点数。cosine では 1 / (1 + コサイン距離)（コサイン距離は 1 − コサイン類似度）で、範囲は約 0.333〜1。"
                 "実際の文は、モデルの次元数（p.8）と同じ数の軸をもつ矢印で、測り方は同じ\n"
                 "注意：座標と値は説明用の例で、実際の検索の点数ではない。@search.score は余弦の値そのものではない。"
                 "ユークリッド距離は小さいほど近い、という向きの違いを言う",
    }


# ---------------------------------------------------------------- p.11 フィルターとファセット
@fig(11)
def p11():
    def cell(x, y, head, color, l1, l2, stroke, fill="#fff", w=460):
        return box(x, y, w, 170, stroke=stroke, fill=fill) + text(x + w // 2, y + 52, head, H, color, True) + \
            text(x + w // 2, y + 102, l1, B) + text(x + w // 2, y + 142, l2, S, GRAY)

    body = svg(
        1600, 540,
        shelf(20, 150), text(170, 128, "検索の対象", B, GRAY, True),
        lines(170, 372, ["問い合わせの記録", "73件"], S, gap=34),
        cell(590, 20, "フィルター", BLUE, "channel eq '電話'", "条件に合う記録だけ残す", BLUE, SOFT),
        cell(1200, 20, "検索の結果", GRAY, "電話の26件の中で", "順位を付ける", GRAY, w=380),
        cell(590, 330, "ファセット", ORANGE, "channel ごとの件数", "電話 26、チャット 25、メール 22", ORANGE),
        cell(1200, 330, "件数の一覧", GRAY, "画面の絞り込みの", "ボタンに使う", GRAY, w=380),
        step(0, arrow([(324, 215), (462, 215), (462, 105), (588, 105)], BLUE), text(530, 84, "① 絞る", 28, BLUE, True),
             arrow([(1052, 105), (1198, 105)], BLUE)),
        step(1, arrow([(324, 265), (462, 265), (462, 415), (588, 415)], ORANGE), text(505, 462, "② 数える", 28, ORANGE, True),
             arrow([(1052, 415), (1198, 415)], ORANGE)),
        step(2, arrow([(1390, 328), (1390, 262), (820, 262), (820, 192)], GREEN),
             text(1368, 306, "③ ボタン「電話」を押すと、その値のフィルターが次の検索に加わる", 28, GREEN, True, "end")),
    )
    return {
        "title": "フィルターは==条件で絞り==、ファセットは==件数を数えて==見せる",
        "caption": "どちらも点数は変えない。どの文書を対象にするか、何件あるかを扱う。件数は説明用の例（問い合わせの記録 73件の場合）",
        "svg": body,
        "notes": "狙い：フィルターは点数を変えずに対象を絞り、ファセットは件数を数えて見せる、と言える。\n"
                 "話すこと：\n"
                 "・段階0：検索の対象は、問い合わせの記録 73件（例）。フィルター（channel eq '電話'）は、条件に合う記録だけを残す。"
                 "残った電話の26件の中で、いつもどおり順位を付ける。点数は変わらず、条件に合わない文書が外れるだけ\n"
                 "・段階1：ファセットは、検索の結果の中で、項目（channel）の値ごとの件数を数えて返す。電話 26、チャット 25、メール 22。"
                 "画面の絞り込みのボタンや一覧に使う\n"
                 "・段階2：利用者がボタン（電話）を押すと、その値でのフィルター（channel eq '電話'）が次の検索に加わる。ファセットで全体をつかみ、フィルターで絞って中身を読む、という使い方\n"
                 "補足：フィルターは $filter に OData の式で書く（複数の値のどれかは search.in）。ファセットは facets に、数えるフィールドを書く。"
                 "フィルターに使うフィールドには filterable、ファセットに使うフィールドには facetable が要る。あとから属性を足すには、インデックスの作り直しが要ることがある。"
                 "ベクトル検索との組み合わせは vectorFilterMode で、preFilter（先に絞る）か postFilter（後で絞る）かを選ぶ。"
                 "部署や見せてよい人での絞り込みにも使う（p.30）\n"
                 "注意：件数は説明用の例（問い合わせの記録 73件の集計）。"
                 "本文の「地方が関東」の例は、フィールド名の例で、この図とは別",
    }


# ---------------------------------------------------------------- p.12 スコアリングプロファイル
@fig(12)
def p12():
    conds = ["フィールドの重み（title は 3 倍など）", "新しさ（freshness）", "数の大きさ（magnitude）",
             "距離（distance）", "タグの一致（tag）"]
    body = svg(
        1600, 600,
        box(20, 100, 260, 170, stroke=GRAY), text(150, 152, "BM25 の点数", H, GRAY, True),
        lines(150, 204, ["単語の一致で", "付いた点数"], B, gap=38),
        box(490, 20, 500, 330, stroke=BLUE, fill=SOFT), text(740, 74, "プロファイル", H, BLUE, True),
        lines(520, 126, conds, S, anchor="start", gap=44),
        box(1130, 60, 460, 260, stroke=GREEN), text(1360, 114, "最終の点数", H, GREEN, True),
        lines(1360, 164, ["上乗せした後の", "点数で並べる"], B, gap=38),
        step(0, arrow([(282, 185), (488, 185)], BLUE), text(385, 160, "① 上乗せ", 28, BLUE, True)),
        step(1, arrow([(992, 190), (1128, 190)], GREEN), text(1060, 165, "② 並べる", 28, GREEN, True)),
        step(2, arrow([(740, 352), (740, 418)], BLUE), text(764, 396, "③ ランカーを使うと", 28, BLUE, True, "start"),
             box(490, 420, 500, 130, stroke=BLUE, dash=True), text(740, 474, "セマンティックランカー", H, BLUE, True),
             text(740, 520, "モデルで並べ直す", S, GRAY)),
        step(3, arrow([(992, 485), (1360, 485), (1360, 322)], ORANGE),
             text(1300, 530, "④ ランカーのあとにも、もう1回上乗せ", 28, ORANGE, True),
             text(1300, 566, "（freshness などの関数だけが対象）", S, GRAY),
             text(1360, 258, "ランカーを使うと、", S, GRAY), text(1360, 296, "@search.rerankerBoostedScore", S, GREEN)),
    )
    return {
        "title": "スコアリングプロファイルは、BM25 の点数に==決めた条件で上乗せ==して並びを変える",
        "caption": "どのフィールドで一致したか、新しさ、数の大きさなどで点数を変える。重みの「3 倍」は説明用の例",
        "svg": body,
        "notes": "狙い：スコアリングプロファイルは、前もって書いた決まりで点数を上乗せする仕組みで、ランカーを使うと2回効く、と言える。\n"
                 "話すこと：\n"
                 "・段階0：BM25 の点数は、単語の一致で付いた点数。プロファイルが、決めた条件で点数を上乗せする。条件は、フィールドの重み（例：title の一致は 3 倍）、"
                 "新しさ（freshness）、数の大きさ（magnitude）、距離（distance）、タグの一致（tag）。決まりは人が前もって書いておく\n"
                 "・段階1：上乗せした後の点数で並べる。並べ替え（sort）は点数を使わず値の順に並べるが、プロファイルは点数を足すので、単語の一致の強さも残る\n"
                 "・段階2：セマンティックランカーを使うと、プロファイルは2回効く。最初の順位付けで1回。ランカーは、決まりではなくモデルで並べ直す（p.5）\n"
                 "・段階3：ランカーが並べ直したあとに、もう1回上乗せする（GA）。最終の並び順は、ランカーのあとにプロファイルを当てた @search.rerankerBoostedScore で決まる"
                 "（セマンティック構成の rankingOrder が boostedRerankerScore のとき。プロファイルがあるときの既定）\n"
                 "補足：インデックスの定義の scoringProfiles に名前を付けて書き、text の weights でフィールドごとの重みを、functions に freshness・magnitude・distance・tag を書く。"
                 "クエリの scoringProfile に名前を指定する（既定のプロファイルも決められる。関数の値は scoringParameters で渡せる）。"
                 "主にキーワード検索の点数に効く。ベクトル検索やハイブリッドでも使えるが、効くのは文字列や数値のフィールドだけで、ベクトルのフィールドには効かない。"
                 "ランカーのあとのブーストは関数だけが対象で、フィールドの重みだけのプロファイルには、ランカーのあとのブーストはない。エージェント型検索では、インデックスのスコアリングプロファイルは使われない\n"
                 "注意：重みの「3 倍」は説明用の例。ランカーを使うと、プロファイルは最初の順位付けとランカーのあとの2回効く、と言う",
    }


# ---------------------------------------------------------------- p.13 同義語マップ
@fig(13)
def p13():
    body = svg(
        1600, 500,
        person(150, 200), text(150, 148, "利用者", H, GRAY, True), text(150, 404, "「独眼竜」", B, GRAY, True),
        box(420, 40, 500, 330, stroke=BLUE, fill=SOFT),
        text(670, 94, "同義語マップ", H, BLUE, True), text(670, 132, "（人が書く表）", S, GRAY),
        text(670, 194, "独眼竜, 伊達政宗", B, bold=True), text(670, 232, "（同じ意味として扱う）", S, GRAY),
        text(670, 304, "学割 => 学生割引", B, bold=True), text(670, 342, "（片方向に置き換える）", S, GRAY),
        box(1080, 100, 480, 200, stroke=GREEN), text(1320, 152, "実際に探す言葉", H, GREEN, True),
        lines(1320, 204, ["独眼竜 または", "伊達政宗"], B, bold=True, gap=42),
        step(0, arrow([(212, 200), (418, 200)], BLUE), text(315, 174, "① 質問", 28, BLUE, True)),
        step(1, f"<rect x='440' y='156' width='460' height='88' rx='10' fill='none' stroke='{BLUE}' stroke-width='8'/>",
             arrow([(922, 200), (1078, 200)], GREEN), text(1000, 174, "② 広げる", 28, GREEN, True)),
        step(2, text(800, 452, "③ 表に書いた言い換えしか広がらない。表を足したら、どの質問に効いたかを確かめる", 28, ORANGE, True)),
    )
    return {
        "title": "同義語マップは、==人が書いた表==で言い換えを広げてから検索する",
        "caption": "ベクトル検索を使わずに、BM25 の言い換えの弱さを補う方法の1つ。「独眼竜」「学割」の例は説明用",
        "svg": body,
        "notes": "狙い：同義語マップは、人が書いた表で言い換えを広げる仕組みで、表に書いたものしか広がらない、と言える。\n"
                 "話すこと：\n"
                 "・段階0：利用者が「独眼竜」と質問する。同義語マップは、言い換えを書いておく表。書き方は2種類。"
                 "「独眼竜, 伊達政宗」は同じ意味として扱う（どちらで探しても両方を探す）。「学割 => 学生割引」は片方向の置き換え（「学割」を「学生割引」に置き換える）\n"
                 "・段階1：質問に表の言葉が出てくると、言い換えも一緒に探す。「独眼竜」は「独眼竜 または 伊達政宗」になる。質問の側で広げるので、文書を入れ直す必要はない\n"
                 "・段階2：表に書いた言い換えしか広がらない。広げすぎると関係のない文書も当たる。表を足したら、どの質問に効いたかを確かめる\n"
                 "補足：Azure AI Search では、synonymMaps に Solr の形式で表を書いて登録する。同義語マップはインデックスとは別の部品。"
                 "フィールドの定義の synonymMaps にマップの名前を書いて結び付け、結び付けたフィールドを検索するときだけ効く（結び付けはインデックスを作り直さずに変えられる）。"
                 "ベクトル検索、フィルター、ファセット、オートコンプリートには効かない。表の言葉も、結び付けたフィールドと同じアナライザーで分けられてから使われる。"
                 "作れる数は層で違い（Free と Basic は3つ、S1 は5つ、S2 は10、S3 は20）、1つのマップに書ける規則は Free で 5,000、ほかの層で 20,000 まで。1つの規則に書ける言い換えは20まで\n"
                 "注意：どちらの方法がよいかは言わない。表で補う方法と意味で探す方法（p.2）の違いだけを見せる",
    }


# ---------------------------------------------------------------- p.14 質問の種類と検索方法の向き不向き
@fig(14)
def p14():
    q = lambda y, head, ls: (box(20, y, 500, 172, stroke=GRAY), text(44, y + 46, head, B, INK, True, "start"),
                             lines(44, y + 86, ls, S, GRAY, anchor="start", gap=32))
    m = lambda y, head, sub, color: (box(740, y, 400, 120, stroke=color, fill=SOFT),
                                     text(940, y + 52, head, H, color, True), text(940, y + 92, sub, S, GRAY))
    body = svg(
        1600, 580,
        *q(20, "そのままの言葉で探す質問", ["型番、ID、固有名詞", "例：「REQ-042」"]),
        *q(212, "意味で探す質問", ["言い換えや説明で探す質問", "例：「目が不自由な武将」"]),
        *q(404, "いくつかの事実をつなぐ質問", ["2つ以上の文書を合わせないと", "答えられない質問", "例：「A社の社長が提携している会社」"]),
        *m(46, "キーワード検索", "（BM25・フィルター）", BLUE),
        *m(238, "ベクトル検索", "（意味の近さで探す）", BLUE),
        box(740, 430, 840, 120, stroke=ORANGE, dash=True),
        text(780, 482, "質問を分ける方法（p.32）", B, INK, True, "start"),
        text(780, 526, "関係をたどる方法（p.31、p.33）", B, INK, True, "start"),
        step(0, arrow([(522, 106), (738, 106)], BLUE), text(630, 80, "① 向く", 28, BLUE, True)),
        step(1, arrow([(522, 298), (738, 298)], BLUE), text(630, 272, "② 向く", 28, BLUE, True)),
        step(2, arrow([(522, 490), (738, 490)], ORANGE, dash=True),
             lines(630, 440, ["③ 1回では", "見つけにくい"], 28, ORANGE, True, gap=34)),
        step(3, "<path d='M1156 46 H1172 V358 H1156' fill='none' stroke='%s' stroke-width='5'/>" % GREEN,
             text(1196, 140, "④ ハイブリッド検索", 28, GREEN, True, "start"),
             lines(1196, 178, ["上の2つの両方を", "1回で扱う"], S, GRAY, anchor="start", gap=34),
             text(1196, 262, "セマンティックランカー", 28, GREEN, True, "start"),
             lines(1196, 300, ["集めた上位の並び順を", "変える"], S, GRAY, anchor="start", gap=34)),
    )
    return {
        "title": "検索方法の向き不向きは、==質問の種類==で変わる",
        "caption": "同じ検索方法でも、質問の種類で結果が変わる",
        "svg": body,
        "notes": "狙い：どの検索方法が合うかは質問の種類で変わり、事実をつなぐ質問は1回の検索では扱いにくい種類だと言える。\n"
                 "話すこと：\n"
                 "・段階0：そのままの言葉で探す質問（型番、ID、固有名詞。例「REQ-042」）には、キーワード検索が向いている\n"
                 "・段階1：意味で探す質問（言い換えや説明で探す。例「目が不自由な武将」）には、ベクトル検索が向いている\n"
                 "・段階2：いくつかの事実をつなぐ質問（2つ以上の文書を合わせないと答えられない。例「A社の社長が提携している会社」）は、"
                 "1回の検索ではどちらの方法でも見つけにくい。質問を分ける方法（p.32）や、関係をたどる方法（p.31、p.33）がある\n"
                 "・段階3：ハイブリッド検索は、最初の2種類の両方を1回で扱う。セマンティックランカーは、集めた上位の並び順を変える\n"
                 "補足：Azure AI Search では、そのままの言葉には BM25 のフルテキスト検索と、filterable のフィールドでのフィルターが使える。"
                 "アナライザーの分け方で、ID の区切りが変わることがある。意味で探すにはベクトル検索とセマンティックランカーが使え、ハイブリッドにするとキーワードの一致も残る。"
                 "事実をつなぐ質問には、エージェント型検索で質問をいくつかの検索に分けられる。関係をたどる機能（グラフ RAG）は Azure AI Search の検索そのものにはない"
                 "（プレビューの Fabric Ontology をナレッジソースにする方法は p.31）\n"
                 "注意：どの方法がよいかは言わない。質問の種類ごとの向き不向きを並べるだけにする。「A社の社長」の例は第3部の例と同じものを使う（p.31）",
    }


# ---------------------------------------------------------------- p.15 クエリの書き換え
@fig(15)
def p15():
    place = lambda x, head, sub: (box(x, 480, 480, 100, stroke=GRAY), text(x + 240, 520, head, B, INK, True),
                                  text(x + 240, 558, sub, S, GRAY))
    body = svg(
        1600, 600,
        person(140, 170), text(140, 118, "利用者", H, GRAY, True),
        lines(140, 372, ["「家から働ける日は", "週何日？」"], S, GRAY, bold=True, gap=34),
        box(400, 20, 500, 360, stroke=BLUE, fill=SOFT), text(650, 74, "書き換え", H, BLUE, True),
        text(650, 140, "言い換えを足す", B, bold=True), text(650, 176, "（在宅勤務、リモート）", S, GRAY),
        text(650, 238, "分ける", B, bold=True), text(650, 274, "（条件ごとの質問）", S, GRAY),
        text(650, 336, "会話の前の発言を補う", B, bold=True),
        box(1100, 90, 480, 220, stroke=GREEN), text(1340, 144, "実際に投げる検索", H, GREEN, True),
        lines(1340, 202, ["在宅勤務の日数", "リモート 週"], B, bold=True, gap=44),
        step(0, arrow([(206, 200), (398, 200)], BLUE), text(302, 174, "① 質問", 28, BLUE, True)),
        step(1, arrow([(902, 200), (1098, 200)], GREEN), text(1000, 174, "② 書き換え", 28, GREEN, True)),
        step(2, text(800, 452, "③ 書き換える場所は3つ", 28, GRAY, True),
             *place(20, "アプリ", "Azure OpenAI を呼んで書き換える"),
             *place(560, "検索サービス", "queryRewrites（プレビュー）"),
             *place(1100, "ナレッジベース", "low・medium・auto（プレビュー）")),
    )
    return {
        "title": "クエリの書き換えは、==質問の言葉を文書の言葉に近づけて==から探す",
        "caption": "書き換えを置く場所は、アプリ、検索サービス、ナレッジベースのどれか。例の言葉は説明用で、書き換えが増えるほど検索の回数も増える",
        "svg": body,
        "notes": "狙い：書き換えは質問の言葉を文書の言葉に近づける処理で、書き換える場所が3つある、と言える。\n"
                 "話すこと：\n"
                 "・段階0：利用者の質問は話し言葉で、言葉が足りないことがある（例「家から働ける日は週何日？」）。文書の言葉（「在宅勤務」「リモート」）と違うと、"
                 "キーワード検索では見つかりにくい。会話の途中の質問は、前の話を入れないと意味が通じないこともある\n"
                 "・段階1：書き換えの種類は、言い換えを足す（「在宅勤務の日数」「リモート 週」）、いくつかのことを聞く質問を小さな質問に分ける、会話の前の発言を補う。"
                 "答えの文を先に作り、その文で探す方法もある（HyDE と呼ばれる）。書き換えた結果がずれると、関係のない文書が当たる\n"
                 "・段階2：書き換える場所は3つ。アプリの中で Azure OpenAI を呼んで書き換え、その結果を検索に渡す。"
                 "検索のサービスの中で自動で書き換える（セマンティックランカーの queryRewrites、プレビュー）。ナレッジベースで生成 AI が質問を分ける（reasoning effort が low・medium・auto のとき、プレビュー）\n"
                 "補足：queryRewrites は、クエリに generative|count-5 のように指定する（1〜10件）。書き換えた質問は、キーワード検索とベクトル検索の両方に使われる。"
                 "debug: queryRewrites で、作られた質問を見られる。ナレッジベースでは、会話の履歴を渡すと前の話を入れた質問に直す。minimal のときは生成 AI で質問を分けない（p.37）。"
                 "アプリで書き換える方法は、生成 AI の呼び出しが増える\n"
                 "注意：queryRewrites はプレビュー。GA の 2026-04-01 にあると言わない。書き換えの例（「在宅勤務の日数」「リモート 週」）は説明用",
    }
