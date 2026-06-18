# 아키텍처 개요 — RAG 문서 정제 파이프라인

## 목적

사내 as_is 폴더의 Markdown 문서를 Apple M4 Max 로컬 환경에서 LLM을 이용해 자동으로 분석하고, 솔루션 구축(Build) / 유지보수(Maintenance) / 장애대응(Incident) 3개 도메인에 해당하는 지식만 추출하여 RAG 최적화 Markdown으로 정제 저장한다.

---

## 전체 데이터 흐름

as_is/
  *.md
   ↓
[1. DocumentLoader]
   ↓ 청크 분리
[2. DomainFilter]
   ↓ 도메인 분류
[3. Refiner.extract]  (PARTIAL일 때)
   ↓ 관련 섹션 추출
[4. Refiner.refine]
   ↓ RAG 최적화 MD 생성
[5. Validator]
   ↓ 검증 통과
[6. 파일 저장]
   ↓
to_be/{build|maintenance|incident}
logs/pipeline_run_*.jsonl

---

## 컴포넌트 상세

### 1. DocumentLoader (`src/loader.py`)

- MD 파일 로드, 정규화, H2 경계 청킹
- 입력: `as_is/**/*.md`
- 출력: `Document` 객체 (청크 포함)
- UTF-8 우선, CP949 폴백
- 8,000 토큰(대략 32,000자) 초과 시 H2 경계 기준으로 청크 분리
- 청크 간 200 토큰 오버랩 유지

### 2. DomainFilter (`src/domain_filter.py`)

- LLM 기반 도메인 분류
- 입력: 문서 앞 3,000자 미리보기
- 출력:
  {
    "domain": ["build", "incident"],
    "confidence": 0.92,
    "is_partial": false
  }

동작 규칙:
- `domain` 배열이 비어 있으면 스킵
- `is_partial: true` 이면 관련 섹션만 추출 후 후속 처리

### 3. Refiner (`src/refiner.py`)

- 관련 섹션 추출 + RAG 최적화 Markdown 정제
- 출력은 YAML front-matter 포함 Markdown

예시 front-matter:

---
title: "Kubernetes 클러스터 초기 구축 가이드"
domain: ["build"]
doc_type: "procedure"
keywords: ["kubernetes", "k8s", "클러스터", "설치", "kubeadm", "helm", "namespace"]
summary: "kubeadm 기반 Kubernetes 클러스터를 온프레미스 환경에 구축하는 절차를 설명한다."
source_file: "k8s_setup_guide.md"
refined_at: "2026-06-18"
---

청크 병합 전략:
1. 첫 번째 청크의 front-matter를 최종 문서 메타데이터로 사용
2. 이후 청크는 front-matter 제거 후 본문만 병합
3. 섹션 경계는 빈 줄 두 개로 연결

### 4. Validator (`src/validator.py`)

검증 항목:
- YAML front-matter 존재 여부
- 필수 필드 완전성
- 본문 길이 200자 이상
- H2 섹션 최소 1개 이상
- 키워드 보존율 70% 이상
- 원문에 없는 4자리 이상 숫자 과다 출현 시 환각 경고

### 5. PipelineOrchestrator (`src/pipeline.py`)

전체 흐름:
1. 문서 로드
2. 도메인 분류
3. 필요 시 부분 추출
4. 정제
5. 검증 및 재시도
6. 저장
7. JSONL 로그 기록

---

## 기술 스택

| 레이어 | 기술 | 선택 이유 |
|---|---|---|
| LLM 추론 | MLX-LM | Apple Silicon Metal 최적화 |
| LLM 모델 | Gemma 4 26B MoE 4bit | 로컬 품질/속도 균형 |
| 설정 관리 | Pydantic v2 + YAML | 타입 안전 |
| 로깅 | JSONL | 구조화 로그 |

---

## M4 Max 메모리 예산

| 항목 | 사용량 |
|---|---|
| Gemma 4 26B MoE 4bit 모델 가중치 | 약 14GB |
| KV 캐시 | 약 4GB |
| Python 런타임 + 문서 버퍼 | 약 2GB |
| 여유 메모리 | 약 16GB |

---

## 출력 디렉토리 구조

to_be/
├── build/
├── maintenance/
└── incident/

하나의 문서가 복수 도메인에 해당하면 각 도메인 폴더에 복사 저장한다.