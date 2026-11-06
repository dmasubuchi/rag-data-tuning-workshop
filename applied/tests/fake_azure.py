"""通信しない試験用の、Azure の作り物（Storage の入れ物、AI Search のインデックス、インデクサー）。

本物と同じ形で答える最小のもの。試験が「どの blob・チャンクに、どんな要求を出したか」を、記録（log）で確かめられる。

  - 入れ物：blob の名前・メタデータ・中身・更新の版。set_blob_metadata は、本物と同じく全部を置き換える
  - インデックス：チャンク（chunk_id、title、kind、allowed など）。filter は、次の形の項を and でつないだものを解釈する
      search.in(title, 'a,b')、allowed/any(a: search.in(a, 'x,y'))、kind eq 'v'
    （それ以外の項は、記録するだけで、絞らない）
  - インデクサー：run_indexer のあと、状態を取るたびに進む（実行中 → 終わり）。終わるときに、入れ物の blob を取り込む
      * blob の更新の版が前回と違うものを、チャンクに切って入れ直す（古いチャンクは消す。allowed は空に戻る）
      * メタデータ IsDeleted=true の blob は、そのチャンクを消す（ignore_deleted=True だと、消さない）
      * blob がなくなっていても、何もしない（取り残しになる。本物と同じ）
"""
import hashlib
import re
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CHUNK = 400


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    return "".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


class Results(list):
    """search の結果（リスト）。get_facets・get_count も持つ。"""

    def __init__(self, rows, facets=None, count=None):
        super().__init__(rows)
        self._facets, self._count = facets or {}, count

    def get_facets(self):
        return self._facets

    def get_count(self):
        return len(self) if self._count is None else self._count


class FakeContainer:
    """Storage の入れ物。exists=False は、まだ作っていない入れ物（本物と同じく、置こうとすると見つからない）。"""

    def __init__(self, az):
        self.az = az
        self.exists = True

    def create_container(self):
        from azure.core.exceptions import ResourceExistsError

        self.az.log.append(("create_container", self.exists))
        if self.exists:
            raise ResourceExistsError("ContainerAlreadyExists")
        self.exists = True

    def upload_blob(self, name, data, overwrite=False, metadata=None, content_settings=None):
        if not self.exists:
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("ContainerNotFound")
        body = data.read() if hasattr(data, "read") else bytes(data)
        self.az.clock += 1
        self.az.blobs[name] = {"data": body, "metadata": dict(metadata or {}), "version": self.az.clock}
        self.az.log.append(("upload_blob", name))

    def list_blobs(self, name_starts_with="", include=None):
        self.az.log.append(("list_blobs", name_starts_with))
        return [SimpleNamespace(name=n, metadata=dict(b["metadata"]), size=len(b["data"]),
                                last_modified=datetime(2026, 11, 3, 10, 0, b["version"] % 60, tzinfo=timezone.utc))
                for n, b in sorted(self.az.blobs.items()) if n.startswith(name_starts_with)]

    def delete_blob(self, name):
        self.az.log.append(("delete_blob", name))
        del self.az.blobs[name]

    def get_blob_client(self, name):
        return FakeBlob(self.az, name)


class FakeBlob:
    def __init__(self, az, name):
        self.az, self.name = az, name

    def get_blob_properties(self):
        b = self.az.blobs[self.name]
        return SimpleNamespace(metadata=dict(b["metadata"]), size=len(b["data"]),
                               last_modified=datetime(2026, 11, 3, 10, 0, b["version"] % 60, tzinfo=timezone.utc))

    def download_blob(self):
        self.az.log.append(("download_blob", self.name))
        data = self.az.blobs[self.name]["data"]
        return SimpleNamespace(readall=lambda: data)

    def set_blob_metadata(self, metadata):
        self.az.log.append(("set_blob_metadata", self.name, dict(metadata)))
        b = self.az.blobs[self.name]
        b["metadata"] = dict(metadata)               # 全部を置き換える（本物と同じ）
        self.az.clock += 1
        b["version"] = self.az.clock                 # 更新日時が新しくなる


