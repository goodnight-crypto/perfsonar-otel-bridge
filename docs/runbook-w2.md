# Runbook W2: パイプライン構築と実験

W1（環境構築〜スキーマ確定）の完了が前提。経緯と判断の記録は experiments/w2-notes.md、
変換仕様は docs/schema.md、測定方針は PROJECT.md を参照。

**このファイルのコマンドは Step 0-4 と Step 7 の前提確認まで実機で検証済み。**
Step 5-6（Splunk UI 作業）と Step 7 の注入手順は未実施のため、その旨を各所に明記している。

---

## Step 0: 前提確認

Mac 再起動後などは VM が自動起動しない。

```bash
# VM と RasPi の testpoint
limactl list                                   # perfsonar-vm が Running か
limactl shell perfsonar-vm docker exec perfsonar-testpoint pscheduler troubleshoot
ssh unpeeled@raspi-testpoint.local 'docker exec perfsonar-testpoint pscheduler troubleshoot'

# Mac の Docker Desktop（起動していないと compose が動かない）
docker info >/dev/null 2>&1 || open -a Docker   # 起動まで約20秒

# pSConfig エージェント（両ノードとも active であること）
limactl shell perfsonar-vm docker exec perfsonar-testpoint systemctl is-active psconfig-pscheduler-agent
ssh unpeeled@raspi-testpoint.local 'docker exec perfsonar-testpoint systemctl is-active psconfig-pscheduler-agent'
```

`.env` の INGEST トークンは 2026-08-21 まで有効。

---

## Step 1: Collector → Splunk 疎通（ブリッジを通さない）

ブリッジを書く前にここを通す。**以降の失敗をブリッジ側のバグと断定できる状態を作るのが目的。**

```bash
cd /Users/dev/src/perfsonar-otel-bridge
set -a; . ./.env; set +a

# 1-1. まず Collector を通さず ingest API へ直接投げて realm/トークンを確定させる
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "https://ingest.${SPLUNK_REALM}.signalfx.com/v2/datapoint" \
  -H "Content-Type: application/json" -H "X-SF-Token: ${SPLUNK_ACCESS_TOKEN}" \
  -d '{"gauge":[{"metric":"perfsonar.bridge.selftest","value":1,"dimensions":{"stage":"direct-curl"}}]}'
# 期待: HTTP 200 と "OK"
```

**トークンは必ず shell 経由で渡すこと。** `docker --env-file` は `.env` のインラインコメントを
値に含めてしまい、22文字のトークンが67文字になって Splunk が 401 を返す。直接 curl は通るのに
Collector だけ 401 になったら真っ先にこれを疑う。判別法:

```bash
docker run --rm --env-file .env busybox sh -c 'echo ${#SPLUNK_ACCESS_TOKEN}'   # 22 以外なら混入
```

---

## Step 2: ブリッジ実装（TDD）

```bash
cd bridge
uv sync
uv run pytest          # 32 件
```

テストのフィクスチャは `docs/samples/` の実測 JSON。モックは使わない。

実装上の要点は bridge/README.md と docs/schema.md に寄せてある。特に外せないのは次の2点。

- **測定失敗時、統計キーは null ではなくキーごと省略される。** 0 を代入すると 100% ロスのリンクが
  「遅延 0ms の健全なリンク」として可視化される。キー存在チェックが必須。
- **ISO8601 duration の ms 変換は Decimal を使う。** `float(x) * 1000` は
  `0.001301 → 1.3010000000000002` になる。実 archiver の封筒を通すまで気付かなかった。

---

## Step 3: compose 起動と archiver 実経路

```bash
cd /Users/dev/src/perfsonar-otel-bridge
set -a; . ./.env; set +a                       # 忘れると compose が明示的に停止する
docker compose -f deploy/mac/compose.yaml up -d --build

docker compose -f deploy/mac/compose.yaml ps   # bridge:8088, collector:4318
```

**ブリッジの公開ポートは 8088**（コンテナ内は 8000）。ホストの 8000 は Hermes Agent の
`honcho-api` が使用中。archiver の `_url` もこのポートを指す。

testpoint コンテナからの到達確認と、archiver 経由の実測:

