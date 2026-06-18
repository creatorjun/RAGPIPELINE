# 장애 보고서 — API Gateway 응답 지연 (2024-11-15)

영업팀에서 고객사 클레임 들어왔다고 난리남. 일단 RCA 정리해서 공유.
아래 내용 사업부 공유용으로 다시 다듬을 예정 — 현재는 기술 내부용.

## 장애 개요

| 항목 | 내용 |
|---|---|
| 발생 일시 | 2024-11-15 14:23 KST |
| 복구 일시 | 2024-11-15 15:41 KST |
| 영향 시간 | 78분 |
| 영향 범위 | 전체 API 엔드포인트 응답 지연 (P99 latency 12초 초과) |
| 심각도 | SEV-2 |

## 장애 타임라인

- **14:23** — 모니터링 알람: API Gateway P99 latency 5초 초과
- **14:27** — 온콜 엔지니어 인지, Slack #incident 채널 개설
- **14:35** — Upstream 서비스 전체 정상 확인, Gateway 레이어 집중 조사 시작
- **14:51** — rate limit Redis 인스턴스 connection pool 고갈 확인
- **15:02** — 임시 조치: rate limit 우회 설정 적용, 지연 완화 시작
- **15:20** — Redis max_connections 증설 (100 → 500) 및 connection pool 설정 수정 배포
- **15:41** — P99 latency 정상(200ms 이하) 복귀, 장애 종료 선언

## 근본 원인 (RCA)

### 직접 원인

API Gateway의 rate limit 모듈이 Redis에 매 요청마다 개별 connection을 생성하는 버그.
11월 배포(v2.3.1)에서 connection pool 재사용 코드가 실수로 제거됨.

### 트리거

평일 14시~15시 트래픽 피크 시간대 + 당일 마케팅 캠페인으로 평소 대비 180% 트래픽 유입.
(사업팀 캠페인 일정이 인프라팀에 사전 공유되지 않아 사전 스케일링 미실시)

### 연쇄 장애 경로

```
트래픽 급증
  → Redis connection 폭발적 증가
  → Redis connection pool 고갈
  → rate limit 응답 대기
  → API Gateway 쓰레드 블로킹
  → 전체 요청 지연
```

## 복구 절차

### 임시 조치 (15:02)

```yaml
# helm values patch — rate limit 우회
rateLimit:
  enabled: false
```

### 영구 조치 (15:20)

```python
# 수정 전 (버그)
def check_rate_limit(user_id: str) -> bool:
    conn = redis.Redis(host=REDIS_HOST)   # 매 호출마다 신규 연결
    return conn.get(f"rl:{user_id}")

# 수정 후
_pool = redis.ConnectionPool(host=REDIS_HOST, max_connections=50)

def check_rate_limit(user_id: str) -> bool:
    conn = redis.Redis(connection_pool=_pool)  # pool 재사용
    return conn.get(f"rl:{user_id}")
```

## 재발 방지 대책

| 항목 | 담당 | 기한 |
|---|---|---|
| Redis connection pool 사용 코드 리뷰 의무화 | 플랫폼팀 | 2024-11-22 |
| 사업팀 캠페인 일정 인프라팀 사전 공유 프로세스 수립 | 사업팀/인프라팀 | 2024-11-29 |
| Redis connection 수 알람 추가 (80% 초과 시 PagerDuty) | 모니터링팀 | 2024-11-22 |
| 스테이징 환경 부하 테스트 의무화 (배포 전) | 플랫폼팀 | 2024-12-06 |
| 트래픽 피크 사전 스케일링 자동화 (HPA 임계값 조정) | 인프라팀 | 2024-12-13 |
