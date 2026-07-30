# Lima VM のホスト側設定

`deploy/psconfig/` が testpoint コンテナ内の設定を持つのに対し、ここは **VM の OS 側**の設定を持つ。
コンテナのボリュームマウントとは違い自動反映されないので、変更したら下の手順で配り直す。

| ファイル | 役割 |
|---|---|
| `chrony-home-lab.conf` | 時刻源の差し替え。`/etc/chrony/conf.d/10-home-lab.conf` に置く |

## なぜ必要か — 片道遅延が測れなくなっていた

2026-07-29、TWAMP の片道遅延の 87% が品質ゲート（`CLOCK_ERROR_THRESHOLD_MS = 10.0`）で
棄却される状態になっていた。朝の時点では棄却率 41% だったので、半日で倍増したことになる。

原因は **VM の NTP 源が全て遠かった**こと。Ubuntu 既定の `pool ntp.ubuntu.com` は
Canonical の欧州サーバで、当環境からの実測 RTT は **256.8ms**。8ソース中4つがこれだった。

| 時刻源 | RTT 中央値 | ジッタ |
|---|---|---|
| `ntp.ubuntu.com`（既定） | **256.82 ms** | 17.57 ms |
| `time.cloudflare.com` | 9.28 ms | 1.63 ms |
| `ntp.jst.mfeed.ad.jp` | 9.37 ms | 2.80 ms |
| `ntp.nict.jp`（stratum 1） | 18.49 ms | 2.11 ms |
| `time.google.com` | 45.01 ms | 6.14 ms |

結果、chrony の root dispersion が 37.7ms まで膨らみ、`max-clock-error` が
恒常的にゲートを超えていた。`chronyd` のログには falseticker 判定と参照元の切り替えが
数分おきに並んでいて、どのソースも互いに一致していなかった。

**RasPi は健全だった**（`systemd-timesyncd`、`2.debian.pool.ntp.org` が国内 IPv6 に解決。
RootDelay 2.75ms / RootDispersion 1.02ms / Jitter 1.48ms）。劣化していたのは VM だけ。

差し替え直後の効果:

| | 変更前 | 変更後 |
|---|---|---|
| 参照元 | 45.76.211.39（US, stratum 2） | 133.243.238.163（NICT, **stratum 1**） |
| Root dispersion | **37.72 ms** | **8.67 ms** |
| Root delay | 12.07 ms | 9.58 ms |
| Last offset | +9.73 ms | +0.60 ms |
| ソースの不確かさ | ±29〜133 ms | ±4.8〜8.9 ms |

## 配置

```bash
limactl shell perfsonar-vm bash -lc '
  sudo cp /Users/dev/src/perfsonar-otel-bridge/deploy/vm/chrony-home-lab.conf \
          /etc/chrony/conf.d/10-home-lab.conf
  # 既定の遠距離プールを無効化する（chrony に unpool 相当の指示は無いためコメントアウト）
  sudo cp -n /etc/chrony/chrony.conf /etc/chrony/chrony.conf.orig
  sudo sed -i -E "s@^(pool .*)\$@#\1@" /etc/chrony/chrony.conf
  sudo systemctl restart chrony'
```

`/etc/chrony/chrony.conf.orig` に元ファイルが残る。戻すときはこれを書き戻して再起動する。

## 検証

```bash
# 参照元・root dispersion・skew
limactl shell perfsonar-vm bash -lc 'chronyc tracking; chronyc -n sources'

# 実測の max-clock-error がゲート（10ms）を下回るか
limactl shell perfsonar-vm docker exec perfsonar-testpoint \
  pscheduler task --format json latency --protocol=twamp \
  --source 192.168.1.104 --dest 192.168.1.101
```

## 収束後（差し替えから約8分）

| | 変更前 | 収束後 |
|---|---|---|
| Root dispersion | 37.72 ms | **0.149 ms** |
| Root delay | 12.07 ms | 9.46 ms |
| Skew | 19.24 ppm | **3.32 ppm** |
| Frequency | 590〜2586 ppm slow | **2.39 ppm slow** |
| Update interval | 64.9 s | 16.2 s |

日中の `max-clock-error` は実測 **0.15〜0.25ms** で、ゲート（10ms）に対して十分な余裕がある。
`Frequency` が 590〜2586 ppm の幅で振れていたのは、
**RTT 257ms・ジッタ 30ms のソースを食わされた chrony が周波数を推定できていなかった**ため。
まともな時刻源を与えたら 2.39 ppm に収まった。

## これで直るのは2つのうち1つだけ

> **重要**: 当初この節には「『VM のクロックが構造的に不安定』という当初の見立ては誤りだった。
> ハードウェアの問題に見えたものが設定の問題だった」と書いていたが、**これは過剰な訂正だった。**
> 日中のデータだけを見て、時刻源の修復を「仮想化の問題は無かった」ことの証拠に使ってしまった。
> **片方の原因を潰したことは、もう片方が無いことの証拠にならない。**