```bash
# 3-1. コンテナ内から Mac のブリッジへ届くか（Mac の LAN IP は 192.168.0.1、/22 で同一セグメント）
limactl shell perfsonar-vm docker exec perfsonar-testpoint \
  curl -s -o /dev/null -w "%{http_code}\n" -X PUT http://192.168.0.1:8088/archive \
  -H "Content-Type: application/json" -d '{"test":{"type":"rtt","spec":{"dest":"192.168.1.101"}},"participants":["check"],"tool":{"name":"ping"},"reference":null,"run":{"end-time":"2026-07-27T12:00:00+00:00"},"result":{"loss":0.0}}'

# 3-2. archiver 定義はコンテナ内のファイルを参照させる。
#      インライン JSON は 多段シェル（local -> limactl -> docker exec）で引用符が壊れる
limactl shell perfsonar-vm docker exec perfsonar-testpoint bash -lc 'cat > /tmp/archiver.json <<EOF
{"archiver": "http", "data": {"_url": "http://192.168.0.1:8088/archive", "op": "put"}}
EOF
pscheduler task --archive=@/tmp/archiver.json --tool twping rtt \
  --source 192.168.1.104 --dest 192.168.1.101 --count 10'
```

着弾の確認は Collector の内部テレメトリで実数を見る。「エラーが出ていない」は着弾の証明にならない。

```bash
docker run --rm --network container:psotel-collector busybox \
  wget -q -O- http://localhost:8888/metrics 2>/dev/null \
  | grep -E "^otelcol_(exporter_sent|exporter_send_failed|receiver_accepted|receiver_refused)_metric_points"
```

rtt 1本につき 3 メトリクス（mean / max / loss）増えるのが期待値。

---

## Step 4: pSConfig 本番化

定義の正は `deploy/psconfig/`。配置手順とハマりどころは deploy/psconfig/README.md にまとめてある。

```bash
# 4-1. 検証（配置前に必ず通す）
limactl shell perfsonar-vm bash -lc 'cp /Users/dev/src/perfsonar-otel-bridge/deploy/psconfig/home-lab-mesh.json ~/psconfig/'
limactl shell perfsonar-vm docker exec perfsonar-testpoint \
  psconfig validate /etc/perfsonar/psconfig/home-lab-mesh.json
# 期待: "pSConfig JSON is valid"

# 4-2. 配置（VM）。コンテナの作り直しは不要
limactl shell perfsonar-vm bash -lc '
  SRC=/Users/dev/src/perfsonar-otel-bridge/deploy/psconfig
  cp $SRC/home-lab-mesh.json $SRC/pscheduler-agent.json $SRC/pscheduler-agent-logger.conf ~/psconfig/
  mkdir -p ~/psconfig/archives.d ~/psconfig/pscheduler.d ~/psconfig/transforms.d'
limactl shell perfsonar-vm docker exec perfsonar-testpoint systemctl restart psconfig-pscheduler-agent

# 4-3. 配置（RasPi）
cd deploy/psconfig
scp home-lab-mesh.json pscheduler-agent.json pscheduler-agent-logger.conf unpeeled@raspi-testpoint.local:~/psconfig/
ssh unpeeled@raspi-testpoint.local '
  mkdir -p ~/psconfig/archives.d ~/psconfig/pscheduler.d ~/psconfig/transforms.d
  docker exec perfsonar-testpoint systemctl restart psconfig-pscheduler-agent'

# 4-4. 生成タスクの確認（VM 6件 / RasPi 3件）
limactl shell perfsonar-vm docker exec perfsonar-testpoint psconfig pscheduler-tasks
```

**ホスト側 `~/psconfig` が空だとイメージ既定の設定ファイルが隠れ、エージェントが起動できない。**
必ず3ファイルを置くこと。詳細は deploy/psconfig/README.md。

エージェントは初回巡回を終えるまで `psconfig pscheduler-tasks` が
`Unable to find last guid ...` を返す（RasPi で20秒程度）。落ちているのと紛らわしいので、
判断は `systemctl is-active` とログの両方で行う。

---

## Step 5: Splunk ダッシュボード【as-code で構築済み】

> **訂正**: 以前この節には「`.env` には INGEST トークンしか無く API からダッシュボードを
> 作れないため UI 作業になる」と書いてあったが、これは誤り。`.env` には
> `SPLUNK_API_TOKEN` があり、Free Edition でも `/v2/chart` `/v2/dashboard` `/v2/detector`
> は POST/PUT とも通る。**UI 作業は不要で、全て as-code で作れる。**
> 取得手順は docs/setup-splunk-api-token.md。

定義の正は `deploy/splunk/`。投入は冪等なスクリプト1本:

