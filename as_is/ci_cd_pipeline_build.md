# CI/CD 파이프라인 구축 — GitLab + ArgoCD

## 개요

본 문서는 GitLab CI와 ArgoCD를 연동한 GitOps 기반 배포 파이프라인 구축 절차를 기술합니다.
대상: 마이크로서비스 신규 서비스 배포 자동화 (스테이징 / 프로덕션 환경)

사업 부서에서 배포 사이클 단축 요청 있었음 — 현재 주 1회 수동 배포를 자동화 목표.
영업팀 고객사 데모용 환경(staging-demo)도 동일 파이프라인으로 처리 예정.

## 아키텍처

```
Developer Push
    ↓
GitLab Repository
    ↓
GitLab CI Pipeline
  ├── 빌드 (Docker Build)
  ├── 단위 테스트
  ├── 이미지 취약점 스캔 (Trivy)
  └── 이미지 푸시 (GitLab Registry)
    ↓
GitLab CI가 Helm values 업데이트 (image tag)
    ↓
ArgoCD (GitOps Sync)
    ↓
Kubernetes Cluster
```

## GitLab CI 설정

### .gitlab-ci.yml

```yaml
stages:
  - build
  - test
  - scan
  - deploy

variables:
  IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

build:
  stage: build
  image: docker:24
  services:
    - docker:dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $IMAGE .
    - docker push $IMAGE

unit-test:
  stage: test
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - pytest tests/unit --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml

trivy-scan:
  stage: scan
  image: aquasec/trivy:latest
  script:
    - trivy image --exit-code 1 --severity HIGH,CRITICAL $IMAGE

update-helm-values:
  stage: deploy
  script:
    - git config user.email "ci@company.com"
    - git config user.name "GitLab CI"
    - |
      sed -i "s/tag:.*/tag: $CI_COMMIT_SHORT_SHA/" \
        helm/values-staging.yaml
    - git add helm/values-staging.yaml
    - git commit -m "ci: update image tag to $CI_COMMIT_SHORT_SHA"
    - git push
  only:
    - main
```

## ArgoCD 설정

### Application 등록

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myapp-staging
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://gitlab.company.com/infra/helm-charts.git
    targetRevision: HEAD
    path: myapp
    helm:
      valueFiles:
        - values-staging.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: myapp-staging
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### 프로덕션 배포 (수동 승인)

프로덕션은 자동 Sync를 비활성화하고 ArgoCD UI에서 수동 승인 후 동기화합니다.

```yaml
syncPolicy:
  automated: null  # 프로덕션은 수동 승인
```

## 롤백 절차

```bash
# 이전 이미지 태그로 Helm values 수동 수정 후 ArgoCD Sync
argocd app sync myapp-production --revision <이전 커밋 SHA>

# 또는 ArgoCD UI에서 History & Rollback 탭 사용
```

## 파이프라인 모니터링

- GitLab CI: `gitlab.company.com/<project>/-/pipelines`
- ArgoCD 대시보드: `argocd.company.com`
- Slack 알람: `#deploy-alerts` 채널 (성공/실패 웹훅)
