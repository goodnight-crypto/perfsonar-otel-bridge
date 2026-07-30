# W3 検証メモ

ハマりポイント・判断の記録。記事の一次情報になるため、失敗もそのまま残す。

## テンプレート
- 日付:
- やったこと:
- 結果 / エラー:
- 判断・回避策:

## Step 1: LG Gram 13Z970 の bare metal 化（Step A〜F 完了）

- 日付: 2026-07-30
- やったこと: `docs/lggram-kitting.md` の Step A〜F をユーザーが実施。
  Windows 10 → Ubuntu Server にディスク全消去で入れ替え、DHCP 予約で IP を固定した。
- 結果 / エラー:
  - ホスト名 `lggram-testpoint`、ユーザー `dev`、**IP `192.168.1.102`**（DHCP 予約）
  - Step F まで到達。SSH は本体コンソールまたはパスワード認証で疎通している
  - **Mac から Claude Code の鍵（`dev@macmini.local`）では公開鍵認証に失敗する。**
    `id_ed25519` / `id_ed25519_lms` のどちらも `Permission denied (publickey,password)`。
    Step E-1 の `ssh-copy-id` が未実施か、別の鍵が入っている。Step G の前提が満たせていない
- 判断・回避策: ユーザーに `ssh-copy-id dev@192.168.1.102` を依頼する。

### 前提条件の訂正: USB NIC が 100M だった

手順書では「USB NIC は手元にある」を前提に組んだが、**実物は 100Base-TX 品**だった。
1000Base-T 対応品は納品待ち。

```
$ sudo ethtool -i enx00e04c5cce6d
driver: r8152
version: v1.12.13
bus-info: usb-0000:00:14.0-3

$ sudo ethtool enx00e04c5cce6d | grep -i speed
        Speed: 100Mb/s

$ sudo ethtool -T enx00e04c5cce6d
Time stamping parameters for enx00e04c5cce6d:
Capabilities:
        software-receive
        software-system-clock
PTP Hardware Clock: none
Hardware Transmit Timestamp Modes: none
Hardware Receive Filter Modes: none
```

#### タイムスタンプ能力（手順書 Step E-4 の記録）

**ハードウェアタイムスタンプは非対応**（`PTP Hardware Clock: none`）。想定どおりで、
これが bare metal 化しても残る精度限界にあたる。

さらに **`software-transmit` も出ていない**（`software-receive` と `software-system-clock` のみ）。
ただし `twping` はカーネルの `SO_TIMESTAMPING` ではなくユーザー空間でタイムスタンプを打つため、
片道遅延の測定がこれで直接できなくなるわけではない。**実測して確かめる必要がある。**

#### 影響範囲の切り分け

| メトリクス | 100M の影響 | 根拠 |
|---|---|---|
| `twamp.delay.*`（片道遅延） | **ほぼ無し** | TWAMP のテストパケットは小さく、100Mbps でのシリアライゼーション遅延は 10µs 未満。測りたい量（0.5ms 前後）に対して2桁小さい。**移行の目的である片道遅延は、100M NIC のままでも検証できる** |
| `rtt.mean` / `rtt.max` | ほぼ無し | 同上 |
| `packet.loss.ratio` | ほぼ無し | 負荷をかけないテストのため |
| `throughput.bps` | **測定不能** | 100Base-TX の上限は TCP goodput で約 94Mbps。**現行ベースライン 929〜940Mbps と一桁違う** |
| `trace.hops` | 無し | — |

#### 運用上の帰結

throughput タスクをこのまま LG Gram に切り替えると、**Splunk の
`lan-throughput-degraded` Detector が恒常的に発火する。** 閾値は直近24時間の
GbE 実測（929〜940Mbps）から決めてあるため、94Mbps は常時「劣化」と判定される。

