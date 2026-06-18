# 쿠버네티스 클러스터 구축 가이드 (On-Premise)

어제 영업팀에서 데모 환경 요청이 들어왔는데 일단 본 문서 기준으로 진행하면 될 것 같음.

## 개요

본 문서는 On-Premise 환경에서 Kubernetes 1.29 클러스터를 구축하는 절차를 기술합니다.
OS는 Ubuntu 22.04 LTS 기준이며 Control Plane 1노드, Worker 3노드 구성입니다.

## 사전 요구사항

- CPU: 각 노드 최소 2 Core
- RAM: Control Plane 8GB, Worker 노드 각 16GB 이상
- 디스크: /var 파티션 100GB 이상
- OS: Ubuntu 22.04 LTS (커널 5.15 이상)
- 네트워크: 노드 간 전용 VLAN, 인터넷 아웃바운드 허용

참고로 사업팀 쪽에서 비용 절감 요청 있었는데 일단 최소 사양으로 맞춰서 진행.

## 설치 절차

### 1단계: 공통 패키지 설치 (전 노드 동일)

```bash
sudo apt-get update && sudo apt-get install -y \
  apt-transport-https ca-certificates curl gpg

curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | \
  sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \
  https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | \
  sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

### 2단계: 컨테이너 런타임 설치 (containerd)

```bash
sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd
sudo systemctl enable containerd
```

### 3단계: 스왑 비활성화

```bash
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab
```

### 4단계: Control Plane 초기화

```bash
sudo kubeadm init \
  --pod-network-cidr=10.244.0.0/16 \
  --apiserver-advertise-address=<CONTROL_PLANE_IP>

mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

### 5단계: CNI 플러그인 설치 (Flannel)

```bash
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
```

### 6단계: Worker 노드 조인

Control Plane init 완료 후 출력되는 `kubeadm join` 명령어를 Worker 노드에서 실행합니다.

```bash
sudo kubeadm join <CONTROL_PLANE_IP>:6443 \
  --token <TOKEN> \
  --discovery-token-ca-cert-hash sha256:<HASH>
```

## 검증

```bash
kubectl get nodes
kubectl get pods -n kube-system
```

모든 노드 STATUS가 Ready, Pod가 Running이면 정상입니다.

## 주의사항

- kubeadm init 실패 시 `sudo kubeadm reset` 후 재시도
- 방화벽 규칙: 6443 (API), 2379-2380 (etcd), 10250 (kubelet) 포트 허용 필요
- 다음 주 영업 미팅 전까지 데모 환경 올려달라고 했는데 일정 확인 필요
