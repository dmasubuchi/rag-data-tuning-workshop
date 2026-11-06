# %% [markdown]
# # 言い換えると、なぜキーワード検索で外れるのか（分かれ方を見る）
#
# 実行：`python compare_analyzers.py`（Notebook では上から順にセルを実行する）
#
# キーワード検索は、質問と本文を「語」に分け、同じ語を持つ文書を探す。
# 言い換えた質問は、本文と同じ語を持たないので外れる。ここでは、
#
# 1. 同じ言葉が、アナライザー（語に分ける仕組み）によってどう分かれるか
# 2. 言い換えの質問3つで、質問と正解の本文に共通の語がどれだけあるか
#
# を、AI Search の Analyze API で確かめる。インデックスの中身は変えない。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:            # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib
from lib import cells, state
from lib.clients import index_client, search_client
from lib.config import require_admin_key, sengoku_index_name
from lib.data import answer_rank, load_bushou, load_questions, names_by_id
from lib.show import section, table, title

cells.start()

# ===== 変えてよい値 ==========================================================
# 言い換えの質問（questions.json の qid）。どれもキーワード検索では上位3件に入らない
QUESTIONS = ["q21", "q23", "q28"]
# 比べる言葉のペア（質問での言い方, 正解の本文での言い方）
WORD_PAIRS = [
    ("立てこもった", "籠城"),
    ("器", "水瓶"),
    ("壊して", "割って"),
    ("眼球", "目玉"),
    ("北海道", "蝦夷地"),
]
# 比べるアナライザー。武将のインデックスの検索する項目は ja.microsoft を使っている
ANALYZERS = ["ja.microsoft", "ja.lucene", "standard.lucene"]
# ============================================================================

# %% [markdown]
# ## 準備
#
# 01-keyword-search で作った、武将のインデックスを使う（Analyze API はインデックスを1つ指定して呼ぶ）。
# なければ、どうすればよいかを1行出して止まる。`REBUILD = True` にすると作り直す。

# %%
REBUILD = False
require_admin_key()      # メンバー用のキー（検索だけ）なら、ここで止まる（Analyze API は管理者キーが要る）
state.ensure("02", rebuild=REBUILD)
INDEX = sengoku_index_name()
ic = index_client()
sc = search_client(INDEX)


def tokens(text: str, analyzer: str = "ja.microsoft") -> list:
    """Analyze API：text を analyzer で語に分け、出てくる順に返す。"""
    from azure.search.documents.indexes.models import AnalyzeTextOptions

    result = ic.analyze_text(INDEX, AnalyzeTextOptions(text=text, analyzer_name=analyzer))
    return [t.token for t in result.tokens]


# %% [markdown]
# ## 1. アナライザーによって、同じ言葉の分かれ方が変わる
#
# 見るところ
# - `ja.microsoft`：文の中の形のまま分ける（「立てこもった」→「立て / こもっ / た」）。
# - `ja.lucene`：辞書の形（基本形）にそろえる（「立てこもった」→「立てこもる」、「壊して」→「壊す」）。
#   活用の違いは吸収できるが、「立てこもる」と「籠城」のような**別の言葉**は、どのアナライザーでも同じ語にならない。
# - `standard.lucene`：日本語を1文字ずつに切る。「北海道」と「蝦夷地」は1文字も重ならない。
#
# アナライザーは項目ごとにインデックスを作るときに決める。あとから変えるには、インデックスを作り直す。

# %%
title("アナライザーによる分かれ方")
rows = []
for asked, written in WORD_PAIRS:
    for word in (asked, written):
        rows.append([word] + [" / ".join(tokens(word, a)) for a in ANALYZERS])
table(["言葉"] + ANALYZERS, rows)

# %% [markdown]
# ## 2. 言い換えの質問と、正解の本文に共通の語
#
# 見るところ
# - 「共通の語」が少ない、または「城」「戦い」のようなどの本文にもある語だけだと、正解は上位に来ない。
#   （「た」「て」のような、ひらがなだけの語は表から省いている）
# - 「キーワードの順位」は、質問をそのままキーワード検索したときの正解の順位（上位50件まで）。
#
# 次の `synonym_map.py` で、辞書（同義語マップ）を使って、この外れを直す。

# %%
section("言い換えの質問と、正解の本文の語")
people = {p["id"]: p for p in load_bushou()}
names = names_by_id()
qs = {q["qid"]: q for q in load_questions()}
rows = []
for qid in QUESTIONS:
    q = qs[qid]
    person = people[q["answer_ids"][0]]
    q_tokens = set(tokens(q["question"]))
    body = "。".join([person["name"], *person.get("aliases", []), *person.get("battles", []), person["profile"]])
    shared = sorted(t for t in q_tokens & set(tokens(body)) if not all("ぁ" <= c <= "ん" for c in t))
    hits = list(sc.search(search_text=q["question"], top=50, select=["id"]))
    rank = answer_rank(hits, q["answer_ids"])
    rows.append([qid, q["question"][:28] + "…", names[person["id"]], " / ".join(shared) or "なし",
                 f"{rank} 位" if rank else "圏外"])
table(["質問", "文", "正解", "共通の語", "キーワードの順位"], rows)

print("\n次は：python synonym_map.py（辞書を作って、同じ質問をもう一度検索する）")