**判断: throughput タスクの切替は GbE NIC の到着まで保留する。**
Lima VM は `docs/lggram-kitting.md`「切替時の注意」のとおり停止せずに残してあるので、
片道遅延の検証だけを LG Gram で先行させ、throughput は VM 側で継続できる。

#### 切り分け結果: アダプタ自体が 100M 品で確定

ケーブルやスイッチポート側のリンクダウングレードではなかった。**GbE 品の買い足しが必要。**

```
$ lsusb | grep -i realtek
Bus 001 Device 010: ID 0bda:8152 Realtek Semiconductor Corp. RTL8152 Fast Ethernet Adapter

$ ethtool enx00e04c5cce6d
	Supported link modes:   10baseT/Half 10baseT/Full
	                        100baseT/Half 100baseT/Full
	Link partner advertised link modes:  10baseT/Half 10baseT/Full
	                                     100baseT/Half 100baseT/Full
	Speed: 100Mb/s
	Duplex: Full
```

`Supported link modes` に 1000baseT が無い。`r8152` ドライバは RTL8152（10/100）と
RTL8153（10/100/1000）を兼ねるため、ドライバ名だけでは判別できない。**製品名は `lsusb` で見る。**

## Step 2: 実機状態の確認（Step G の着手前）

- 日付: 2026-07-30
- やったこと: 鍵認証が通るようになったので、Mac から SSH で状態を棚卸しした。
- 結果 / エラー:

| 項目 | 実測値 | 判定 |
|---|---|---|
| `uname -m` | `x86_64` | OK（RasPi / VM は `aarch64`） |
| OS | Ubuntu 24.04.4 LTS | OK |
| `stat -fc %T /sys/fs/cgroup/` | `cgroup2fs` | OK |
| IP | `192.168.1.102/23` | OK（後述） |
| 蓋・スリープ | `HandleLidSwitch=ignore`、sleep 系4ターゲット全て masked | OK（Step E-2 / E-3 完了） |
| 時刻同期 | `systemd-timesyncd`（NTPSynchronized=yes）、chrony 未導入 | **要対応** |
| タイムゾーン | `Etc/UTC` | **要判断**（RasPi / VM と揃えるなら Asia/Tokyo） |
| Docker | 未導入 | **要対応** |
| `sudo -n` | パスワード必須 | **ブロッカー**（後述） |
| RasPi への疎通 | ICMP RTT avg **1.557 ms**（3発、ロス0） | 後述 |

#### ネットマスクが /23 だった

`192.168.1.102/23` すなわち `192.168.0.0/23` で、`192.168.0.x` と `192.168.1.x` が同一セグメント。
archiver の `_url` が `http://192.168.0.1:8088/archive`（Mac）でありながら
testpoint 群が `192.168.1.x` にいるのは、これで整合する。**設定ミスではない。**

#### lg-laptop ドライバは有効だった

手順書 Step E-5 で「実機で確認する」としていた点の結論。**ドライバは読み込まれている。**

```
$ ls /sys/devices/platform/lg-laptop/
battery_care_limit  fan_mode  fn_lock  leds  reader_mode  usb_charge  ...

$ cat /sys/devices/platform/lg-laptop/battery_care_limit
80
```

**既に 80 で、こちらから設定する必要は無かった。** バッテリーは `BAT0` ではなく `CMB0`
という名前で、現在 97% / `Not charging`。上限 80% に対して 97% あるので、
放電して 80% で止まるまで充電が入らない状態と読める。手順書の `BAT*` 前提は外れていた。

#### 気になる観測: RasPi への RTT が VM より遅い

| 経路 | ツール | RTT |
|---|---|---|
| VM → RasPi（既存ベースライン） | `twping` | **0.944 ms** |
| LG Gram → RasPi（今回） | ICMP `ping` | **1.557 ms** |

**ツールが違うので直接比較はできない。** ただし +0.6ms は 100Base-TX の
シリアライゼーション遅延（小パケットで 10µs 未満）では説明が付かない。
説明候補は **USB ホストコントローラのポーリング遅延**で、これは PROJECT.md が
W4 候補の時点で挙げていた「USB NIC はジッタで逆効果」という懸念そのものにあたる。

