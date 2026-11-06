"""（構築する人用）人事の知識ソース hr-docs-ks と知識ベース hr-docs-kb を、チームの AI Search に作る。メンバーは実行しない。

エージェント型検索（トピック 19）は、AI Search の「知識ベース」に質問を渡す。知識ベースは、
  知識ソース hr-docs-ks   既存のインデックス hr-docs を指す（インデックスは変えない）
  知識ベース hr-docs-kb   知識ソースと、質問を分解する LLM をまとめたもの
の2つでできている。LLM は Azure OpenAI のキーで呼ぶ（キーを知識ベースに登録する。マネージド ID やロールの割り当ては使わない）。
LLM のモデル名は .env.local の AZURE_OPENAI_CHAT_MODEL（既定 gpt-5-mini）、デプロイ名は AZURE_OPENAI_CHAT_DEPLOYMENT から読む。

【プレビューの API】LLM を使う機能は GA（2026-04-01）にはなく、プレビューの API 版（lib/agentic.py の API_VERSION。auto がある版）で使う。

やること：
  1. 前提の確認：インデックス hr-docs があること（読むだけ）
  2. 知識ソース → 知識ベース の順に作る（あれば更新）
  3. 動作確認：LLM を使わない minimal と、LLM で質問を分解する low を1回ずつ呼ぶ（LLM の呼び出しは1回、約1,000 トークン）

実行：python applied/tools/build_hr_kb.py             作る（あれば更新）
      python applied/tools/build_hr_kb.py --status    いまの状態を見る（何も変えない。LLM も呼ばない）
      python applied/tools/build_hr_kb.py --recreate  消してから作り直す
      python applied/tools/build_hr_kb.py --delete    消す

必要なもの：構築する人の .env.local（AI Search の管理者キー）。メンバーの設定では、始めに止まります。
扱うのは hr-docs-ks と hr-docs-kb だけです。インデックス・データソース・インデクサー・Storage には触りません。
知識ベースに登録した LLM のキーは、AI Search 側では伏せ字で返る。この画面にもキーは出さない。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(next(p for p in (HERE, *HERE.parents) if p.name == "applied")))
import lib  # noqa: E402
from lib import agentic, clients, config, show  # noqa: E402

SMOKE_QUESTION = "REQ-042 の求人の必須条件は何ですか。"


def require_index():
    """前提：インデックスがあること。読むだけ。"""
    if config.HR_INDEX not in set(clients.index_client().list_index_names()):
        raise config.SetupError(f"インデックス {config.HR_INDEX} がありません。先に applied/tools/build_hr_index.py で作ってください。")


def create_or_update():
    show.section("1. 知識ソース → 知識ベース を作る（あれば更新）")
    require_index()
    agentic.call("PUT", f"/knowledgesources/{agentic.KNOWLEDGE_SOURCE}", agentic.knowledge_source_definition())
    print(f"  知識ソース {agentic.KNOWLEDGE_SOURCE}（インデックス {config.HR_INDEX} を指す）")
    agentic.call("PUT", f"/knowledgebases/{agentic.KNOWLEDGE_BASE}", agentic.knowledge_base_definition())
    s = config.get_settings()
    print(f"  知識ベース {agentic.KNOWLEDGE_BASE}（LLM {s.chat_model}、デプロイ {s.chat_deployment}、キーで接続）")


def smoke_test():
    """動作確認。キーで LLM につながるか（low が質問を分解できるか）を、実際に1回呼んで確かめる。"""
    show.section("2. 動作確認")
    for effort in ("minimal", "low"):
        r = agentic.retrieve(SMOKE_QUESTION, effort)
        a = r["activity"]
        planning = (f"　LLM が質問を分解（入力 {a['input_tokens']:,} / 出力 {a['output_tokens']:,} トークン）" if a["planning_calls"]
                    else "　LLM は使っていない")
        print(f"  {effort:<8} 検索 {a['search_count']} 回　資料 {len(r['evidence'])} 件　{r['elapsed_s']} 秒{planning}")
        if effort == "low" and not a["planning_calls"]:
            raise config.SetupError("low で質問の分解が行われませんでした。知識ベースの LLM につながっていない可能性があります。")
        if not r["evidence"]:
            raise config.SetupError(f"{effort} で資料が1件も返りませんでした。"
                                    "インデックスの allowed（見てよい人）が付いているか、applied/tools/build_hr_index.py --status で確かめてください。")


def status():
    show.section("いまの状態")
    stats = agentic.call("GET", "/servicestats")["counters"]
    for label, key in (("知識ソース", "knowledgeSourcesCount"), ("知識ベース", "knowledgeBasesCount")):
        c = stats.get(key) or {}
        print(f"  {label}：AI Search 全体で {c.get('usage')} 個（上限 {c.get('quota')}）")
    ks = agentic.call("GET", f"/knowledgesources/{agentic.KNOWLEDGE_SOURCE}", missing_ok=True)
    if ks is None:
        print(f"  知識ソース {agentic.KNOWLEDGE_SOURCE}：なし")
    else:
        p = ks.get("searchIndexParameters") or {}
        print(f"  知識ソース {agentic.KNOWLEDGE_SOURCE}：{ks.get('kind')}　インデックス {p.get('searchIndexName')}"
              f"　セマンティック構成 {p.get('semanticConfigurationName')}")
    kb = agentic.call("GET", f"/knowledgebases/{agentic.KNOWLEDGE_BASE}", missing_ok=True)
    if kb is None:
        print(f"  知識ベース {agentic.KNOWLEDGE_BASE}：なし")
    else:
        models = [(m.get("azureOpenAIParameters") or {}) for m in kb.get("models") or []]
        llm = ", ".join(f"{m.get('modelName')}（デプロイ {m.get('deploymentId')}）" for m in models) or "なし"
        sources = ", ".join(s.get("name") for s in kb.get("knowledgeSources") or [])
        print(f"  知識ベース {agentic.KNOWLEDGE_BASE}：知識ソース {sources}　LLM {llm}"
              f"　既定の考える量 {(kb.get('retrievalReasoningEffort') or {}).get('kind')}　出力 {kb.get('outputMode')}")
    print(f"  API の版：{agentic.API_VERSION}（プレビュー）")


def delete():
    show.section("消す")
    for label, path in (("知識ベース", f"/knowledgebases/{agentic.KNOWLEDGE_BASE}"),
                        ("知識ソース", f"/knowledgesources/{agentic.KNOWLEDGE_SOURCE}")):
        gone = agentic.call("DELETE", path, ok=(200, 204), missing_ok=True)
        print(f"  {label} {path.rsplit('/', 1)[1]}：" + ("もともとありません" if gone is None else "消しました"))
    print(f"  インデックス {config.HR_INDEX} には触っていません")


def main():
    parser = argparse.ArgumentParser(description="（構築する人用）人事の知識ソース・知識ベースを作る")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true", help="いまの状態を見る（何も変えない）")
    g.add_argument("--recreate", action="store_true", help="消してから作り直す")
    g.add_argument("--delete", action="store_true", help="消す")
    args, _ = parser.parse_known_args()
    config.require_admin_key()          # メンバーの設定（検索だけのキー）なら、ここで日本語で止まる
    show.title("人事の知識ベース（エージェント型検索）")
    print(agentic.PREVIEW_NOTICE)
    if args.status:
        status()
        return
    if args.delete:
        delete()
        return
    if args.recreate:
        delete()
    create_or_update()
    smoke_test()
    status()
    print("\n完了。トピック 19・20 はこの知識ベースを使います。")


if __name__ == "__main__":
    main()
