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

LAN 区間（LG Gram ↔ RasPi、双方に TWAMP responder がある）は twping を使う。WAN 側は宛先で分かれる:

- **公開 perfSONAR ホスト**（`perf-tokyo.sinet.ad.jp` / `ps-tkb-100g.riken.jp`）は responder を
  持つので **twping**。片道遅延と同一プロトコル・同一パケット系にすることで、
  非対称（RTT − 片道 − 片道）にプロトコル差が混入しない
- **responder を持たない宛先**（1.1.1.1 / 8.8.8.8 / 8091.info）は ICMP **ping**

サンプル: `rtt-twping-192.168.1.101-*.taskoutput.json`

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
| perfsonar.twamp.clock_error | Gauge | ms | `.result.max-clock-error`。**品質ゲートの判定に使う値。遅延が欠測した理由を追えるよう、ゲートで落とした場合も必ず出力する** |

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

### max-clock-error だけでは不十分。値の妥当性も見る

**`max-clock-error` に閾値を置く設計だけでは機能しない**ことが実測で判明した。誤差 0.23ms と
自己申告しながら片道遅延 102ms を返す run が実在し、閾値を何 ms にしてもこれは止められない。

そこで**値そのものの妥当性検査**を追加した。判定条件は次の2つを両方満たすこと。

```
0 < max-clock-error <= 10.0     （クロック誤差のゲート。全経路共通）
0 < 片道遅延の中央値 <= 上限     （値の妥当性。上限は path.id ごとに違う）
```

負の片道遅延は物理的にありえない。

### 上限は `path.id` ごとに分ける（2026-07-30 改訂）

**当初は全経路一律 50.0ms だった。これは LAN ペア（RTT 約0.9ms）だけを前提にした値**であり、
ソース中のコメント自身が「WAN 区間で使うなら経路に応じた値に変える必要がある」と断っていた。
WAN パスを本番投入した時点でその前提が崩れたので、`bridge/psotel/convert.py` の
`DELAY_CEILING_MS` を dict にした。

| `path.id` | 上限 | 根拠 |
|---|---|---|
| `lan-wired` | **5.0 ms** | GbE 化後の実測は中央値 0.220ms、幅も 0.2〜0.64ms（experiments/w3-notes.md Step 8）。50ms は2桁緩い |
| `wan-sinet-tokyo` | **200.0 ms** | 平常 3.9ms。ただし ICEPP で **80〜90ms の輻輳**を実測しており（public-hosts.md Step 4）、この規模の劣化は捨てずに残す必要がある |
| `wan-riken-tsukuba` | **200.0 ms** | 平常 4.7ms。同上 |
| （path.id なし） | **50.0 ms**（既定） | 手動 task は `reference` が null で経路が分からない。緩めも締めもできないので従来値を据え置く |

**一律 50ms のままだと二重に間違う。** LAN には2桁緩くて 6ms の異常を素通しし、WAN では
実在する輻輳（80〜90ms）を無言で捨てる。**「捨てた」ことが後から分からない形で捨てるのが
最悪**なので、上限は経路の実態に合わせる。未知の `path.id` は既定値 50.0 に落ちる。

> **LAN を 5.0ms に絞っても 30分ごとの iperf3 とは衝突しない。** `throughput` は `exclusive`、
> `rtt` は `background`、`latency` は `normal` のスケジューリングクラスで、
> **pScheduler は iperf3 実行中に自分の他の測定を走らせない**（experiments/w2-notes.md:303-305 の実測）。
> iperf3 に押し上げられた片道遅延が誤ってゲートに落ちる経路は設計上塞がれている。
> 測定は失われず slip するだけ。

> **運用上の帰結: LAN の delay 系列は今後まばらになる。** GbE 化で片道遅延が測定精度の床に
> 当たり、負値や `Not Reported` が頻出するようになった（w3-notes.md Step 8）。これらは
> `0 < median` のゲートに落ちる。**チャートの欠測は不具合ではなく実態の反映**である。