**前節で「100M の影響は片道遅延にほぼ無い」と書いたが、それはリンク速度の話でしかない。
USB 接続であること自体の上乗せは別問題として残る。** Step G で `twping` を同条件で
実測して切り分ける。ここで効くのは定常的なオフセットではなく**ジッタ**なので、
`twping` の two-way jitter と片道遅延の分散を見る。

- 判断・回避策: Step G の実測待ち。GbE NIC が届いたら同じ測定を繰り返して
  「100M USB / GbE USB / virtio(VM) / RasPi 実 NIC」の4条件を並べる。**記事の材料になる。**

#### ブロッカーだったもの: sudo にパスワードが必要（解決済み）

Docker 導入・chrony 導入・タイムゾーン変更が全て `sudo` を要求し、
Claude Code の SSH（疑似端末なし）からは実行できない。
RasPi は `sudo -n true` が通る（Raspberry Pi OS の既定）ため、これまで問題にならなかった。
LG Gram は Ubuntu Server の既定でパスワードを要求する。**ユーザー判断待ち。**

## Step 3: Step G 完了 — 片道遅延が測れるようになった

- 日付: 2026-07-30
- やったこと: `sudo` の NOPASSWD 設定後、`docs/lggram-kitting.md` Step G を実施。
  タイムゾーン設定 → chrony 導入 → Docker 導入 → testpoint 起動 → 実測。
- 結果 / エラー: **移行の目的を達成した。片道遅延が正の値で測れている。**

### つまずき2件

**1. `usermod -aG docker $USER` が効かない。** `ssh host 'command'` は非対話シェルで
`$USER` が未設定のため、`usermod -aG docker ""` になっていた。`dev` を直接書く。

**2. グループ追加後も新しい SSH セッションに反映されない。** Mac 側 `~/.ssh/config` の
`Host *` に `ControlMaster auto` / `ControlPersist 10m` があり、接続が多重化されて
再ログインになっていなかった。`ssh -O exit <host>` でマスター接続を切ると反映される。
**RasPi でも同じ罠を踏む可能性がある。**

### chrony（`deploy/timesync/chrony-home-lab.conf` をそのまま流用）

| | 導入直後 | 収束後（約8分） |
|---|---|---|
| Stratum | 2 | 2 |
| Root dispersion | 9.23 s | **0.389 ms** |
| Skew | 1000000 ppm | **3.648 ppm** |
| RMS offset | 678 µs | **364 µs** |
| Update interval | 1.2 s | 16.1 s |

参照元は NICT（133.243.238.163、stratum 1）ほか。VM の収束後（root dispersion 0.149ms /
Skew 3.32ppm）と同水準。**設定ファイルは VM 用と同一のもので足りた。**

### 本題: 片道遅延（TWAMP、LG Gram → RasPi、100発）

生 JSON は `docs/samples/latency-twamp-lggram-192.168.1.101-20260730-154500.json`。

| | Lima VM（2026-07-27） | **LG Gram（今回）** |
|---|---|---|
| 片道遅延の分布 | 89ビン全て **-11.71 〜 -11.86 ms** | **0.150 〜 0.380 ms** |
| 中央値 | 負値（物理的にあり得ない） | **0.220 ms** |
| 負値の発数 | 全発 | **0 発** |
| `max-clock-error` | 27.47 ms（ゲート 10ms 超過 → 全棄却） | **0.32 ms**（余裕をもって通過） |

**Lima を出たことで、品質ゲートに落ちない片道遅延が初めて得られた。**

### RTT の比較（同日・同条件、どちらも `twping`）

| 経路 | Min | Mean | Max | **StdDev** |
|---|---|---|---|---|
| VM → RasPi | 0.606 | 0.986 | **2.805** | **0.240** ms |
| LG Gram → RasPi | 1.005 | 1.334 | **1.748** | **0.180** ms |

