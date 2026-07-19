#!/usr/bin/env bash
# perfSONAR testpoint 起動スクリプト (RasPi / Linux VM 共用)
# 前提: 64bit OS (aarch64), Docker, cgroup v2
set -euo pipefail

IMAGE="perfsonar/testpoint:systemd"
NAME="perfsonar-testpoint"
PSCONFIG_DIR="${HOME}/psconfig"   # pSConfig をホスト側で永続化

mkdir -p "${PSCONFIG_DIR}"
docker pull "${IMAGE}"
docker rm -f "${NAME}" 2>/dev/null || true

docker run -td --name "${NAME}" \
  --net=host \
  --tmpfs /run --tmpfs /run/lock --tmpfs /tmp \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw --cgroupns host \
  -v "${PSCONFIG_DIR}:/etc/perfsonar/psconfig" \
  --cap-add CAP_NET_RAW \
  --restart unless-stopped \
  "${IMAGE}"

echo "--- waiting for services ---"
sleep 20
docker exec "${NAME}" pscheduler troubleshoot || true
