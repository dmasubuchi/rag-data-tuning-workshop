"""Azure の取り込みの設計図（トピック 15）。構築する人のツール（tools/build_hr_index.py）が作り、参加者のスクリプトが読んで表示する。

流れ（14 で手元の Python がしたことを、Azure の部品に置き換える）：

  Storage（入れ物の全体。文書は manifest の相対パスのまま置く。例 jobs/JOB-REQ042-v3.pdf）
     │  データソース：どこの文書を読むか（接続文字列、入れ物、削除の印）
     ▼
  インデクサー：文書を1つずつ開き、文字と画像を取り出す（PDF・Word・Excel・メール・画像）
     │  スキルセット：取り出したものに順に手を加える
     │    1. OCR           画像の中の文字を読む（スキャンした書類）
     │    2. 文字の結合     本文と、OCR で読んだ文字を1つの文章にまとめる
     │    3. 分割          400 文字ずつ（重なりなし）チャンクに切る
     │    4. 埋め込み      チャンクを Azure OpenAI でベクトルにする
     ▼
  インデックス（hr-docs）：チャンクを1件ずつ登録する（インデックスの射影＝親の文書とチャンクの親子）
     │
  後処理（acl.py）：各チャンクに「見てよい人」の一覧を付ける（16 で使う）

文書ごとの情報（文書の番号、種類、求人、応募、人）は、Storage に置くときに blob のメタデータとして付け、
インデックスの射影で各チャンクの欄に写す。後のトピックで使う：
  req_id・application_ids・person_keys  求人・応募・人の番号（18 関係で探す）

blob のメタデータは英数字（ASCII）の文字列しか入らないので、複数の値は空白で区切った文字列にし、
インデックスでは空白で区切って一致を見る欄（whitespace アナライザー）にする。

「見てよい人」（allowed）は、役割（role:recruiter など）と個人（user:U-1006 など）を並べた一覧（Collection）。
インデクサーは blob のメタデータから一覧を作れないので、取り込みの後に acl.py が付ける（インデクサーを動かすたびに付け直す）。
後処理なので、チャンクごとに変えられる（現年収を含むチャンクは採用担当だけ、など）。

分割は 400 文字・重なりなし。見てよい人をチャンクごとに変えるので、重なりで隣のチャンクに
現年収などの一部が漏れないようにする。Azure の分割は長さで切るので、Excel の1行や Word の見出しは考えない（14 との違い）。
"""
from .config import (HR_DATASOURCE, HR_INDEX, HR_INDEXER, HR_SKILLSET, SEMANTIC_CONFIG, VECTOR_ALGORITHM, VECTOR_FIELD,
                     VECTOR_PROFILE, VECTORIZER, SetupError, get_settings)

CHUNK_SIZE = 400          # 分割の大きさ（文字）
CHUNK_OVERLAP = 0         # 重なりなし（見てよい人をチャンクごとに変えるため）
EMBEDDING_MODEL = "text-embedding-3-small"
# 削除の検出：blob のメタデータにこの名前で true を付けてインデクサーを動かすと、インデックスから消える（17 で使う）。
# 方針は最初のインデクサー実行から設定しておく。方針を入れる前に消した blob の文書は、あとで足しても索引に残る。
# 更新の検出：blob の最終更新日時（LastModified）を、インデクサーが自動で見る（設定は要らない）。
DELETE_MARK = "IsDeleted"

# 文書ごとの情報（blob のメタデータの名前 → インデックスの欄の名前は同じ）
META_FIELDS = ("doc_id", "kind", "req_id", "application_ids", "person_keys")


def blob_name(rel_path: str) -> str:
    """Storage の中の名前。manifest の相対パスのまま、入れ物の直下に置く。例 jobs/JOB-REQ042-v3.pdf

    入れ物の外を指す名前（.. を含む、先頭が /）や、空の名前は、受け付けない。
    """
    if not rel_path or rel_path.startswith("/") or ".." in rel_path.replace("\\", "/").split("/"):
        raise SetupError(f"Storage の名前は、入れ物の中の相対パスにしてください（今は {rel_path!r}）。")
    return rel_path


NO_VALUE = "-"   # 値がないときの印。空のメタデータは Storage で消え、射影が「値がない」と警告するため


def blob_metadata(f: dict) -> dict:
    """manifest の1ファイル分から、blob のメタデータを作る（値は ASCII の文字列。空なら「-」）。"""
    values = {
        "doc_id": f.get("doc_id") or "",
        "kind": f.get("kind") or "",
        "req_id": f.get("req_id") or "",
        "application_ids": " ".join(f.get("application_ids") or []),
        "person_keys": " ".join(f.get("person_keys") or []),
    }
    return {k: (v or NO_VALUE) for k, v in values.items()}


