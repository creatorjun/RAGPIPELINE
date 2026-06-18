# 모니터링 시스템 구성 가이드 — Prometheus + Grafana

## 개요

본 문서는 Prometheus + Grafana + Alertmanager 스택을 Kubernetes 환경에 구성하는 절차를 기술합니다.
kube-prometheus-stack Helm 차트를 사용합니다.

사업팀/영업팀에서 SLA 보고서 요청이 잦아지고 있어 가용성 대시보드 별도 구성 검토 중.
일단 본 가이드는 기술 운영팀 내부용이며 사업팀 공유용 대시보드는 별도 작성 예정.

## 설치

```bash
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo update

helm install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values values-monitoring.yaml
```

### values-monitoring.yaml 핵심 설정

```yaml
prometheus:
  prometheusSpec:
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: standard
          resources:
            requests:
              storage: 100Gi

grafana:
  adminPassword: "<CHANGE_ME>"
  persistence:
    enabled: true
    size: 10Gi
  grafana.ini:
    server:
      root_url: https://grafana.company.com

alertmanager:
  config:
    global:
      slack_api_url: "<SLACK_WEBHOOK_URL>"
    route:
      receiver: slack-alerts
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
    receivers:
      - name: slack-alerts
        slack_configs:
          - channel: "#infra-alerts"
            send_resolved: true
```

## 주요 알람 룰

### 노드 알람

```yaml
groups:
  - name: node.rules
    rules:
      - alert: NodeMemoryUsageHigh
        expr: |
          (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)
          / node_memory_MemTotal_bytes > 0.90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "노드 메모리 사용률 90% 초과"

      - alert: NodeDiskUsageHigh
        expr: |
          (node_filesystem_size_bytes - node_filesystem_free_bytes)
          / node_filesystem_size_bytes > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "노드 디스크 사용률 85% 초과"
```

### API 서비스 알람

```yaml
      - alert: ApiHighErrorRate
        expr: |
          rate(http_requests_total{status=~"5.."}[5m])
          / rate(http_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "API 5xx 에러율 5% 초과"

      - alert: ApiHighLatency
        expr: |
          histogram_quantile(0.99,
            rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API P99 응답 시간 2초 초과"
```

## Grafana 대시보드

| 대시보드 | Grafana ID | 용도 |
|---|---|---|
| Kubernetes Cluster Overview | 7249 | 클러스터 전체 리소스 현황 |
| Node Exporter Full | 1860 | 노드별 CPU/메모리/디스크 |
| Kubernetes Pods | 6336 | 파드별 리소스 사용 |
| PostgreSQL Overview | 9628 | DB 성능 모니터링 |

## 운영 팁

- Prometheus retention은 기본 30일. 장기 보관이 필요하면 Thanos 또는 VictoriaMetrics 연동 검토
- Grafana 대시보드는 JSON export 후 Git 관리 권장
- alertmanager silence 설정: 정기 점검 시 불필요 알람 억제

```bash
amtool silence add --alertname="NodeDiskUsageHigh" \
  --duration=2h --comment="정기 디스크 점검"
```
