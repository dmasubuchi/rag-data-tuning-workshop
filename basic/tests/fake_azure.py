"""AI Search の偽物（試験用）。通信しない。呼び出しの記録（log）を残して、順序や削除先を確かめられるようにする。

使い方：with fake_search(service): …  のあいだ、lib.clients の index_client()・search_client() が偽物を返す。
"""
import contextlib
import re
from types import SimpleNamespace
from unittest import mock


class FakeService:
    def __init__(self):
        self.indexes = {}      # 名前 → SearchIndex（azure の本物のクラス）
        self.docs = {}         # 名前 → {キー: 文書の辞書}
        self.log = []          # 変更の記録：("delete", 名前) ("create", 名前) ("update", 名前) ("upload", 名前, 件数) ("merge", 名前, 件数)

    def add_index(self, name: str, docs: dict = None, key: str = "id") -> None:
        """前から入っているインデックスを足す（log には残さない）。"""
        from azure.search.documents.indexes.models import SearchField, SearchIndex

        self.indexes[name] = SearchIndex(name=name, fields=[SearchField(name=key, type="Edm.String", key=True)])
        self.docs[name] = dict(docs or {})


class FakeIndexClient:
    def __init__(self, service):
        self.s = service

    def list_index_names(self):
        return list(self.s.indexes)

    def get_index(self, name):
        if name not in self.s.indexes:
            from azure.core.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError(f"index {name} not found")
        return self.s.indexes[name]

    def delete_index(self, name):
        self.s.log.append(("delete", name))
        self.s.indexes.pop(name)
        self.s.docs.pop(name, None)

    def create_or_update_index(self, index):
        self.s.log.append(("update" if index.name in self.s.indexes else "create", index.name))
        self.s.indexes[index.name] = index
        self.s.docs.setdefault(index.name, {})
        return index


class FakeResults(list):
    def get_count(self):
        return len(self)


class FakeFacetResults(FakeResults):
    """facets を渡した検索の結果。件数（include_total_count）は top で切る前の件数、ファセットは欄ごとの件数。"""

    def __init__(self, rows, total, facets):
        super().__init__(rows)
        self.total, self.facets = total, facets

    def get_count(self):
        return self.total

    def get_facets(self):
        return self.facets


# 絞り込みの条件（OData）の、ごく一部だけをまねる：「欄 演算子 値」を and・or でつないだもの（かっこ、not、関数は扱わない）
_ODATA_TERM = re.compile(r"^\s*(\w+)\s+(eq|ne|lt|le|gt|ge)\s+('(?:[^']|'')*'|true|false|null|-?\d+)\s*$")
_ODATA_OPS = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "lt": lambda a, b: a is not None and a < b,
              "le": lambda a, b: a is not None and a <= b, "gt": lambda a, b: a is not None and a > b,
              "ge": lambda a, b: a is not None and a >= b}


def _odata_value(text):
    if text.startswith("'"):
        return text[1:-1].replace("''", "'")
    return {"true": True, "false": False, "null": None}.get(text, int(text) if text.lstrip("-").isdigit() else text)


def odata_matcher(flt):
    """絞り込みの条件を、文書の辞書 → True/False の関数にする。まねられない書き方なら None。"""
    if not flt:
        return lambda row: True
    alternatives = []
    for part in re.split(r"\s+or\s+", flt):
        terms = []
        for term in re.split(r"\s+and\s+", part):
            m = _ODATA_TERM.match(term)
            if not m:
                return None
            terms.append((m.group(1), _ODATA_OPS[m.group(2)], _odata_value(m.group(3))))
        alternatives.append(terms)
    return lambda row: any(all(op(row.get(f), v) for f, op, v in terms) for terms in alternatives)


