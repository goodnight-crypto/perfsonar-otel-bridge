# perfsonar-otel-bridge

perfSONAR の測定結果を OpenTelemetry メトリクスに変換し、Splunk Observability Cloud に送信するブリッジと、自宅ラボでの検証環境一式。

「ネットワークパスをサービスとみなして SLO を張る」ことを目標に、pScheduler の HTTP archiver → 自作ブリッジ → OTel Collector → Splunk O11y というパイプラインを構築する。

> **Status**: パイプライン・ダッシュボード・Detector・障害注入実験まで完了（W2）。記事執筆中（W3）。
> Zenn コンテスト「OpenTelemetryの知見を、記事にしよう」Splunk Observability 部門向け。
> 企画意図・ロードマップは [PROJECT.md](./PROJECT.md)、判断と失敗の記録は
> [experiments/w2-notes.md](./experiments/w2-notes.md) を参照。

## アーキテクチャ

```
┌─ 自宅LAN ──────────────────────────────────────────┐
│                                                    │
│  Raspberry Pi 4B 4GB (有線)                         │
│   └ perfsonar/testpoint:systemd (arm64, --net=host)│
│                                                    │
│  Mac mini M4 16GB                                  │
│   ├ Linux VM (Lima, bridged network)                │
│   │   └ perfsonar/testpoint (arm64)                │
│   ├ bridge/ … pScheduler HTTP archiver 受け口       │
│   │           JSON → OTel Metrics 変換 (FastAPI)    │
│   └ OTel Collector contrib                          │
│        └ OTLP → Splunk Observability Cloud          │
└────────────────────────────────────────────────────┘
外部ターゲット: 8091.info (Cloudflare edge) / 1.1.1.1
```

測定は pSConfig テンプレート1枚（[deploy/psconfig/](./deploy/psconfig/)）で宣言的に定義し、
ダッシュボードと Detector も as-code（[deploy/splunk/](./deploy/splunk/)）で管理する。UI 作業はない。

送出するメトリクスは8種類。変換仕様は [docs/schema.md](./docs/schema.md)。

| メトリクス | テスト | クロック依存 |
|---|---|---|
| `perfsonar.rtt.mean` / `.max` | rtt（twping / ping） | なし |
| `perfsonar.packet.loss.ratio` | rtt | なし |
| `perfsonar.throughput.bps` / `.retransmits` | throughput（iperf3） | なし |
| `perfsonar.trace.hops` | trace（traceroute） | なし |
| `perfsonar.twamp.delay.median` | latency（twamp） | **あり**（下記の制約を参照） |
| `perfsonar.twamp.clock_error` | latency | — |

### 設計判断: LAN 基準線に片道遅延を使わない

当初は LAN 区間の基準線を twamp の片道遅延にする設計だったが、**`rtt` テストを
`--tool twping` で実行する**方式に変更した。RTT はクロック非依存で、両端の時刻同期の質に
結果が左右されないため。

片道遅延も送出はするが、**2段の品質ゲート**を通ったものだけに限る
（[bridge/psotel/convert.py](./bridge/psotel/convert.py)）:

- `clock_error <= 10ms` — 自己申告のクロック誤差の上限
- `0 < median <= 50ms` — 値そのものの妥当性（負値と非現実的な大きさを落とす）

自己申告の誤差は実際の誤差より小さく出るため、**値の妥当性検査が別に必要**だった。
経緯は [experiments/w2-notes.md](./experiments/w2-notes.md) の Step 5-2 / Step 7。

## 既知の制約

**Lima の VM は片道遅延の測定ノードとして使えない。** Lima のホストエージェントは10秒ごとに
ゲストのクロックを監視し、閾値（約100ms）を超えるとホスト時刻に強制上書きする。実測では
**約68秒に1回・中央値 123ms・最大 6,725ms** の上書きが発生していた。Lima 2.2.0 に
これを無効化する設定は無く、設計意図どおりの動作である。