class FakeSearch:
    def __init__(self, az):
        self.az = az

    _IN_TITLE = re.compile(r"^search\.in\(title, '([^']*)'\)$")
    _IN_ALLOWED = re.compile(r"^allowed/any\(a: search\.in\(a, '([^']*)'\)\)$")
    _KIND_EQ = re.compile(r"^kind eq '([^']*)'$")

    def _match(self, doc, flt):
        if not flt:
            return True
        for term in flt.split(" and "):
            term = term.strip()
            if m := self._IN_TITLE.match(term):
                if doc.get("title") not in m.group(1).split(","):
                    return False
            elif m := self._IN_ALLOWED.match(term):
                if not set(doc.get("allowed") or []) & set(m.group(1).split(",")):
                    return False
            elif m := self._KIND_EQ.match(term):
                if doc.get("kind") != m.group(1):
                    return False
        return True                                           # 解釈できない項は、絞らない（記録だけ）

    def search(self, search_text="*", filter=None, top=None, select=None, facets=None, include_total_count=False, **kw):
        self.az.log.append(("search", filter))
        rows = [d for d in self.az.chunks.values() if self._match(d, filter)]
        text = (search_text or "*").strip()
        if text != "*":
            words = [text.strip('"')] if text.startswith('"') else text.split()
            rows = [d for d in rows if any(w in d.get("chunk", "") for w in words)]
        out = [{k: v for k, v in d.items() if not select or k in select} for d in rows]
        fct = {}
        for f in facets or []:
            field = f.split(",")[0]
            counts = {}
            for d in rows:
                counts[d.get(field)] = counts.get(d.get(field), 0) + 1
            fct[field] = [{"value": v, "count": c} for v, c in sorted(counts.items())]
        return Results(out[:top] if top is not None else out, fct, len(rows))

    def delete_documents(self, docs):
        ids = [d["chunk_id"] for d in docs]
        self.az.log.append(("delete_documents", ids))
        res = []
        for i in ids:
            if not self.az.resurrect:
                self.az.chunks.pop(i, None)
            res.append(SimpleNamespace(key=i, succeeded=True, status_code=200, error_message=None))
        if self.az.inflight:                         # 実行中のインデクサーが、いま、読み終えたチャンクを索引に入れる
            for c in self.az.inflight:
                self.az.chunks[c["chunk_id"]] = c
            self.az.inflight = []
        return res

    def merge_documents(self, docs):
        self.az.log.append(("merge_documents", [d["chunk_id"] for d in docs]))
        res = []
        for d in docs:
            k = d["chunk_id"]
            plan = self.az.merge_plan.get(k)
            if k not in self.az.chunks:
                res.append(SimpleNamespace(key=k, succeeded=False, status_code=404, error_message="not found"))
            elif plan:
                self.az.merge_plan[k] = plan - 1 if plan > 0 else plan      # 負の数なら、何回でも失敗する
                res.append(SimpleNamespace(key=k, succeeded=False, status_code=503, error_message="busy"))
            else:
                self.az.chunks[k].update({a: b for a, b in d.items() if a != "chunk_id"})
                res.append(SimpleNamespace(key=k, succeeded=True, status_code=200, error_message=None))
        return res


class FakeIndexer:
    def __init__(self, az):
        self.az = az

    def run_indexer(self, name):
        self.az.log.append(("run_indexer", name))
        if self.az.state != "idle" or self.az.hold_running > 0:
            e = Exception("Another indexer invocation is currently in progress; concurrent invocations are not allowed.")
            e.status_code = 409
            raise e
        self.az.state = "queued"

    def get_indexer_status(self, name):
        az = self.az
        if az.status_failures > 0:
            az.status_failures -= 1
            raise ConnectionError("network down")
        if az.state == "queued":
            az.state = "running"
            az.polls_left = az.run_polls
            az.last = SimpleNamespace(start_time=f"run{az.runs + 1}", status="inProgress", item_count=0, failed_item_count=0,
                                      warnings=[], errors=[])
            az.log.append(("status", "inProgress"))
        elif az.state == "running":
            if az.polls_left > 0:
                az.polls_left -= 1
                az.log.append(("status", "inProgress"))
            else:
                az.runs += 1
                n = az.ingest()
                az.state = "idle"
                az.last = SimpleNamespace(start_time=f"run{az.runs}", status="success", item_count=n, failed_item_count=0,
                                          warnings=[], errors=[])
                az.log.append(("status", "success"))
        elif az.hold_running > 0:                  # ほかの人の実行が走っている（頼んだ覚えのない実行中）
            az.hold_running -= 1
            az.log.append(("status", "inProgress"))
            if az.hold_running == 0 and az.inflight:
                for c in az.inflight:                # 読み終えた blob のチャンクが、実行の終わりに索引に入る
                    az.chunks[c["chunk_id"]] = c
                az.inflight = []
            return SimpleNamespace(status="running", last_result=SimpleNamespace(
                start_time="other", status="inProgress", item_count=0, failed_item_count=0, warnings=[], errors=[]))
        return SimpleNamespace(status="running", last_result=az.last)


