# RAGPIPELINE

사내 기술 문서(Markdown)를 RAG(Retrieval-Augmented Generation) 형식으로 자동 정제·색인·검색하는 로컬 AI 파이프라인입니다.  
외부 API 없이 Apple Silicon(MLX) 위에서 완전히 로컬로 동작합니다.

---

## 전체 아키텍처

```
 as_is/*.md          원본 사내 문서 (노이즈 포함)
      │
      ▼
┌─────────────────────────────────────────┐
│  Phase 1 · 2  정제 파이프라인  (run.py) │
│                                         │
│  DocumentLoader → DomainFilter          │
│       → Refiner → Validator             │
│       → JSONL 로그 / Resume             │
└─────────────────────────────────────────┘
      │
      ▼
 to_be/{build,maintenance,incident}/*.md   정제된 RAG 문서
      │
      ▼
┌─────────────────────────────────────────┐
│  Phase 3  인덱싱           (embed.py)   │
│                                         │
│  H2 청킹 → bge-m3 임베딩               │
│       → Qdrant 저장 + BM25 빌드        │
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Phase 3  검색 / 응답      (search.py)  │
│                                         │
│  Dense(Qdrant) + Sparse(BM25)           │
│       → RRF 융합 → bge-reranker         │
│       → Gemma 4 26B MoE 응답 생성      │
└─────────────────────────────────────────┘
```

---

## 요구 사항

| 항목 | 버전 / 사양 |
|---|---|
| Python | 3.12 이상 |
| 하드웨어 | Apple Silicon (M1 Pro 이상 권장, 통합 메모리 32GB+) |
| 모델 | `mlx-community/gemma-4-26b-moe-instruct-4bit` |
| 임베딩 | `BAAI/bge-m3` |
| Re-ranker | `BAAI/bge-reranker-v2-m3` |

---

## 프로젝트 구조

```
RAGPIPELINE/
├── run.py                    # Phase 1·2 정제 파이프라인 진입점
├── embed.py                  # Phase 3 인덱싱 진입점
├── search.py                 # Phase 3 검색·응답 진입점
├── config.yaml               # 전체 설정 파일
├── glossary.yaml             # 사내 용어집
├── requirements.txt
│
├── as_is/                    # 원본 문서 입력 폴더
├── to_be/                    # 정제 문서 출력 폴더
│   ├── build/
│   ├── maintenance/
│   └── incident/
├── logs/                     # JSONL 실행 로그
├── models/                   # MLX 모델 다운로드 위치
├── qdrant_db/                # Qdrant 로컬 DB + BM25 인덱스
│
├── src/
│   ├── config.py             # Pydantic v2 설정 모델
│   ├── models.py             # Document, FilterResult, ValidationResult
│   ├── loader.py             # UTF-8/CP949 로드, H2 청킹, 오버랩
│   ├── llm_client.py         # MLX-LM 래퍼 (지연 로드)
│   ├── domain_filter.py      # LLM 기반 도메인 분류
│   ├── refiner.py            # 섹션 추출 + RAG MD 정제
│   ├── validator.py          # YAML·필드·키워드 보존율·환각 검증
│   ├── pipeline.py           # PipelineOrchestrator (Resume, 동시성)
│   ├── resume.py             # 이전 로그 기반 완료 파일 스킵
│   ├── progress.py           # 터미널 프로그레스 바 + 통계
│   └── rag/
│       ├── models.py         # RagChunk, SearchResult, RagAnswer
│       ├── chunker.py        # to_be MD → front-matter 파싱 + H2 청킹
│       ├── embedder.py       # BgeEmbedder (bge-m3)
│       ├── vector_store.py   # QdrantStore (upsert / cosine search)
│       ├── bm25_index.py     # BM25Okapi (한국어 토크나이저, pickle)
│       ├── retriever.py      # HybridRetriever (RRF + bge-reranker)
│       ├── answer_generator.py # AnswerGenerator (LLMClient 재사용)
│       ├── indexer.py        # RagIndexer (임베딩 → Qdrant → BM25)
│       └── engine.py         # RagEngine (검색 + 응답 통합)
│
└── tools/
    └── log_analyzer.py       # 로그 분석 CLI (6개 서브커맨드)
```

---

## 설치

