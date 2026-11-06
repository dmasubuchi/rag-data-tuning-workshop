"""同義語マップ（02-analyzers-synonyms）の道具。

同義語マップは「この語で検索されたら、あの語でも探す」という辞書。AI Search に辞書を作り、インデックスの検索する項目に割り当てると、
その項目を検索するたびに（検索の要求で辞書を指定しなくても）、質問の語が辞書のとおりに広げられる。

  t = target()               操作する相手（武将のインデックス sengoku、辞書 sengoku-synonyms）を、始めに1回だけ決める
  save_rules(t, rules)       辞書を作る（あれば中身を入れ替える）。確認用の1行を足す
  attach(t, True)            辞書を、武将のインデックスの検索する項目（name、aliases、battles、profile）につなぐ
  attach(t, False)           外す（辞書は消さずに残る）
  apply(t, rules)            入れて、つないで、効き始めるまで待つ
  snapshot(t) / restore(t, s)  今の状態（辞書のルールと、項目へのつなぎ）を取っておき、あとでその状態に戻す
  delete_map(t)              辞書を消す（つながっていれば先に外す）

名前を取り違えないために
  ・名前は固定（インデックス sengoku、辞書 sengoku-synonyms）。target() で1回だけ決め、どの操作にも同じ t を渡す。
  ・辞書やインデックスを変える前に check(t) で、t の名前が固定の名前と同じかを確かめる。
    手で作った Target（別の名前）を渡したときは、何も変えずに止まる。同じ AI Search の、ほかのインデックスや辞書は変えられない。
  ・辞書やインデックスを作る・変えるには、AI Search の管理者キー（構築する人の設定）が要る。メンバーのキー（検索だけ）では、
    変える前に「構築する人の設定で実行します」と止まる（lib/clients.py）。

ルールの書き方（Solr の形式）
  北海道, 蝦夷地          どちらで検索しても、両方で探す（同等）
  第六天魔王 => 織田信長  左の語で検索されたら、右の語に置き換えて探す（一方向）

注意
  ・同義語マップは、AI Search 全体で数に上限がある（Basic は3つ）。ここで作るのは sengoku-synonyms の1つ。ほかの用途で上限まで作っているときは、使っていない辞書を消してから作る。
  ・ルールを入れ替えた直後は、しばらく古いルールで検索されることがある（2026-11-03 の実測で、入れ替えて8秒後でも古い結果が返った）。
    そのため、入れ替えるたびに「確認用の1行」（例 kakuninabcdefgh => 織田信長）を足し、その語で武将が出るようになるまで待つ。
    確認用の行は、画面に出すルールの一覧には入れない。
"""
import random
import string
import time
from dataclasses import dataclass

from .clients import index_client, search_client
from .config import SetupError, sengoku_index_name, synonym_map_name

SEARCH_FIELDS = ("name", "aliases", "battles", "profile")   # 武将のインデックスの検索する項目（01-keyword-search の create_index.py）
DEFAULT_MAX_MAPS = 3            # Basic の上限。AI Search から読めないときに使う
PROBE_PREFIX = "kakunin"        # 確認用の語の頭（ローマ字だけにして、1つの語として扱われるようにする）
PROBE_TARGET = "織田信長"       # 確認用の語を置き換える先（必ず武将が見つかる語）
WAIT_LIMIT = 60                 # ルールが効き始めるまで待つ上限（秒）
WAIT_STEP = 2                   # 確かめる間隔（秒）


@dataclass(frozen=True)
class Target:
    """操作する相手。武将のインデックスと、辞書の名前。"""
    index_name: str
    map_name: str


def target() -> Target:
    """操作する相手（固定の名前）を決める。スクリプトの始めに1回だけ呼び、以後は同じものを渡す。"""
    return Target(index_name=sengoku_index_name(), map_name=synonym_map_name())


def check(t: Target) -> None:
    """辞書やインデックスを変える前に呼ぶ。t の名前が固定の名前（sengoku、sengoku-synonyms）でなければ、何も変えずに止める。"""
    if t.index_name != sengoku_index_name() or t.map_name != synonym_map_name():
        raise SetupError(
            f"固定の名前（インデックス {sengoku_index_name()}、辞書 {synonym_map_name()}）以外は変えません"
            f"（インデックス {t.index_name}、辞書 {t.map_name}）。\n"
            "  操作する相手は synonyms.target() で決めてください。")


def is_probe(rule: str) -> bool:
    return rule.strip().startswith(PROBE_PREFIX)


def visible_rules(rules) -> list:
    """画面に出すルール（確認用の行を除く）。"""
    return [r for r in (rules or []) if r.strip() and not is_probe(r)]


def make_probe() -> "tuple[str, str]":
    """確認用の語と、その1行。語は毎回変える（前のルールの確認用の語と混ざらないように）。"""
    word = PROBE_PREFIX + "".join(random.choice(string.ascii_lowercase) for _ in range(8))
    return word, f"{word} => {PROBE_TARGET}"


def existing_map_names() -> list:
    return list(index_client().get_synonym_map_names())