実際には**2つの独立した問題が重なっていた**（experiments/w2-notes.md Step 14 / Step 16）:

| | 症状 | 原因 | 状態 |
|---|---|---|---|
| 問題1 | 終日 `clock_error` 20ms 前後、root dispersion 37.7ms | 遠距離 NTP 源（RTT 257ms） | **このファイルで解決** |
| 問題2 | 深夜のみ 0.6〜5.8 秒のステップ補正、`clock_error` 1156ms | vz のクロック飢餓 | **未解決** |

### 問題2: Lima がゲストのクロックを毎分上書きしている（設定では直らない）

**Lima のホストエージェントは10秒ごとにゲストのクロックを監視し、
閾値（約100ms）を超えたらホスト時刻に強制上書きする。**
`~/.lima/perfsonar-vm/ha.stderr.log` に記録が残る:

```
03:00:02  Time sync: guest clock adjusted (was 2464ms off)
03:00:12  Time sync: guest clock adjusted (was 648ms off)
03:00:22  Time sync: drift 0ms within threshold
03:00:42  Time sync: guest clock adjusted (was 5400ms off)
```

ゲスト側では時刻が**巻き戻る**:

```
lima-guestagent: SyncTime: system time synchronized with host (drift was 5.785047093s)
systemd-journald: Time jumped backwards, rotating.
```

VM 作成（2026-07-26）からの実績:

| | |
|---|---|
| 監視ポーリング | **27,452 回**（10秒間隔） |
| 実際に上書きした回数 | **4,734 回**（約15%） |
| 頻度 | 89.6時間で 4,734 回 = **約68秒に1回** |
| drift 中央値 | **123 ms** |
| drift p90 / p99 | 1,468 ms / 3,618 ms |
| drift 最大 | **6,725 ms** |
| 1秒超の上書き | **518 回（10.9%）** |

chrony は `makestep 0.1 -1` なので 100ms 未満は slew、それ以上でステップする。
**chrony は常に負け続けている。**

#### 無効化できない

- `lima-guestagent daemon` のフラグは `--tick` / `--runtime-dir` / `--socket-owner` /
  `--virtio-port` / `--vsock-port` のみ。**時刻同期を切るものは無い**
- Lima のデフォルトテンプレート（`limactl tmpl copy template://default`）にも設定項目が無い
- `--plain` はマウント・ポートフォワード・containerd ごと落とすので代替にならない

**これは Lima の設計意図**（ゲストの時刻をホストに追従させる）であってバグではない。
開発用 VM としては正しい動作だが、**自前の NTP 規律と正直な誤差申告が要る
測定ノードとは根本的に両立しない。**

#### 影響範囲

| メトリクス | 影響 |
|---|---|
| `rtt.mean` / `rtt.max`（twping） | **なし**（クロック非依存） |
| `packet.loss.ratio` | **なし** |
| `throughput.bps` / `retransmits` | **なし** |
| `trace.hops` | **なし** |
| `twamp.delay.median`（片道遅延） | **測定不能**。測りたい量が 0.5ms なのに、クロックが68秒ごとに中央値 123ms 上書きされる |

W2 Step 0 で「LAN 区間の RTT は `latency`(twamp) ではなく `rtt` テストを `--tool twping`
で実行する」と決めていたため、**パイプラインは片道遅延に依存していない。**
品質ゲートが壊れた値を落としているので、データの正しさも保たれている。

#### 確認コマンド

```bash
# 上書きの総数と drift の分布
grep -ac 'guest clock adjusted' ~/.lima/perfsonar-vm/ha.stderr.log
grep -ao 'was [0-9]*ms off' ~/.lima/perfsonar-vm/ha.stderr.log \
  | grep -o '[0-9]*' | sort -n | tail -3
```

#### 次の一手

**片道遅延を測りたいなら、測定ノードを Lima の外に出す**しかない
（bare metal、または時刻同期を強制しない仮想化）。
物理マシンではこれが起きないことを RasPi が同期間で実証している。
片道遅延を諦めるなら現状のままで問題ない。

## さらに詰めるなら

日中に限れば、**仮想マシンである VM のほうが物理マシンの RasPi より2桁良い**:

| | VM（Lima・仮想） | RasPi（物理） |
|---|---|---|
| RMS offset | **20.9 µs** | — |
| Jitter | — | **2.620 ms** |
| Skew | **0.070 ppm** | — |
| Root dispersion | **117 µs** | 274 µs |
| ポーリング間隔 | **16〜64 秒** | **34分8秒** |

RasPi は `systemd-timesyncd` がサーバ1台を34分間隔で引いているだけで、その間クロックは
自由にドリフトする。片道遅延の実測が RTT 0.95ms に対し 0.01〜2.27ms の鋸歯状になるのは
ここから来ている可能性が高い。**RasPi にも chrony を入れて両端を対称にするのが次の一手。**

`/dev/ptp*` は存在しないので、ホストのクロックを直接引き込む手（`refclock PHC`）は使えない。