```bash
# 1. 가상환경 생성
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. MLX 모델 다운로드
huggingface-cli download mlx-community/gemma-4-26b-moe-instruct-4bit \
  --local-dir ./models/gemma-4-26b-moe
```

> bge-m3 / bge-reranker-v2-m3 는 `embed.py` / `search.py` 첫 실행 시 Hugging Face Hub에서 자동 다운로드됩니다.

---

## 사용 방법

### Phase 1·2 — 문서 정제

원본 Markdown 파일을 `as_is/` 폴더에 넣고 실행합니다.

```bash
# 기본 실행 (Resume 활성화)
python run.py

# 전체 재처리 (Resume 무시)
python run.py --no-resume

# 처리 대상 확인만 (LLM 호출 없음)
python run.py --dry-run

# 설정 파일 지정
python run.py --config config.yaml
```

실행 완료 후 `to_be/{build,maintenance,incident}/` 에 정제된 문서가 생성됩니다.

### Phase 3 — 인덱싱

```bash
python embed.py
```

- `to_be/**/*.md` 전체를 H2 단위로 청킹
- bge-m3로 임베딩 생성 → Qdrant 저장
- BM25 인덱스 빌드 → `qdrant_db/bm25_index.pkl` 저장

### Phase 3 — 검색 및 응답

```bash
# 전체 도메인 검색
python search.py "Redis connection pool 고갈 시 복구 절차는?"

# 도메인 필터 적용
python search.py "Kubernetes 클러스터 구축 절차" --domain build
python search.py "PostgreSQL 백업 주기" --domain maintenance
python search.py "OOM 장애 대응 방법" --domain incident

# LLM 응답 없이 검색 결과만 출력
python search.py "모니터링 알람 설정" --no-answer
```

---

## 설정 파일 (config.yaml)

```yaml
model:
  path: ./models/gemma-4-26b-moe   # MLX 모델 경로
  max_tokens: 4096
  temperature: 0.1

pipeline:
  input_dir: ./as_is
  output_dir: ./to_be
  log_dir: ./logs
  max_chunk_tokens: 8000            # 청크 최대 토큰
  overlap_tokens: 200               # 청크 간 오버랩
  max_retries: 2                    # LLM 재시도 횟수
  keyword_retention_threshold: 0.7  # 키워드 보존율 최소 기준
  resume: true                      # 중단 재개 활성화
  concurrency: 1                    # 동시 처리 수

domains:
  - name: build
    output_folder: build
    keywords: [구축, 설치, 배포, 설계, 환경, 인프라, 구성]
  - name: maintenance
    output_folder: maintenance
    keywords: [운영, 유지보수, 모니터링, 백업, 튜닝, 점검, 최적화]
  - name: incident
    output_folder: incident
    keywords: [장애, 에러, 복구, 롤백, RCA, 인시던트, 대응]

rag:
  embedding_model: BAAI/bge-m3
  qdrant_path: ./qdrant_db
  collection_name: rag_docs
  top_k_dense: 10                   # Dense 검색 후보 수
  top_k_bm25: 10                    # BM25 검색 후보 수
  top_k_rerank: 5                   # Re-rank 최종 반환 수
  rrf_k: 60                         # RRF 파라미터
  reranker_model: BAAI/bge-reranker-v2-m3
  answer_max_tokens: 2048
```

---

## 로그 분석

```bash
# 상태별 집계 (success / fail / skip)
python -m tools.log_analyzer status

# 도메인별 분류 통계
python -m tools.log_analyzer domains

# 실패 문서 목록 및 원인
python -m tools.log_analyzer failures

# 토큰 사용량 및 처리 시간
python -m tools.log_analyzer tokens

# 키워드 보존율 통계
python -m tools.log_analyzer retention

# 전체 종합 리포트
python -m tools.log_analyzer report
```

---

## 의존성

| 패키지 | 용도 |
|---|---|
| `mlx-lm` | Apple Silicon LLM 추론 (정제 + 응답 생성) |
| `FlagEmbedding` | bge-m3 임베딩 / bge-reranker-v2-m3 |
| `qdrant-client` | 로컬 벡터 DB |
| `rank-bm25` | BM25 희소 검색 |
| `pydantic` | 설정 모델 검증 |
| `PyYAML` | config.yaml 파싱 |

---

## 라이선스

MIT