class FakeAzure:
    """3つの作り物（入れ物・インデックス・インデクサー）と、状態、要求の記録（log）。"""

    def __init__(self, ignore_deleted=False, resurrect=False, run_polls=1):
        self.blobs, self.chunks, self.seen, self.log = {}, {}, {}, []
        self.clock, self.runs, self.state, self.polls_left = 0, 0, "idle", 0
        self.ignore_deleted, self.resurrect, self.run_polls = ignore_deleted, resurrect, run_polls
        self.merge_plan = {}          # chunk_id → あと何回、503 で失敗するか
        self.status_failures = 0      # 状態の取得が、あと何回、通信の失敗になるか
        self.hold_running = 0         # ほかの人の実行が、あと何回の確認のあいだ、走っているか
        self.inflight = []            # ほかの人の実行が、終わるときに索引に入れるチャンク
        self.last = SimpleNamespace(start_time="run0", status="success", item_count=0, failed_item_count=0, warnings=[], errors=[])
        self.container, self.search, self.indexer = FakeContainer(self), FakeSearch(self), FakeIndexer(self)

    # ---- 取り込み
    @staticmethod
    def _text(name, data):
        if name.endswith(".pdf"):
            return _pdf_text(data)
        return f"{Path(name).name} 岩崎 俊樹 " + data[:40].decode("utf-8", "ignore")

    def ingest(self) -> int:
        n = 0
        for name, b in sorted(self.blobs.items()):
            md = b["metadata"]
            if md.get("IsDeleted") == "true" and not self.ignore_deleted:
                for k in [k for k, d in self.chunks.items() if d["parent_id"] == name]:
                    del self.chunks[k]
                self.seen[name] = b["version"]
                n += 1
            elif self.seen.get(name) != b["version"]:
                for k in [k for k, d in self.chunks.items() if d["parent_id"] == name]:
                    del self.chunks[k]
                text = self._text(name, b["data"])
                key = hashlib.md5(name.encode()).hexdigest()[:10]
                for i in range(0, max(len(text), 1), CHUNK):
                    cid = f"{key}_pages_{i // CHUNK}"
                    self.chunks[cid] = {"chunk_id": cid, "parent_id": name, "title": Path(name).name, "chunk": text[i:i + CHUNK],
                                        "kind": md.get("kind"), "doc_id": md.get("doc_id"), "req_id": md.get("req_id"),
                                        "application_ids": md.get("application_ids", ""), "person_keys": md.get("person_keys", ""),
                                        "allowed": []}
                self.seen[name] = b["version"]
                n += 1
        return n

    # ---- 使う側
    def chunk_ids(self, title=None):
        return sorted(k for k, d in self.chunks.items() if title is None or d.get("title") == title)

    def blob_names(self, prefix=""):
        return sorted(n for n in self.blobs if n.startswith(prefix))

    def snapshot(self):
        """入れ物の blob（名前・メタデータ・中身）とチャンク（番号・本文・allowed）の、比べるための写し。更新の版は含めない。"""
        blobs = {n: (dict(b["metadata"]), hashlib.md5(b["data"]).hexdigest()) for n, b in self.blobs.items()}
        chunks = {k: (d["title"], d["chunk"], tuple(d["allowed"])) for k, d in self.chunks.items()}
        return blobs, chunks

    def build(self):
        """構築する人が build_hr_index.py で作った状態にする：manifest の全文書を置き、インデクサーを動かし、見てよい人を付ける。"""
        from lib import acl, docops

        with self.patched():
            docops.put_manifest(only_changed=False)
            docops.run_indexer(say=lambda s: None)
            acl.sync()
        self.log.clear()
        return self

    @contextmanager
    def patched(self):
        import lib

        with ExitStack() as st:
            st.enter_context(mock.patch.object(lib.clients, "container_client", return_value=self.container))
            st.enter_context(mock.patch.object(lib.clients, "search_client", return_value=self.search))
            st.enter_context(mock.patch.object(lib.clients, "indexer_client", return_value=self.indexer))
            st.enter_context(mock.patch("time.sleep"))
            yield self