```bash
./deploy/splunk/apply.sh --dry-run   # 送信せず差分を見る
./deploy/splunk/apply.sh             # チャート → ダッシュボード → Detector
./deploy/splunk/apply.sh --only detectors
```

生成された ID は `deploy/splunk/.ids.json` に記録され、2回目以降は同じ ID に PUT する。
UI 側で消された場合は GET が 404 になるので POST に倒れる。
**トークンはヘッダにしか載せない**（`curl -H` はプロセス引数に出るため、スクリプトは
Python の urllib で送っている。CLAUDE.md 規約1）。

Splunk O11y の API は**チャートを個別に POST してから、その ID をダッシュボードの
`charts[]` に row/column/width/height 付きで並べる**構造になっている。グリッドは12カラム。
`dashboard-network-slo.json` はチャートを**ファイル名**で参照する `layout` を持ち、
apply 時に ID へ解決される。

| チャート定義 | 内容 |
|---|---|
| `charts/lan-rtt.json` | LAN RTT の mean / max。Detector 閾値 5ms を highWatermark で描画 |
| `charts/wan-rtt.json` | `path.id: wan-*` の RTT を宛先別に |
| `charts/packet-loss.json` | ロス率を経路別。Detector 閾値 1% を描画 |
| `charts/throughput.json` | iperf3 スループットを方向別。900 Mbps を lowWatermark で描画 |
| `charts/throughput-retransmits.json` | TCP 再送数。方向非対称が一目で分かる |
| `charts/trace-hops.json` | traceroute のホップ数 |
| `charts/twamp-delay-gated.json` | **記事の核**。片道遅延・同経路の RTT・clock_error を2軸で重ね、ゲート閾値2本を描画 |

最後の1枚が主題。**clock_error が跳ねた区間で片道遅延が欠測する一方、同じ経路の RTT は
連続している**ことを1枚で示す（実データで delay は n=111/86、同区間の rtt は n=288）。
「欠測 = 壊れた」ではなく「欠測 = 信頼できないので捨てた」という設計判断が絵になる。

ゲートは実装上**2段**なので、線も2本引いている（`bridge/psotel/convert.py`）:

- `CLOCK_ERROR_THRESHOLD_MS = 10.0` — max-clock-error の上限（右軸）
- `DELAY_CEILING_MS = 50.0` — 片道遅延の値そのものの妥当性上限（左軸）

利用できる dimension: `ps.source` `ps.destination` `ps.test.type` `ps.tool` `path.id`。

> `ps.max_clock_error` / `ps.retransmits` は **dimension としては廃止済み**（コミット
> `1772259` でメトリクス化した）。カーディナリティ爆発の残骸として旧系列が114本残っているが、
> 新規作成は 2026-07-28 14時で停止しており最終データ点も同日昼なので、24時間ウィンドウの
> チャートには写らない。チャート側の対処は不要（データの無い系列は描画されない）。
> なお全チャートの programText は `.mean(by=[...])` で集約しているため、残骸があっても
> 系列が増えない。

### 検証

- `apply.sh` を2回流して `.ids.json` の ID が変わらないこと
- **`./deploy/splunk/check-charts.sh`** — 各チャートの programText を SignalFlow で実際に評価し、
  publish ラベルごとにデータ点が返ることを確認する。ブラウザを開く前にここで潰せる

  ```
  lan-rtt                  mean=系列2/点141  max=系列2/点141
  packet-loss              loss=系列4/点277
  throughput-retransmits   retransmits=系列2/点22
  throughput               bps=系列2/点22
  trace-hops               hops=系列1/点13
  twamp-delay-gated        delay=系列2/点83  rtt=系列2/点141  clock_error=系列2/点133
  wan-rtt                  mean=系列2/点135
  ```

  `twamp-delay-gated` の **delay 83点に対し rtt 141点**（同一6時間）が、
  ゲートによる欠測を数字で示している

- ブラウザでダッシュボードを開き、レイアウトと閾値線が意図どおり描かれていること

> **読み取りに `/v1/timeserieswindow` を使わないこと。** 連投すると HTTP 200 の本文で
> `"Your role doesn't let you perform this action."` を返し、さらに叩くと 403 に落ちる
> （権限の問題に見えるが実体はレート制限）。SignalFlow の
> `POST https://stream.<realm>.signalfx.com/v2/signalflow/execute` を使う。
> チャートと同じ programText をそのまま評価できる点でも素直。

---

## Step 6: Detector【as-code で構築済み・4本】

