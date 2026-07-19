# Runbook W1: 環境構築〜疎通〜スキーマ観察

対象期間: 〜7/26。実行主体は Claude Code + ユーザー（アカウント取得・物理作業はユーザー）。
各ステップは独立して再開可能。詰まったら無理に進めず experiments/ にメモを残す。

## Step 0: Splunk O11y Free Edition 取得【ユーザー作業】

1. https://www.splunk.com/ja_jp/download/observability-cloud-free-edition.html からサインアップ
   - ※「14日間トライアル」ではなく「Free Edition」であること
2. ログイン後の URL `app.<realm>.signalfx.com` から realm を控える
3. Settings → Access Tokens → INGEST トークンを発行
4. リポジトリ直下で `cp .env.example .env` し、realm とトークンを記入
5. CLAUDE.md の環境インベントリ（realm）を更新

## Step 1: RasPi 準備

```bash
# 1-1. 64bit 確認（aarch64 でなければ OS 入れ替えが必要 → ユーザーへエスカレーション）
ssh <raspi> 'uname -m && cat /etc/os-release | head -2'

# 1-2. cgroup v2 確認（"cgroup2fs" が期待値）
ssh <raspi> 'stat -fc %T /sys/fs/cgroup/'

# 1-3. Docker 未導入なら
ssh <raspi> 'curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER'

# 1-4. NTP 同期確認（chrony or systemd-timesyncd が同期済みであること）
ssh <raspi> 'timedatectl status'

# 1-5. testpoint 起動（deploy/raspi/run-testpoint.sh を scp して実行）
scp deploy/raspi/run-testpoint.sh <raspi>:~/ && ssh <raspi> 'bash run-testpoint.sh'

# 1-6. 起動確認
ssh <raspi> 'docker exec perfsonar-testpoint pscheduler troubleshoot'
```

**チェックポイント**: `pscheduler troubleshoot` が全項目 OK。NG 項目はログを experiments/w1-notes.md に記録。

## Step 2: Mac 側 Linux VM + testpoint

方針: Lima (Ubuntu 24.04 arm64)。**要件は「RasPi から VM に inbound で届くこと」**（twamp/iperf3 の双方向テストに必須）。

```bash
# 2-1. Lima インストール
brew install lima

# 2-2. ブリッジネットワーク構成
# Lima の LAN ブリッジには socket_vmnet が必要。
brew install socket_vmnet
# → deploy/mac/lima-testpoint.yaml（W1 で作成）に networks 設定を記述して limactl start
```

> **要検証ポイント**: socket_vmnet のブリッジ構成が不安定な場合のフォールバックは UTM で
> Ubuntu Server arm64 VM をブリッジ接続で立てる。どちらを採用したかと理由を
> experiments/w1-notes.md に記録（記事ネタ）。

```bash
# 2-3. VM 内で Docker + testpoint 起動（run-testpoint.sh を流用）
# 2-4. RasPi から VM へ ping / 逆方向 ping で LAN 到達性を確認
```

**チェックポイント**: RasPi ↔ VM で相互に ping 到達。VM の IP を CLAUDE.md に記入。

## Step 3: 手動疎通テスト

```bash
# VM 内または RasPi 内の testpoint コンテナから実行
# 3-1. twamp（本命。クロック非依存の RTT + ロス）
docker exec perfsonar-testpoint pscheduler task twamp --source <vm-ip> --dest <raspi-ip>

# 3-2. rtt（外部ターゲット。片端で完結）
docker exec perfsonar-testpoint pscheduler task rtt --dest 8091.info
docker exec perfsonar-testpoint pscheduler task rtt --dest 1.1.1.1

# 3-3. trace
docker exec perfsonar-testpoint pscheduler task trace --dest 1.1.1.1

# 3-4. iperf3（実行前にユーザー確認。深夜帯 or 許可を得て短時間）
docker exec perfsonar-testpoint pscheduler task throughput --source <vm-ip> --dest <raspi-ip>
```

**チェックポイント**: twamp / rtt / trace / throughput の 4 種が正常結果を返す。
RasPi 側スループットの実測値（~300Mbps 想定）をメモ。

## Step 4: HTTP archiver の生 JSON 観察

ブリッジ実装前に、pScheduler が POST してくる JSON の実物を確保する。

```bash
# 4-1. Mac 側で受け口を立てる（使い捨て）
python3 -c "
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, datetime
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        fn = f'docs/samples/{datetime.datetime.now():%Y%m%d-%H%M%S}.json'
        open(fn,'wb').write(body); print('saved', fn)
        self.send_response(200); self.end_headers()
HTTPServer(('0.0.0.0', 8000), H).serve_forever()
"

# 4-2. archiver 付きでタスク実行（twamp / rtt / throughput / trace の 4 種すべて）
docker exec perfsonar-testpoint pscheduler task \
  --archive '{"archiver": "http", "data": {"_url": "http://<mac-ip>:8000/", "op": "put"}}' \
  twamp --source <vm-ip> --dest <raspi-ip>
```

**チェックポイント**: 4 テスト種すべてのサンプル JSON が docs/samples/ に保存されている。

## Step 5: スキーマ確定

サンプル JSON を読み、docs/schema.md に以下を確定させる:
- 各テスト種の JSON 内で必要な値の JSONPath（RTT mean/max、loss ratio、bps、hop 数、run の end time）
- OTel メトリクス名・型・attributes へのマッピング表
- エラー run（測定失敗時）の JSON 形状と、ブリッジでの扱い（スキップ or エラーメトリクス化）

## Exit Criteria（W1 完了条件）

- [ ] Splunk realm / トークンが .env に設定済み、CLAUDE.md 更新済み
- [ ] RasPi・Mac VM 両方で testpoint が稼働、`pscheduler troubleshoot` OK
- [ ] 4 テスト種の手動疎通 OK
- [ ] 4 テスト種の archiver JSON サンプル取得済み
- [ ] docs/schema.md 初版確定（ブリッジ実装に着手できる状態）
