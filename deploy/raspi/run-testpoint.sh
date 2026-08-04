#!/usr/bin/env bash
# perfSONAR testpoint 起動スクリプト (RasPi / Linux VM 共用)
# 前提: 64bit OS (aarch64), Docker, cgroup v2
set -euo pipefail

IMAGE="perfsonar/testpoint:systemd"
NAME="perfsonar-testpoint"
PSCONFIG_DIR="${HOME}/psconfig"   # pSConfig をホスト側で永続化

# /etc/resolv.conf をホストから読み取り専用でマウントする理由:
# Docker はコンテナ生成時にホストの resolv.conf を「写す」ため、ホストの再起動直後
# （dhcpcd が nameserver を書く前）にコンテナが起動すると、**nameserver 行が空のまま
# 固定される**。そうなると pScheduler の limit processor が
#   Limit processor is not initialized: Resolver configuration could not be read
# で初期化に失敗し、psconfig-pscheduler-agent が NoResolverConfiguration で
# クラッシュループする。外から見ると「コンテナは Up、troubleshoot も途中まで OK」なので
# 気付きにくい。実際 2026-08-04 に RasPi の PoE 断による再起動でこれが起きた
# （experiments/w3-notes.md Step 20）。--net=host なのでホストの resolver が常に正しい。

mkdir -p "${PSCONFIG_DIR}"
docker pull "${IMAGE}"
docker rm -f "${NAME}" 2>/dev/null || true

docker run -td --name "${NAME}" \
  --net=host \
  --tmpfs /run --tmpfs /run/lock --tmpfs /tmp \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw --cgroupns host \
  -v "${PSCONFIG_DIR}:/etc/perfsonar/psconfig" \
  -v /etc/resolv.conf:/etc/resolv.conf:ro \
  --cap-add CAP_NET_RAW \
  --restart unless-stopped \
  "${IMAGE}"

echo "--- waiting for services ---"
sleep 20
docker exec "${NAME}" pscheduler troubleshoot || true
