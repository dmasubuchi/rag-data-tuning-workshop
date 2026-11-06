"""トピックを始めるのに必要な状態（インデックス、登録済みのデータ、埋め込み）を、確かめる・作り直す。

  ensure("04")                      04 に必要な状態があるか確かめる。なければ「どうすればよいか」を1行出して止まる
  ensure("04", rebuild=True)        武将のインデックスを消して、04 の開始の状態に作り直す（埋め込み済みファイルを使う）

tools/reset.py は、これを呼ぶだけ。スクリプトは、始めに ensure(トピックの番号) を呼ぶ（Notebook でも同じ）。

状態は、トピックが残していくもの（STEPS）の積み重ね。
  01 が残す  sengoku_text    武将のインデックス（文字の項目だけ）と、登録した武将
  03 が残す  sengoku_vector  ベクトルの項目、埋め込み、セマンティックの設定
02・04・05・06 は、インデックスの状態を残さない（02 は同義語マップを作るが、最後に項目から外す）。
新しいトピックが状態を残すときは、STEPS に足し、確かめる関数と作る関数を書く。

rebuild=True は、ハンズオン資料の流れでの開始の状態（それ以前のトピックが残す状態を全部）を作る。
rebuild=False の確認は、そのトピックが実際に要るものだけを見る（NEEDS）。番号にない新しいトピックは、それ以前の全部を見る。
消すのは武将のインデックス sengoku だけ。同じ AI Search にある、ほかのインデックスと、同義語マップには触らない。

AI Search のキーが query（メンバー用。検索だけ）のとき：
  ・確かめる（rebuild=False）は、文書の検索と件数だけで行う（インデックスの定義は、管理者キーでないと読めない）。
    足りなければ、「構築する人に実行してもらってください」と案内して止まる。
  ・作り直す（rebuild=True）は、始める前に「構築する人の設定で実行します」と止まる。
"""
from . import worklog
from .clients import index_client, index_exists, search_client
from .config import (SENGOKU_SEMANTIC, SENGOKU_VECTOR_FIELD, SetupError, get_settings, index_names, is_query_key,
                     require_admin_key, reset_command, sengoku_index_name)
from .data import load_bushou
from .show import step

# トピックが残していく状態（作る順）
STEPS = [("01", "sengoku_text"), ("03", "sengoku_vector")]

# 状態を作るスクリプト（確認で止まるときの案内に使う）
MADE_BY = {
    "sengoku_text": "01-keyword-search の create_index.py と upload.py",
    "sengoku_vector": "03-vector-search の embed.py",
}

# そのトピックが実際に要る状態（rebuild=False の確認で見る）
NEEDS = {
    "01": [],
    "02": ["sengoku_text"],
    "03": ["sengoku_text"],
    "04": ["sengoku_vector"],
    "05": ["sengoku_vector"],
    "06": ["sengoku_vector"],
}


def topic_number(topic) -> str:
    """"1"、"01"、"01-keyword-search" のどれでも、"01" にそろえる。"""
    head = str(topic).strip().split("-")[0]
    if not head.isdigit():
        raise SetupError(f"トピックは番号で指定してください（例 03 または 03-vector-search。今は {topic!r}）。")
    return head.zfill(2)


def states_before(topic) -> list:
    """ハンズオン資料の流れで、そのトピックを始める前に出来ている状態（作る順）。"""
    n = topic_number(topic)
    return [state for num, state in STEPS if num < n]


def states_needed(topic) -> list:
    n = topic_number(topic)
    return NEEDS[n] if n in NEEDS else states_before(n)


# ------------------------------------------------------------------ 確かめる（問題があれば文章、なければ None）

MAX_FETCH = 1000     # AI Search の1回の取得の上限。武将は 150 なので足りる


def expected_sengoku_ids() -> set:
    """武将のインデックスに入っているはずの id（同梱の bushou.json から）。"""
    return {p["id"] for p in load_bushou()}


def index_ids(index_name: str, key_field: str) -> set:
    """インデックスに登録されている文書のキーの集合。"""
    res = search_client(index_name).search(search_text="*", select=[key_field], top=MAX_FETCH)
    return {r[key_field] for r in res}


def ids_with_vectors(index_name: str, key_field: str, vector_field: str, dims: int) -> set:
    """ベクトルが入っている文書のキーの集合。ありえない向きのベクトルで近い順に全件を取る（ベクトルのない文書は出てこない）。"""
    from azure.search.documents.models import VectorizedQuery

    probe = [1.0] + [0.0] * (dims - 1)
    res = search_client(index_name).search(
        search_text=None, vector_queries=[VectorizedQuery(vector=probe, k_nearest_neighbors=MAX_FETCH, fields=vector_field)],
        top=MAX_FETCH, select=[key_field])
    return {r[key_field] for r in res}


def _check_sengoku_text():
    name = sengoku_index_name()
    if not index_exists(name):
        return f"インデックス {name} がありません"
    expected, found = expected_sengoku_ids(), index_ids(name, "id")
    if expected - found:
        return f"{name} に武将が {len(expected & found)}/{len(expected)} 件しか登録されていません"
    return None


