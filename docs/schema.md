# perfSONAR JSON → OTel メトリクス変換仕様

W1 Step 5にて docs/samples/ の実JSON（2026-07-27取得）を基に確定。

## 共通のJSON構造（4テスト種共通）

pSchedulerのHTTP archiverが送るJSONは、トップレベルの`result`が`run.result-merged`と同一内容。
ブリッジはトップレベルの以下を共通で参照する。

| フィールド | JSONPath | 備考 |
|---|---|---|
| テスト種別 | `.test.type` | `"rtt"` / `"latency"` / `"trace"` / `"throughput"` |
| 宛先 | `.test.spec.dest` | 常に存在 |
| 送信元 | `.test.spec.source` | **rtt/traceには存在しない**（送信元＝participants[0]が暗黙の送信元）。latency/throughputには存在 |
| 観測時刻 | `.run.end-time` | ISO8601。送信遅延と測定時刻を分離するためend-timeを採用 |
| 参加ノード | `.participants[]` | 例: `["lima-perfsonar-vm"]` や `["192.168.1.104"]`。source省略時のフォールバックに使う |
| run ID | `.id` | UUID |
| 成否 | `.result.succeeded` | **注意**: ロス100%でも`succeeded: true`になりうる（後述） |

## テスト種別ごとのJSONPathとメトリクスマッピング

### rtt（ICMP ping、`tool: ping`）

```
.result.mean / .min / .max / .stddev   → ISO8601 duration文字列 "PT0.009059S" (要パース→ms)
.result.loss                            → float, 0.0-1.0
.result.sent / .received / .lost        → int
.result.roundtrips[]                    → 個別パケット詳細（集計指標には不要）
```

| メトリクス | 型 | 単位 | JSONPath |
|---|---|---|---|
| perfsonar.rtt.mean | Gauge | ms | `.result.mean` (duration→ms変換) |
| perfsonar.rtt.max | Gauge | ms | `.result.max` |
| perfsonar.packet.loss.ratio | Gauge | 1 (0.0-1.0) | `.result.loss` |

#### rtt を twping で実行する場合（LAN 基準線）

`pscheduler plugins` で確認したところ、`twping` ツールの対応テストは **`['latency', 'rtt']` の2つ**。
つまり TWAMP は片道遅延専用ではなく、`rtt` テストのツールとしても選択できる。

```bash
pscheduler task --tool twping rtt --source 192.168.1.104 --dest 192.168.1.101 --count 20
```

**このとき返る JSON は ICMP ping 版の `rtt` と完全に同一スキーマ**（`mean`/`min`/`max`/`stddev`/`loss`/
`sent`/`received`/`roundtrips[]`）。上記マッピング表がそのまま適用でき、**ブリッジの追加実装は不要**。

TWAMP は Sender-Reflector 間の4タイムスタンプ(T1-T4)から `(T4-T1)-(T3-T2)` で RTT を算出するため、
**両端のクロックがズレていても RTT は正しい**。実測でも、同一測定内で片道遅延が -0.874ms と負に壊れて
いる状況で RTT は 0.777/1/1.16 ms（min/median/max）と妥当な値を返した。

> **補足（記事ネタ）**: `twping` の生出力には `round-trip time` と `two-way jitter` が含まれるが、
> pScheduler の **`latency` テストの結果 JSON はこれらを捨てて `histogram-latency`（片道）しか残さない**。
> 同じ TWAMP 測定でも、どちらのテスト種別で実行するかで取れる情報が変わる。

LAN 区間（VM ↔ RasPi、双方に TWAMP responder がある）は twping、対向に responder が無い WAN 側
（8091.info / 1.1.1.1）は ICMP ping を使う。サンプル: `rtt-twping-192.168.1.101-*.taskoutput.json`

### latency（TWAMP、`--protocol=twamp`、`tool: twping`相当）

```
.result.packets-sent / -received / -lost / -reordered / -duplicated → int
.result.max-clock-error         → float, ms単位。TWAMPが両端のクロック誤差見積もりを埋め込む
.result.histogram-latency       → {"<delay_ms>": count, ...} 形式のヒストグラム
```

