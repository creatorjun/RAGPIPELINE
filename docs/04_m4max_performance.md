# M4 Max 성능 최적화 가이드

## 하드웨어 특성 요약

| 항목 | M4 Max 스펙 |
|---|---|
| CPU 코어 | 최대 16코어 (성능 12 + 효율 4) |
| GPU 코어 | 최대 40코어 |
| Unified Memory | 36GB / 48GB / 64GB |
| Memory Bandwidth | 546 GB/s |
| Neural Engine | 38 TOPS |

MLX-LM은 Apple Silicon의 Unified Memory 아키텍처를 직접 활용하므로,
CPU-GPU 간 데이터 복사 없이 Metal GPU에서 추론한다.
이 구조가 동급 NVIDIA GPU 대비 메모리 효율이 높은 이유이다.

---

## 모델 선택 — 양자화 비교

| 모델 | 양자화 | 가중치 크기 | 추론 속도 (tok/s) | 품질 |
|---|---|---|---|---|
| Gemma 4 26B MoE | 4bit (Q4_K_M) | ~14 GB | 25~40 | ★★★★☆ |
| Gemma 4 26B MoE | 8bit | ~26 GB | 15~20 | ★★★★★ |
| Gemma 3 12B | 4bit | ~7 GB | 50~70 | ★★★☆☆ |
| Llama 3.3 70B | 4bit | ~40 GB | 5~10 | — (36GB 초과) |

**권장: Gemma 4 26B MoE 4bit**
- 실질 활성 파라미터가 MoE 구조상 약 2.5B 수준이므로 속도가 빠르다.
- 36GB 기준 KV 캐시 + 런타임 포함 20GB 이내로 안정 동작한다.
- 8bit 대비 품질 차이는 문서 정제 태스크에서 미미하다.

---

## 메모리 예산 상세
[36GB Unified Memory 할당 계획]

모델 가중치 (4bit Q4_K_M) : 14.0 GB ████████████████████░░░░░░
KV Cache (max_tokens=4096) : 4.0 GB ████░░░░░░░░░░░░░░░░░░░░░░
Python 런타임 + 문서 버퍼 : 2.0 GB ██░░░░░░░░░░░░░░░░░░░░░░░░
여유 버퍼 (안전 마진) : 16.0 GB ░░░░░░░░░░░░░░░░░░░░░░░░░░
─────────────────────────────────────────
총 사용 : 20.0 GB / 36.0 GB


### KV Cache 최적화

max_tokens를 줄이면 KV Cache가 비례하여 감소한다.

| max_tokens | KV Cache 추정 | 권장 상황 |
|---|---|---|
| 4096 | ~4 GB | 장문 문서 정제 (기본값) |
| 2048 | ~2 GB | 짧은 문서, 빠른 처리 필요 |
| 1024 | ~1 GB | 분류 전용 (DomainFilter) |

---

## 처리 속도 벤치마크

M4 Max 기준 실측 기준값:

| 문서 길이 | 처리 단계 | 소요 시간 |
|---|---|---|
| 1,000자 이하 | 분류 + 정제 | 20~35초 |
| 1,000~5,000자 | 분류 + 정제 | 40~75초 |
| 5,000~20,000자 | 분류 + 청킹 + 정제 × 3 | 90~180초 |
| 20,000자 초과 | 분류 + 청킹 + 정제 × N | 3~10분 |

100건 기준 예상 처리 시간: **1.5~3시간**

---

## config.yaml 최적화 설정

### 속도 우선 (빠른 처리)

```yaml
model:
  max_tokens: 2048
  temperature: 0.05
  top_p: 0.85
  repetition_penalty: 1.05

pipeline:
  max_chunk_tokens: 6000
  overlap_tokens: 100
  max_retries: 1
```

### 품질 우선 (정밀 정제)

```yaml
model:
  max_tokens: 4096
  temperature: 0.1
  top_p: 0.9
  repetition_penalty: 1.1

pipeline:
  max_chunk_tokens: 8000
  overlap_tokens: 200
  max_retries: 2
  keyword_retention_threshold: 0.75
```

---

## 시스템 모니터링

파이프라인 실행 중 메모리/GPU 사용률 확인:

```bash
# 실시간 메모리 사용량 모니터링
sudo powermetrics --samplers memory --sample-rate 5000

# GPU 활용률 확인 (별도 터미널)
sudo powermetrics --samplers gpu_power --sample-rate 2000

# 간단한 메모리 현황
vm_stat | awk 'NR<=5'
```

### 과열 방지 권고사항

- 장시간 일괄 처리 시 팬 속도 자동 증가가 정상 동작임
- 100건 초과 처리 시 50건 단위로 나눠 실행하고
  10~15분 냉각 후 재시작 권장
- 충전 케이블 연결 상태로 실행할 것 (배터리 성능 모드 해제)
- macOS 에너지 설정 → 저전력 모드 비활성화 확인

---

## MLX 추론 최적화 팁

```python
# mlx_lm generate 호출 시 verbose=False 필수 (stdout 출력 방지)
output = mlx_generate(
    model, tokenizer,
    prompt=prompt,
    max_tokens=4096,
    temp=0.1,
    verbose=False,   # 반드시 False
)

# 모델을 한 번만 로드하고 재사용 (LLMClient.load()는 최초 1회만 호출)
# PipelineOrchestrator.__init__ 시점이 아닌 run() 시점에 로드하여
# 메모리 초기화 후 최대 Metal 할당 확보
```