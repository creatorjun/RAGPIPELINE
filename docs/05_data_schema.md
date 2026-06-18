# 데이터 스키마 명세

## 1. YAML Front-Matter 전체 필드 정의

정제된 to_be 문서 최상단에 반드시 포함되는 메타데이터 블록이다.

```yaml
***
title: string          # 필수 — 문서 핵심 주제 제목 (검색 결과 표시용)
domain: list[string]   # 필수 — ["build"|"maintenance"|"incident"] 배열
doc_type: string       # 필수 — 아래 허용값 중 택1
keywords: list[string] # 필수 — 5~10개 검색 키워드
summary: string        # 필수 — 2문장 이내 핵심 질문/답변 요약
source_file: string    # 필수 — 원본 파일명 (예: k8s_setup.md)
refined_at: string     # 필수 — 정제 날짜 YYYY-MM-DD
***
```

### doc_type 허용값

| 값 | 설명 |
|---|---|
| `runbook` | 반복 운영 작업의 단계별 절차서 |
| `architecture` | 시스템 구조/설계 문서 |
| `troubleshooting` | 문제 증상 → 원인 → 해결 방법 |
| `policy` | 운영 정책, 규정, 기준 문서 |
| `procedure` | 일회성 또는 주기적 수행 절차 |
| `reference` | API, 설정값, 명령어 레퍼런스 |

### 출력 예시

```yaml
***
title: "PostgreSQL 마스터-슬레이브 복제 장애 복구 절차"
domain: ["incident", "maintenance"]
doc_type: "runbook"
keywords: ["postgresql", "replication", "복제", "장애", "복구", "failover", "슬레이브", "마스터"]
summary: "PostgreSQL 스트리밍 복제 중단 시 슬레이브 재동기화 및 페일오버 절차를 설명한다. WAL 수신 오류부터 서비스 복원까지 전 과정을 다룬다."
source_file: "pg_replication_recovery.md"
refined_at: "2026-06-18"
***
```

---

## 2. Document 데이터 클래스

```python
@dataclass
class DocumentChunk:
    source_file: str    # 원본 파일명
    content: str        # 청크 텍스트
    chunk_index: int    # 0-based 순번
    total_chunks: int   # 전체 청크 수

@dataclass
class Document:
    source_file: str          # 원본 파일명
    content: str              # 전체 텍스트
    chunks: List[DocumentChunk]
```

---

## 3. FilterResult 데이터 클래스

```python
@dataclass
class FilterResult:
    domains: List[str]   # ["build", "incident"] 등
    confidence: float    # 0.0 ~ 1.0
    is_partial: bool     # True이면 섹션 추출 단계 진입
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `domains` | `List[str]` | 빈 배열이면 해당 문서 스킵 |
| `confidence` | `float` | 0.7 미만은 주의 (로그에 기록) |
| `is_partial` | `bool` | True이면 extract_domain_sections 호출 |

---

## 4. ValidationResult 데이터 클래스

```python
@dataclass
class ValidationResult:
    is_valid: bool                # 최종 통과 여부
    keyword_retention_rate: float # 0.0 ~ 1.0
    errors: List[str]             # 실패 사유 목록
```

### keyword_retention_rate 계산 방식

원본 텍스트에서 추출되는 키워드의 종류:
- 숫자 (버전, 포트, 크기 등) — 정규식 `\b\d+(?:\.\d+)?\b`
- 버전 문자열 — 정규식 `v?\d+\.\d+(?:\.\d+)?`
- 백틱 코드 — 정규식 `` `[^`]{2,30}` ``

보존율 = 정제 문서에 존재하는 원본 키워드 수 / 전체 원본 키워드 수

---

## 5. JSONL 로그 스키마

파이프라인 실행마다 `logs/pipeline_run_{YYYYMMDD_HHMMSS}.jsonl` 파일이 생성되고, 문서 1건당 1개의 JSON 라인이 기록된다.

```json
{
  "timestamp": "2026-06-18T12:30:00+09:00",
  "source_file": "k8s_setup.md",
  "stage": "domain_filter",
  "status": "success",
  "domain": ["build"],
  "output_files": ["./to_be/build/k8s_setup.md"],
  "retry_count": 0,
  "keyword_retention_rate": 0.87,
  "tokens_in": 1450,
  "tokens_out": 2100,
  "duration_sec": 42.3,
  "error": null
}
```

### status 값 정의

| 값 | 설명 |
|---|---|
| `success` | 정상 처리 완료 |
| `skip` | 관련 도메인 없거나 PARTIAL 추출 후 내용 없음 |
| `fail` | 최대 재시도 초과 또는 예외 발생 |
| `processing` | 실행 중 (완료 전 비정상 종료 시 이 상태로 남음) |

### 로그 분석 예시

```bash
# 도메인별 처리 건수
cat logs/pipeline_run_*.jsonl | python3 -c "
import sys, json
from collections import Counter
rows = [json.loads(x) for x in sys.stdin]
domain_cnt = Counter()
for r in rows:
    for d in r.get('domain', []):
        domain_cnt[d] += 1
for d, c in domain_cnt.most_common():
    print(f'{d}: {c}건')
"

# 토큰 사용량 합산
cat logs/pipeline_run_*.jsonl | python3 -c "
import sys, json
rows = [json.loads(x) for x in sys.stdin]
t_in  = sum(r['tokens_in']  for r in rows)
t_out = sum(r['tokens_out'] for r in rows)
print(f'입력 토큰 합계: {t_in:,}')
print(f'출력 토큰 합계: {t_out:,}')
"
```

---

## 6. config.yaml 전체 필드 정의

```yaml
model:
  path: string          # 모델 폴더 경로
  max_tokens: int       # LLM 최대 생성 토큰 (기본 4096)
  temperature: float    # 생성 온도, 낮을수록 결정론적 (기본 0.1)
  top_p: float          # nucleus sampling (기본 0.9)
  repetition_penalty: float  # 반복 억제 (기본 1.1)

pipeline:
  input_dir: string           # 입력 폴더
  output_dir: string          # 출력 폴더
  log_dir: string             # 로그 폴더
  max_chunk_tokens: int       # 청크 최대 토큰 (기본 8000)
  overlap_tokens: int         # 청크 오버랩 토큰 (기본 200)
  max_retries: int            # 검증 실패 시 최대 재시도 (기본 2)
  keyword_retention_threshold: float  # 키워드 보존율 하한 (기본 0.7)
  min_sections: int           # 최소 H2 섹션 수 (기본 1)
  min_doc_length: int         # 최소 본문 길이 in chars (기본 200)

domains:
  - name: string              # 도메인 식별자 (LLM 분류 결과와 매핑)
    output_folder: string     # to_be 하위 폴더명
    keywords: list[string]    # 도메인 관련 한국어 키워드 (참고용)

glossary_path: string         # 용어집 YAML 파일 경로
```