**USB NIC は平均を +0.35ms 押し上げたが、ジッタは VM より小さい。**
最大値も 2.805 → 1.748ms と裾が締まっている。

PROJECT.md が W4 候補の時点で書いていた「USB NIC はジッタで逆効果」という懸念は、
**少なくとも Lima VM との比較では外れた。** USB ホストコントローラのポーリングは
定常的なオフセットとして乗るが、仮想化のスケジューリング遅延ほど分散を生まない。
片道遅延で効くのはオフセットよりジッタなので、この結果は移行に有利に働いている。

### 断定できないこと

片道遅延の中央値 0.220ms に対し、RTT の半分は 0.667ms である。差分 0.45ms は
**「往路が速く復路が遅い経路非対称」と読めるが、断定できない。**
`max-clock-error` が 0.32ms あり、**測ろうとしている量と同じオーダーの不確かさ**が残っている。

不確かさの主因は RasPi 側と考えられる。RasPi は `systemd-timesyncd` がサーバ1台を
34分8秒間隔で引いているだけで、その間クロックは自由にドリフトする（W2 の実測）。
**W3 課題「RasPi に chrony を入れて両端を対称にする」を先に片付けないと、
この非対称は解像できない。**

- 判断・回避策:
  - **切替判定は合格。** ただし throughput タスクのみ GbE NIC 到着まで VM 側に残す
  - 次は RasPi への chrony 導入。両端を対称にしてから片道遅延を再測定する

## Step 4: RasPi の時刻源を chrony に統一（両端の対称化）

- 日付: 2026-07-30
- やったこと: RasPi の `systemd-timesyncd` を chrony に置き換え、
  LG Gram / VM と同じ `deploy/timesync/chrony-home-lab.conf` を配った。
- 結果 / エラー:

### 移行前（`systemd-timesyncd`）

```
       Server: 240b:4009:23a:c064:fe41:d658:e951:c18f (2.debian.pool.ntp.org)
Poll interval: 34min 8s (min: 32s; max 34min 8s)
       Offset: +1.092ms
        Delay: 9.776ms
       Jitter: 1.544ms
 Packet count: 185
    Frequency: -9.767ppm
Root distance: 2.593ms
```

**時刻源はサーバ1台のみ、ポーリング間隔は 34分8秒。** その間クロックは自由にドリフトする。
W2 の時点で「片道遅延が RTT 0.95ms に対し 0.01〜2.27ms の鋸歯状になる」原因として
疑っていた箇所である。

なお OS は **Debian 13 (trixie)**。`docs/raspi-kitting.md` は Bookworm 前提で書いてあるが、
実機は trixie に上がっている。`confdir /etc/chrony/conf.d` はそのまま使える。

### 設定の配置

Debian の `chrony.conf` は `confdir /etc/chrony/conf.d` を持つため、LG Gram / VM と同じ手順で通る。
既定の `pool 2.debian.pool.ntp.org iburst` はコメントアウトした。

`sourcedir /run/chrony-dhcp` も設定にあるが**中身は空**で、
ルーターは DHCP で NTP サーバを配っていない。意図しない時刻源の混入は無い。

### 設定ファイルの置き場所について（要整理）

`chrony-home-lab.conf` は現在 `deploy/timesync/` にあるが、**VM・LG Gram・RasPi の3台に
同じものを配っている。** ファイル冒頭のコメントも「Lima VM の時刻源を差し替える」のままで
実態と合っていない。`deploy/timesync/` 等へ移すのが素直だが、
`deploy/timesync/README.md` は記事の一次情報を多く含むため、移動はユーザー判断を仰ぐ。

### 移行後（chrony、収束約8分）