def max_maps() -> int:
    """同義語マップの上限。AI Search の利用状況から読む（読めなければ Basic の 3）。"""
    try:
        stats = index_client().get_service_statistics()
        counters = stats["counters"] if isinstance(stats, dict) else stats.counters
        counter = counters["synonymMaps"] if isinstance(counters, dict) else counters.synonym_map_counter
        quota = counter["quota"] if isinstance(counter, dict) else counter.quota
        return int(quota) if quota else DEFAULT_MAX_MAPS
    except Exception:  # noqa: BLE001  読めなくても、既定の上限で案内できればよい
        return DEFAULT_MAX_MAPS


def check_room(name: str) -> None:
    """新しく作るときに、上限に達していないか確かめる。達していれば、どうすればよいかを出して止める。"""
    names = existing_map_names()
    if name in names:
        return
    limit = max_maps()
    if len(names) >= limit:
        raise SetupError(
            f"同義語マップは、この AI Search 全体で {limit} つまでです。いまあるもの：{'、'.join(names)}\n"
            f"  {name} を作れません。使っていない辞書を消してから、もう一度実行してください。")


def current_rules(t: Target) -> list:
    """辞書のルール（確認用の行を除く）。辞書がなければ空。"""
    if t.map_name not in existing_map_names():
        return []
    return visible_rules(index_client().get_synonym_map(t.map_name).synonyms)


def _put(t: Target, rules) -> str:
    """辞書の中身を rules ＋確認用の1行にする（確かめは呼ぶ側で済ませる）。確認用の語を返す。"""
    from azure.search.documents.indexes.models import SynonymMap

    word, probe = make_probe()
    index_client().create_or_update_synonym_map(SynonymMap(name=t.map_name, synonyms=visible_rules(rules) + [probe]))
    return word


def save_rules(t: Target, rules) -> str:
    """辞書を作る（あれば中身を入れ替える）。確認用の1行を足し、確認用の語を返す。"""
    check(t)
    rules = visible_rules(rules)
    if not rules:
        raise SetupError("同義語のルールが1行もありません。RULES に「北海道, 蝦夷地」のような行を書いてください。")
    check_room(t.map_name)
    return _put(t, rules)


def attached(t: Target) -> dict:
    """検索する項目ごとに、つながっている辞書の名前。{項目: [辞書の名前]}"""
    index = index_client().get_index(t.index_name)
    return {f.name: list(f.synonym_map_names or []) for f in index.fields if f.name in SEARCH_FIELDS}


def _update_fields(t: Target, change) -> None:
    """検索する項目ごとに、つなぐ辞書の一覧を change(項目, 今の一覧) に変える。インデックスの中の文書は変わらない。"""
    ic = index_client()
    index = ic.get_index(t.index_name)
    for f in index.fields:
        if f.name in SEARCH_FIELDS:
            f.synonym_map_names = list(change(f.name, list(f.synonym_map_names or [])))
    ic.create_or_update_index(index)


def attach(t: Target, on: bool) -> None:
    """辞書を検索する項目につなぐ（on=True）、外す（on=False）。外すときは、この辞書だけを外す（ほかの辞書のつなぎは残す）。"""
    check(t)
    if on:
        _update_fields(t, lambda field, names: [t.map_name])     # 1つの項目につなげる辞書は1つ
    else:
        _update_fields(t, lambda field, names: [n for n in names if n != t.map_name])


def wait_until_active(t: Target, word: str, limit: int = WAIT_LIMIT, step: int = WAIT_STEP) -> float:
    """確認用の語で武将が見つかるようになるまで待つ。待った秒数を返す。上限を過ぎたら止める。"""
    sc = search_client(t.index_name)
    t0 = time.time()
    while True:
        res = sc.search(search_text=word, top=1, select=["id"])
        if list(res):
            return time.time() - t0
        if time.time() - t0 > limit:
            raise SetupError(f"辞書のルールが {limit} 秒たっても検索に効きませんでした。少し待ってから、もう一度実行してください。")
        time.sleep(step)


def apply(t: Target, rules) -> float:
    """ルールを入れて、つないで、効き始めるまで待つ。待った秒数を返す。"""
    word = save_rules(t, rules)
    attach(t, True)
    return wait_until_active(t, word)


def snapshot(t: Target) -> dict:
    """今の状態。{"exists": 辞書があるか, "rules": ルール, "attached": 項目ごとにつながっている辞書}"""
    exists = t.map_name in existing_map_names()
    return {"exists": exists, "rules": current_rules(t) if exists else [], "attached": attached(t)}


def restore(t: Target, snap: dict) -> None:
    """snapshot() で取っておいた状態に戻す。辞書がなかったときは、作った辞書を消す。"""
    check(t)
    word = _put(t, snap["rules"]) if snap["exists"] else None
    _update_fields(t, lambda field, names: snap["attached"].get(field, []))
    if not snap["exists"] and t.map_name in existing_map_names():
        index_client().delete_synonym_map(t.map_name)
    if word and any(t.map_name in names for names in snap["attached"].values()):
        wait_until_active(t, word)


def delete_map(t: Target) -> bool:
    """辞書を消す（つながっていれば先に外す）。消したら True。"""
    check(t)
    if t.map_name not in existing_map_names():
        return False
    attach(t, False)
    index_client().delete_synonym_map(t.map_name)
    return True