測りたい量が 0.5ms オーダーの片道遅延に対して、これは致命的。RTT / ロス / スループット /
ホップ数はクロック非依存なので影響を受けない。詳細と確認手順は
[deploy/timesync/README.md](./deploy/timesync/README.md)、経緯は w2-notes.md の Step 17。

**時刻源はディストリ既定を信用しないこと。** Ubuntu 既定の `pool ntp.ubuntu.com` は
当環境からの実測 RTT が 256.8ms で、root dispersion が 37.7ms まで膨らんでいた。
近距離の時刻源に差し替える設定を [deploy/timesync/](./deploy/timesync/) に置いている。

## クイックスタート

> **このリポジトリの IP・ホスト名は作者の LAN 固有。** 再現するには少なくとも
> `deploy/psconfig/home-lab-mesh.json` の `addresses` と `archives.otel-bridge.data._url`
> （ブリッジを動かすホストの LAN IP）を自分の環境に合わせて書き換える必要がある。

### 1. Splunk のトークンを2種類用意する

Free Edition（15ホストまで無料・期間制限なし）で足りる。**INGEST トークンと
User API Access Token は役割が排他で、互いに代用できない。**

- INGEST トークン … データ送信用（Collector が使う）
- User API Access Token … ダッシュボード / Detector / メトリクス検索用（`apply.sh` が使う）

取得手順は [docs/setup-splunk-api-token.md](./docs/setup-splunk-api-token.md)。

### 2. `.env` を作る

```bash
cp .env.example .env
# SPLUNK_REALM / SPLUNK_ACCESS_TOKEN / SPLUNK_API_TOKEN を設定
```

**値の後ろにインラインコメントを書かないこと。** `docker --env-file` はコメントごと値として
渡すため、22文字のトークンが67文字になって Splunk が 401 を返す。

### 3. Splunk への疎通を先に確認する

ブリッジを動かす前にここを通す。以降の失敗をブリッジ側の問題と切り分けられる状態を作るのが目的。

```bash
set -a; . ./.env; set +a
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "https://ingest.${SPLUNK_REALM}.signalfx.com/v2/datapoint" \
  -H "Content-Type: application/json" -H "X-SF-Token: ${SPLUNK_ACCESS_TOKEN}" \
  -d '{"gauge":[{"metric":"perfsonar.bridge.selftest","value":1}]}'
# 期待: HTTP 200
```

### 4. testpoint を2ノードに立てる

```bash
# Raspberry Pi（64bit OS・Docker・cgroup v2 が前提）
scp deploy/raspi/run-testpoint.sh <user>@<raspi>:~/
ssh <user>@<raspi> 'bash run-testpoint.sh'

# Mac 側の Linux VM（Lima。bridged network で LAN から到達可能にする）
limactl start --name=perfsonar-vm deploy/mac/lima-testpoint.yaml
limactl shell perfsonar-vm bash -lc 'bash /path/to/repo/deploy/raspi/run-testpoint.sh'
```

`run-testpoint.sh` は RasPi と VM で共用できる。**pSConfig をホスト側の `~/psconfig` に
volume マウントする**ので、コンテナを作り直しても設定が消えない。

### 5. VM の時刻源を直す

```bash
# deploy/timesync/README.md の手順。省略すると片道遅延が常時ゲートで落ちる
limactl shell perfsonar-vm bash -lc '
  sudo cp /path/to/repo/deploy/timesync/chrony-home-lab.conf /etc/chrony/conf.d/10-home-lab.conf
  sudo cp -n /etc/chrony/chrony.conf /etc/chrony/chrony.conf.orig
  sudo sed -i -E "s@^(pool .*)\$@#\1@" /etc/chrony/chrony.conf
  sudo systemctl restart chrony'
```

### 6. ブリッジと Collector を起動する

```bash
set -a; . ./.env; set +a                       # 忘れると compose が明示的に停止する
docker compose -f deploy/mac/compose.yaml up -d --build
```

