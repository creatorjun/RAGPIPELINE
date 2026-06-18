# 장애 보고서 — Redis OOM으로 인한 캐시 전면 장애 (2025-01-08)

사업팀에서 당일 저녁 매출 통계 이상하다고 먼저 연락 왔음.
영업팀 연초 프로모션이랑 겹쳐서 피해가 더 컸음 — 사후 협의 필요.

## 장애 개요

| 항목 | 내용 |
|---|---|
| 발생 일시 | 2025-01-08 19:47 KST |
| 복구 일시 | 2025-01-08 21:03 KST |
| 영향 시간 | 76분 |
| 영향 범위 | 전체 캐시 계층 다운 → DB 직접 쿼리 폭증 → 주문 서비스 응답 지연 |
| 심각도 | SEV-1 |

## 장애 타임라인

- **19:47** — Redis OOM Killer 발생, 프로세스 종료
- **19:49** — 캐시 미스 폭증, DB 커넥션 풀 고갈 알람 발생
- **19:52** — 주문 서비스 503 에러율 80% 초과
- **20:01** — 온콜 SEV-1 에스컬레이션
- **20:08** — Redis 재시작, `maxmemory-policy` 설정 확인
- **20:15** — Redis `maxmemory` 미설정 확인 → 즉시 설정 적용
- **20:31** — DB 커넥션 정상화, 주문 서비스 회복 시작
- **21:03** — 전면 정상화 확인

## 근본 원인 (RCA)

### 직접 원인

Redis 인스턴스에 `maxmemory` 설정이 누락되어 메모리 무제한 증가.
연초 프로모션으로 세션 데이터 및 캐시 키 급증 → 컨테이너 메모리 한계(8GB) 초과 → OOM Killer 발생.

### 설정 누락 경위

12월 인프라 마이그레이션 시 Redis 설정 파일을 신규 ConfigMap으로 교체하는 과정에서
`maxmemory` 및 `maxmemory-policy` 항목이 누락됨. 마이그레이션 검증 체크리스트에 해당 항목 없었음.

### 연쇄 장애 경로

```
Redis OOM → 프로세스 종료
  → 캐시 계층 전면 다운
  → 모든 요청이 DB 직접 조회
  → DB 커넥션 풀 고갈 (max_connections 200 초과)
  → 주문 서비스 요청 대기 → 503 에러
```

## 복구 절차

### 즉시 조치

```bash
# Redis maxmemory 설정 적용 (재시작 없이)
redis-cli CONFIG SET maxmemory 6gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru
redis-cli CONFIG REWRITE
```

### ConfigMap 수정 (영구 반영)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
data:
  redis.conf: |
    maxmemory 6gb
    maxmemory-policy allkeys-lru
    save 900 1
    save 300 10
    appendonly yes
```

## 재발 방지 대책

| 항목 | 담당 | 기한 |
|---|---|---|
| Redis 설정 검증 항목 체크리스트 추가 (maxmemory 포함) | 인프라팀 | 2025-01-15 |
| Redis 메모리 사용률 80% 알람 추가 | 모니터링팀 | 2025-01-12 |
| DB 커넥션 수 알람 추가 (75% 초과 시 경고) | 모니터링팀 | 2025-01-12 |
| 캐시 장애 시 Circuit Breaker 패턴 적용 검토 | 백엔드팀 | 2025-02-28 |
| 인프라 마이그레이션 후 검증 자동화 스크립트 구축 | 인프라팀 | 2025-02-14 |
| 영업 프로모션 일정 → 인프라팀 사전 공유 프로세스 수립 | 사업팀 | 2025-01-22 |