def facet_values(rows, spec):
    """ファセットの書き方（"category,count:20"、"timestamp,interval:month"）から、[{"value":…, "count":…}] を作る。件数の多い順。"""
    from collections import Counter
    from datetime import datetime, timezone

    name, *opts = spec.split(",")
    opts = dict(o.split(":", 1) for o in opts)
    counts = Counter()
    for r in rows:
        v = r.get(name)
        values = v if isinstance(v, list) else [v]
        for x in values:
            if x is None:
                continue
            if opts.get("interval") == "month":      # AI Search と同じく、協定世界時（UTC）の月で区切る
                t = datetime.fromisoformat(x).astimezone(timezone.utc)
                x = t.strftime("%Y-%m-01T00:00:00Z")
            counts[x] += 1
    if opts.get("interval"):
        items = sorted(counts.items())
    else:
        items = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:int(opts.get("count", 10))]
    return [{"value": v, "count": c} for v, c in items]


class FakeSearchClient:
    def __init__(self, service, index_name):
        self.s, self.name = service, index_name

    def _require_index(self):
        """本物と同じく、インデックスがなければ 404（ResourceNotFoundError）。"""
        if self.name not in self.s.indexes:
            from azure.core.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError(f"index {self.name} not found")

    def _key(self):
        return next(f.name for f in self.s.indexes[self.name].fields if f.key)

    def _results(self, ok_keys):
        return [SimpleNamespace(succeeded=True, key=k, error_message=None) for k in ok_keys]

    def upload_documents(self, documents):
        key = self._key()
        self.s.log.append(("upload", self.name, len(documents)))
        for d in documents:
            self.s.docs[self.name][d[key]] = dict(d)
        return self._results(d[key] for d in documents)

    def merge_or_upload_documents(self, documents):
        key = self._key()
        self.s.log.append(("merge", self.name, len(documents)))
        for d in documents:
            self.s.docs[self.name].setdefault(d[key], {}).update(d)
        return self._results(d[key] for d in documents)

    def get_document_count(self):
        self._require_index()
        return len(self.s.docs[self.name])

    def delete_documents(self, documents):
        key = self._key()
        self.s.log.append(("delete_docs", self.name, len(documents)))
        for d in documents:
            self.s.docs[self.name].pop(d[key], None)
        return self._results(d[key] for d in documents)

    def search(self, search_text=None, vector_queries=None, top=50, select=None, include_total_count=False, **kw):
        self._require_index()
        rows = list(self.s.docs[self.name].values())
        match = odata_matcher(kw.get("filter"))
        if match is not None:  # まねられる条件（欄 演算子 値 を and・or でつないだもの）なら、そのとおりに絞る
            rows = [r for r in rows if match(r)]
        else:
            kinds = re.findall(r"kind eq '([^']+)'", kw.get("filter") or "")
            if kinds:          # まねられない条件のときは、種類の欄（kind eq '…'）だけで絞る。ほかの条件は無視する
                rows = [r for r in rows if r.get("kind") in kinds]
        if vector_queries:     # ベクトルの項目に値がある文書だけが、ベクトル検索に出てくる
            field = vector_queries[0].fields
            rows = [r for r in rows if r.get(field)]
        picked = [({k: r.get(k) for k in select} if select else dict(r)) for r in rows][:top]
        if kw.get("facets"):
            return FakeFacetResults(picked, len(rows), {s.split(",")[0]: facet_values(rows, s) for s in kw["facets"]})
        return FakeResults(picked)


@contextlib.contextmanager
def fake_search(service):
    """azure.search.documents のクライアントを偽物に差し替える。lib.clients の index_client() のキャッシュも空にする。"""
    from lib import clients

    clients.index_client.cache_clear()
    with mock.patch("azure.search.documents.indexes.SearchIndexClient", lambda endpoint, credential: FakeIndexClient(service)), \
            mock.patch("azure.search.documents.SearchClient", lambda endpoint, index_name, credential: FakeSearchClient(service, index_name)):
        try:
            yield service
        finally:
            clients.index_client.cache_clear()


def have_azure() -> bool:
    try:
        import azure.search.documents  # noqa: F401
        return True
    except ImportError:
        return False