**ブリッジの公開ポートは 8088**（コンテナ内は 8000）。archiver の `_url` もこれを指す。
`env_file` は使わないこと（上記のインラインコメント混入の理由）。

### 7. pSConfig を両ノードに配る

手順とハマりどころは [deploy/psconfig/README.md](./deploy/psconfig/README.md)。

**ホスト側 `~/psconfig` が空だとイメージ既定の設定ファイルが隠れてエージェントが
起動できない**ので、必ず3ファイルを置く。

```bash
limactl shell perfsonar-vm docker exec perfsonar-testpoint \
  psconfig validate /etc/perfsonar/psconfig/home-lab-mesh.json   # 配置前に必ず通す
```

### 8. ダッシュボードと Detector を投入する

```bash
./deploy/splunk/apply.sh --dry-run   # 送信せず差分を見る
./deploy/splunk/apply.sh             # チャート → ダッシュボード → Detector
```

冪等。生成された ID は `deploy/splunk/.ids.json` に記録され、2回目以降は同じ ID に PUT する。

### 9. 着弾を確認する

「エラーが出ていない」は着弾の証明にならないので、実数を見る。

```bash
# Collector の内部テレメトリ
docker run --rm --network container:psotel-collector busybox \
  wget -q -O- http://localhost:8888/metrics 2>/dev/null \
  | grep -E "^otelcol_(exporter_sent|exporter_send_failed|receiver_accepted|receiver_refused)_metric_points"

# 各チャートの programText を実際に評価してデータが返るか
./deploy/splunk/check-charts.sh

# Detector の状態と発火履歴
./deploy/splunk/check-alerts.sh
```

## リポジトリ構成

```
├ README.md            # 本ファイル
├ LICENSE              # MIT
├ CLAUDE.md            # Claude Code 向け運用ガイド（環境・規約・ガードレール）
├ PROJECT.md           # 企画概要・ロードマップ・記事構成案・公開前チェックリスト
├ .gitleaks.toml       # secrets scan の追加ルール（Splunk トークン用）
├ bridge/              # FastAPI ブリッジ実装（pytest 48件）
├ deploy/
│  ├ raspi/            # testpoint 起動スクリプト（RasPi / VM 共用）
│  ├ mac/              # Lima VM / Collector / bridge の compose 構成
│  ├ vm/               # VM の OS 側設定（chrony の時刻源）
│  ├ psconfig/         # pSConfig テンプレート（測定定義の正）
│  └ splunk/           # ダッシュボード / チャート / Detector（as-code）
├ docs/
│  ├ runbook-w1.md     # Week1 手順書（環境構築〜疎通〜スキーマ観察）
│  ├ runbook-w2.md     # Week2 手順書（パイプライン・可視化・検知・障害注入）
│  ├ schema.md         # perfSONAR JSON → OTel メトリクス変換仕様
│  ├ setup-splunk-api-token.md
│  ├ raspi-kitting.md
│  ├ samples/          # HTTP archiver の生 JSON サンプル
│  └ screenshot/       # 記事用スクリーンショット
└ experiments/         # 検証メモ（判断と失敗の一次記録）
   ├ w1-notes.md
   └ w2-notes.md
```

## 前提環境

| ノード | 要件 |
|---|---|
| Raspberry Pi 4B 4GB | 64bit OS (`uname -m` = `aarch64`)、Docker、cgroup v2 |
| Mac mini (Apple Silicon) | Lima 2.0+（LAN からブリッジ到達可能な VM）、Docker Desktop |
| Splunk Observability Cloud | Free Edition（15 ホストまで無料・期間制限なし） |

RasPi は SD カード運用なのでログとDBの増加に注意。testpoint イメージ側は logrotate まで
面倒を見てくれるが、**自分で足した compose 側には上限が無かった**（w2-notes.md Step 9）。

## テスト

```bash
cd bridge && uv run pytest -q     # 48件
```

フィクスチャは `docs/samples/` の実測 JSON。モックは使わない。

## License

[MIT](./LICENSE)