| | RasPi 移行前 (timesyncd) | **RasPi 移行後** | 参考: LG Gram |
|---|---|---|---|
| 参照元 | `2.debian.pool.ntp.org` の1台 | **`ntp-b2.nict.go.jp`（stratum 1）** | **同じ `ntp-b2.nict.go.jp`** |
| ポーリング間隔 | **34分8秒** | **64.2 秒** | 64.2 秒 |
| RMS offset | —（Jitter 1.544ms） | **111 µs** | 68 µs |
| Skew | — | **0.789 ppm** | 0.171 ppm |
| Root dispersion | 2.593 ms（root distance） | **0.405 ms** | 0.409 ms |

**両ノードが同一のサーバを参照する状態になった。** 共通の参照点を持つことで、
ソース間の食い違いが片道遅延に化ける経路を断てる。

## Step 5: 両端 chrony での片道遅延 — 経路非対称が解像した

- 日付: 2026-07-30
- やったこと: 両端 chrony の状態で、片道遅延を**両方向**測定した。
  生 JSON は `docs/samples/latency-twamp-lggram-to-raspi-20260730-161800.json` と
  `docs/samples/latency-twamp-raspi-to-lggram-20260730-161900.json`。
- 結果 / エラー:

| 方向 | min | **median** | mean | max | stddev | `max-clock-error` |
|---|---|---|---|---|---|---|
| LG Gram → RasPi | 0.180 | **0.230** | 0.241 | 0.360 | **0.036** ms | 0.39 ms |
| RasPi → LG Gram | 0.680 | **1.150** | 1.181 | 1.600 | **0.210** ms | 0.37 ms |

### 測定の内部整合性が取れた

```
片道遅延の合計 (mean): 0.241 + 1.181 = 1.423 ms
実測 twping RTT (mean):                 1.369 ms
差:                                     0.054 ms
```

**差 0.054ms は `max-clock-error` 0.39ms の 1/7 で、誤差の範囲に収まっている。**
別々に測った2方向の片道遅延の和が、独立に測った RTT と一致した。
**Step 3 で「断定できない」としていた非対称は、実在した。**

### 非対称の正体は USB NIC の受信側

差は **0.940 ms**。向きは **LG Gram が受け取る方向が遅い**。

`max-clock-error` 0.39ms に対して非対称が 0.94ms あり、**約2.4倍。**
クロック誤差では説明できない大きさなので、経路の性質として読める。

USB NIC の送受信は非対称である。**送信はホスト起点で即座に発行できるが、
受信はホストコントローラがポーリングするまでカーネルに上がらない。**
`ethtool -T` が `software-receive` しか出さなかったこととも符合する
（`software-transmit` が無い = 送信側でカーネルがタイムスタンプを打つ経路が無い）。

RasPi 側は PCIe 直結の GbE なのでこの遅延を持たない。したがって
**「LG Gram が受信する方向にだけ約0.9ms 乗る」**という観測になる。

### これは記事の山場になる

W2 の時点では「Lima がクロックを壊すので片道遅延は測れない」で終わっていた。
bare metal 化と両端の時刻源統一を経て、**同じ測定系で「経路の非対称」という
ネットワークの性質を検出できるところまで来た。**

しかも検出したのは自分で持ち込んだ USB NIC の癖であり、
**「測定系の限界を測定系自身で可視化した」**という筋になっている。
片道遅延を RTT の半分で代用してはいけない理由の実例としても使える。

### 残る注意点

- 0.94ms の非対称は **100M NIC での値**。GbE 品に替えたら再測定して差分を見る
- `max-clock-error` 0.37〜0.39ms は依然として **0.23ms（順方向の中央値）より大きい。**
  順方向の絶対値は誤差と同オーダーで、まだ精度が足りない。
  非対称の 0.94ms が誤差より十分大きいので今回の結論は立つ、という関係にある
- 判断・回避策: GbE NIC 到着後に同じ2方向測定を繰り返す。
  W3 課題「RasPi の時刻同期を対称にする」は**完了**とする。

