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

## Step 5: Splunk ダッシュボード【ユーザー作業・未実施】

`.env` には INGEST トークンしか無く API からダッシュボードを作れないため、UI 作業になる。

作る前にデータを溜めること。RTT / ロスは5分間隔、スループットは30分間隔なので、
半日〜1日置けばスクリーンショットがそのまま記事に使える密度になる。

想定するチャート:

| チャート | メトリクス | 分割 |
|---|---|---|
| LAN RTT の推移 | `perfsonar.rtt.mean` / `.max` | `path.id` = lan-wired、`ps.source` で方向別 |
| WAN RTT の推移 | `perfsonar.rtt.mean` | `path.id` = wan-cloudflare / wan-blog |
| パケットロス率 | `perfsonar.packet.loss.ratio` | `path.id` 別 |
| スループット | `perfsonar.throughput.bps` | `path.id` = lan-wired（30分間隔、`ps.source` で方向別） |
| 経路ホップ数 | `perfsonar.trace.hops` | `path.id` = wan-cloudflare |
| 片道遅延（品質ゲート付き） | `perfsonar.twamp.delay.median` | `ps.max_clock_error` を併記 |

利用できる dimension: `ps.source` `ps.destination` `ps.test.type` `ps.tool` `path.id`
`ps.max_clock_error`（latency のみ） `ps.retransmits`（throughput のみ）。

`ps.tool` で LAN の RTT が TWAMP 由来（twping）か ICMP 由来（ping）かを判別できる。

---

## Step 6: Detector 3種【ユーザー作業・未実施】

| Detector | 条件 | 狙い |
|---|---|---|
| パケットロス（静的閾値） | `perfsonar.packet.loss.ratio` > 0.01 が継続 | 明確な障害 |
| RTT 異常検知 | `perfsonar.rtt.mean` の急上昇（過去比） | 遅延の劣化 |
| スループット劣化 | `perfsonar.throughput.bps` が基準値を下回る | 有線区間の劣化 |

**ロス率の閾値を決める前に、平常時のロス率を実データで確認すること。** 平常時が常に 0.0 なら
静的閾値で足りるが、揺らぎがあるなら誤検知する。

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

### 注意

**netem は egress にのみ効く。** また `lima0` は測定経路であると同時に**ブリッジへの
テレメトリ経路でもある**（Mac の 192.168.0.1 は同一 LAN）。注入すると archiver の PUT にも
同じ遅延・ロスがかかる。100ms の遅延と 3% のロスは TCP の再送で吸収される範囲だが、
「メトリクスが届かない」と「メトリクスが劣化を示す」を混同しないよう、注入中も
Collector のカウンタが増え続けていることを確認すること。

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
- [ ] Splunk ダッシュボードで `path.id` 別の RTT / ロス / スループットが見える
- [ ] Detector 3種が定義され、平常時に誤検知しないことを確認
- [ ] tc netem 注入 → メトリクス変化 → Detector 発火 → 復旧、を記録（スクリーンショット込み）
