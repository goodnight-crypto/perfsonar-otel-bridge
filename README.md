# perfsonar-otel-bridge

perfSONAR の測定結果を OpenTelemetry メトリクスに変換し、Splunk Observability Cloud に送信するブリッジと、自宅ラボでの検証環境一式。

「ネットワークパスをサービスとみなして SLO を張る」ことを目標に、pScheduler の HTTP archiver → 自作ブリッジ → OTel Collector → Splunk O11y というパイプラインを構築する。

> **Status**: 検証中（Zenn コンテスト「OpenTelemetryの知見を、記事にしよう」Splunk Observability 部門向け）。
> 企画意図・ロードマップは [PROJECT.md](./PROJECT.md) を参照。

## アーキテクチャ

```
┌─ 自宅LAN ──────────────────────────────────────────┐
│                                                    │
│  Raspberry Pi 4B 4GB (有線)                         │
│   └ perfsonar/testpoint:systemd (arm64, --net=host)│
│                                                    │
│  Mac mini M4 16GB                                  │
│   ├ Linux VM (ブリッジ接続)                          │
│   │   └ perfsonar/testpoint (arm64)                │
│   ├ bridge/ … pScheduler HTTP archiver 受け口       │
│   │           JSON → OTel Metrics 変換 (FastAPI)    │
│   └ OTel Collector contrib                          │
│        └ OTLP → Splunk Observability Cloud          │
└────────────────────────────────────────────────────┘
外部ターゲット: 8091.info (Cloudflare edge) / 1.1.1.1
```

- 測定は pSConfig テンプレート 1 枚（[deploy/psconfig/](./deploy/psconfig/)）で宣言的に定義する
- RasPi はクロック精度の制約から片方向遅延 (owamp) を使わず、**twamp (RTT) + ロス**を主軸にする
- メトリクス変換仕様は [docs/schema.md](./docs/schema.md) を参照

## リポジトリ構成

```
├ README.md            # 本ファイル
├ CLAUDE.md            # Claude Code 向け運用ガイド（環境・規約・ガードレール）
├ PROJECT.md           # 企画概要・ロードマップ・記事構成案
├ docs/
│  ├ runbook-w1.md     # Week1 手順書（環境構築〜疎通〜スキーマ観察）
│  ├ schema.md         # perfSONAR JSON → OTel メトリクス変換仕様
│  └ samples/          # HTTP archiver の生 JSON サンプル
├ bridge/              # FastAPI ブリッジ実装（W2）
├ deploy/
│  ├ raspi/            # RasPi 側 testpoint 起動スクリプト
│  ├ mac/              # Mac 側 VM / Collector / bridge 構成
│  └ psconfig/         # pSConfig テンプレート
└ experiments/         # tc netem 障害注入シナリオと結果
```

## クイックスタート

> 実装完了後に確定版を記載する。現時点の手順は [docs/runbook-w1.md](./docs/runbook-w1.md) を参照。

1. Splunk Observability Cloud Free Edition のアカウントを取得し、realm と INGEST トークンを控える
2. `.env.example` をコピーして `.env` を作成し、トークンを設定する（**`.env` はコミット禁止**）
3. RasPi で `deploy/raspi/run-testpoint.sh` を実行
4. Mac 側で VM + testpoint、Collector、bridge を起動
5. pSConfig テンプレートを両 testpoint に配布

## 前提環境

| ノード | 要件 |
|---|---|
| Raspberry Pi 4B 4GB | 64bit OS (`uname -m` = `aarch64`)、Docker、cgroup v2 |
| Mac mini (Apple Silicon) | Linux VM（LAN からブリッジ到達可能であること）、Docker |
| Splunk Observability Cloud | Free Edition（15 ホストまで無料・期間制限なし） |

## License

未定（public 化時に MIT を予定）。