## Step 6: pSConfig 切替は GbE NIC 到着まで待つ（判断）

- 日付: 2026-07-30
- 判断: **切替を待つ。** GbE NIC が同日到着予定のため、100M のまま切り替えて
  throughput だけ VM に残す変則構成を作らない。

`home-lab-mesh.json` を「1グループ = 1ノード」から「latency 系は LG Gram、
throughput だけ VM」に割るには、`groups` と `tasks` の両方を分ける必要がある。
**数時間しか使わない構成のために構造を複雑にする価値が無い。**
GbE NIC が届けば `addresses.vm` を差し替えるだけで済む。

### 現在の状態（切替待ち）

| | 状態 |
|---|---|
| Splunk へのデータ | **VM 経由で継続中。欠測なし** |
| LG Gram | testpoint 稼働中。pSConfig 未投入のため定期タスクは持たない |
| RasPi | chrony 化済み。**VM とのペアでも LG Gram とのペアでも対称** |
| Lima VM | 稼働中。停止しない |

RasPi の chrony 化だけは先に入れたが、これは**どちらのノードと組んでも有利**なので
切替を待つ理由が無い。VM との既存ペアの片道遅延も、Lima のクロック上書きが残る以上
改善しないが、悪化もしない。

### GbE NIC 到着後にやること

1. アダプタを差し替え、`ethtool` で `Speed: 1000Mb/s` を確認
2. **MAC が変わるので、ルーターの DHCP 予約をやり直す**（`docs/lggram-kitting.md` Step F）。
   192.168.1.102 を維持できるかを先に確認する
3. 片道遅延を両方向で再測定し、**Step 5 の 0.940ms の非対称が GbE でどう変わるかを見る**。
   USB のポーリング由来なら残り、100M のリンク速度由来なら消える。**切り分けの好機**
4. throughput を手動で1回測り、929〜940Mbps 相当が出ることを確認（**実行前にユーザー確認**）
5. `home-lab-mesh.json` の `addresses.vm` を差し替えて pSConfig 再適用
6. Splunk で着弾を確認してから `limactl stop perfsonar-vm`

## Step 7: 公開 perfSONAR ホストの選定に着手（GbE NIC 待ちの窓）

- 日付: 2026-07-30
- 作業ログ: **[public-hosts.md](public-hosts.md)**（候補一覧・実測・選定理由はすべてそちら）
- 手順書: `docs/runbook-w2-public-hosts.md`（W2 に書いたもの。今回の実行で 5 点を修正した）

GbE NIC の到着待ちで空いた窓に、W2 の Runbook の **Step 1〜4（候補選定の実測）**を進める。
pSConfig への組み込み（Step 5）は **Step 6 の切替作業にまとめる**ので今回は触らない。

**今日の作業でこの Runbook の価値が上がった。** W2 当時は片道遅延が測れず、WAN パスを
足しても ICMP RTT が増えるだけだった。いまは公開ホストの TWAMP responder に対して
**WAN 区間の片道遅延と経路非対称**が取れる可能性がある。Step 5 で見つけた 0.94ms の
非対称は自分の USB NIC 由来だが、**インターネット区間の非対称は経路由来**であり、
記事の主張を一段強くする。

### 実行前に Runbook の前提が 2 つ崩れていた

- **stats.perfsonar.net は Grafana の SPA。** JavaScript が要るので WebFetch では
  ホスト一覧を取れない（HTTP 200 は返るが本文はローディング失敗のメッセージのみ）
- **Lookup Service に GET の検索 API が無い。** `ls.perfsonar.net/lookup/records` は
  POST 専用の登録用エンドポイント（GET は 405）

→ **Step 1 の候補リストアップはユーザーがブラウザで実施**する形に一本化した。

### 実行ノードを VM から LG Gram に変えた

Runbook は VM を前提に書いていたが、**LG Gram（192.168.1.102）で実行する。**

