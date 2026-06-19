# RAGPIPELINE · v1.0

사내 기술 문서(Markdown)를 **RAG(Retrieval-Augmented Generation)** 형식으로 자동 정제·색인·검색하는 로컬 AI 파이프라인입니다.  
Apple Silicon(MLX) 위에서 완전히 로컬로 동작하며 외부 API 의존이 없습니다.

---

## 목차

1. [아키텍처 개요](#아키텍처-개요)
2. [요구 사항](#요구-사항)
3. [프로젝트 구조](#프로젝트-구조)
4. [설치](#설치)
5. [빠른 시작](#빠른-시작)
6. [설정 파일](#설정-파일-configyaml)
7. [주요 모듈](#주요-모듈)
8. [로그 분석](#로그-분석)
9. [의존성](#의존성)
10. [변경 이력](#변경-이력)

---

## 아키텍처 개요

```
 as_is/*.md           원본 사내 문서 (노이즈 포함)
      │
      ▼
┌──────────────────────────────────────────────┐
│  Phase 1·2  문서 정제 파이프라인  (run.py)   │
│                                              │
│  ModelServer (mlx_lm / mlx_vllm 자동 기동)  │
│  Loader → DomainFilter → Refiner             │
│        → StructureValidator → JudgeLLM       │
│        → SearchAugmenter (SearXNG 선택)      │
│        → JSONL 로그 / LLM 응답 로그 / Resume │
└──────────────────────────────────────────────┘
      │
      ▼
 to_be/{build,maintenance,incident}/*.md   정제된 RAG 문서
      │
      ▼
┌──────────────────────────────────────────────┐
│  Phase 3  인덱싱                (embed.py)   │
│                                              │
│  H2 청킹 → bge-m3 임베딩                    │
│         → Qdrant 저장 + BM25 빌드           │
└──────────────────────────────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────┐
│  Phase 3  검색 / 응답          (search.py)   │
│                                              │
│  Dense(Qdrant) + Sparse(BM25)                │
│         → RRF 융합 → bge-reranker            │
│         → LLM 최종 응답 생성                │
└──────────────────────────────────────────────┘
```

### 정제 파이프라인 흐름 (단일 문서)

```
Document
  └─► DomainFilter       LLM으로 도메인 분류 (build / maintenance / incident)
        └─► Refiner       도메인 관련 섹션 추출 → RAG Markdown 정제
              └─► StructureValidator   YAML front-matter + H2 구조 검증
                    └─► JudgeLLM (선택)  충실성 / 완전성 LLM 판정
                          └─► SearchAugmenter (선택)  SearXNG 웹 검색 보강
                                └─► PipelineIO   파일 저장 + JSONL 로그
```

---

## 요구 사항

| 항목 | 사양 |
|---|---|
| Python | 3.12 이상 |
| 하드웨어 | Apple Silicon (M1 Pro 이상, 통합 메모리 32 GB+) |
| LLM (프로덕션) | `mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit` |
| LLM (테스트) | `google/gemma-4-E2B-it` (`--test` 플래그로 자동 전환) |
| 임베딩 | `BAAI/bge-m3` |
| Re-ranker | `BAAI/bge-reranker-v2-m3` |
| 웹 검색 *(선택)* | [SearXNG](https://docs.searxng.org/) 로컬 인스턴스 |

> **참고** bge-m3 / bge-reranker-v2-m3 는 `embed.py` / `search.py` 최초 실행 시 Hugging Face Hub 에서 자동 다운로드됩니다.

---

## 프로젝트 구조

```
RAGPIPELINE/
├── run.py                      # Phase 1·2 정제 파이프라인 진입점
├── embed.py                    # Phase 3 인덱싱 진입점
├── search.py                   # Phase 3 검색·응답 진입점
├── config.yaml                 # 전체 설정 (단일 진실 출처)
├── glossary.yaml               # 사내 용어집
├── requirements.txt
│
├── as_is/                      # 원본 문서 입력 폴더
├── to_be/                      # 정제 문서 출력 폴더
│   ├── build/
│   ├── maintenance/
│   └── incident/
├── logs/                       # JSONL 실행 로그 + LLM 응답 로그
├── models/                     # MLX 모델 저장 위치
├── qdrant_db/                  # Qdrant 로컬 DB + BM25 인덱스
│
├── src/
│   ├── ports.py                # ★ LLMClientPort, AugmenterPort (추상 인터페이스)
│   ├── config.py               # Pydantic v2 설정 모델
│   ├── models.py               # Document, FilterResult, JudgeVerdict 등 도메인 모델
│   ├── loader.py               # UTF-8/CP949 로드, H2 청킹, 토큰 오버랩
│   ├── llm_client.py           # LLMClientPort 구현체 (OpenAI-compatible 래퍼)
│   ├── llm_logger.py           # ★ LLM 요청/응답 전체 기록 전용 로거
│   ├── model_server.py         # ★ mlx_lm / mlx_vllm 서버 자동 기동·헬스체크·종료
│   ├── web_search.py           # WebSearchClientPort + SearXNGClient
│   ├── domain_filter.py        # LLM 기반 도메인 분류 (OCP 준수)
│   ├── refiner.py              # 섹션 추출 + RAG Markdown 정제 + 키워드 보존
│   ├── validator.py            # YAML·섹션 구조·최소 길이 검증
│   ├── judge.py                # JudgeLLM — 충실성/완전성 판정, JudgeError 발생
│   ├── search_augmenter.py     # SearXNG 검색 → 정제 문서 보강
│   ├── pipeline_io.py          # 디렉터리 초기화, JSONL 로그, 파일 저장 (SRP)
│   ├── pipeline_runner.py      # DocumentRunner — 단일 문서 실행 (SRP)
│   ├── pipeline.py             # PipelineOrchestrator — 의존성 조립 + 일괄 실행
│   ├── resume.py               # 이전 로그 기반 완료 파일 스킵
│   ├── progress.py             # 터미널 진행 바 + 통계
│   └── rag/
│       ├── models.py           # RagChunk, SearchResult, RagAnswer
│       ├── chunker.py          # to_be Markdown → front-matter + H2 청킹
│       ├── embedder.py         # BgeEmbedder (bge-m3)
│       ├── vector_store.py     # QdrantStore (upsert / cosine 검색)
│       ├── bm25_index.py       # BM25Okapi (한국어 토크나이저, pickle)
│       ├── retriever.py        # HybridRetriever (RRF + bge-reranker)
│       ├── answer_generator.py # AnswerGenerator (LLMClient 재사용)
│       ├── indexer.py          # RagIndexer (임베딩 → Qdrant → BM25)
│       └── engine.py           # RagEngine (검색 + 응답 통합 진입점)
│
└── tools/
    └── log_analyzer.py         # 로그 분석 CLI (6개 서브커맨드)
```

---

## 설치

```bash
# 1. 가상환경 생성
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 프로덕션 모델 다운로드 (선택 — server.managed=true 이면 자동 다운로드)
huggingface-cli download mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit \
  --local-dir ./models/gemma-4-26b
```

> `server.managed: true` (기본값) 이면 `run.py` 실행 시 모델 서버가 **자동으로 기동**됩니다.  
> 별도로 `mlx_lm.server` 를 미리 띄울 필요가 없습니다.

---

## 빠른 시작

### Phase 1·2 — 문서 정제

`as_is/` 폴더에 원본 Markdown 파일을 넣고 실행합니다.

```bash
# 기본 실행 — 서버 자동 기동 후 정제 시작 (이전 완료 파일 스킵)
python run.py

# 테스트 모드 — 경량 모델(gemma-4-E2B)로 빠르게 동작 확인
python run.py --test

# 처리 대상 확인만 (LLM 호출 없음)
python run.py --dry-run
python run.py --test --dry-run

# 전체 재처리 (Resume 무시)
python run.py --no-resume

# 외부에서 이미 서버를 기동한 경우 — 자동 기동 스킵
python run.py --no-server

# mlx_vllm 백엔드로 강제 전환
python run.py --backend mlx_vllm
```

#### CLI 옵션 전체 목록

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--config` | 설정 파일 경로 | `config.yaml` |
| `--test` | 테스트 모드 (경량 모델, 포트 8001, mlx_vllm) | 비활성 |
| `--no-resume` | 완료 파일 스킵 무시, 전체 재처리 | 비활성 |
| `--dry-run` | LLM 호출 없이 대상 목록만 출력 | 비활성 |
| `--backend` | 서버 백엔드 강제 지정 (`mlx_lm` / `mlx_vllm`) | config 따름 |
| `--no-server` | 서버 자동 기동 스킵 (외부 서버 사용) | 비활성 |

#### CLI 옵션 우선순위

```
config.yaml  <  --test preset  <  --backend / --no-server
```

#### 테스트 모드 vs 프로덕션 모드

| 항목 | 프로덕션 (`python run.py`) | 테스트 (`python run.py --test`) |
|---|---|---|
| 모델 | `mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit` | `google/gemma-4-E2B-it` |
| 백엔드 | `mlx_lm` (config 따름) | `mlx_vllm` |
| 포트 | `8000` | `8001` |
| max_tokens | `4096` | `2048` |
| startup_timeout | `180`초 | `120`초 |
| LLM 응답 로그 | config 따름 | 항상 활성 |

> 포트가 달라 **두 모드를 동시에 실행해도 충돌하지 않습니다.**

### Phase 3 — 인덱싱

```bash
python embed.py
```

- `to_be/**/*.md` 전체를 H2 단위로 청킹
- bge-m3 로 임베딩 생성 → Qdrant 저장
- BM25 인덱스 빌드 → `qdrant_db/bm25_index.pkl` 저장

### Phase 3 — 검색 및 응답

```bash
# 전체 도메인 검색
python search.py "Redis connection pool 고갈 시 복구 절차는?"

# 도메인 필터 적용
python search.py "Kubernetes 클러스터 구축 절차" --domain build
python search.py "PostgreSQL 백업 주기"           --domain maintenance
python search.py "OOM 장애 대응 방법"             --domain incident

# LLM 응답 없이 검색 결과만 출력
python search.py "모니터링 알람 설정" --no-answer
```

---

## 설정 파일 (`config.yaml`)

`config.yaml` 은 파이프라인 전체의 **단일 진실 출처(Single Source of Truth)** 입니다.  
`domains` 리스트가 DomainFilter 의 유효 도메인과 자동 동기화됩니다.

```yaml
model:
  base_url: http://127.0.0.1:8000/v1  # server.managed=false 일 때 사용
  api_key: sk-no-key-required
  model_name: mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit
  max_tokens: 4096
  temperature: 0.1
  top_p: 0.9

server:                               # LLM 서버 자동 기동 설정
  managed: true                       # false → 외부 서버 재사용
  model_path: mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit
  host: 0.0.0.0
  port: 8000
  backend: mlx_lm                     # mlx_lm | mlx_vllm
  trust_remote_code: false
  extra_args: []                      # 추가 CLI 인수 (예: ["--log-level", "debug"])
  startup_timeout: 180                # 초 — 대형 모델은 120~180초 소요

logging:
  llm_log_enabled: true               # false 로 변경 시 llm_*.log 생성 안 함

pipeline:
  input_dir: ./as_is
  output_dir: ./to_be
  log_dir: ./logs
  max_chunk_tokens: 8000
  overlap_tokens: 200
  max_retries: 2
  keyword_retention_threshold: 0.7
  resume: true
  concurrency: 1

judge:
  enabled: true
  max_tokens: 1024
  on_error: fail                      # "skip" 으로 변경 시 판정 실패 무시
  judge_input_chars: 6000

search:                               # SearXNG 웹 검색 보강 (선택)
  enabled: false
  base_url: http://localhost:8080
  timeout: 10
  max_results: 5

domains:                              # 이 목록이 DomainFilter 유효 도메인과 동기화됨
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
  chunk_size_h2: true
  top_k_dense: 10
  top_k_bm25: 10
  top_k_rerank: 5
  rrf_k: 60
  reranker_model: BAAI/bge-reranker-v2-m3
  answer_max_tokens: 2048
  bm25_index_path: ./qdrant_db/bm25_index.pkl
```

---

## 주요 모듈

### 의존성 방향 (Clean Architecture)

```
[pipeline.py]  ─── 조립(Composition Root)
      │
      ├── ModelServer                          ← 서버 생애주기 관리
      ├── LLMLogger                            ← LLM 대화 전체 기록
      ├── DomainFilter(LLMClientPort)          ← 추상에 의존
      ├── Refiner(LLMClientPort, AugmenterPort)
      ├── JudgeLLM(LLMClientPort)
      ├── SearchAugmenter(LLMClientPort, WebSearchClientPort)
      │
      └── LLMClient implements LLMClientPort   ← 구체 클래스는 최외곽에만
```

도메인 레이어는 `ports.py` 의 추상 인터페이스에만 의존합니다.  
LLM 또는 검색 엔진 교체 시 `llm_client.py` / `web_search.py` 구현체만 수정하면 됩니다.

### `src/model_server.py` — ModelServer

`mlx_lm.server` 또는 `mlx_vllm` 서버를 하위 프로세스로 자동 기동·종료합니다.

| 메서드 / 속성 | 역할 |
|---|---|
| `from_config(cfg)` | `AppConfig.server` 섹션으로 인스턴스 생성 |
| `start()` | 하위 프로세스로 서버 런치 |
| `wait_ready(timeout)` | `/health` 엔드포인트 폴링 — 준비 완료까지 대기 |
| `stop()` | SIGTERM → (10초) → SIGKILL 순서로 안전 종료 |
| `base_url` | LLMClient 에 주입할 OpenAI-compatible URL |
| context manager | `with server:` 사용 시 자동 start / stop |

`managed: false` 설정 시 외부에서 이미 기동한 서버를 그대로 재사용합니다.

### `src/llm_logger.py` — LLMLogger

LLM 호출 1건당 system prompt · user prompt · 응답 전체를 `llm_*.log` 에 기록합니다.

```
logs/
├── pipeline_run_20260619_101500.jsonl   ← 파이프라인 요약 로그 (기존)
└── llm_20260619_101500.log              ← LLM 전체 대화 로그 (신규)
```

`llm_*.log` 블록 형식:

```
========================================================================
[2026-06-19 10:15:32 UTC] CALL #3  stage=refine  file=k8s_runbook.md
========================================================================
--- SYSTEM ---
<system prompt 전체>
--- USER ---
<user prompt 전체>
--- ASSISTANT ---
<LLM 응답 전체>
(tokens: prompt=1847  completion=623  total=2470  finish=stop)
========================================================================
```

`logging.llm_log_enabled: false` 설정 시 파일 생성 없이 no-op 으로 동작합니다.

### `src/judge.py` — JudgeLLM

정제 완료된 문서를 세 가지 기준으로 LLM 판정합니다.

| 기준 | 설명 |
|---|---|
| `faithfulness` | 정제 문서의 모든 수치·명령·버전이 원본에 존재하는가 |
| `completeness` | 원본의 안전-임계 정보가 정제 문서에 빠짐없는가 |
| `structure_ok` | YAML front-matter + H2 섹션 구조가 유효한가 |

판정 실패 시 `retry_hint` 를 포함한 `JudgeVerdict` 를 반환하고 Refiner 가 재시도합니다.  
LLM 호출 실패 또는 JSON 파싱 실패 시 `JudgeError` 를 발생시켜 호출측에서 `on_error` 정책을 선택하게 합니다.

### `src/pipeline_runner.py` — DocumentRunner

단일 문서의 전체 파이프라인을 실행하는 책임만 가집니다.

| 메서드 | 역할 |
|---|---|
| `run(doc)` | 진입점. 예외를 잡아 `"success"` / `"skip"` / `"fail"` 반환 |
| `_execute()` | 도메인 필터 → 추출 → refine 루프 → 저장 |
| `_run_refine_loop()` | refine → validate → judge 반복 루프 |
| `_run_judge()` | Judge 단독 실행 + `on_judge_error` 정책 처리 |
| `_maybe_extract()` | `is_partial` 문서에서 도메인 관련 섹션만 추출 |

### `src/pipeline_io.py` — PipelineIO

I/O 책임만 담당하는 독립 모듈입니다.

- `init_dirs()` — 출력/로그 디렉터리 생성
- `open_log(run_ts)` — JSONL 로그 파일 열기 (LLMLogger 와 동일 타임스탬프 공유)
- `write_log(entry)` — thread-safe JSONL 로깅. `open_log()` 미호출 시 경고 출력
- `save_output()` — 도메인별 출력 폴더에 정제 문서 저장

---

## 로그 분석

`logs/` 의 JSONL 파일을 분석하는 CLI 도구입니다.

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

JSONL 로그 항목 스키마:

```jsonc
{
  "timestamp":    "2026-06-19T00:00:00+00:00",
  "source_file":  "example.md",
  "stage":        "done",                 // start | domain_filter | extract | refine | structure_validate | judge | done
  "status":       "success",              // processing | success | skip | fail
  "domain":       ["incident"],
  "output_files": ["to_be/incident/example.md"],
  "retry_count":  0,
  "tokens_in":    3200,
  "tokens_out":   1850,
  "duration_sec": 12.4,
  "error":        null,
  "judge": {
    "passed":       true,
    "faithfulness": true,
    "completeness": true,
    "structure_ok": true,
    "critique":     "PASS",
    "retry_hint":   "none",
    "attempt":      0
  }
}
```

---

## 의존성

| 패키지 | 용도 |
|---|---|
| `mlx-lm` | Apple Silicon LLM 추론 서버 (`mlx_lm` 백엔드) |
| `mlx-vllm` *(선택)* | vLLM 호환 추론 서버 (`mlx_vllm` 백엔드, `--test` 기본) |
| `openai` | OpenAI-compatible REST 클라이언트 |
| `FlagEmbedding` | bge-m3 임베딩 / bge-reranker-v2-m3 |
| `qdrant-client` | 로컬 벡터 DB |
| `rank-bm25` | BM25 희소 검색 |
| `pydantic` | 설정 모델 검증 |
| `PyYAML` | config.yaml 파싱 |
| `requests` | ModelServer 헬스체크 + SearXNG 웹 검색 |
| `tiktoken` *(선택)* | 정확한 토큰 계산 (미설치 시 근사값 사용) |

---

## 변경 이력

### v1.0 (2026-06-19)

**정제 파이프라인 안정성·확장성 대폭 강화**

#### 초기 릴리스 (아키텍처 재설계)

- **Clean Architecture 적용** — `ports.py` 에 `LLMClientPort`, `AugmenterPort` 추상 인터페이스 추가.  
  도메인 레이어(DomainFilter, Refiner, JudgeLLM, SearchAugmenter)가 구체 클래스에 의존하지 않음
- **OCP 준수 — DomainFilter** — 유효 도메인 목록을 하드코딩에서 `config.yaml` 주입으로 변경.  
  도메인 추가 시 소스 수정 불필요
- **JudgeLLM 도입** — 충실성/완전성/구조 3개 기준 LLM 판정 + `retry_hint` 피드백 루프.  
  판정 실패 시 `JudgeError` 명시적 발생 (silent false-positive 제거)
- **SearchAugmenter 도입** — SearXNG 로컬 인스턴스와 연동하여 정제 문서를 실시간 웹 정보로 보강
- **`judge_input_chars` 설정화** — Judge 에 전달하는 문서 트런케이션 상한을 `config.yaml` 로 외부화
- **`write_log()` 안전성 강화** — `open_log()` 미호출 시 무음 데이터 손실 → 경고 메시지 출력으로 변경
- **SRP 분리** — `pipeline.py` God-class 를 `pipeline_io.py`, `pipeline_runner.py`, `pipeline.py` 3개로 분리.  
  `_execute()` 내 refine 루프를 `_run_refine_loop()`, `_run_judge()`, `_maybe_extract()` 로 추가 분리
- **`on_judge_error` 정책** — Judge 오류 시 `"skip"`(무시) 또는 `"fail"`(실패) 선택 가능

#### ModelServer — LLM 서버 자동 기동

- **`src/model_server.py` 신규** — `mlx_lm.server` / `mlx_vllm` 서버를 하위 프로세스로 자동 기동·종료.  
  `run.py` 실행만으로 서버 수동 기동 불필요
- **`config.yaml` `server:` 섹션 추가** — `managed`, `model_path`, `backend`, `port`, `startup_timeout`, `extra_args` 설정
- **`managed: false` 지원** — 외부에서 이미 기동한 서버(다른 머신 포함) 재사용 가능
- **`AppConfig.resolved_model_path()` / `resolved_base_url()` 추가** — `server` 섹션 설정 기반 주소 자동 결정

#### LLM 응답 전체 로깅

- **`src/llm_logger.py` 신규** — LLM 호출 1건당 system/user prompt + 응답 + 토큰 통계를 `llm_*.log` 에 기록.  
  `pipeline_run_*.jsonl` 과 동일 타임스탬프로 로그 파일 쌍 생성
- **`LLMClient` 에 `LLMLogger` 주입** — 정상 응답과 빈 응답(`<EMPTY RESPONSE>`) 모두 기록.  
  `stage`, `source_file` 컨텍스트 정보 함께 기록
- **`config.yaml` `logging.llm_log_enabled`** — `false` 설정 시 no-op 으로 동작 (런타임 오버헤드 없음)

#### 테스트 모드 CLI

- **`--test` 플래그 추가** — `google/gemma-4-E2B-it` 모델을 `mlx_vllm` 백엔드, 포트 `8001` 로 자동 기동.  
  프로덕션(포트 8000)과 동시 실행 가능, LLM 응답 로깅 항상 활성
- **`TestPreset` dataclass** — 테스트 설정을 소스 최상단에 명시적으로 선언.  
  CLI 우선순위: `config.yaml` < `--test` < `--backend` / `--no-server`

---

## 라이선스

MIT
