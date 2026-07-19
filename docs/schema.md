# perfSONAR JSON → OTel メトリクス変換仕様（ドラフト）

> W1 Step 5 で docs/samples/ の実 JSON を基に確定させる。以下は設計時点の案。

## メトリクス定義

| メトリクス名 | 型 | 単位 | 元データ (テスト種) |
|---|---|---|---|
| perfsonar.twamp.rtt.mean | Gauge | ms | twamp |
| perfsonar.twamp.rtt.max  | Gauge | ms | twamp |
| perfsonar.packet.loss.ratio | Gauge | 1 (0.0-1.0) | twamp / rtt |
| perfsonar.throughput.bps | Gauge | bit/s | throughput (iperf3) |
| perfsonar.trace.hops | Gauge | {hops} | trace |

## 共通 attributes

| attribute | 例 | 備考 |
|---|---|---|
| ps.source | 192.0.2.10 | 測定元 |
| ps.destination | 192.0.2.20 | 測定先 |
| ps.test.type | twamp | pScheduler test type |
| ps.tool | twping | 実行ツール |
| path.id | lan-wired | 論理パス名（pSConfig 側で reference として付与） |

## タイムスタンプ

- observation timestamp には run の end time を採用（送信遅延と測定時刻を分離）

## TODO (W1 Step 5)

- [ ] 各値の JSONPath を実サンプルで確定
- [ ] 測定失敗 run の JSON 形状と扱いを決定
- [ ] path.id を archiver JSON にどう埋め込むか（pSConfig の reference / _meta）を確定