**上限一律 50.0 時代の実データ141 run での効果**（LAN の片道遅延が妥当な範囲を 0〜20ms として評価）:

| ゲート方式 | 出力数 | うち異常値 | 汚染率 |
|---|---|---|---|
| 旧（誤差 ≤ 5.0） | 64 | 22 | 34.4% |
| 中間（0 < 誤差 ≤ 10.0） | 57 | 17 | 29.8% |
| **誤差 + 値の妥当性（上限 50.0）** | **40** | **0** | **0.0%** |

57→40 で除かれた17件がちょうど汚染分と一致し、正常な40件は失われていない。
なお負値の排除は評価基準と判定条件が一致するため自明だが、上限側は判定が 50ms・
評価が 20ms と異なり、**その間に該当する標本は無かった**。

**この評価は上限を 5.0 に絞った後の効果を測っていない。** 当時の標本は 100M USB NIC 時代の
LAN のもので、片道遅延の分布そのものが今と違う（GbE 化で中央値が 0.22ms まで下がった）。
5.0ms の上限が新たに落とす帯域（5〜20ms）に標本があったかは、この 141 run からは言えない。
**LAN 5.0 は実測で検証した境界ではなく、GbE 化後の実測分布から引いた発見的な値**である。
`CLOCK_ERROR_THRESHOLD_MS` と同じ性格の数字だと理解しておくこと。

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
| perfsonar.throughput.retransmits | Gauge | {retransmits} | `.result.summary.summary.retransmits` |

**ブリッジ実装上の注意**: `.result.intervals[]`と`.result.diags`はOTelメトリクスに変換せず無視する（サイズが大きく、集計値のみで十分）。

## 共通 attributes

| attribute | 例 | 備考 |
|---|---|---|
| ps.source | 192.168.1.104 | `.test.spec.source`優先、無ければ`.participants[0]` |
| ps.destination | 192.168.1.101 | `.test.spec.dest` |
| ps.test.type | latency | `.test.type` |
| ps.tool | twping | **`.tool.name`**（実サンプルで確認。値は`{"name": "ping", "version": "1.0"}`の形）。`rtt`テストでは`ping`/`twping`のどちらかが入るため、LAN基準線がTWAMP由来かICMP由来かをこの属性で判別できる |

> **測定ごとに変わる数値を attribute にしないこと。** Splunk は dimension の組み合わせごとに
> 別々の時系列（MTS）を作るため、値が変わるたびに新しい時系列が生まれて際限なく増える。
> 当初 `ps.max_clock_error` と `ps.retransmits` を attribute にしていたところ、
> **1日で `perfsonar.packet.loss.ratio` が 269 系列、`perfsonar.twamp.delay.median` が 64 系列**に
> 膨らんだ（本来はそれぞれ数系列）。Free Edition の枠を圧迫するうえ、
> 「`path.id` 別にロス率を表示」しようとすると 269 本の線が引かれてダッシュボードが成立しない。
> **この2つは Gauge メトリクスに移した**（`perfsonar.twamp.clock_error` /
> `perfsonar.throughput.retransmits`）。attribute に置いてよいのは値域が有限で安定した識別子だけ。
>
> この欠陥は Collector のカウンタからもブリッジのテストからも見えず、Splunk の
> `/v2/metrictimeseries` を API で覗いて初めて判明した（experiments/w2-notes.md Step 8）。
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

## archiver の retry-policy — 無いと1回の失敗で測定結果が消える

`home-lab-mesh.json` の `archives.otel-bridge.data` に `retry-policy` を書いている。

```json
"data": {
  "_url": "http://192.168.0.1:8088/archive",
  "op": "put",
  "retry-policy": [
    { "attempts": 8, "wait": "PT30S" },
    { "attempts": 4, "wait": "PT5M" }
  ]
}
```

合計12回・最大約24分の再送。形式は `attempts`（回数）と ISO8601 の `wait`（間隔）の配列。
**30秒段を8回（= 4分）にしてあるのは意図的**。理由は下の「再送しても Splunk には載らない」を参照。