def _openai_base(endpoint: str) -> str:
    return endpoint.rstrip("/")


def _ai_services_subdomain(endpoint: str) -> str:
    """https://<名前>.openai.azure.com/ から https://<名前>.cognitiveservices.azure.com/ を作る（OCR の課金のつなぎ先）。"""
    from urllib.parse import urlparse

    host = urlparse(endpoint).hostname or ""
    name = host.split(".")[0]
    return f"https://{name}.cognitiveservices.azure.com/"


# ------------------------------------------------------------------ データソース

def datasource():
    from azure.search.documents.indexes.models import (SearchIndexerDataContainer, SearchIndexerDataSourceConnection,
                                                       SoftDeleteColumnDeletionDetectionPolicy)

    s = get_settings(need_storage=True)     # 接続文字列と入れ物の名前は、構築する人の設定（Storage の項目）にだけある
    account = s.storage_connection_string
    return SearchIndexerDataSourceConnection(
        name=HR_DATASOURCE,
        type="azureblob",
        connection_string=account,
        # query（フォルダの指定）を付けない＝入れ物の全体を読む
        container=SearchIndexerDataContainer(name=s.storage_container),
        data_deletion_detection_policy=SoftDeleteColumnDeletionDetectionPolicy(
            soft_delete_column_name=DELETE_MARK, soft_delete_marker_value="true"),
        description="応用編の文書（入れ物の全体）",
    )


# ------------------------------------------------------------------ インデックス

def index():
    from azure.search.documents.indexes.models import (AzureOpenAIVectorizer, AzureOpenAIVectorizerParameters,
                                                       HnswAlgorithmConfiguration, SearchableField, SearchField,
                                                       SearchFieldDataType, SearchIndex, SemanticConfiguration,
                                                       SemanticField, SemanticPrioritizedFields, SemanticSearch,
                                                       SimpleField, VectorSearch, VectorSearchProfile)

    s = get_settings()
    S = SearchFieldDataType.String
    fields = [
        # チャンクの番号（インデックスの射影が自動で付ける。射影の決まりで keyword アナライザー）
        SearchField(name="chunk_id", type=S, key=True, searchable=True, filterable=True, sortable=True,
                    analyzer_name="keyword"),
        SimpleField(name="parent_id", type=S, filterable=True),                 # 親の文書（blob）の番号
        SearchableField(name="chunk", type=S, analyzer_name="ja.microsoft"),    # チャンクの本文（OCR の文字を含む）
        SearchField(name=VECTOR_FIELD, type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True, vector_search_dimensions=s.dimensions, vector_search_profile_name=VECTOR_PROFILE),
        SearchableField(name="title", type=S, filterable=True, sortable=True),   # ファイル名
        SimpleField(name="source_path", type=S),                                # Storage の場所
        SimpleField(name="doc_id", type=S, filterable=True, facetable=True),
        SimpleField(name="kind", type=S, filterable=True, facetable=True),      # 文書の種類
        SimpleField(name="req_id", type=S, filterable=True, facetable=True),    # 求人の番号
        SearchableField(name="application_ids", type=S, analyzer_name="whitespace", filterable=True),
        SearchableField(name="person_keys", type=S, analyzer_name="whitespace", filterable=True),
        # 見てよい人（role:… と user:… の一覧）。インデクサーではなく、取り込みの後に acl.py が付ける
        SimpleField(name="allowed", type=SearchFieldDataType.Collection(S), filterable=True, facetable=True),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=VECTOR_ALGORITHM)],
        profiles=[VectorSearchProfile(name=VECTOR_PROFILE, algorithm_configuration_name=VECTOR_ALGORITHM,
                                      vectorizer_name=VECTORIZER)],
        # 統合ベクトル化：検索するときの質問も、AI Search が Azure OpenAI でベクトルにする（手元で埋め込まない）
        vectorizers=[AzureOpenAIVectorizer(vectorizer_name=VECTORIZER, parameters=AzureOpenAIVectorizerParameters(
            resource_url=_openai_base(s.openai_endpoint), deployment_name=s.embedding_deployment,
            api_key=s.openai_key, model_name=EMBEDDING_MODEL))],
    )
    semantic = SemanticSearch(configurations=[SemanticConfiguration(
        name=SEMANTIC_CONFIG,
        prioritized_fields=SemanticPrioritizedFields(title_field=SemanticField(field_name="title"),
                                                     content_fields=[SemanticField(field_name="chunk")]))])
    return SearchIndex(name=HR_INDEX, fields=fields, vector_search=vector_search, semantic_search=semantic)