def _check_sengoku_vector():
    problem = _check_sengoku_text()
    if problem:
        return problem
    name, dims = sengoku_index_name(), get_settings().dimensions
    if not is_query_key():
        # インデックスの定義を読めるのは管理者キーだけ。メンバーは、下のベクトルの検索で確かめる
        index = index_client().get_index(name)
        if not any(f.name == SENGOKU_VECTOR_FIELD for f in index.fields):
            return f"{name} にベクトルの項目 {SENGOKU_VECTOR_FIELD} がありません"
        if not any(c.name == SENGOKU_SEMANTIC for c in (index.semantic_search.configurations if index.semantic_search else [])):
            return f"{name} にセマンティックの設定 {SENGOKU_SEMANTIC} がありません"
    expected = expected_sengoku_ids()
    try:
        with_vec = ids_with_vectors(name, "id", SENGOKU_VECTOR_FIELD, dims)
    except Exception as e:  # noqa: BLE001  メンバーは項目の有無を読めない。ベクトルの検索が通らないなら、項目がないとみなす
        if not is_query_key():
            raise
        return f"{name} でベクトルを検索できません（ベクトルの項目がまだないようです。{type(e).__name__}）"
    if expected - with_vec:
        return f"{name} でベクトルが入っている武将が {len(expected & with_vec)}/{len(expected)} 件です"
    return None


CHECKS = {"sengoku_text": _check_sengoku_text, "sengoku_vector": _check_sengoku_vector}


def problems(topic) -> list:
    """そのトピックが要る状態のうち、足りないもの。[(状態の名前, 何が足りないか), ...]"""
    out = []
    for state in states_needed(topic):
        problem = CHECKS[state]()
        if problem:
            out.append((state, problem))
    return out


# ------------------------------------------------------------------ 作る（トピックのスクリプトの関数をそのまま使う）

def _build_sengoku_text(use_file: bool) -> None:
    from . import sengoku   # 01-keyword-search の create_index.py と upload.py が使う部品

    name = sengoku_index_name()
    index_client().create_or_update_index(sengoku.build_index(name))
    print(f"  インデックス {name} を作りました。")
    n = sengoku.register(search_client(name), load_bushou())
    print(f"  武将 {n} 件を登録しました。")


def _build_sengoku_vector(use_file: bool) -> None:
    from . import sengoku   # 03-vector-search の embed.py が使う部品

    name = sengoku_index_name()
    sengoku.add_vector_fields(index_client(), name, get_settings().dimensions)
    print("  ベクトルの項目とセマンティックの設定を足しました。")
    n = sengoku.embed_and_register(search_client(name), load_bushou(), use_file)
    print(f"  ベクトルを登録しました（文書 {n} 件）。")


BUILDS = {"sengoku_text": _build_sengoku_text, "sengoku_vector": _build_sengoku_vector}
STATE_TITLES = {
    "sengoku_text": "武将のインデックスを作り、登録する（文字の項目だけ）",
    "sengoku_vector": "ベクトルの項目を足し、武将を埋め込んで登録する",
}


def delete_indexes() -> None:
    """このハンズオンが作るインデックス（武将）だけを消す。同じ AI Search の、ほかのインデックスには触らない。"""
    require_admin_key()
    ic = index_client()
    for name in index_names():
        if index_exists(name):
            ic.delete_index(name)
            print(f"  削除：{name}")
        else:
            print(f"  （なし）：{name}")


def rebuild_state(topic, use_file: bool = True) -> None:
    """武将のインデックスを消して、そのトピックの開始の状態（ハンズオン資料の流れ）に作り直す。"""
    require_admin_key()     # 何も消さないうちに、メンバー用のキーなら止める
    states = states_before(topic)
    total = 1 + len(states)
    step(1, total, "武将のインデックスを消す")
    delete_indexes()
    worklog.clear()
    for i, state in enumerate(states, start=2):
        step(i, total, STATE_TITLES[state])
        BUILDS[state](use_file)


def ensure(topic, rebuild: bool = False, use_file: bool = True) -> None:
    """そのトピックに必要な状態を確かめる。rebuild=True なら、作り直す（use_file=True は埋め込み済みファイルを使う）。

    rebuild=False で足りないものがあれば、どうすればよいかを書いた SetupError で止まる（スクリプトは何もせずに終わる）。
    """
    n = topic_number(topic)
    if rebuild:
        rebuild_state(n, use_file)
        return
    found = problems(n)
    if found:
        first_state, first_problem = found[0]
        if is_query_key():
            raise SetupError(f"{first_problem}。構築する人に、{MADE_BY[first_state]} を実行してもらってください（メンバーの設定では作れません）。")
        raise SetupError(
            f"{first_problem}。{MADE_BY[first_state]} を先に実行するか、{reset_command(n)} で作り直せます。"
        )
