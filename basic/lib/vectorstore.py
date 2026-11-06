"""埋め込み済みファイル（embeddings.json）の読み書き。

ファイルの形
  {
    "format": 1,
    "model": "text-embedding-3-small",   埋め込みに使ったモデル名（Azure が返した名前）
    "deployment": "...",                 作ったときのデプロイ名（参考）
    "dimensions": 1536,                  次元
    "created_at": "2026-10-25T...",
    "vectors": { "<埋め込んだ文字列の SHA-256>": [ ...数の並び... ], ... }
  }

ベクトルは「埋め込んだ文字列そのもの」のハッシュで探す。武将の文やチャンクを書き換えたら、ハッシュが変わるので、
古いベクトルは使われない（その分だけ、その場で埋め込み直す）。

使ってよいファイルの条件：モデル名と次元が、いま使っているものと同じ。合わなければ使わない（理由を表示する）。
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import llm
from .config import get_settings

FORMAT = 1


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_file(path: Path):
    """ファイルを読む。なければ None。壊れていれば None（理由は check_file で出す）。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_file(data, path: Path) -> "tuple[bool, str]":
    """埋め込み済みファイルを使ってよいか。(使える, 理由) を返す。"""
    s = get_settings()
    if data is None:
        return False, f"埋め込み済みファイルがありません（{Path(path).name}）"
    if data.get("format") != FORMAT or "vectors" not in data:
        return False, "埋め込み済みファイルの形式が違います"
    if data.get("dimensions") != s.dimensions:
        return False, f"次元が合いません（ファイル {data.get('dimensions')}、.env.local の EMBEDDING_DIMENSIONS {s.dimensions}）"
    mine = llm.embedding_model_name()
    if data.get("model") != mine:
        return False, f"モデルが合いません（ファイル {data.get('model')}、いま使っているもの {mine}）"
    return True, f"モデル {mine}、次元 {s.dimensions}、{len(data['vectors'])} 件"


def get_vectors(texts: list, path: Path, use_file: bool, label: str = "") -> list:
    """texts の埋め込みを返す。use_file が True なら、使えるファイルから探し、なかった分だけ Azure OpenAI で埋め込む。"""
    vectors: list = [None] * len(texts)
    from_file = 0
    if use_file:
        data = load_file(path)
        ok, why = check_file(data, path)
        if ok:
            print(f"  埋め込み済みファイルを使います：{why}")
            table = data["vectors"]
            for i, t in enumerate(texts):
                v = table.get(text_key(t))
                if v is not None:
                    vectors[i] = v
                    from_file += 1
        else:
            print(f"  埋め込み済みファイルは使いません：{why}。その場で埋め込みます。")
    missing = [i for i, v in enumerate(vectors) if v is None]
    if missing:
        if use_file and from_file:
            print(f"  ファイルにない {len(missing)} 件を、Azure OpenAI で埋め込みます。")
        new = llm.embed_texts([texts[i] for i in missing], label=label)
        for i, v in zip(missing, new):
            vectors[i] = v
    print(f"  埋め込みの元：ファイル {from_file} 件、Azure OpenAI {len(missing)} 件")
    return vectors


def save_file(path: Path, texts: list, vectors: list, merge: bool = False) -> None:
    """texts と vectors を埋め込み済みファイルに書く。merge=True なら、同じモデル・次元のファイルの中身に足す。"""
    s = get_settings()
    model = llm.embedding_model_name()
    old = load_file(path) if merge else None
    table: dict = {}
    if old and old.get("format") == FORMAT and old.get("model") == model and old.get("dimensions") == s.dimensions:
        table = dict(old["vectors"])
    for t, v in zip(texts, vectors):
        table[text_key(t)] = [round(x, 8) for x in v]   # float32 の精度で足りる桁にそろえて、ファイルを小さくする
    out = {
        "format": FORMAT,
        "model": model,
        "deployment": s.embedding_deployment,
        "dimensions": s.dimensions,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vectors": table,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
