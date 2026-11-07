"""評価するデータ（武将・人事・ホテル）ごとの設定：インデックスと項目の名前、権限の絞り込み、漏れの数え方。

名前は、コードと手順書から写したもの（ずれていないことは tests/test_eval_search.py が確かめる）。
  sengoku  basic/lib/config.py の SENGOKU_INDEX・SENGOKU_VECTOR_FIELD・SENGOKU_SEMANTIC。キーは id
  hr       applied/lib/config.py の HR_INDEX・VECTOR_FIELD・SEMANTIC_CONFIG。1文書が多くのチャンクに分かれ、
           文書の ID は各チャンクの doc_id（チャンクのキーは chunk_id）
  hotel    guide/hotel.md の hotels-blob（ベクトルなし）と hotels-cosmos（DescriptionVector）。キーは HotelId。
           手順書にセマンティックの設定はないので、その名前（HOTEL_SEMANTIC）は、足したときの約束

権限（人事だけ）：どの検索にも、聞く人（質問の as_role。なければ role:recruiter）に見える分だけに絞る式を掛ける。
式は applied/lib/acl.py の allowed_filter と同じ（標準ライブラリだけで、ここに書く）。
"""
import re
from dataclasses import dataclass

from .questions import DataError

HR_RECRUITER = "role:recruiter"
HR_PUBLIC_KINDS = ("job_posting",)      # 一般社員に見えるのは求人票だけ（applied/lib/acl.py の PUBLIC_KINDS）
HOTEL_SEMANTIC = "hotels-semantic"
PRINCIPAL = re.compile(r"(?:role|user):[A-Za-z0-9_-]+")     # applied/lib/acl.py と同じ形


@dataclass(frozen=True)
class Setup:
    """1つの方式が検索するところ。vector_field が None なら、ベクトルのクエリを付けない。"""
    index: str
    vector_field: str = None
    semantic_config: str = None


@dataclass(frozen=True)
class Dataset:
    name: str
    id_field: str                   # 検索結果から、文書の ID を取る項目
    select: str                     # 検索で取る項目（ID だけ）
    setups: dict                    # 方式 → Setup
    chunked: bool = False           # 1文書が多くのチャンクに分かれる（同じ文書は、最初のチャンクの順位で1回だけ数える）
    permission: bool = False        # 質問の as_role で絞る（人事）
    supports_condition: bool = False  # 質問の condition を絞り込み（+filter の方式）にできる（ホテル）
    fallback_id_field: str = None   # id_field が空のときに、代わりに使う項目（人事のチャンクのキー）


def _same_index(index, vector_field, semantic_config):
    return {"keyword": Setup(index), "vector": Setup(index, vector_field), "hybrid": Setup(index, vector_field),
            "semantic": Setup(index, vector_field, semantic_config)}


SPECS = {
    "sengoku": Dataset("sengoku", id_field="id", select="id",
                       setups=_same_index("sengoku", "profile_vector", "sengoku-semantic")),
    "hr": Dataset("hr", id_field="doc_id", select="doc_id,chunk_id", chunked=True, permission=True,
                  fallback_id_field="chunk_id", setups=_same_index("hr-docs", "text_vector", "applied-semantic")),
    "hotel": Dataset("hotel", id_field="HotelId", select="HotelId", supports_condition=True, setups={
        "keyword": Setup("hotels-blob"),
        "vector": Setup("hotels-cosmos", "DescriptionVector"),
        "hybrid": Setup("hotels-cosmos", "DescriptionVector"),
        # hotels-blob にベクトルの項目はないので、キーワード検索にセマンティック ランカーを足したもの
        "semantic": Setup("hotels-blob", None, HOTEL_SEMANTIC),
    }),
}


# ------------------------------------------------------------------ 絞り込み

def allowed_filter(principals) -> str:
    """「見てよい人」で絞る式（applied/lib/acl.py の allowed_filter と同じ）。例  allowed/any(a: search.in(a, 'role:employee'))"""
    items = [principals] if isinstance(principals, str) else list(principals)
    if not items or any(not PRINCIPAL.fullmatch(str(x)) for x in items):
        raise DataError(f"見てよい人の印は role:… か user:… の形で書きます（今は {items!r}）。例 role:recruiter、user:U-1006")
    return f"allowed/any(a: search.in(a, '{','.join(items)}'))"


def role_of(dataset: Dataset, question: dict):
    """聞く人の役割。人事は as_role（なければ role:recruiter）。そのほかのデータは None。"""
    if not dataset.permission:
        return None
    return question.get("as_role") or HR_RECRUITER


def base_filter(dataset: Dataset, question: dict):
    """どの方式にもいつも掛ける絞り込み（人事の権限）。なければ None。"""
    role = role_of(dataset, question)
    return allowed_filter(role) if role else None


def combine(*filters):
    """絞り込みの式を and でつなぐ（None は飛ばす）。2つ以上のときは、それぞれを括弧で囲む。"""
    parts = [f for f in filters if f]
    if len(parts) <= 1:
        return parts[0] if parts else None
    return " and ".join(f"({f})" for f in parts)


# ------------------------------------------------------------------ 漏れ

class Visibility:
    """文書が、聞く人に見えてよいか（漏れの数え方）。doc_kinds は {文書の ID: 種類}（人事の manifest の files）。

    漏れ＝上位 k 件に出た、その役割が見られない文書（文書ごとに1）。次のどれかなら漏れ。
      ・質問の hidden_ids に書いてある文書
      ・一般社員（role:employee）に、求人票でない文書（種類が分からない文書も）
    採用担当は全部見える。面接官など、担当の応募ごとに見える文書が違う役割は、hidden_ids だけで数える。
    """

    def __init__(self, doc_kinds=None):
        self.doc_kinds = dict(doc_kinds or {})

    def leaked(self, role, hidden_ids, doc_id) -> bool:
        if doc_id in hidden_ids:
            return True
        if role == "role:employee":
            return self.doc_kinds.get(doc_id) not in HR_PUBLIC_KINDS
        return False

    def leaked_docs(self, role, hidden_ids, docs) -> list:
        """漏れた文書の ID の並び（docs の順。同じ文書は1回だけ）。権限のないデータ（role が None）は空。"""
        if role is None:
            return []
        hidden = set(hidden_ids or [])
        return [doc_id for doc_id in dict.fromkeys(docs) if self.leaked(role, hidden, doc_id)]

    def count(self, role, hidden_ids, docs) -> int:
        return len(self.leaked_docs(role, hidden_ids, docs))


def leakable(dataset: Dataset, question: dict) -> bool:
    """この質問は、漏れが起きうるか。聞く人が採用担当でない（採用担当は全部見える）か、見えてはいけない文書（hidden_ids）がある質問。

    漏れの割合（漏れた質問の数 ÷ 漏れうる質問の数）の分母になる。権限のないデータ（武将・ホテル）は、どの質問も False。
    """
    role = role_of(dataset, question)
    return bool(role) and (role != HR_RECRUITER or bool(question.get("hidden_ids")))


def doc_kinds_of(manifest) -> dict:
    """人事の manifest から {doc_id: kind}。"""
    try:
        return {str(f["doc_id"]): str(f["kind"]) for f in manifest["files"]}
    except (KeyError, TypeError):
        raise DataError("人事のデータの形が違います（files の doc_id と kind が取り出せません）") from None