**これが無いとどうなるか**: http archiver プラグインは失敗時に必ず再送するわけではない。

```python
# /usr/lib/pscheduler/classes/archiver/http/archive の 204-208 行
if "retry-policy" in json['data']:
    policy = pscheduler.RetryPolicy(json['data']['retry-policy'], iso8601=True)
    retry_time = policy.retry(json["attempts"])
    if retry_time is not None:
        result["retry"] = retry_time
return result
```

`retry-policy` が**設定されているときだけ** `result["retry"]` が返る。未設定なら
`{"succeeded": False, "error": ...}` だけが返り、pScheduler は再送せずその run の結果を捨てる。
ブリッジの再起動・Mac のスリープ・LAN の一時断のたびに、その間の測定が無音で失われる。

これは netem 障害注入実験（docs/runbook-w2.md Step 7）の前提でもある。注入対象の `lima0` は
測定経路であると同時にテレメトリ経路でもあるため、retry-policy が無いと
「劣化を検知した」と「テレメトリが届かず欠測した」が区別できない。

### 再送しても Splunk には載らない — 順序逆転で捨てられる

**再送が成功しても、その測定値が Splunk に現れるとは限らない。** リハーサルで実測した
（experiments/w2-notes.md Step 12）。

ブリッジを12分停止したときの pScheduler 側の記録:

```
run 11:09:48  archived=True  attempts=6  → 11:21:23 に成功
run 11:15:10  archived=True  attempts=5  → 11:21:46 に成功
run 11:20:53  archived=True  attempts=1  → 11:20:58 に成功（ブリッジ復旧直後）
```

ブリッジは3件とも受け取り（PUT 200）、Collector も 0 失敗で送出した。
にもかかわらず **Splunk に残ったのは 11:20:53 の run だけ**で、11:09:48 と 11:15:10 は消えた。
双方向とも同じ結果。

理由: pScheduler は5分段の再送で古い run を復旧するので、**復旧点は必ず
「その間に成功した新しい点」より後に届く**。Splunk O11y の ingest は、同一 MTS に対して
既に新しい点が書かれた後に届いた古い点を**黙って捨てる**（HTTP は 200 OK を返す）。

「古すぎるから落ちた」ではないことは使い捨てメトリクスで確認した:
新規 MTS に**10分前の点を単独で**送ると正常に着弾する。落ちたのは 6.6 分前の点で、
かつ既に新しい点が書かれていた MTS だった。順序逆転が最も整合する説明。
（順序逆転だけを単独で再現するプローブは MTS 自体が現れず不成立だったので、
ここは実測から導いた最有力の説明であって、機構の確定ではない。）

**設計上の帰結**:

- 30秒段を8回（4分）にして、**タスク間隔（5分）より前に復旧を終わらせる**。
  4分以内の障害なら次の run より先に届くので順序が保たれ、Splunk にも載る。
- それより長い障害では、測定値は pScheduler の DB には残るが **Splunk 側は欠測のまま**。
  5分段の再送は「run を archived にして pScheduler 側の記録を閉じる」意味しか無い。
- したがって**障害注入実験の一次証拠は Splunk のグラフではなく
  pScheduler の run ごとの archivings 診断**（`GET /pscheduler/tasks/<id>/runs/<id>`）。
  ここには全試行の時刻・成否・次の retry 間隔が残る。

### Detector の maxDelay

再送で遅れて届いたデータ点は、Splunk O11y の Detector からは `maxDelay`（最大15分）を
超えた遅延データとして評価対象外になりうる。`maxDelay` を上げれば拾えるが、その分だけ
発火も遅くなる。`deploy/splunk/detectors/` では `maxDelay: null`（自動）にして
**発火の速さを優先**している。上のとおり長時間障害の復旧点はそもそも ingest で捨てられるので、
`maxDelay` を上げても救えるものは少ない。

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
