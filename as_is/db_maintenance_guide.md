# PostgreSQL 운영 및 정기 점검 가이드

## 개요

본 문서는 운영 환경 PostgreSQL 15 인스턴스의 정기 점검, 백업, 성능 튜닝 절차를 정의합니다.
대상 환경: 상품 DB (prod-db-01), 주문 DB (prod-db-02)

영업팀 요청으로 월말 결산 기간(매월 28~31일)에는 점검 작업 금지 일정 공유 필요.

## 정기 점검 항목

### 일간 점검

```sql
-- 접속 수 확인
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

-- 장기 실행 쿼리 확인 (10분 이상)
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active'
  AND now() - query_start > interval '10 minutes';

-- 테이블 bloat 간이 확인
SELECT schemaname, tablename, n_dead_tup, n_live_tup
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
```

### 주간 점검

```sql
-- 인덱스 사용률
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC
LIMIT 20;

-- 캐시 히트율 확인 (95% 미만이면 shared_buffers 검토)
SELECT
  sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) AS cache_hit_ratio
FROM pg_statio_user_tables;
```

## 백업 절차

### 논리 백업 (pg_dump)

```bash
#!/bin/bash
BACKUP_DIR=/data/backup/postgres
DATE=$(date +%Y%m%d)

pg_dump -U postgres -Fc -d prod_db -f ${BACKUP_DIR}/prod_db_${DATE}.dump
find ${BACKUP_DIR} -name "*.dump" -mtime +30 -delete
```

- 실행 주기: 매일 02:00 cron
- 보관 기간: 30일
- 백업 확인: `pg_restore --list <파일>` 로 목록 검증

### WAL 아카이빙 (Point-in-Time Recovery)

`postgresql.conf` 설정:

```
wal_level = replica
archive_mode = on
archive_command = 'cp %p /data/wal_archive/%f'
restore_command = 'cp /data/wal_archive/%f %p'
```

## 성능 튜닝 파라미터

| 파라미터 | 권장값 | 설명 |
|---|---|---|
| shared_buffers | 전체 RAM의 25% | 버퍼 캐시 크기 |
| work_mem | 64MB | 정렬/해시 작업 메모리 |
| maintenance_work_mem | 512MB | VACUUM, 인덱스 빌드용 |
| effective_cache_size | 전체 RAM의 75% | 플래너 캐시 힌트 |
| checkpoint_completion_target | 0.9 | 체크포인트 분산 쓰기 |
| max_connections | 200 | 최대 접속 수 (pgBouncer 사용 시 더 줄일 것) |

사업 부서 쪽에서 신규 서비스 연동 예정이라 max_connections 증설 요청 검토 중.
pgBouncer 도입이 더 적합할 것 같음 — 별도 검토 문서 작성 예정.

## VACUUM 정책

```bash
# 수동 VACUUM ANALYZE (점검 시)
vacuumdb -U postgres -d prod_db --analyze --verbose

# autovacuum 상태 확인
SELECT schemaname, tablename, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY last_autovacuum ASC NULLS FIRST;
```

autovacuum이 비활성화된 테이블은 수동 VACUUM 스케줄을 별도 관리합니다.
