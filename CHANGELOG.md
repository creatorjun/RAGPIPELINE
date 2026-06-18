# CHANGELOG

모든 주목할 만한 변경 사항을 이 파일에 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며,
버전 관리는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

---

## [Unreleased]

---

## [0.3.0] - 2026-06-18

### Added
- `src/web_search.py` — SearXNG HTTP 클라이언트 (`SearXNGClient`, `SearchResult`)
  - `search(query)` → `List[SearchResult]`
  - `format_for_prompt()` — LLM 프롬프트용 텍스트 직렬화
- `src/search_augmenter.py` — 2단계 LLM 웹 검색 보강 루프
  - 1단계: LLM이 문서를 보고 검색 필요 여부 및 쿼리를 JSON으로 판단
  - 2단계: SearXNG 검색 결과를 컨텍스트로 주입 후 문서 보강
  - 보강된 내용에 `[웹 참조 YYYY-MM-DD]` 주석 자동 삽입
- `config.yaml` — `search` 섹션 추가 (`enabled`, `base_url`, `timeout`, `max_results`)
- `src/config.py` — `SearchConfig` Pydantic 모델 추가

### Changed
- `src/refiner.py` — `Refiner.__init__`에 `augmenter` 옵셔널 파라미터 추가, `refine_document()` 마지막에 `augmenter.augment()` 호출
- `src/pipeline.py` — `SearXNGClient` + `SearchAugmenter` 생성 후 `Refiner`에 주입

---

## [0.2.0] - 2026-06-18

### Fixed
- `src/refiner.py` — `domain` 직렬화 버그 수정
  - 기존: `str(domains)` → YAML에 `"['build']"` 문자열로 삽입되어 `chunker.py` 파싱 시 리스트 타입 깨짐
  - 수정: `domains_yaml`을 명시적 YAML 리스트 형식(`- build`)으로 프롬프트에 주입

### Added
- `src/rag/models.py` — `RagChunk`에 `title: str = ""` 필드 추가
  - 문서 레벨 제목(`front-matter title`)을 청크에 전달하여 RAG 검색 시 문서 제목 컨텍스트 보존
- `src/rag/chunker.py` — front-matter에서 `title` 파싱 추가 (`meta.get("title", path.stem)`)
- `src/rag/chunker.py` — `keywords`, `domain` 타입 안전 처리 추가
  - LLM 출력이 문자열로 파싱되는 경우를 대비한 `isinstance(x, list) else [x]` 가드 적용

---

## [0.1.0] - 2026-06-18

### Added

#### 프로젝트 골격 (Phase 0 — 환경 설정)
- `run.py` — CLI 진입점 (`--input-dir`, `--output-dir` 옵션)
- `config.yaml` — 전체 설정 파일 (모델/파이프라인/도메인/용어집 경로)
- `requirements.txt` — 의존성 (`mlx-lm`, `pydantic>=2`, `PyYAML`)
- `glossary.yaml` — 사내 용어집 초기 버전
- 디렉터리 구조: `as_is/`, `to_be/`, `logs/`, `models/`

#### 파이프라인 레이어 (`src/`)
- `src/models.py` — `Document`, `DocumentChunk`, `FilterResult`, `ValidationResult` 데이터클래스
- `src/config.py` — Pydantic v2 `AppConfig` (YAML 파싱, `SearchConfig` 포함)
- `src/loader.py` — `DocumentLoader` (UTF-8/CP949 자동 감지, H2 단위 청킹, 오버랩)
- `src/llm_client.py` — MLX-LM 래퍼 (지연 로드, `_ensure_loaded()`)
- `src/domain_filter.py` — LLM 기반 도메인 분류 (JSON 파싱, `build`/`maintenance`/`incident`)
- `src/refiner.py` — 섹션 추출 + RAG MD 정제 + 청크 병합 로직
- `src/validator.py` — YAML/필드/본문 길이/H2/키워드 보존율/환각 검증 (6개 항목)
- `src/pipeline.py` — `PipelineOrchestrator` (전체 플로우 제어, JSONL 로그 기록)

#### RAG 레이어 (`src/rag/`)
- `src/rag/models.py` — `RagChunk`, `SearchResult`, `RagAnswer` 데이터클래스
- `src/rag/chunker.py` — front-matter 파싱 + H2 단위 청킹 → `RagChunk` 생성
- `src/rag/embedder.py` — 임베딩 인터페이스
- `src/rag/bm25_index.py` — BM25 스파스 인덱스
- `src/rag/vector_store.py` — 벡터 스토어 (Dense 검색)
- `src/rag/retriever.py` — Hybrid Retrieval (RRF 기반 BM25 + Dense 결합)
- `src/rag/indexer.py` — 인덱싱 파이프라인
- `src/rag/engine.py` — RAG 엔진 (검색 → 생성 통합)
- `src/rag/answer_generator.py` — LLM 기반 답변 생성
- `embed.py` — 인덱싱 실행 스크립트
- `search.py` — 검색 실행 스크립트

#### 테스트 데이터 (`as_is/`)
- `k8s_cluster_build.md` — Kubernetes On-Premise 클러스터 구축 (노이즈: 영업/사업팀 메모)
- `ci_cd_pipeline_build.md` — CI/CD 파이프라인 구축 (노이즈: 사업부 배포 사이클 단축 요청)
- `db_maintenance_guide.md` — PostgreSQL 정기 점검 가이드 (노이즈: 영업팀 월말 점검 금지 요청)
- `monitoring_setup.md` — Prometheus/Grafana 모니터링 구축 (노이즈: 사업팀 SLA 보고서 요청)
- `api_gateway_incident.md` — API Gateway 장애 보고서 (노이즈: 영업팀 고객사 클레임 메모)
- `redis_oom_incident.md` — Redis OOM 장애 보고서 (노이즈: 사업팀 매출 통계 문의)

---

[Unreleased]: https://github.com/creatorjun/RAGPIPELINE/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/creatorjun/RAGPIPELINE/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/creatorjun/RAGPIPELINE/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/creatorjun/RAGPIPELINE/releases/tag/v0.1.0
