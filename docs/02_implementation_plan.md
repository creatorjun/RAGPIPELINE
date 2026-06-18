# 구현 계획 — 단계별 체크리스트

## 개발 환경 요구사항

| 항목 | 최소 사양 | 권장 사양 |
|---|---|---|
| 하드웨어 | Apple Silicon M3 Pro | M4 Max 36GB |
| OS | macOS 14 | macOS 15 이상 |
| Python | 3.11 | 3.12 |
| 디스크 | 30GB 여유 | 50GB 이상 |

---

## Phase 0 — 환경 설정

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

pip install huggingface_hub
huggingface-cli login

huggingface-cli download mlx-community/gemma-4-26b-moe-instruct-4bit \
  --local-dir ./models/gemma-4-26b-moe
```

체크리스트:
- [ ] Python 버전 확인
- [ ] mlx-lm import 확인
- [ ] 모델 폴더 확인
- [ ] 모델 로드 테스트

---

## Phase 1 — 소규모 파일럿 테스트

```bash
mkdir -p as_is
cp /path/to/internal/docs/sample*.md ./as_is/
python run.py --input-dir ./as_is --output-dir ./to_be
```

검증 포인트:
- [ ] 도메인 분류 결과 확인
- [ ] 출력 폴더 생성 확인
- [ ] YAML front-matter 확인
- [ ] 키워드 보존율 평균 70% 이상
- [ ] 실패 문서 원인 분석

튜닝 기준:

| 지표 | 낮으면 | 조치 |
|---|---|---|
| 도메인 분류 정확도 | 오분류 증가 | keywords 보강 |
| 키워드 보존율 | 수치/버전 누락 | threshold 완화 또는 프롬프트 강화 |
| 처리 속도 | 너무 느림 | max_tokens 축소 |

---

## Phase 2 — 전체 문서 일괄 처리

```bash
cp -r /path/to/all/internal/docs/*.md ./as_is/
nohup python run.py > ./logs/stdout.log 2>&1 &
tail -f ./logs/stdout.log
```

예상 처리 속도:
- 문서 1건당 30~90초
- 100건 기준 약 1~2.5시간

완료 후 검증:
- [ ] 실패 문서 목록 추출
- [ ] 각 도메인 폴더 문서 수 확인
- [ ] 샘플링 품질 검토

---

## Phase 3 — RAG 임베딩 연동

후속 파이프라인:
1. `to_be/**/*.md` 로드
2. H2 기준 청킹
3. bge-m3 임베딩 생성
4. Qdrant 저장
5. BM25 병행 구축
6. Hybrid 검색 + RRF + Re-ranker
7. 로컬 LLM 응답 생성

추가 패키지:
- sentence-transformers
- qdrant-client
- rank-bm25
- FlagEmbedding

---

## 로그 분석 명령어

```bash
cat logs/pipeline_run_*.jsonl | python3 -c "
import sys, json
from collections import Counter
rows = [json.loads(x) for x in sys.stdin]
status = Counter(r['status'] for r in rows)
print(status)
"

cat logs/pipeline_run_*.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    if r['status'] == 'fail':
        print(r['source_file'], r['error'])
"
```