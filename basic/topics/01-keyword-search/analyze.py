# %% [markdown]
# # 質問と本文が、どんな単語に分かれる（分かち書きされる）かを見る
#
# AI Search の Analyze API で、質問と、正解の武将の本文を分かち書きします。
# キーワード検索は「同じ単語を持つか」で一致を決めるので、質問と本文で同じ単語に分かれるかが分かれ目になります。
# 質問の単語ごとに、正解の武将の各項目にあるか、その単語を含む武将が何人いるかも表示します。
#
# 実行：`python analyze.py`
# 自分の言い換え：`python analyze.py --q "自分で考えた言い換え"`
#
# 前提：先に `create_index.py` と `upload.py` を実行して、武将を登録してあること。

# %%
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:   # Notebook のとき
    HERE = Path.cwd()
sys.path.insert(0, str(HERE.parents[1]))   # basic/
import lib  # noqa: F401  標準出力を UTF-8 にする
from lib import cells, state
from lib.clients import index_client, search_client
from lib.config import require_admin_key, sengoku_index_name
from lib.data import load_bushou, qid_note, resolve_question
from lib.show import one_line, pad, section, title

cells.start()

# %%
# ===== 変えてよい値 ==========================================================
QUESTION = None                                # None のとき、questions.json の言い換えの質問（正解の本文は別の言い方をしている）
ANALYZER = "ja.microsoft"                      # インデックスの検索する項目と同じアナライザー
BODY_NAME = None                               # 本文を割る武将の名前。None のときは、質問の正解の武将
REBUILD = False                                # True にすると、武将のインデックスを、01 が終わった状態に作り直してから始める
# ============================================================================

import argparse

parser = argparse.ArgumentParser(description="Analyze API で分かち書きを見る")
parser.add_argument("--q", default=None, help="質問（省略すると、QUESTION）")
parser.add_argument("--rebuild", action="store_true", help="武将のインデックスを作り直してから始める")
args, _ = parser.parse_known_args()
QUESTION = args.q or QUESTION
REBUILD = REBUILD or args.rebuild

# %% [markdown]
# ## 1. 準備：質問と、本文を割る武将を決める
# 本文を割る武将は、`BODY_NAME` があればその人、なければ質問の正解の武将です。

# %%
question, q = resolve_question(QUESTION, "paraphrase")

require_admin_key()      # メンバー用のキー（検索だけ）なら、ここで止まる（Analyze API は管理者キーが要る）
state.ensure("03", rebuild=REBUILD)      # 武将のインデックスと、登録した武将があるか
index_name = sengoku_index_name()
ic = index_client()
sc = search_client(index_name)
people = load_bushou()

if BODY_NAME:
    person = next((p for p in people if p["name"] == BODY_NAME), None)
elif q and q.get("answer_ids"):
    person = next((p for p in people if p["id"] == q["answer_ids"][0]), None)
else:
    person = None
if person is None:
    print("本文を割る武将を決められませんでした（質問が questions.json にありません）。")
    print("BODY_NAME = \"伊達政宗\" のように、このファイルの先頭で武将の名前を指定してください。")


def tokens_of(text: str) -> list:
    """Analyze API：text をアナライザーで単語に分ける。単語の一覧を、出てくる順に返す。"""
    from azure.search.documents.indexes.models import AnalyzeTextOptions

    result = ic.analyze_text(index_name, AnalyzeTextOptions(text=text, analyzer_name=ANALYZER))
    return [t.token for t in result.tokens]


# %% [markdown]
# ## 2. 質問と本文を分かち書きする
# **見るところ**：質問が何個の単語に分かれたか。本文（profile）が何文字から何個の単語に分かれたか。

# %%
if person is not None:
    title(f"分かち書き（アナライザー：{ANALYZER}）")
    q_tokens = tokens_of(question)
    print(f"質問：{question}{qid_note(q)}")
    print(f"分かれた単語（{len(q_tokens)} 個）：{' / '.join(q_tokens)}")

    section(f"正解の武将の本文：{person['name']}")
    body_tokens = tokens_of(person["profile"])
    print(f"本文（profile）は {len(person['profile'])} 文字 → {len(body_tokens)} 個の単語に分かれました。")
    print("  " + one_line(" / ".join(body_tokens), 300))

# %% [markdown]
# ## 3. 質問の単語ごとに確かめる
# 質問の単語ごとに、正解の武将のどの項目（name、aliases、battles、profile）に出てくるか、その単語を単独で検索したとき一致する武将が何人いるかを調べます。
# **見るところ**：「正解の項目」（その単語が、正解の武将のどの項目に出てくるか）と、「含む武将」（多いほど、検索では軽く扱われる）。

# %%
if person is not None:
    section("質問の単語ごとの確認")
    field_texts = {
        "name": person["name"],
        "aliases": "。".join(person.get("aliases") or []),
        "battles": "。".join(person.get("battles") or []),
        "profile": person["profile"],
    }
    field_tokens = {k: set(tokens_of(v)) if v else set() for k, v in field_texts.items()}

    print("  ・正解の項目：その単語が、正解の武将のどの項目に出てくるか")
    print("  ・含む武将：その単語を単独で検索したとき、一致する武将の人数（多いほど、検索では軽く扱われる）")
    print()
    seen = []
    for tok in q_tokens:
        if tok in seen:
            continue
        seen.append(tok)
        in_fields = [k for k, toks in field_tokens.items() if tok in toks]
        res = sc.search(search_text=tok, include_total_count=True, top=0)
        list(res)
        n = res.get_count()
        where = "、".join(in_fields) if in_fields else "どの項目にもない"
        print(f"  {pad(tok, 8)} 正解の項目：{pad(where, 24)} 含む武将：{n} 人")

# %% [markdown]
# ## 4. 共通の単語
# **見るところ**：質問と正解の武将で共通の単語。共通の単語がない（あっても、どの武将にもある語だけ）と、キーワード検索では正解が上位に来にくくなります。

# %%
if person is not None:
    shared = [t for t in seen if any(t in toks for toks in field_tokens.values())]
    print()
    if shared:
        print(f"質問と正解の武将で共通の単語：{' / '.join(shared)}")
    else:
        print("質問と正解の武将で共通する単語は、1つもありません。")
    print("→ 共通の単語がない（あっても、どの武将にもある語だけ）と、キーワード検索では正解が上位に来にくくなります。")
    print("次は：python search_paraphrase.py（この質問をキーワード検索で実行する）")