# ------------------------------------------------------------------ スキルセット

def skillset():
    from azure.search.documents.indexes.models import (AIServicesAccountKey, AzureOpenAIEmbeddingSkill,
                                                       InputFieldMappingEntry, MergeSkill, OcrSkill,
                                                       OutputFieldMappingEntry, SearchIndexerIndexProjection,
                                                       SearchIndexerIndexProjectionSelector,
                                                       SearchIndexerIndexProjectionsParameters, SearchIndexerSkillset,
                                                       SplitSkill)

    s = get_settings()
    ocr = OcrSkill(
        name="1-ocr", description="画像の中の文字を読む（スキャンした書類）",
        context="/document/normalized_images/*", default_language_code="ja", should_detect_orientation=True,
        inputs=[InputFieldMappingEntry(name="image", source="/document/normalized_images/*")],
        outputs=[OutputFieldMappingEntry(name="text", target_name="text")],
    )
    merge = MergeSkill(
        name="2-merge", description="本文と、OCR で読んだ文字を1つにまとめる",
        context="/document", insert_pre_tag=" ", insert_post_tag=" ",
        inputs=[InputFieldMappingEntry(name="text", source="/document/content"),
                InputFieldMappingEntry(name="itemsToInsert", source="/document/normalized_images/*/text"),
                InputFieldMappingEntry(name="offsets", source="/document/normalized_images/*/contentOffset")],
        outputs=[OutputFieldMappingEntry(name="mergedText", target_name="merged_content")],
    )
    split = SplitSkill(
        name="3-split", description=f"{CHUNK_SIZE} 文字ずつ（{CHUNK_OVERLAP} 文字重ねて）チャンクに切る",
        context="/document", text_split_mode="pages", maximum_page_length=CHUNK_SIZE,
        page_overlap_length=CHUNK_OVERLAP, default_language_code="ja",
        inputs=[InputFieldMappingEntry(name="text", source="/document/merged_content")],
        outputs=[OutputFieldMappingEntry(name="textItems", target_name="pages")],
    )
    embed = AzureOpenAIEmbeddingSkill(
        name="4-embed", description="チャンクをベクトルにする",
        context="/document/pages/*", resource_url=_openai_base(s.openai_endpoint),
        deployment_name=s.embedding_deployment, api_key=s.openai_key, model_name=EMBEDDING_MODEL,
        dimensions=s.dimensions,
        inputs=[InputFieldMappingEntry(name="text", source="/document/pages/*")],
        outputs=[OutputFieldMappingEntry(name="embedding", target_name=VECTOR_FIELD)],
    )
    mappings = [
        InputFieldMappingEntry(name="chunk", source="/document/pages/*"),
        InputFieldMappingEntry(name=VECTOR_FIELD, source=f"/document/pages/*/{VECTOR_FIELD}"),
        InputFieldMappingEntry(name="title", source="/document/metadata_storage_name"),
        InputFieldMappingEntry(name="source_path", source="/document/metadata_storage_path"),
    ] + [InputFieldMappingEntry(name=m, source=f"/document/{m}") for m in META_FIELDS]
    projection = SearchIndexerIndexProjection(
        selectors=[SearchIndexerIndexProjectionSelector(
            target_index_name=HR_INDEX, parent_key_field_name="parent_id",
            source_context="/document/pages/*", mappings=mappings)],
        parameters=SearchIndexerIndexProjectionsParameters(projection_mode="skipIndexingParentDocuments"),
    )
    return SearchIndexerSkillset(
        name=HR_SKILLSET, description="OCR → 文字の結合 → 分割 → 埋め込み",
        skills=[ocr, merge, split, embed], index_projection=projection,
        # OCR の課金先：チームの Foundry（AI Services）。AI Search と同じ地域でないと使えない
        cognitive_services_account=AIServicesAccountKey(key=s.openai_key,
                                                        subdomain_url=_ai_services_subdomain(s.openai_endpoint)),
    )


# ------------------------------------------------------------------ インデクサー

def indexer():
    from azure.search.documents.indexes.models import (IndexingParameters, IndexingParametersConfiguration,
                                                       SearchIndexer)

    return SearchIndexer(
        name=HR_INDEXER, data_source_name=HR_DATASOURCE, target_index_name=HR_INDEX,
        skillset_name=HR_SKILLSET, description="応用編の文書を取り込む",
        parameters=IndexingParameters(configuration=IndexingParametersConfiguration(
            data_to_extract="contentAndMetadata",
            image_action="generateNormalizedImages",     # 画像（スキャン、PDF の中の画像）を取り出して OCR に渡す
            parsing_mode="default",
        )),
    )