### 実測ベースライン（直近24h、`/v1/timeserieswindow`）

閾値はこの実データから決めた。「閾値を決める前に平常時を確認する」はこれで満たしている。

| メトリクス | 系列 | n | med | p95 | max |
|---|---|---|---|---|---|
| `rtt.mean` | lan-wired 双方向 | 376/288 | 0.94–0.98 ms | 1.02–1.08 | 6.3–6.8 |
| `rtt.mean` | wan-cloudflare / wan-blog | 288 | 9.03–9.12 ms | 9.76–9.82 | 14.4 |
| `packet.loss.ratio` | lan-wired 双方向 | 376/288 | 0 | 0 | **0** |
| `packet.loss.ratio` | wan-blog | 288 | 0 | 0 | **0.1**（単発1回） |
| `throughput.bps` | lan-wired 双方向 | 41/40 | 940.0–940.8 Mbps | — | min 936.7 |
| `throughput.retransmits` | 104→101 | 41 | **11** | 11 | 12 |
| `throughput.retransmits` | 101→104 | 40 | **0** | 0 | 0 |
| `twamp.clock_error` | lan-wired 双方向 | 243 | 0.48 ms | 53–60 | 189 |
| `twamp.delay.median` | lan-wired 双方向 | 111/86 | 0.72–1.17 ms | 2.5–3.1 | 35–46 |
| `trace.hops` | wan-cloudflare | 48 | 8 | 9 | 9 |

この表から2点言える:

1. **スループットの静的閾値は「妥協」ではない。** 実測は 936.7–941.3 Mbps・変動 0.5% 未満で
   異常に安定している。900 Mbps は実測 min の約4%下で、誤検知ゼロが実データで担保できる。
   この区間では静的閾値のほうが動的ベースラインより素直に機能する。
2. **`throughput.retransmits` が方向で完全非対称。** 104→101 は常に 11–12、101→104 は常に 0。
   80回の測定で一度も逆転していない。原因は未究明だが、観察事実として記録しておく。

### Detector

| 定義ファイル | 条件 | 根拠 |
|---|---|---|
| `detectors/packet-loss.json` | `packet.loss.ratio > 0.01` が2データポイント連続 | LAN は 24h 全て 0。wan-blog に 0.1 の単発が1回あるので、単発では発火させない条件が必須 |
| `detectors/lan-rtt-degraded.json` | `path.id=lan-wired` の `rtt.mean > 5ms` が2点連続 | p95 は 1.02–1.08ms だが外れ値 max が 6.8ms あり単発では誤検知する。netem の 100ms なら確実に発火 |
| `detectors/lan-throughput-degraded.json` | `path.id=lan-wired` の `throughput.bps < 9e8` | 実測 min 936.7 Mbps。30分間隔なので連続性は要求しない |
| `detectors/wan-rtt-sudden-change.json` | `against_recent` で 4σ 上振れ（**任意**） | WAN は ISP の揺らぎがあり静的閾値だと運用しづらい。静的閾値との使い分けを示すための4本目で、Exit Criteria には含まれない |

### 「2データポイント連続」の書き方

`lasting()` ではなく **12分窓の最小値 + 点数**で表現している:

```
sustained = loss.min(over='12m')
enough    = loss.count(over='12m')
detect(when(sustained > 0.01 and enough >= 2)).publish('packet_loss_sustained')
```

`lasting()` を使わない理由: 欠測区間で直前の値を引き延ばすため、5分間隔
（slip PT2M で実効 5〜7分）の疎な測定系列では意図と合わない。

> **`count(over=)` は後から足した。** 当初は `min(over='12m')` だけで
> 「窓内の全データポイントが閾値超え = 2点以上連続」と考えていたが、これは誤り。
> **窓内に1点しか無いとその1点だけで判定する**ため、単発スパイクの直後にデータが
> 途切れると発火してしまう。実際、11:05 の単発スパイク（wan-cloudflare のロス 0.1）の直後に
> ブリッジ停止リハーサルで 11:08〜11:20 のデータが欠測し、誤検知した
> （experiments/w2-notes.md Step 15）。
>
> **疎な測定系列では「窓の集約」は点数の保証にならない。** 点数も併せて要求して初めて
> 「N点連続」になる。

### 検証

作成後、**netem に進む前に最低6時間は平常運転で放置し、1件も発火しないことを確認する。**

```bash
# 発火履歴（空であること）
./deploy/splunk/check-alerts.sh
```