**重要**: このテストには **mean/median等の直接フィールドが存在しない**。one-way delayの代表値は
`histogram-latency`から中央値・平均をブリッジ側で計算する必要がある（W1 Step3で発覚した
VM側クロック精度問題により、このone-way delayは`max-clock-error`が大きい場合は信頼できない
→ [PROJECT.mdの設計判断](../PROJECT.md#メトリクススキーマ詳細-docsschemamd)参照）。

| メトリクス | 型 | 単位 | JSONPath |
|---|---|---|---|
| perfsonar.twamp.delay.median | Gauge | ms | `.result.histogram-latency` から算出 |
| perfsonar.packet.loss.ratio | Gauge | 1 (0.0-1.0) | `.result.packets-lost / .result.packets-sent` |
| （属性）ps.max_clock_error | attribute | ms | `.result.max-clock-error`。**閾値超過時はdelayメトリクスを欠測扱いにする品質ゲートとして使う** |

**品質ゲートの限界（実測済みの偽陰性）**: `max-clock-error` は TWAMP 両端の**自己申告の推定値**であり、
実態と乖離することがある。experiments/w1-notes.md:42 に、RasPi→VM 方向で片道遅延が
中央値 -4.62ms / 最小 -23.92ms と明らかに壊れているのに **`max-clock-error` は 0.0ms と報告された**
ケースが記録されている。つまり「ゲートは通るがデータは壊れている」状態が起こりうる。

したがってこのゲートは「壊れたデータを完全に排除する仕組み」ではなく「明らかに壊れた区間を落とす
ベストエフォート」として位置づける。**LAN 基準線の RTT は `rtt`+`twping` で別途取得しており
（前述）、そちらはこの問題の影響を受けない**ため、SLO 指標の信頼性は担保される。

**閾値は 10.0 ms**（2026-07-28 に 5.0 から変更）。

当初の 5.0 は「正常時 0.0ms / 異常時 27.47ms の中間」という根拠だった。その後 VM のクロックが
収束し、**正常時が 0.0ms ではなく 4.67〜4.88ms** だと判明して根拠が崩れた（余裕が 0.12〜0.33ms
しか無く、わずかな悪化で系列が断続する）。健全域(〜4.88)と既知の異常(27.47)の対数中間
√(4.88×27.47)≒11.6 に近い 10.0 へ引き上げた。**異常サンプルは n=1 なので、これは検証済みの
境界ではなく発見的な閾値**である。

**`max-clock-error` が 0.0 の場合もゲートで落とす。** TWAMP の Error Estimate は
`Multiplier × 2^Scale` 形式で、クロック同期機構が誤差見積もりを提供できないと Multiplier が 0 の
まま埋まる実装がある。つまり「誤差なし」と「推定できていない」が同じ 0.0 として出力されうる。
実際 experiments/w1-notes.md:42 に 0.0 報告なのに片道遅延が中央値 -4.62ms と壊れていた例がある。
判定条件は `0 < max-clock-error <= 10.0`。

### trace（`tool: traceroute`相当）

```
.result.paths[0][]   → hop配列。各要素は {ip, hostname?, rtt, as?} または応答なしの場合 {}
```

| メトリクス | 型 | 単位 | JSONPath |
|---|---|---|---|
| perfsonar.trace.hops | Gauge | {hops} | `len(.result.paths[0])` |

hop単位のRTT/AS番号はW1時点ではメトリクス化せず、生JSONのまま保持する方針（必要になればW2で属性化）。

### throughput（iperf3、`tool: iperf3`相当）

```
.result.summary.summary.throughput-bits           → sender側 bps
.result.summary.summary.receiver-throughput-bits   → receiver側 bps（iperf3の慣習でこちらを正とする）
.result.summary.summary.retransmits                → int
.result.intervals[]                                 → 秒間の詳細（メトリクス化不要、大きい。95KB中の大半を占める）
.result.diags                                        → iperf3の生テキスト出力の重複（メトリクス化不要）
```

| メトリクス | 型 | 単位 | JSONPath |
|---|---|---|---|
| perfsonar.throughput.bps | Gauge | bit/s | `.result.summary.summary.receiver-throughput-bits` |
| （属性）ps.retransmits | attribute | count | `.result.summary.summary.retransmits` |

**ブリッジ実装上の注意**: `.result.intervals[]`と`.result.diags`はOTelメトリクスに変換せず無視する（サイズが大きく、集計値のみで十分）。

## 共通 attributes

| attribute | 例 | 備考 |
|---|---|---|
| ps.source | 192.168.1.104 | `.test.spec.source`優先、無ければ`.participants[0]` |
| ps.destination | 192.168.1.101 | `.test.spec.dest` |
| ps.test.type | latency | `.test.type` |
| ps.tool | twping | **`.tool.name`**（実サンプルで確認。値は`{"name": "ping", "version": "1.0"}`の形）。`rtt`テストでは`ping`/`twping`のどちらかが入るため、LAN基準線がTWAMP由来かICMP由来かをこの属性で判別できる |
| path.id | `.reference["path.id"]` | archiver封筒に**`reference`キーは実在する**（手動taskでは`null`）。pSConfigのreference機能がここを埋めるので、ブリッジは`.reference`を読み、無ければ属性を付けない実装とする。実際の値はW2のpSConfig本番化で確定 |

## エラー / 測定失敗runの扱い

実サンプルで確認した失敗パターン（`rtt-FAILED-192.0.2.1-100pct-loss-*.json`、到達不能な宛先への
rttテスト）:

```json
{
  "loss": 1.0,
  "lost": 5,
  "sent": 5,
  "received": 0,
  "succeeded": true,
  "roundtrips": []
}
```

**重要な発見**: 100%ロスでも`succeeded: true`のまま。`mean`/`min`/`max`/`stddev`キーは**存在しない
（nullではなくキーごと省略される）**。プレーンテキスト出力では`None`と表示されるが、JSON上は
キー自体がない。

ブリッジの実装方針:
- `succeeded`フラグは「pSchedulerタスクとして実行できたか」であり、「測定対象が到達可能か」ではない
- ロス率メトリクスは`loss`/`lost`/`sent`から常に計算可能（キー欠落なし）
- 遅延系メトリクス（mean/max/histogram-latency等）は**キーの存在チェックが必須**。欠落時はメトリクスを送らない（0や欠測扱いではなく、単に出力しない）
- 真の「タスク失敗」（`succeeded: false`、DNS解決失敗等のエラー）のサンプルは未取得。W2のブリッジ実装時に`.result.error`フィールドの有無で分岐する設計とし、必要になった時点でサンプルを追加取得する

## 参考: 実サンプル一覧（docs/samples/）

| ファイル | テスト種 | 備考 |
|---|---|---|
| rtt-1.1.1.1-*.json | rtt | 正常系 |
| rtt-8091.info-*.json | rtt | 正常系 |
| rtt-FAILED-192.0.2.1-100pct-loss-*.json | rtt | 異常系（100%ロス、`succeeded:true`） |
| latency-twamp-192.168.1.101-*.json | latency(twamp) | 正常系。max-clock-error要参照 |
| trace-1.1.1.1-*.json | trace | 正常系 |
| throughput-192.168.1.104-to-192.168.1.101-*.json | throughput | 正常系。95KBと大きい(intervals/diags含む) |
| rtt-twping-192.168.1.101-*.taskoutput.json | rtt(twping) | LAN基準線。**`.taskoutput`サフィックス付きは`pscheduler task --format json`の出力で`result`部分のみ**。他のサンプルと違い`test`/`run`/`participants`/`reference`の封筒が無い |
| rtt-twping-192.168.1.101-archiver.json | rtt(twping) | **上記の封筒付き実物**（2026-07-27、実 archiver がブリッジへ PUT したものを捕獲）。`.tool.name` が `twping`、ICMP版と違い `.test.spec.source` が存在する |

> **封筒の構造**: archiver が PUT する JSON のトップレベルキーは
> `['id', 'participants', 'reference', 'result', 'run', 'schedule', 'task', 'test', 'tool']`（実サンプルで確認）。
