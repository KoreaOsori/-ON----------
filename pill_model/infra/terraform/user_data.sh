#!/bin/bash
# 워커 EC2 최초 부팅 시 1회 실행: Docker·git·compose 설치, 작업 폴더 준비.
# 앱 배포(git clone → fetch_models → docker compose up)는 SSM 접속 후 사람이 한다 (PLAN 5단계).
set -euxo pipefail

dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user

# AL2023 저장소에는 compose 플러그인이 없어서 GitHub 릴리스에서 버전 고정으로 설치
# buildx 도 같이 설치 (최신 compose 의 build 가 buildx 를 요구함)
COMPOSE_VERSION=v2.29.7
BUILDX_VERSION=v0.17.1
PLUGIN_DIR=/usr/local/lib/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"
curl -fsSL -o "$PLUGIN_DIR/docker-compose" \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64"
curl -fsSL -o "$PLUGIN_DIR/docker-buildx" \
  "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64"
chmod +x "$PLUGIN_DIR/docker-compose" "$PLUGIN_DIR/docker-buildx"

# 저장소를 받을 폴더 (ec2-user 소유)
mkdir -p /opt/pill_model
chown ec2-user:ec2-user /opt/pill_model

docker --version
docker compose version