> **発火判定は `events[].anomalyState == "ANOMALOUS"` で見ること。**
> レスポンスに含まれる `is` フィールドで判定すると常に空振りし、
> **発火していても「0件」と表示される。** 実際にこれで6時間の観察結果を誤判定した
> （experiments/w2-notes.md Step 15）。`check-alerts.sh` は修正済みで、
> 継続中のインシデント（`/v2/detector/<id>/incidents` の `active`）も併せて出す。

通知先は設定していない（`notifications: []`）。Free Edition では発火の記録は
Detector の Alerts 履歴で足りる。

---

## Step 7: tc netem 障害注入実験【手順は未実施】

### 前提（実機で確認済み）

- 注入対象は **VM の `lima0`**（192.168.1.104/23）。`eth0`（192.168.5.15）は Lima の
  ユーザーモード網なので、ここに入れても LAN 測定には効かない。
- RasPi 側の LAN インタフェースは `eth0`（192.168.1.101/23）。
- `tc` は VM が `/usr/sbin/tc`、RasPi が `/sbin/tc`（非ログインシェルでは PATH に無いので絶対パスで叩く）。
- `sch_netem` カーネルモジュールあり。VM はパスワードなし sudo が通る。
- 構文は無通信の `docker0` で検証済み:
  `tc qdisc add dev <if> root netem delay 100ms loss 3%` / `tc qdisc show dev <if>` /
  `tc qdisc del dev <if> root`（削除後は `noqueue` に戻る）。

### 前提: archiver の retry-policy（これが無いと実験の信頼性が崩れる）

`home-lab-mesh.json` の `archives.otel-bridge.data` に `retry-policy` が**必須**。

```json
"retry-policy": [
  { "attempts": 8, "wait": "PT30S" },
  { "attempts": 4, "wait": "PT5M" }
]
```

なぜ必須か: http archiver プラグインは `retry-policy` が**設定されているときだけ**
`pscheduler.RetryPolicy` を適用して `result["retry"]` を返す
（`/usr/lib/pscheduler/classes/archiver/http/archive` の 204–208 行）。未設定だと
**1回の PUT 失敗で測定結果が捨てられる**。

netem は測定経路とテレメトリ経路が同一（`lima0`）なので、retry-policy 無しで注入すると
「劣化を検知した」と「テレメトリが届かず欠測した」が区別できない。

**ただし再送で Splunk のグラフが埋まるわけではない。** 復旧点は「その間に成功した新しい点」
より後に届くため、Splunk O11y の ingest が順序逆転として黙って捨てる（実測。docs/schema.md）。
30秒段を8回（4分）にしてあるのは、タスク間隔の5分より前に復旧を終わらせて順序を保つため。

したがって**この実験の一次証拠は Splunk のグラフではなく、pScheduler の run ごとの
archivings 診断**にする。全試行の時刻・成否・次の retry 間隔がここに残る:

```bash
# 注入区間の run について、PUT の試行履歴を出す
limactl shell perfsonar-vm docker exec perfsonar-testpoint python3 -c "
import json,subprocess
def g(u): return json.loads(subprocess.run(['curl','-s','-k',u],capture_output=True,text=True).stdout)
tasks=g('https://localhost/pscheduler/tasks')
for tu in tasks:
    t=g(tu)
    if (t.get('reference') or {}).get('path.id')!='lan-wired' or t['test']['type']!='rtt': continue
    if not any('retry-policy' in a.get('data',{}) for a in (t.get('archives') or [])): continue
    for ru in g(tu+'/runs?limit=8'):
        r=g(ru)
        for a in (r.get('archivings') or []):
            d=a.get('diags') or []
            print(r.get('start-time','')[11:19], 'archived=', a.get('archived'), 'attempts=', len(d))
            for x in d:
                so=x.get('stdout') or {}
                print('   ', x['time'][11:19], 'succeeded=', so.get('succeeded'), 'retry=', so.get('retry'))
"
```

### 注意

**netem は egress にのみ効く。** また `lima0` は測定経路であると同時に**ブリッジへの
テレメトリ経路でもある**（Mac の 192.168.0.1 は同一 LAN）。注入すると archiver の PUT にも
同じ遅延・ロスがかかる。100ms の遅延と 3% のロスは TCP の再送で吸収される範囲だが、
「メトリクスが届かない」と「メトリクスが劣化を示す」を混同しないよう、注入中も
Collector のカウンタが増え続けていることを確認すること。