- LG Gram は **pSConfig 未投入で定期タスクを持たない**ので、手動テストが本番スケジュールと
  衝突しない（VM は 6 タスクが 5 分間隔で回っている）
- **LG Gram が切替後の本番ノード**なので、選定の実測がそのまま本番構成の実測になる
- USB 100M NIC 由来の上乗せ（RTT +0.35ms・片道 +0.94ms）は、**WAN の RTT 10〜50ms 想定**に対して
  選定の判断に影響しない

### 結果: 2 台を選定した（Step 1〜4 完了）

| | ホスト | 組織 | 測定 |
|---|---|---|---|
| 1 台目 | `perf-tokyo.sinet.ad.jp` | SINET（NII） | **twamp**（片道遅延可） |
| 2 台目 | `ps-tkb-100g.riken.jp` | 理化学研究所 | **twamp**（片道遅延可） |

**TWAMP は自宅 NAT を越えた。** 事前に最大のリスクと見ていた点だったが、候補 7 台中 5 台で
片道遅延が取れた。**WAN 区間でも片道遅延と経路非対称を観測できる**ことになる。

### 収穫 1: 「速い」と「安定」は一致しなかった

`perfsonar1.icepp.jp` は **Round 1 で 3.70ms と最速タイ**、ロス 0、`max-clock-error` 0.3ms の
優等生だった。それが **Round 2 で 79.89ms、Round 3 で 90.31ms + 初のロス**に劣化した。
**1 回の測定で選んでいたら確実に掴んでいた。**

逆に最も振れ幅が小さかったのは、最も遅い `perf-osaka.sinet.ad.jp`（3 回で 0.14ms）だった。

### 収穫 2: 既存の常時観測だけで切り分けられた

ICEPP の劣化が自宅の上り側かどうかを、**追加の測定を一切せずに**切り分けられた。
VM が 5 分間隔で 1.1.1.1 に打っている本番タスクの実測値を引いたところ、劣化した時刻帯を
挟んで平常値（mean 8.9ms、ロス 0）だった。同じ Round の直後に測った理研 2 台も平常だった。

→ **劣化は ICEPP 側の経路に固有。** 単発の測定では「自分の回線か相手か」を切り分けられない。
**常時観測を持っていることの価値の実演**として、記事にそのまま使える。

### WAN の非対称は、まだ NIC の癖と分離できていない

同一プロトコル（TWAMP）で片道と RTT の両方を測り、非対称を出した。ただし
**Step 5 で判明した「USB 100M NIC が受信方向にだけ +0.94ms 乗せる」**が復路に効くため、
東京 +0.86ms・ICEPP +1.05ms・理研つくば +0.84ms は**ほぼ全部が自分の NIC で説明できてしまう。**

NIC の癖で説明できないのは 2 つだけ。

- **大阪 −0.39ms**: 受信側に +0.94ms 乗ってなお復路が速い。**経路は往路が約 1.3ms 遅い**
- **理研・横浜 +1.93ms**: NIC 分を引いてもなお約 +1.0ms 残る

→ **Step 6 に書いた「GbE 交換は切り分けの好機」が、LAN だけでなく WAN でも使えることになった。**
NIC 由来の 0.94ms が消えれば、残る非対称は経路由来と言い切れる。

### 現在の状態

| | 状態 |
|---|---|
| Step 1〜4（候補選定の実測） | **完了。2 台選定済み** |
| Step 5（pSConfig への組み込み） | **GbE 切替にまとめる**（Step 6 の作業リストに追加済み） |
| Runbook の修正 | **完了**（Step 1 の取得手段、実行ノード、Step 3 のコマンド、Step 4 の間隔、Step 5 の延期） |
| LG Gram の testpoint | オールOK。**残留タスク 0 件** |
| VM の本番測定 | 8 タスク稼働中。**欠測なし** |
| Splunk への着弾 | 直近 6 時間・**全 7 チャートにデータあり** |