retry-policy を入れたので、**注入中に PUT が失敗しても後から埋まる**。この「埋まった」
証拠を残せば、上の混同に実測で答えられる。

### 手順

```bash
# 7-1. 注入前の状態を記録する。これを省くと、観測された遅延増が注入起因か
#      VM クロックのステップ補正起因か区別できず、デモの信頼性が崩れる
limactl shell perfsonar-vm bash -lc 'chronyc tracking | grep -E "System time|Frequency|Skew|Last offset"'
limactl shell perfsonar-vm bash -lc 'sudo tc qdisc show dev lima0'
date -u +"注入前 %Y-%m-%dT%H:%M:%SZ"

# 7-2. 注入（遅延 100ms + ロス 3%）
limactl shell perfsonar-vm bash -lc 'sudo tc qdisc add dev lima0 root netem delay 100ms loss 3%'
limactl shell perfsonar-vm bash -lc 'sudo tc qdisc show dev lima0'   # netem が入ったこと

# 7-3. 5分間隔のタスクが2〜3回走るまで待つ（15分程度）。その間に確認するもの:
#      - Splunk で perfsonar.rtt.mean が 100ms 前後に跳ねる
#      - perfsonar.packet.loss.ratio が 0.03 前後になる
#      - Detector が発火する
#      - Collector のカウンタが増え続けている（テレメトリ経路が生きている）
docker run --rm --network container:psotel-collector busybox \
  wget -q -O- http://localhost:8888/metrics 2>/dev/null | grep "^otelcol_exporter_sent_metric_points"

# 7-4. 復旧
limactl shell perfsonar-vm bash -lc 'sudo tc qdisc del dev lima0 root'
limactl shell perfsonar-vm bash -lc 'sudo tc qdisc show dev lima0'   # noqueue または fq_codel に戻る
date -u +"復旧 %Y-%m-%dT%H:%M:%SZ"

# 7-5. 注入後のクロック状態を記録し、実験区間でステップ補正が入っていないことを確認
limactl shell perfsonar-vm bash -lc 'chronyc tracking | grep -E "System time|Frequency|Skew|Last offset"'
```

### 片道遅延の扱い

TWAMP の片道遅延（`perfsonar.twamp.delay.median`）は `ps.max_clock_error` による品質ゲートを
通ったときだけ出力される。注入実験では **「RTT では 100ms の跳ね上がりが明確に見えた」と
「片道遅延はゲートの状態次第で欠測になりうる」の対比**として扱う。クロックオフセットが一定だと
仮定して片道遅延の変化量から結論を出すことはしない（W1 でドリフトが断続的なステップ補正である
ことが判明しているため。experiments/w1-notes.md:71 参照）。

---

## Exit Criteria（W2 完了条件）

- [x] ブリッジが archiver の PUT を受けて OTLP に変換し Collector へ送る（テスト32件）
- [x] Collector → Splunk の着弾を Collector の内部テレメトリで実数確認
- [x] compose でブリッジと Collector が常駐し、実 archiver からの経路が通る
- [x] pSConfig が両ノードで稼働し、`path.id` 付きのタスクが自動生成される
- [x] archiver の retry-policy を入れ、ブリッジ停止中の測定が復旧後に埋まることを実証
- [x] Splunk ダッシュボードで `path.id` 別の RTT / ロス / スループットが見える（`deploy/splunk/` で as-code）
- [x] Detector 3種が定義され、平常時に誤検知しないことを確認
      - 平常運転区間（11:23〜21:20、約6時間）は発火0件
      - **ただし観測窓の冒頭で2件発火していた。** 当初「0件」と判定したのは
        `check-alerts.sh` のバグ（`is` フィールドで判定していた）。発火の原因は
        ブリッジ停止リハーサルによるデータ欠測で、Detector 側も修正した
        （experiments/w2-notes.md Step 15）
- [x] tc netem 注入 → メトリクス変化 → Detector 発火 → 復旧、を記録
      - RTT 0.93ms → 105ms、ロス 0 → 2〜6%、スループット 940Mbps → 241Mbps
      - Detector は RTT（双方向）・スループット・WAN 異常検知の**3種が発火**。
        ロスだけ発火せず（20発サンプルに 3% ロスでは 54% の確率でロス0になるため）
      - 注入区間でクロックのステップ補正なし（Skew 0.108ppm）。
        Collector は全区間で送出継続・失敗0
