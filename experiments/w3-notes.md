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

## Step 8: GbE NIC への交換 — 0.94ms の非対称は消え、測定は精度の床に当たった

- 日付: 2026-07-30
- 交換品: **ASIX AX88179**（`0b95:1790`）。USB 3.0 接続、Bus 002・5000M
- 結論: **Step 5 の 0.940ms の非対称は USB 2.0 接続由来だった。GbE 化で消えた。**
  同時に、**LAN の片道遅延はクロック精度の限界に達し、もう非対称を解像できない。**

### 交換前後の機材比較

| | 旧 RTL8152 | 新 AX88179 |
|---|---|---|
| チップ | **Fast Ethernet 専用品**（GbE 品の 100M 動作ではなかった） | Gigabit |
| USB | Bus 001 / **480M** | Bus 002 / **5000M** |
| ドライバ | `r8152` | `ax88179_178a`（後述の config 切替が必要） |
| `ethtool -T` | `software-receive` のみ | **`software-transmit` + `software-receive`** |

`software-transmit` が生えたことは、Step 5 の「送信側でカーネルがタイムスタンプを
打つ経路が無い」という読みのドライバ側の裏付けになる。

### つまずき 1: netplan がインタフェース名を直書きしていた（交換前に発見・回避）

`/etc/netplan/50-cloud-init.yaml` が `enx00e04c5cce6d` を直書きしていた。
NIC を替えると名前が `enx<新MAC>` になり、**netplan がマッチせず DHCP を打たない。**
`wlp1s0` は DOWN なので、そのまま抜いていれば**コンソール作業でしか復旧できなかった。**

対処（交換前に実施。現 NIC にもマッチするので当時の接続は切れない）:

```yaml
network:
  version: 2
  ethernets:
    usbnic:
      match:
        name: "enx*"
      dhcp4: true
```

あわせて `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg` に
`network: {config: disabled}` を置き、cloud-init による再生成を止めた。

**教訓: NIC 交換の手順書には「抜く前にインタフェース名の直書きを潰す」を入れる。**

### つまずき 2: 汎用ドライバ cdc_ncm が先に掴んでいた

AX88179 は USB configuration を 3 つ持ち、**既定で config 2（CDC-NCM）**を選ぶ。
すると汎用の `cdc_ncm` が bind し、次の状態になる。

| | cdc_ncm | ax88179_178a |
|---|---|---|
| Duplex | **Half**（誤報告） | Full |
| Auto-negotiation | **off**（誤報告） | on |
| 送信コアレス | **`tx_timer_usecs=400`** | 無し |

**`tx_timer_usecs=400` は最大 0.4ms の送信遅延を入れる。** 片道遅延 0.2ms を測る
機材としては使えない。config 1（Vendor Specific Class）に切り替えると
専用ドライバ `ax88179_178a` が bind する。

`bConfigurationValue` への書き込みは USB 再列挙を誘発するため、**write(2) 自体は
`Connection timed out` を返すが切替は成功している。** 自動リバート付きのスクリプトを
書いたが、リバート側も `No such device` で失敗し、結果として config 1 に残った。
**狙って得た挙動ではない。** 再起動時に config 2 へ戻らないよう udev で固定した。

```
# /etc/udev/rules.d/99-ax88179-config.rules
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="0b95", ATTR{idProduct}=="1790", ATTR{bConfigurationValue}="1"
```

`udevadm test` で `writing '1'` を確認済み（再起動での実地確認は未実施）。

### 成果: 0.94ms の非対称は消えた

LAN（LG Gram ↔ RasPi）の片道遅延。

| 方向 | 100M（Step 5） | **GbE** | 差 |
|---|---|---|---|
| LG Gram → RasPi | 0.230 ms | 0.64 ms | +0.41 |
| **RasPi → LG Gram**（LG Gram が受信） | **1.150 ms** | **0.39 ms** | **−0.76** |
| 非対称 | **0.940 ms** | 0.25 ms（向きが逆転） | |

**改善したのは、まさに Step 5 で「USB ホストコントローラのポーリング由来」と
推定した受信方向だった。** リンク速度（100M→1000M）ではなく **USB 2.0 接続そのもの**が
原因だったことになる。ICMP RTT も **1.557ms → 0.338ms** と 1.2ms 改善している。

### 同時に判明した限界: もう LAN の非対称は解像できない

**残る 0.25ms の非対称は主張できない。** 根拠は 3 つ。

- **負値が再出現した**（復路の最小 **−0.15ms**）。物理的にあり得ない値の出現は、
  クロック誤差が真の遅延を超えた証拠。100M 時代は負値 0 発だった
- **`max-clock-error` 0.55〜0.62ms が、測っている片道遅延 0.37〜0.64ms より大きい**
- **2 方向の和 1.03ms が、独立測定の TWAMP RTT 0.745ms と一致しない。**
  Step 5 ではこの 2 つが一致したことを根拠に非対称を主張していた

両端の chrony の質にも差がある。

| | LG Gram | RasPi |
|---|---|---|
| RMS offset | 0.128 ms | **0.0128 ms** |
| Skew | 1.228 ppm | **0.044 ppm** |

**皮肉な結果になった。** 経路を速くしたことで、経路の性質より測定系の誤差のほうが
大きくなった。**「測定系の限界を測定系自身で可視化した」という Step 5 の筋は、
ここで一段深くなる。** これ以上 LAN の片道遅延を詰めるならハードウェアタイムスタンプ
（PTP 対応 NIC）が要る。AX88179 も `PTP Hardware Clock: none` である。

### WAN の非対称: 東京・つくばは機材由来だった。大阪は経路由来

WAN は片道 3.9〜7.8ms あり、クロック誤差 0.3〜0.5ms より十分大きいので**まだ測れる**。

| ホスト | 非対称（100M） | **非対称（GbE）** | 読み |
|---|---|---|---|
| SINET 東京 | +0.86 ms | **−0.00 ms** | **機材由来だった。消えた** |
| 理研つくば | +0.84 ms | **−0.04 ms** | **機材由来だった。消えた** |
| **SINET 大阪** | −0.39 ms | **−0.82 ms** | **残った。経路由来** |

**public-hosts.md で「+0.86〜+1.05ms はほぼ全部が自分の NIC で説明できてしまう」と
書いた但し書きが、実測で正しかったと確認された。** 東京とつくばの非対称は消え、
**100M でも GbE でも一貫して負だった大阪だけが残った。**

大阪は復路（大阪→自宅）が往路より 0.82ms 速い。`max-clock-error` 0.54ms より大きい。
**インターネット区間の経路非対称を、自宅から観測できた。**

### 間欠的なパケットロス: NIC 起因とは言えなかった（当初の判断を訂正）

交換直後、TWAMP の latency テストで間欠的にロスが出た。

| 対象 | 発生時のロス |
|---|---|
| LAN | 4/100、30/100 |
| SINET 東京 | 4/100 |
| SINET 大阪 | **60/100** |

交換前は LAN も WAN 7 台 × 3 ラウンドも全てロス 0 だったため、**当初は「交換で入り込んだ
回帰」と判断した。この判断は誤りだった。** 反復試験で再現しなかった。

| 検証 | 結果 |
|---|---|
| LAN の TWAMP を **12 回連続**（計装付き） | **11 回ロス 0**、1 回は `timeout` で出力なし |
| SINET 東京・大阪の TWAMP を再実行 | **どちらも 0/100** |
| LG Gram → RasPi の ICMP 30 発 | 0% |
| LG Gram → 1.1.1.1 の ICMP 30 発 | 0% |

**さらに、ロスが出た時間帯には外部の経路イベントが同時に起きていた。**
参照パス（1.1.1.1）が **RTT 8.9ms → 122ms** に劣化しており、これは Mac からも
LG Gram からも同じ値で観測された（下記）。**測定環境として荒れた窓だった。**

計装下で捕まえたカウンタは全てクリーンだった。

- リンク層のエラーは両端ともゼロ（CRC / frame / fifo / collision）
- UDP カウンタもゼロ（`InErrors` / `RcvbufErrors` / `InCsumErrors` / `MemErrors`）
- `rx_dropped` は毎ラン一定の +22（背景のマルチキャスト。ロスの有無と無相関）
- USB autosuspend は無効（`control=on`）、EEE は `not supported`
- ufw 無効。iptables に旧インタフェース名の参照なし

**正確に言うと、「NIC が原因だと示せなかった」であって「NIC は無実だと証明した」では
ない。** 発生した 4 件のうち LAN の 2 件は USB 再列挙の直後に集中しており、そちらは
インタフェースの再初期化に伴う一過性と読むのが素直である。
**pSConfig 切替後も `packet.loss.ratio` を注視する。**

### 副産物: 監視系が実際の WAN 経路イベントを捉えた

切り分けの過程で、**1.1.1.1 への経路が RTT 8.9ms → 122ms（約 13 倍）に劣化している**
ことが判明した。同時刻の実測は次のとおり。

| 経路 | Mac | LG Gram |
|---|---|---|
| → 1.1.1.1 | 0% / **121.7 ms** | 0% / **122.7 ms** |
| → SINET 東京 | 0% / 8.83 ms | 0% / 8.46 ms |
| → RasPi | — | 0% / 0.501 ms |

**2 ホストが同じ値を出し、SINET 向けは正常。** つまり自宅の上り全体ではなく
**1.1.1.1（Cloudflare）への経路に固有の事象**である。ロスは伴わず遅延だけが増える形。

**これは Detector が拾うべき本物のイベントであり、記事の実例になる。**
「参照パスを 1 本持っておくと、機材の疑いを晴らすのにも使える」という
public-hosts.md の主張が、今度は逆向き（機材を疑ったが外部要因だった）で再確認された。

### throughput の手動確認: 両方向 942 Mbps・再送 0

CLAUDE.md 規約 2 に基づきユーザー確認を得たうえで手動実行した。VM の定期 iperf3 と
衝突しない空き窓（22:14 JST の次回実行まで）を選んでいる。

| 方向 | 送信側 | 受信側 | 再送 |
|---|---|---|---|
| LG Gram → RasPi | **942.27 Mbps** | 941.42 Mbps | **0** |
| RasPi → LG Gram | **942.32 Mbps** | 940.82 Mbps | **0** |

**既存ベースライン（VM ↔ RasPi）の 929〜940 Mbps を上回った。**
100M NIC のままなら約 94 Mbps だったので一桁違う。

**注目すべきは両方向が一致したこと。** 片道遅延では受信方向に 0.94ms の上乗せが
あったが、**throughput には非対称が一切出ていない**（差 0.05 Mbps、誤差の範囲）。

これは Step 5 の解釈と整合する。USB ホストコントローラのポーリング遅延は
**1 パケットあたりのレイテンシに乗る性質**のもので、パイプラインが埋まる
バルク転送ではスループットに影響しない。**「レイテンシとスループットは別物」の実例**
として記事に使える。

Detector への影響も無い。`lan-throughput-degraded` の閾値は VM 実測（929〜940 Mbps）
から決めてあり、942 Mbps はそれを下回らないため誤発火しない。

#### 途中のつまずき: 1 回目が `Run did not complete: Missed`

VM の定期 throughput が `Pending` の状態と重なった。空き窓の判定で `Running` だけを
見ていたのが誤りで、**`Pending` も含めて避ける必要がある。**
`pscheduler schedule PT35M` で前後の予定を確認してから実行する。

## Step 9: 本番の WAN 参照パスが Cloudflare 1 本だけだった（設計の弱点が実イベントで露呈）

- 日付: 2026-07-30 21:50 頃
- きっかけ: NIC 交換の切り分け中、参照パス（1.1.1.1）が RTT 8.9ms → 122ms に劣化していた

### 事象: Cloudflare だけが遠回りしている

| 宛先 | RTT avg | stddev | 判定 |
|---|---|---|---|
| 1.1.1.1（Cloudflare） | **121.5 ms** | 6.5 ms | **劣化** |
| **1.0.0.1（Cloudflare）** | **116.5 ms** | 2.5 ms | **劣化** |
| 8.8.8.8（Google） | 8.1 ms | 1.0 ms | 正常 |
| 9.9.9.9（Quad9） | 8.7 ms | 1.5 ms | 正常 |
| SINET 東京 | 8.8 ms | 0.4 ms | 正常 |

**Cloudflare の 2 アドレスだけが揃って劣化し、他の anycast DNS と学術網は正常。**

```
$ traceroute -n 1.1.1.1
 1  192.168.1.1        1.093 ms
 2-6 *                            ← ISP 側は traceroute に応答しない
 7  103.22.201.123   114.594 ms   ← Cloudflare (AS13335) の網内
 8  1.1.1.1          115.375 ms

$ traceroute -n 8.8.8.8
 1  192.168.1.1        1.552 ms
 2-6 *
 6  8.8.8.8           12.152 ms
```

**Cloudflare の網に入る時点で既に 114.6ms ある。** Cloudflare 内部ではなく、
そこへ到達するまでの経路が長い。両アドレスとも**最小値が 114ms で揃い、ジッタは小さい**
（1.0.0.1 で stddev 2.5ms）。輻輳なら最小値は低いまま最大値だけ伸びるので、
**これは安定した遠回りであり、anycast が普段と違う PoP に向いている形**と読める。

自宅の上り全体は正常である（他の 3 宛先が 8ms 台）。**ISP 障害ではない。**

### 露呈した弱点: 参照パスが 1 本しかない

本番の `wan-rtt` タスクは **1.1.1.1 のみ**を宛先にしている。

**今日の public-hosts.md で、ICEPP の劣化を「自宅の上りは無実」と切り分けた根拠は、
同時刻の 1.1.1.1 が平常値だったことだった。** あの推論は、**たまたま Cloudflare が
正常だったから成立した。** 今回のようなイベントが重なっていれば成立しなかった。

参照パスが 1 本だと、次の 2 つを区別できない。

- 自宅の上りが悪い
- **その 1 本の相手側（または相手への経路）が悪い**

今日選定した SINET 東京・理研つくばで経路多様性は増えるが、**どちらも学術網**である。
商用網側の参照が Cloudflare 1 本という構造は変わらない。

### 提案: `wan-rtt` に 8.8.8.8 を追加する

2 本が同時に動けば自宅側、片方だけなら相手側、と機械的に切り分けられる。
**今回の実測がそのまま必要性の証拠になる**（Cloudflare だけが 14 倍に伸び、
Google は平常だった）。

pSConfig 切替時にまとめて入れる。負荷は ICMP の rtt タスク 1 本分で、
公開測定ホストへの配慮は不要（パブリック DNS リゾルバ宛）。

### 記事の材料として

**自宅から常時観測を回していると、こういう事象が向こうから飛び込んでくる。**
Detector が拾うべき本物のイベントであり、「片方の指標だけ見ていると誤読する」
という主張の実例にもなっている。しかも**自分の設計の穴を自分の測定系が暴いた**形で、
Step 8 の「測定系の限界を測定系自身で可視化した」と同じ筋が繰り返されている。

## Step 10: pSConfig 切替 — 測定ノードを LG Gram へ移し、WAN パスを 3 本足した

- 日付: 2026-07-30（切替完了 22:52 JST）
- 結論: **移行は完了した。** LG Gram が LAN 3 本 + WAN 9 本を担い、**VM のタスクは 0 件**。
  VM は停止せず起動したまま残してある（ロールバック手段）。
- 同時に、今日の作業で露呈した設計上の不備 2 つを直した。
  **参照パスが Cloudflare 1 本しかない**（Step 9）ことと、
  **片道遅延の品質ゲートが LAN 専用の値だった**こと。

### 変更点

| 対象 | 変更 |
|---|---|
| `bridge/psotel/convert.py` | `DELAY_CEILING_MS` を float → dict。LAN 5.0 / WAN 200.0 / 既定 50.0 |
| `deploy/psconfig/home-lab-mesh.json` | `vm` → `lggram` に改名、公開ホスト 2 台 + 8.8.8.8 を追加。groups 3・test 1・schedule 1・tasks 6 を追加 |
| `deploy/splunk/charts/wan-owd.json` | 新規。WAN の片道遅延・同一プロトコル RTT・clock_error の 3 系列 |
| `deploy/splunk/charts/twamp-delay-gated.json` | watermark 50 → 5。ゲートの説明も書き直し |

### 品質ゲートを `path.id` 別にした理由

`DELAY_CEILING_MS = 50.0` は**ソース中のコメント自身が「WAN で使うなら経路に応じた値に
変える必要がある」と断っていた**。WAN を本番投入する今日がその日だった。

一律のままだと**二重に間違う**。LAN には 2 桁緩くて 6ms の異常を素通しし、WAN では
今日 ICEPP で実測した 80〜90ms の輻輳を**無言で捨てる**。後者のほうが悪い。
捨てたことが誰にも分からない形で捨てるからだ。

TDD で入れた。**RED で落ちたのは 4 ケース中 2 つだけ**だった（`lan-wired` 6.0ms を落とす、
`wan-sinet-tokyo` 90.0ms を通す）。残り 2 つ（GbE 実測 0.22ms が通る、path.id 無しの 60ms が
落ちる）は旧実装でも通る回帰ガードで、これは想定どおり。

### つまずき: LG Gram の agent は着手時点でクラッシュループしていた

`~/psconfig` が空だったため、イメージ内の既定ファイルがマウントで隠れて
`psconfig-pscheduler-agent` が起動できずにいた。`deploy/psconfig/README.md` が警告している
症状そのものが実際に起きていた形になる。

**厄介なのは、外からは正常に見えたこと。** `docker ps` はコンテナを `Up` と表示し、
`pscheduler troubleshoot` もオールOKを返す（public-hosts.md の着手前チェックがまさにそれ）。
`systemctl is-active psconfig-pscheduler-agent` を叩いて初めて `activating` だと分かる。
3 ファイルを配って restart したら一発で `active` になった。

**restart の前に必ず `psconfig validate` を通した。** 既にクラッシュループしている相手に
不正な定義を入れて restart すると、直そうとしている `status=1/FAILURE` を再発させるだけになる。

### 未確認だった点はどうなったか

| 事前の懸念 | 結果 |
|---|---|
| **`wan-owd` の test spec で `source` 省略が pSConfig のスキーマを通るか** | **通った。** `psconfig validate` はオールOK。CLI で通ったからスキーマでも通るとは限らないと見ていたが、杞憂だった |
| メッシュ変更の反映に agent 再起動が必須か | **未確認のまま。** 慣習どおり restart した |
| `exclusive` がエージェント全体を止めるのか LAN グループだけか | **未確認のまま。** 切替後に WAN 系列の時刻の乱れとして観察できる |

もう 1 つ、事前に想定していなかった挙動: **`psconfig pscheduler-tasks` は agent が 1 回
走り終えるまで `Unable to find last guid in ...` を返す。** restart 直後に叩いて空振りしたが
異常ではない。LG Gram では 2 分弱かかった。

### 反映の順序と、意図的な二重測定

**LG Gram → RasPi → VM** の順で restart した。新しい測定を先に立ち上げてから古い方を畳むので、
その間（数分）だけ LG Gram 発の新 LAN タスクと VM 発の旧 LAN タスクが同時に RasPi へ向かう。
**欠測を避けるための意図的なトレードオフ。** Splunk 側にも `ps.source` 違いの系列が並んだ。

```
lan-wired  192.168.1.102 → 192.168.1.101   （新）
lan-wired  192.168.1.104 → 192.168.1.101   （旧・この直後に止まった）
```

### 検証結果

| 項目 | 結果 |
|---|---|
| `pytest`（bridge） | **52 passed**（48 → 新規 4 ケース） |
| LG Gram の agent | **`active`**（クラッシュループ解消） |
| LG Gram の生成タスク | **12 件** = LAN 3（rtt/latency/throughput）+ WAN 9 |
| RasPi の生成タスク | **3 件**（LAN の逆方向。RasPi も自分が source のタスクを作る） |
| VM の生成タスク | **0 件**。`pscheduler schedule PT20M` も `Nothing scheduled`。**VM 自体は起動したまま** |
| `psconfig validate` | LG Gram・RasPi とも `pSConfig JSON is valid` |
| Splunk への着弾 | `wan-sinet-tokyo` / `wan-riken-tsukuba` / `wan-google` の 3 path.id とも着弾 |
| `wan-owd` チャート | delay・rtt・clock_error の 3 系列とも点あり |

> **プラン記載の「WAN 8 本」は数え間違いだった。** 既存 WAN 3 本（cloudflare rtt/trace、
> blog rtt）+ 新規 6 本 = **9 本**が正しい。実機の生成数と一致している。

### 最初の本番データが Step 8 の結論を裏書きした（**この見出しは保留。下の追記予定を参照**）

切替後 1 時間の実測（Splunk から取得）:

| path.id | 片道 (A) | twping RTT (B) | 復路 = B − A | 非対称 | `max-clock-error` |
|---|---|---|---|---|---|
| `wan-sinet-tokyo` | 3.88 ms | 7.770 ms | 3.89 ms | **+0.01 ms** | 0.22 ms |
| `wan-riken-tsukuba` | 4.74 ms | 9.417 ms | 4.68 ms | **−0.06 ms** | 0.25 ms |

Step 8 の手動再測定（東京 −0.00 / つくば −0.04）と一致した。**100M USB NIC 時代の
+0.86 / +0.84ms が機材由来だったという結論を、本番の定点観測が独立に裏書きした形**になる。

ただし**これは n=1 であり、断定の材料ではない**。片道と RTT は別タスクで PT15M・`sliprand: true`
なので**同時刻に測っていない**し、非対称の大きさ（0.01〜0.06ms）は `max-clock-error`
（0.22〜0.25ms）より 1 桁小さい。**誤差以下の値が誤差以下のまま出ている**というのが正確な読み。
価値があるのは「消えたままである」ことの継続的な確認であって、この 2 行の数字ではない。

> **保留（2026-07-31 01:45 JST 追記）: 上の「裏書きした」は 12 点で見ると成立しない。**
> 切替後 2 時間 48 分・各系列 12 点で平均を取り直すと、東京 **+1.02ms** / つくば **+0.58ms** で、
> **復路（相手→自宅）のほうが遅い**という向きが出た。上表の +0.01 / −0.06 は 22:55 の
> **初回 1 点だけ**の値で、その後は片道が下がり（3.88 → 3.4 台）RTT が上がって（7.77 → 8.2 台）いる。
>
> 断定できない理由は 3 つ。(1) 片道と RTT は非同時測定で、12 点平均でも時間ずれが残る。
> (2) `max-clock-error` 0.22〜0.25ms からクロックオフセット由来のバイアスは最大 ±0.5ms 程度で、
> つくばの +0.58ms はその範囲内。(3) Step 8 の手動測定は夕方〜夜、この 12 点は深夜で、**時間帯差**の
> 可能性がある。
>
> いずれも **LG Gram の受信方向**が遅い向きで、100M USB NIC 時代に +0.94ms が乗っていた向きと同じ。
> GbE 化で消えたはずの方向なので、確認が要る。
>
> **24 時間分（各系列 約 96 点）が貯まってから評価し直して追記する。**
> 早くても 2026-07-31 22:52 JST 以降。それまで上の結論は採用しないこと。

### Splunk の時系列がここで一度切れる

`ps.source` / `ps.destination` でグルーピングしている系列は、**`192.168.1.104` が止まり
`192.168.1.102` が 0 から始まる**。対象は `lan-rtt` / `twamp-delay-gated` / `packet-loss` と
Detector の `lan-rtt-degraded` / `lan-throughput-degraded`。

**ダッシュボードを見た人（記事の読者を含む）には「データが消えた」に見える。**
断絶の日時（2026-07-30 22:52 JST）と理由を CLAUDE.md と runbook に明記した。

なお WAN 側は `ps.destination` が変わらないため `wan-cloudflare` / `wan-blog` の系列も
`ps.source` が `lima-perfsonar-vm` → `lggram-testpoint` に変わって引き直しになる。

### LAN の片道遅延はこれから「まばら」になる

Step 8 で判明したとおり、GbE 化で LAN の片道遅延は測定精度の床に当たり、負値や
`Not Reported` が頻出する。ゲートの `0 < median` に落ちるので、**`twamp-delay-gated` の
LAN 系列は今後まばらになる。** 実際、切替直後の 1 時間で RasPi → LG Gram 方向の
`delay.median` は 1 点も出ていない（RTT は出ている）。

**これは不具合ではなく実態の反映である。** チャートの description にもそう書いた。

### 切替後 24〜48 時間の監視項目（Exit Criteria とは別）

- **`packet-loss` Detector の誤発火。** WAN は PT15M なので 12 分窓に 2 点入らず実質発火しない
  想定だが、`sliprand: true` で偶然 2 点が接近する可能性は排除できない。severity は `Major`
- **`wan-rtt-sudden-change` の挙動。** `against_recent` が `historical_window='4h'` を使うため、
  新パスは投入直後に 4 時間分の履歴を持たない。少ないサンプルで誤発火しないか
- **間欠 TWAMP ロスの再発。** Step 8 で最大 60/100 を観測しており、
  「NIC が原因だと示せなかった」であって無実の証明ではない
- **系列数の増加。** `packet.loss.ratio` が 1 日で 269 系列に膨らんだ前例がある。
  切替直後は移行の重複で 10 系列（6 時間窓）。落ち着いたら再確認する

### 今回やらなかったこと

- **`limactl stop perfsonar-vm`** — 安定を確認してから別途判断する
- **Detector の閾値変更** — 新パスのベースラインが貯まるまで触らない
- **`packet-loss` Detector の PT15M 対応** — 12 分窓に 2 点入らない既知の制約として記録に留める

## Step 11: ダッシュボード v2 を適用。ついでに 7/29 の「ロス Detector 未発火」の説明が誤りだと分かった

- 日付: 2026-07-31
- 結論は 2 つある。
  1. ダッシュボード v2 を適用した。B 案（SLO ビュー）を新規作成し、C 案（復路系列）を
     既存の `wan-owd` に移植した。Detector には触っていない。
  2. **7/29 の「ロス Detector が発火しなかったのはサンプルサイズのせい」という説明は誤りだった。**
     100 発の系列は当時から存在していた。Detector の集約キーがそれを 20 発の系列と
     平均で潰していたのが実際の機序である。

### 適用したもの

| ファイル | 種別 | 中身 |
|---|---|---|
| `deploy/splunk/charts/slo-baseline-ratio.json` | 新規 | 全パスの RTT を自身の直近 24h 中央値で割った倍率。`filter('path.id', '*')` で 6 系列 |
| `deploy/splunk/charts/wan-owd.json` | 更新 | 15 分平滑 + `reverse = rtt − delay` を追加。**ファイル名は変えていない**ので `.ids.json` の `HOeHn4kCEAA` を保持して PUT になった |
| `deploy/splunk/dashboard-network-slo.json` | 更新 | `slo-baseline-ratio` を row0 全幅で追加し、既存 8 チャートを row+1 |

投入前の `check-charts.sh` で `ratio` が 6 系列、`reverse` が 2 系列返ることを確認した。
`reverse` に負値は出ていない（sinet 3.6〜5.2ms、riken 4.7〜5.9ms）。往路より復路が
一貫して長く、非対称が目視で読める形になった。

`median(over='24h')` は SignalFlow がそのまま受理した。`percentile(pct=50, over='24h')`
への置換は不要だった。

### 対数軸は chart API に存在しない

B 案は LAN の 100 倍級と WAN の 10 倍級を 1 枚に収めたかったので対数軸を狙ったが、
**v2 の chart モデルに該当フィールドが無い**と分かった。線形軸のままにしてある。

確認の手順を残しておく。**この API は未知のフィールドを名前付きで 400 にする**ので、
使い捨てチャートを POST するだけで総当たりができる。

```
"message" : "Failed to deserialize payload: Unrecognized field \"logScale\"
  (class sf.domain.chart.visualization.TimeSeriesChartOptions) ..."
```

`options` 直下の `logScale` / `yAxisScale`、`axes[]` の `logScale` / `scale` / `axisScale` /
`type` / `scaleType` / `logarithmic` を試して全滅した。空の入れ子オプションを渡して
GET し直すとモデル全体が既定値で展開されるので、そちらでも裏を取れる。
**`axes[]` のフィールドは `label` / `min` / `max` / `highWatermark` /
`highWatermarkLabel` / `lowWatermark` / `lowWatermarkLabel` の 7 つで打ち止めである。**

撮影側で対応する。キービジュアルは線形 1 枚（SS-01）で撮り、Y 軸 max を 3 に切った
ズーム版を同一レンジで SS-01b として追加する。詳細は `docs/runbook-w3-screenshots.md`。

### 7/29 の「サンプルサイズが原因」は誤りだった

w2-notes.md Step 15 は「LAN の rtt は count=20 なので 3% ロスでは 54% の確率で
1 発も落ちない。だからロス Detector が発火しなかった」と書いた。**これは違う。**

`bridge/psotel/convert.py` を読み直すと、`latency` テストは
`packets-lost / packets-sent` をゲートなしでロス率として出している。
`lan-owd-task`（twamp / 5 分間隔 / count 指定なし = 既定 100 発）は
`1fff334`（2026-07-27）から動いており、**7/29 の時点で 100 発の系列は存在していた。**

Step 15 が記録したロス系列 `0.02 / 0.00 / 0.03 / 0.05 / 0.00` 自体が証拠になっている。
20 発なら取り得る値は 0.00 / 0.05 / 0.10 …だけで、**`0.02` と `0.03` は 100 発側しか
出せない。**

では何が起きていたか。Detector もチャートも集約キーが
`['path.id', 'ps.source', 'ps.destination']` で、**`ps.test.type` を含まない。**
`lan-rtt-task`（20 発）と `lan-owd-task`（100 発）は 3 キーがすべて同じなので、
**2 つのタスクが 1 本の系列に平均されている。**

7/31 の実データで算術が合うことを確かめた。

| 時刻 | rtt（20 発） | latency（100 発） | 集約後 |
|---|---|---|---|
| 07:50 | 0.0 | 0.26 | **0.13** |
| 09:35 | 0.5 | 0.0 | **0.25** |

7/29 の注入区間（21:20:21〜21:36:22）も保持期間内だったので、Detector の中間ストリームを
そのまま評価し直した。

| 時刻 | 集約後 `loss` | `sustained = min(over='12m')` | `enough = count(over='12m')` |
|---|---|---|---|
| 21:25 | 0.02 | 0.0 | 3 |
| 21:30 | 0.035 | 0.0 | 3 |
| **21:35** | 0.015 | **0.015** | 3 |
| 21:40 | 0.0 | 0.0 | 3 |

**発火条件を満たしたのは 21:35 の 1 点だけ**だった（101→104 方向のみ。逆方向は一度も
超えていない）。原因は 3 つ重なっている。

1. **集約キーの設計ミス。** 20 発と 100 発を平均するので、注入中の 0.03 が 0.015 まで
   半減する。閾値 0.01 に対する余裕が半分になる
2. **20 発側が 0 を吐く。** 平均の片側が 0 になると集約値が閾値ぎわまで落ちる
3. **16 分の注入に対して 12 分窓。** 窓が全部注入区間に収まる時刻がほとんど無い

「サンプルサイズの問題」という見立ては方向としては合っていたが、**機序が違う。**
正しくは **「集約キーが測定タスクを潰していた」** である。記事の該当箇所はこの筋で
書き直す必要がある。

### 現構成では同じ Detector が実際に発火している

`check-alerts.sh` に **2026-07-31 07:47 の `packet-loss` 発火**が出ている
（`path.id=lan-wired`、192.168.1.102 → 192.168.1.101）。7/29 とは違って、
LG Gram 構成では LAN のロス Detector が現に動く。

このときの生値は latency 側が 07:45 に 0.25、07:50 に 0.26 で、25% 級の自然発生ロスである。
同じ朝の 08:00 に `lan-throughput-degraded` も 629Mbps で発火している（平常は 940Mbps）。
**原因は未調査。** 注入実験とは無関係の事象なので、別途追う。

### 3% 注入で発火するかは運任せ

上の機序が分かったので、再注入時の見込みを立て直す。

- latency（100 発）は 0.03 前後を出す
- rtt（20 発）は 54% の確率で 0、残りは 0.05 以上
- 集約後は 0.015〜0.04 になり、いずれも閾値 0.01 は超える
- ただし **rtt 単独のバケットで 0 が 1 つでも入ると `min(over='12m')` が 0 に落ちる**

つまり **3% 注入では発火する確率が五分五分**で、7/29 と同じ賭けになる。
Detector の集約キーを直せば 100 発系列が単独で評価され、確実に発火する側に倒せる。
**触るかどうかは Phase 4 前にユーザーと決める。**

WAN 側（`wan-sinet-tokyo` / `wan-riken-tsukuba`）は別の理由で発火しない。
`count(over='12m')` を実測すると **常に 1** だった。15 分間隔である上に、
rtt タスクと latency タスクが同じ 5 分バケットに落ちて 1 点に潰れるので、
**集約しても点数が増えない。** Step 10 の監視項目に書いた「12 分窓に 2 点入らない」は
実測で裏が取れた形になる。

### CHANGES-dashboard-v2.md の訂正と削除

指示書は B 案の対象を「lan-wired + wan-* 5 本」と書いていたが、
`deploy/psconfig/home-lab-mesh.json` の `path.id` は **6 種**である
（`lan-wired` + `wan-cloudflare` / `wan-google` / `wan-blog` / `wan-sinet-tokyo` /
`wan-riken-tsukuba`）。`check-charts.sh` も 6 系列を返している。

また指示書は `wan-icepp` を前提に書かれていたが、この path は現行の pSConfig に無い。

統合が済んだので `docs/CHANGES-dashboard-v2.md` と、`deploy/splunk/` 直下に置かれていた
`chart-slo-baseline-ratio.json` / `chart-wan-owd-asymmetry-v2.json` は削除した。
**`charts/` 配下が正**で、二重管理は残さない。

### 24h 待ちの前提は緩かった

B 案は「各パスに 24h 分溜まるまで系列が出ない」と想定していたが、
SignalFlow の `over` 集計は窓が埋まる前から値を出す。WAN 公開ホスト 2 台も含めて
**6 系列すべてが投入直後から 0.9〜1.1 に乗っている。**

ただし 7/31 22:52 を過ぎるまでベースラインは 24h 未満のデータで動くので、
**キービジュアルの撮影はその時刻以降**という条件は維持する。

## Step 12: 再注入の準備 — LG Gram 用の注入手順とイベントオーバーレイ

- 日付: 2026-07-31
- 撮影セッション（`docs/runbook-w3-screenshots.md`）の準備を Phase 2・3 まで進めた。
  **注入はまだ実施していない。** 実施はユーザーの合図を待つ（CLAUDE.md 規約 2）。

### 注入対象の前提を実機で取り直した

| 項目 | 結果 |
|---|---|
| デフォルトルート | `default via 192.168.1.1 dev enxa0cec8fe0854`。**LAN も WAN も同一 NIC** |
| 現在の qdisc | `fq_codel`（root）。netem は root に入るので**注入中は fq_codel が外れる** |
| `sudo -n` | NOPASSWD で通る |
| `sch_netem` | あり（6.8.0-136-generic） |
| `systemd-run` | `/usr/bin/systemd-run` |
| chrony | System time 59µs fast、Skew 0.067ppm。注入前の基準として記録 |
| retry-policy | 展開後の **12 タスク全ての `archives` に入っている**（欠落 0） |

同一 NIC なので、**egress に入れれば LAN 3 本と WAN 全パスが同時に崩れる。**
1 枚のキービジュアルで全パス劣化が撮れるという Phase 4 の前提が成り立つ。

### `psconfig pscheduler-tasks` は展開後の完全な spec を出す

計画では「タスク名の一覧しか出さないので retry-policy の確認には使えない」と見込んでいたが、
**実際は archives を含む完全な JSON を出す。** ホスト側ファイルの grep より強い確認手段になる。
マウントされたファイルではなく、**pScheduler が実際に受け取る形**を見られるためである。

### デッドマンスイッチは systemd に委譲する

7/29 は `limactl shell` のローカル実行だったが、今回は **SSH 自体が注入対象 NIC を通る。**
解除コマンドが届かない事態への保険が要る。

`ssh host 'cmd &'` + `nohup` は使わない。stdin をリダイレクトしないと、
**バックグラウンドの子プロセスが exec チャネルの stdin を握ったまま残り、ssh 側が
`sleep` の時間だけブロックして返ってこない。** これが起きるとタイマーだけ進んで注入が
始まらず、実験そのものが壊れる。

`--on-active=60` でリハーサルした結果は次のとおり。

- **ssh は 0.042 秒で返った**（`Running timer as unit: ...` を出して即終了）
- `systemctl list-timers` に `LEFT 59s` で出る
- `systemctl stop` 後は `could not be found`。トランジェントユニットなので残骸が出ない

本番は `--on-active=1200`（20 分）を注入の**前**に仕込む。注入は 16 分なので、
解除に成功したら `systemctl stop` でキャンセルする。

### イベントオーバーレイのスキーマを確定させた

`eventOverlays` / `selectedEventOverlays` はダッシュボードモデルに存在するが、
既定は `null` である。使い捨てダッシュボードを POST してスキーマを観察した
（チャートと同じく、**この API は未知のフィールドを名前付きで 400 にする**）。

**`eventType` に指定できるのは `detectorEvents` と `eventTimeSeries` の 2 値だけ。**
`alertEvents` / `detector` は `EventSignal$EventSignalType` の deserialize で落ちる。
Detector の発火マーカーを出すなら `detectorEvents` で、`eventTimeSeries` は
自前でイベント API に投げたイベント用である。

as-code 側は Detector の**キーだけ**を書く形にした。`apply.sh` が `.ids.json` から ID を、
`detectors/<key>.json` から表示名を引いて展開する。**ID を定義に直書きすると
Detector を作り直したときに追従できない**ためで、チャートの扱いと揃えた。

`selectedEventOverlays` は全件 ON で生成する。**撮影時にトグルを忘れて発火マーカーが
写っていないのが、この実験で一番痛い失敗**だからである。撮り直しは再注入を意味する。

副作用として `apply.sh` は detectors をダッシュボードより先に流す順序に変えた。
overlay が Detector の ID を要求するためで、`--only dashboard` の挙動は変わらない。

### 目視検証は合格した

ユーザーが 7/29 21:20〜22:20 のレンジで確認した。証跡は
`docs/article/images/verify/ph3-overlay-{01,02,03}.png`。

- **Event overlay バーに 4 本が並び、全部 ON になっている**（青いチップ）
- **21:23〜21:41 にマーカーが立つ。** 発火（塗り）と解消（中抜き）が対で出る
- **SLO ビューがダッシュボード先頭に全幅で表示されている**

Phase 3 はこれで合格。当日の表示は保証された。

### 副産物: 線形軸の限界が絵として確定した

7/29 のレンジは、そのまま**キービジュアルの下見**になった。`lan-wired` の ratio が
100 倍を超えて跳ねており、**Y 軸が 0〜117 に伸びる。**

その結果、**watermark の 1.0 と 1.5 が軸の底で重なり、ラベルが
「+50%ライン (1.0)」のように潰れて読めない。** WAN も 115ms まで跳ねたはずだが、
ratio では平坦な線に見えてしまう。

**SS-01b（Y 軸 max = 3 のズーム版）は「あれば良い」ではなく必須**だと分かった。

また SLO ビューは `h1`（1 行）だと凡例が出ない。**SS-01 は必ずチャート単体拡大で撮る。**

### 撮影方法が決まり、ズーム版はチャート定義に昇格した

ユーザーから撮影方法の指定があった。**ブラウザは Safari、チャート右上の 3 点リーダー →
`View fullscreen` で撮る。** これで 3 つ同時に片付く。

1. ブラウザ枠と Splunk の**アカウント表示名が写らない**
2. チャートが画面いっぱいに広がるので**凡例が出る**
3. 軸ラベルが省略されない（`RTT / 24h中央値 (...` のような切れ方をしない）

これを受けて **SS-01b の撮り方を変えた。** 当初は「チャートビルダーで Y 軸 max を 3 にして
撮り、保存せず破棄する」運用にしていたが、**ビルダーはブラウザ枠ごと写る**上に、
実験中に「保存しない」を要求するのは事故のもとである。

`deploy/splunk/charts/slo-baseline-ratio-zoom.json` を**独立したチャートとして作り**、
ダッシュボード row0 に本体と並べて置いた（w6 + w6）。同じ programText で
`axes[0].max = 3` だけが違う。これで SS-01 と SS-01b が**同じ手順で撮れる。**

副作用として、平常時のダッシュボードも「全景 + ベースライン帯のズーム」の 2 枚組になった。
SLO ダッシュボードとしてはむしろ素直な形なので、そのまま SS-09 にも写す。

### fullscreen はダッシュボード全景でも AI Assistant でも使える

検証ショット 4 枚の内訳が判明した。

| ファイル | 撮り方 |
|---|---|
| `ph3-overlay-01.png` | 非 fullscreen。ブラウザ枠とアカウント表示名が写っている |
| `ph3-overlay-02.png` / `ph3-overlay-03.png` | **ダッシュボード全景の fullscreen** |
| `ph3-overlay-04.png` | fullscreen のまま **AI Assistant を開いた状態** |

**AI Assistant は fullscreen で使える。** しかも `Use current page filters` が ON なので、
表示中の絶対レンジをそのまま見てくれる。**SS-07 は「AI に何を見せたか」が
同じ画面に写る**形で撮れることになり、W3 の積み残し回収として都合が良い。

つまり写り込みを気にする必要があるのは **Alerts 画面（SS-05）だけ**である。
ダッシュボードではないので fullscreen があるか未確認。撮影後に確認し、
写り込みがあれば Phase 5 でマスクする。PROJECT.md の公開チェックリストに関わる。

### 撮影 URL に `overlayId` を残してはいけない

Phase 3 の検証で使った URL はこの形だった。

```
.../dashboard/HOWdHgXCEAI?groupId=...&configId=...
  &startTimeUTC=1785327600000&endTimeUTC=1785331200000
  &selectedEventOverlays=nfendE&selectedEventOverlays=Vt74qr
  &selectedEventOverlays=86r5Xr&selectedEventOverlays=F0fPyN
```

時刻は `startTime` / `endTime` ではなく **`startTimeUTC` / `endTimeUTC`**。

問題は `selectedEventOverlays` のほうで、**`overlayId` はダッシュボードを PUT するたびに
サーバが振り直す。** 上の 4 個は、直後にズームチャートを追加した時点で無効になり、
`EwrMfn` / `4WHJzp` / `lPXi59` / `VVAHJr` に変わっていた。使い捨てダッシュボードで
スキーマを調べたときにも、POST で `Knxgt5` だった値が PUT 後に `JhkG9o` へ変わっている。

**撮影 URL には時刻レンジだけを残す。** `apply.sh` が `selectedEventOverlays` を
全件 ON で生成するので、URL に書かなくてもマーカーは出る。

あわせて運用ルールを 1 つ足した。**撮影が完全に終わるまで
`apply.sh --only dashboard` を流さない。** 流すと開いていたタブの URL まで再現しなくなる。

## Step 13: ロス Detector の集約キーを直した。ただし 12 分窓の制約は残る

- 日付: 2026-07-31
- Step 11 で見つけた集約キーの設計ミスを、再注入の**前に**直すと決めた（ユーザー判断）。
  検知系の欠陥を直してから撃つほうが、記事の筋が完結するため。

### 変更点

| ファイル | 変更 |
|---|---|
| `deploy/splunk/detectors/packet-loss.json` | 集約キーに `ps.test.type` を追加。理由を programText のコメントに残した |
| `deploy/splunk/charts/packet-loss.json` | 同上。凡例にも `ps.test.type` を出す |

系列は **7 本から 11 本**に増えた。`ps.test.type` が `rtt` なら 20 発、`latency` なら
100 発の分解能だと凡例で読める。適用後の Detector は `ACTIVE` で継続中 0 件、
誤発火は出ていない。

### 直した効果は「半減の解消」までで、発火の確実性までは買えていない

7/29 の実データを修正後の集約キーで再評価した。

| 系列 | `sustained = min(over='12m')` の最大 |
|---|---|
| 集約キー修正**前**（20 発と 100 発の平均） | 0.015 |
| 集約キー修正**後**（100 発のみ、101→104） | **0.02** |

閾値 0.01 に対する余裕は倍になった。**ただし条件を満たす時刻は依然として 1 点だけ**である。

理由は Step 11 に書いた 3 つ目の要因が残っているからだ。**16 分の注入に対して 12 分窓**では、
窓が完全に注入区間へ収まる時刻がほとんど無い。窓の中に注入前の 0 が 1 点でも入れば
`min(over)` は 0 に落ちる。

- 5 分間隔なので、16 分の注入に入る測定点は 3 点ほど
- `min(over='12m')` が閾値を超えられるのは、その 3 点が全部窓に入る最後の 1 点だけ

**注入を 25 分程度まで伸ばせば測定点が 5 点になり、発火はほぼ確実になる。**
16 分は 7/29 との比較可能性のために選んだ値なので、当日どちらを取るかはユーザーが決める。

### 7/29 に発火しなかった理由は完全には詰め切れていない

修正前の `sustained` も 21:35 に 0.015 で閾値 0.01 を超えている。**1 点でも条件が真になれば
発火するはずなのに、していない。** 当時の Detector は `count(over)` を足す前の
`min(over='12m') > 0.01` だけの形で、こちらのほうが発火しやすい。

Detector の評価解像度や、注入終了直後に到着した点の扱いが絡んでいる可能性はあるが、
**再現できていない以上、断定はしない。** 記事では「集約キーが測定タスクを潰していた」と
「16 分の注入に 12 分窓は狭すぎた」の 2 点までを書き、残りは未解明として残す。


## Step 14: 撮影リハーサルを 3 巡した。凡例が as-code の問題だと分かった

- 日付: 2026-07-31〜08-01
- 注入前に撮影手順を通しで試した。**結果として 5 つの問題を潰し、撮り方が確定した。**
  注入は未実施。

### 撮り方は OS スクショではなく Splunk の書き出し

ユーザーが見つけた。**チャートは 3 点リーダー → `Download chart as image`、
ダッシュボードは 3 点リーダー → `Export` → フォーマット image。**
ブラウザ枠もアカウント表示名も一切写らない。OS の `Cmd+Shift+4` より素直で、
これを標準にした。Alerts 画面だけは書き出しが無いので OS スクショになる。

### 最大の問題は「書き出し画像に凡例が入らない」

`Download chart as image` は **Splunk 標準の凡例パネルを含まない。**
5 系列ある WAN RTT は色違いの線が並ぶだけ、Chart 6 は `delay` / `rtt` / `clock_error` が
区別できない。Step 5 の「凡例が読める」を満たせず、**SS-02 の物語が成立しなかった。**

`options.onChartLegendOptions` で**チャート内に凡例を描かせる**ことで解決した。

```json
"onChartLegendOptions": { "showLegend": true, "dimensionInLegend": "path.id" }
```

`dimensionInLegend` は必須で、`null` を渡すと
`Default dimension to show on chart legend missing.` の 400 になる。値は自由文字列で、
`sf_streamLabel` や `sf_originatingMetric` のようなメタデータ系も通る。
**1 つしか出せない**ので、チャートごとに主役の次元を選んだ。

`sf_streamLabel` が当たりだった。`delay` / `rtt` / `reverse` / `clock_error` や
`mean` / `max` のように短く、publish ラベルそのものが出る。
`sf_originatingMetric` は `perfsonar.rtt.max` のように長く、凡例の幅を食って
末尾が `See all` に畳まれてしまう。

### 3 巡で潰した問題

| # | 症状 | 対処 |
|---|---|---|
| 1 | 書き出し画像に凡例が無い | `onChartLegendOptions` を 10 チャートに追加 |
| 2 | SLO ビューの凡例が 6 系列中 5 つで `See all` に畳まれ、`wan-sinet-tokyo` が隠れた | タイルを w6 → **w12** に |
| 3 | `+50%` と `ベースライン (1.0)` のラベルが重なって両方読めない | 全景側の watermark を **1.0 のみ**に。`+50%` はズーム版が担当 |
| 4 | `clock_error` の棒グラフが画面を埋め、`delay` / `rtt` / `reverse` の線を覆い隠す | **ColumnChart → LineChart**（Chart 6 と WAN 片道遅延） |
| 5 | 書き出しが横長すぎてキービジュアルが薄い（3010×412） | SLO 2 枚を **h1 → h2** に（3010×852） |

問題 3 は**平常時と注入時の両方で起きる。** 平常時は Y 軸上限が 1.1 前後なので 1.5 の
watermark が軸外に出てラベルだけ上端に残り、注入時は 117 倍まで伸びて両方が底に潰れる。
**全景とズームで役割を分けるのが正解だった。**

### 撮影運用で分かったこと

- **チャート単体の Download は絶対レンジを保持する。** ダッシュボードの Export は
  落とすことがあり、14:00〜16:00 を指定したのに 24 時間で書き出された。
  **書き出した画像の時刻軸を毎回見る**
- **Active alerts は継続中のインシデントしか出さない。** 発火 15 件の状態でも
  画面は `No data found` だった。**SS-05a（一覧）は発火中にしか撮れない**ので
  注入中の最優先ショットにする。SS-05b（詳細）は Resolved でも撮れる
- **AI Assistant は落ちることがある。** `I couldn't complete metric discovery right now.`
  で失敗した。注入直後に 1 回投げて疎通を確かめてから本番の質問をする
- ダウンロード時のリネームで**先頭スペースと `.png.png` が混入した**（9 件 + 1 件）。
  保存後にファイル名も確認する

### 残る既知の弱点（許容する）

WAN 片道遅延チャートは `colorBy: Dimension` なので、**色は宛先（SINET / 理研）を表し、
同じ色の中で `delay` / `reverse` / `rtt` が区別できない。** ただし 3 本は
`rtt` > `reverse` > `delay` の順に明確な帯として分離するので、キャプションで
「上から rtt / reverse / delay」と補えば読める。`colorBy` を変えると今度は
2 拠点が区別できなくなるため、このままにする。

SLO ビューでは **`lan-wired` と `wan-sinet-tokyo` の色がどちらもマゼンタ系で紛らわしい。**
`path.id` がアルファベット順に並ぶため、パレットの 1 番目と 6 番目がたまたま近い。
チャート API に次元ごとの色指定は無いので運用で対処する。注入時は LAN が 117 倍、
WAN が 12 倍で縦に大きく離れるので実害は小さい。キャプションで
「最上部の急騰が `lan-wired`」と補う。

### ズーム版の上限は 3 では足りなかった（ラウンド 4→5）

タイルを h2 にして撮り直したとき、**Y 軸 0〜3 では注入時に WAN も振り切れる**ことに気付いた。
7/29 の実績で WAN RTT は 9ms → 115ms、**約 12.8 倍**である。上限 3 のままだと
ズーム版に写るのはベースライン帯だけになり、「WAN とベースライン帯のズーム版」という
役割を果たさない。

**上限を 15 に変えた。** WAN の全振幅とベースライン帯・watermark（1.0 / 1.5）が
同時に入る。LAN（約 117 倍）が振り切れるのは想定どおりで、実値は全景側で読ませる。

計画が書いていた「max = 3」は、対数軸が使えないと分かる前の暫定値で、
**WAN の実績値と突き合わせていなかった。** 撮って初めて気付いた類の誤りである。

ラウンド 5 で上限 15 の watermark 可読性を確認して、リハーサルは終了。
`+50%`（1.5）と `ベースライン (1.0)` は近接するが読み分けられる。

## Step 15: 注入直前に中止。USB NIC がリンクフラップしていた

- 日付: 2026-08-01（23:42 に発覚、同 23:50 に注入中止を決定）
- **注入は実施していない。** 直前のアラート確認で継続中のインシデントを見つけ、
  追ったところ**測定ノードのハードウェア障害**に行き着いた。
- 結論: LG Gram の USB GbE アダプタ（ASIX AX88179A）が**リンクフラップしている。**
  ネットワークの問題でも測定系の問題でもない。

### 発覚の経緯

注入前チェックのつもりで `check-alerts.sh` を叩いたら、`lan-throughput-degraded` が
**継続中 1 件**だった（08-01 23:25、RasPi → LG Gram、520.8 Mbps）。

同時刻の周辺指標を引くと、単なるスループット低下では説明できない組み合わせが出た。

| 指標 | 平常 | 23:25〜23:30 |
|---|---|---|
| `throughput.bps`（101→102） | 940 Mbps | **520.8 Mbps** |
| `throughput.retransmits`（101→102） | **常に 0** | **554** |
| `packet.loss.ratio`（101→102 / rtt 20発） | 0 | **0.95**（20 発中 19 発ロス） |
| `rtt.mean` 両方向 | 0.5〜1.1ms | **変化なし** |

**RTT が正常なのに 95% のロスが出る**のは、輻輳では説明がつかない。リンクが
落ちている時間帯があると考えるのが自然で、`dmesg` を見たら当たりだった。

### 証拠

```
[Sat Aug  1 23:35:41] ax88179 - Link status is: 0
[Sat Aug  1 23:35:44] ax88179 - Link status is: 1
[Sat Aug  1 23:35:45] ax88179 - Link status is: 0   ← 1 秒後にまた落ちる
[Sat Aug  1 23:35:48] ax88179 - Link status is: 1
```

- **リンクダウン 116 回。** 初出は 2026-07-30 21:12:46、直近は 2026-08-01 23:36:10
- NIC の enumerate は 2026-07-30 20:45:43。**装着の 27 分後から始まっている**
- 経過約 51 時間で 116 回 = **約 2.3 回/時**。数分おきに数回まとめて落ちるバースト型で、
  1 回あたり 3 秒前後
- インタフェース統計は RX errors 7 / **RX dropped 90,818**。TX 側は全て 0
- 7/30 21:05:28 に `usb 2-2: USB disconnect` が 1 回あり、device number 3 → 4 で
  再 enumerate されている

### 過去の「原因未調査」が全部これだった

時間帯別に数えて、これまで記録に残していたアラートと突き合わせた。**全件一致する。**

| 事象 | 同時間帯のリンクダウン |
|---|---|
| 07-31 07:47 `packet-loss` 発火（LAN 25% ロス） | 07 時台 **22 回** |
| 07-31 08:00 `lan-throughput-degraded`（629 Mbps） | 同上 |
| 07-31 09:58 `lan-throughput-degraded`（567 Mbps） | 09 時台 4 回 |
| 08-01 03:29 `wan-rtt-sudden-change` | 02 時台 12 回 / 03 時台 3 回 |
| 08-01 11:21 `packet-loss` 発火 | 11 時台 **16 回** |
| 08-01 23:25 `lan-throughput-degraded`（521 Mbps） | 23 時台 **32 回** |

Step 11 で「原因は未調査。注入実験とは無関係の事象なので、別途追う」と書いた 2 件も
ここに含まれる。**単一の物理原因に還元された。**

### 切り分け済みのこと

- **RasPi は無実。** `eth0` の最後のリンク断は 2026-07-26 09:39 で、RX errors 0
- **USB オートサスペンドは無関係。** `/sys/bus/usb/devices/2-2/power/control` は
  既に `on`（= 電源管理を無効化した状態）
- **EEE（省電力イーサネット）も無関係。** `ethtool --show-eee` が `not supported`
- リンク確立時の速度・Duplex は正常（1000Mb/s Full）

残る候補は **USB ポート / USB 側の接触 / LAN ケーブル / スイッチのポート /
アダプタ本体**。安い順に試して、それぞれ数時間フラップ 0 を確認する。

```bash
# フラップ回数の監視
ssh dev@192.168.1.102 'sudo dmesg -T | grep -c "Link status is: 0"'
```

### 注入を止めた理由

1. **交絡。** netem の 100ms / 3% とフラップの区別がつかず、実験が成立しない
2. **SS-04 が壊れる。** 「940 → 241 Mbps の谷」は 940 のベースラインが前提である
3. **デッドマンスイッチの SSH がこの NIC を通る。** systemd タイマーの保険はあるが、
   リスクを重ねる意味がない

**フラップが数時間ゼロになってから注入する。**

### データへの影響

フラップの初出は **2026-07-30 21:12** で、pSConfig 切替（同 22:52）の **1 時間 40 分前**である。
つまり **LG Gram に移してからの測定は、すべてフラップしているリンクの上で取られている。**

平常値そのものは壊れていない。941 Mbps・変動 0.5% 未満という Step 10 以降の記録は
フラップに当たらなかった大多数の run のものである。**汚染されているのは外れ値のほうで、
「たまに大きく外れる」の正体がこれだった。**

Step 10 の監視項目に残していた「間欠 TWAMP ロスの再発。Step 8 で最大 60/100 を観測しており、
『NIC が原因だと示せなかった』であって無実の証明ではない」は、**今回ようやく物理原因が
特定できた形になる。**

### 記事ネタ

- **監視を作ったら、監視対象ではなく監視基盤そのものの故障を検出した。**
  perfSONAR で家庭内ネットワークを測るつもりが、最初に見つかったのは測定ノードの
  USB アダプタだった
- **別々に見えた 5 種類のアラートが、1 つの物理原因に還元された。**
  スループット低下・パケットロス・WAN RTT 逸脱と、症状は 3 系統に分かれていた。
  相関を取る価値がそのまま出た例になる
- **RTT が正常なのにロスが 95% という組み合わせが決め手だった。**
  輻輳ならロスの前に遅延が伸びる。伸びないのにロスだけ出るなら、リンクが
  無くなっている時間帯があると考える。**指標を複数持っている意味がここに出る**
- 注入実験の直前チェックで見つかった。**「平常運転の確認では 0 件であること」という
  Exit Criteria が実際に仕事をした**

## Step 16: USB ポートを変えた — フラップは止まったが USB 2.0 に落ちた

- 日付: 2026-08-02
- **フラップは止まった。代わりにスループットが 941 → 355 Mbps になった。**
  「速いが不安定」か「安定だが 355 Mbps」の二択になっている。
- 判断: **別のアダプタに交換して様子を見る**（ユーザー）。注入は引き続き保留。

### 試した 2 ポートはどちらも USB 2.0 だった

| ポート | 変更時刻 | バス速度 | スループット | リンクダウン |
|---|---|---|---|---|
| `usb 2-2`（元） | 07-30 20:45 | **SuperSpeed 5000M** | 941 Mbps 両方向 | **124 回 / 51h（2.4 回/時）** |
| `usb 1-4` | 08-02 09:10:19 | high-speed 480M | 354 / 359 Mbps | **0 回 / 3h50m** |
| `usb 1-1` | 08-02 13:03:09 | high-speed 480M | 未測定 | 計測開始 |

**`dmesg` の全履歴で SuperSpeed の enumerate は `usb 2-2` の 3 回しかない。**
`lsusb -t` でも Bus 002（SuperSpeed・4 ポート root hub）にデバイスが 1 つも無い。
このマシンでこのアダプタが USB 3.0 で繋がるのは `2-2` だけである。

Ethernet 側は USB 2.0 でも `1000Mb/s Full` でリンクしている。**ボトルネックは USB バス**で、
355 Mbps は USB 2.0 接続の GbE アダプタとして典型的な実効値である。

### フラップ 0 は「まだ強い証拠ではない」

`1-4` での 3 時間 50 分は、変更前のレート（2.4 回/時）なら **約 9 回**起きているはずの窓である。
止まったと見てよいが、**バースト型で数時間空くこともあった**ため、
たまたま静かな時間帯だった可能性を完全には排除できない。**判定には 24 時間ほしい。**

挿し直しのたびに `USB disconnect → 再 enumerate` が 1 回起きている
（`1-4` で device 5→6、`1-1` で device 7→8）。USB 2.0 側でも初回に一度つまずく。

### 切り分けの限界

**アダプタ不良かポート不良かは、手元の情報では切り分けられない。**
USB 3.0 のリンクだけが不安定という症状はアダプタの USB3 PHY か `2-2` の信号品質を指すが、
どちらかを言うには**別のアダプタか別のマシン**が要る。だから別個体を試す。

### 副作用: スループット Detector が継続中のまま

`lan-throughput-degraded`（閾値 900 Mbps）が **継続中 2 件**（両方向、08-02 09:24 / 09:28 発火）
になっている。355 Mbps では当然である。

このままだと注入実験の **SS-05a（Active alerts 一覧）と SS-06（発火中の全景）に、
注入と無関係のアラートが常時写り込む。** 「平常運転の確認では 0 件」という
Exit Criteria も満たせない。**USB 2.0 で実験する場合は閾値を下げる必要がある**
（実測 350.7〜359.7 Mbps なので、当初の設計思想「実測 min の約 4% 下」に倣うと 335 Mbps 前後）。

### 「比較可能性」の整理

計画の「7/29 と同じ 100ms / 3%、16 分」は**注入パラメータの話**であって、
絶対値 940 → 241 Mbps を再現することではない。7/29 は Lima VM での測定なので、
**どのみち絶対値は変わる。** USB 2.0 のまま実験しても筋は通る。

ただしその場合、SS-04 の説明は「940 → 241」ではなく「355 → X」になり、
**GbE アダプタが USB 2.0 で頭打ちになっている話を先に書く必要がある。**

## Step 17: アダプタ交換でフラップは解決。ただし構成が変わり、37 分の欠測が出た

- 日付: 2026-08-02（交換 18:54:38）
- **リンクフラップは解決した。** 交換から 43 分でキャリア断 0 回、RX/TX errors 0。
- ただし**交換に伴って 3 つの変化と 1 つの障害**が出た。注入の前に片付ける。

### 交換したもの

| | 旧 | 新 |
|---|---|---|
| 製品 | ASIX AX88179A（USB 直挿し） | **Anker USB-C ハブ**経由の Realtek RTL8153A |
| USB ID | `0b95:1790` | `291a:0817`（ハブ）→ 配下に NIC |
| ドライバ | `ax88179_178a` | **`r8152`** v1.12.13 / firmware `rtl8153a-4 v2` |
| インタフェース名 | `enxa0cec8fe0854` | **`enxa0cec8e91ea0`** |
| MAC | `a0:ce:c8:fe:08:54` | `a0:ce:c8:e9:1e:a0` |
| USB バス | `2-2` SuperSpeed（ただしフラップ） | `2-2.2` **SuperSpeed 5000M** |

IP は DHCP で **`192.168.1.102/23` を維持**した。デフォルトルートも新 NIC 経由になっている。
リンクは `1000Mb/s Full`、qdisc は `fq_codel`。

### 変化 1: インタフェース名が変わった

`enxa0cec8fe0854` → `enxa0cec8e91ea0`。**netem の注入対象名が変わる。**
`docs/runbook-w3-screenshots.md` Step 2.5 と `docs/runbook-w2.md`、CLAUDE.md を更新した。

**インタフェース名は NIC を替えるたびに変わる**（MAC 由来の命名）。
コマンド実行前に `ip route show default` で確かめる運用にする。

### 変化 2: ハブ経由になり、USB3 帯域を他デバイスと共有する

`lsusb -t` を見ると、Anker ハブの下に NIC（`2-2.2`）と **Mass Storage（`2-2.3`）**が
ぶら下がっている。**測定中にストレージが動くとネットワークに影響しうる。**
注入実験の前に外すか、少なくとも動かさないことを確認する。

### 障害: 交換直後から 37 分間、LAN の測定が全滅した

18:55〜19:32 の間、**LAN のタスクだけが全て Failed**（WAN は無傷）。エラーはこれ。

```
twping: NTP: STA_NANO should be set. Make sure ntpd is running, and your NTP configuration is good.
twping: bind(): Cannot assign requested address
twping: Unable to open control connection to 192.168.1.101:862
```

**原因はクロック同期の喪失だった。** 旧 NIC を抜いた瞬間の chrony ログ。

```
Aug 02 18:54:53 chronyd[820]: Source 210.173.160.57 offline
（以下 7 ソースすべて offline）
Aug 02 18:54:53 chronyd[820]: Can't synchronise: no selectable sources
```

**twping は NTP 同期を要求する。** インタフェースが消えて chronyd が全ソースを offline に
落とし、再同期するまでの間、twping が動けなかった。19:32 に自然回復して、
19:35 の測定から LAN の RTT が戻っている（1.11 / 1.015 ms、正常値）。
現在の chrony は System time 33ns slow、Skew 0.065ppm、Leap Normal。

**切り分けの経路を記録しておく。** ここは遠回りした。

1. `check-alerts.sh` → 継続中のアラート
2. Splunk → **LAN 系列だけが欠測、WAN は正常**（ここで NIC 全体の障害ではないと分かる）
3. Mac 側のブリッジ → PUT を 200 OK で受け続けていた（**パイプラインは無実**）
4. ARP と ping → 両方向とも正常（**L2/L3 も無実**）
5. `pscheduler schedule` → LAN タスクが Failed
6. `pscheduler result` → twping のエラー本文
7. `journalctl -u chrony` → 全ソース offline

**「ブリッジは 200 OK を返しているのに Splunk にデータが無い」という状態を、
パイプラインの故障だと早合点しなかったのが効いた。** メトリクスの
どの系列が欠けているかを先に見たので、2 手目で範囲が絞れた。

### 記事ネタ

- **NIC を交換したら測定が 37 分止まり、原因は NTP だった。**
  ネットワーク測定ツールが時刻同期に依存していることが、いちばん痛い形で出る例。
  片道遅延だけでなく **RTT の測定すら止まる**（twping は twamp なので当然だが、
  「RTT はクロック非依存」という本文の記述と衝突して見えるので書き分けが要る）
- **障害の切り分けで、まず「どの系列が欠けているか」を見る。**
  LAN だけ欠測・WAN 正常、という形が分かった時点で、パイプライン全体の故障は消える

### 残っている確認

- **スループットが 940 Mbps に戻るか。** 30 分間隔なので次の run 待ち。
  USB 2.0 に落ちていた間は 355 Mbps だった。SuperSpeed で繋がっているので戻るはず
- **`lan-throughput-degraded` の継続中アラート**は、940 Mbps に戻れば自然に解消する
- **24 時間フラップ 0** を確認してから注入する

## Step 18: 新アダプタでも再発した。犯人はアダプタではない

- 日付: 2026-08-03
- **訂正が 1 つある。** 前回「新 NIC のキャリア断 0 回」と報告したが、**grep の文字列が違った。**
  旧 ASIX は `Link status is: 0`、**新 Realtek（`r8152`）は `carrier off`** と書く。
  数え直すと 09:46 時点で **15 回**で、いまも継続している。
- 結論: **アダプタ交換では直らなかった。** 別メーカー・別チップの 2 台が同じ症状を出した以上、
  原因はアダプタ側ではない。

### 経過

| 時刻 | 事象 |
|---|---|
| 08-02 18:54:38 | Anker ハブ + RTL8153A に交換 |
| 08-02 18:55 〜 08-03 09:14 | **フラップ 0**（14 時間 20 分クリーン） |
| 08-03 09:14:06 | 初回の `carrier off` |
| 08-03 09:35〜09:45 | **14 回が集中**。バースト型なのは旧アダプタと同じ |

スループット自体は **941 Mbps に完全復帰**した（USB 3.0 に戻った効果は本物）。
ただし **09:30 の run だけ 94.1 Mbps**で、再送 164・同時刻の twping RTT が 16.7% ロス。
941 のちょうど 1/10 なので、**カリア断のあと 100BASE-TX でネゴシエーションし直した疑い**がある。

### 共通項は USB ポート `2-2` と SuperSpeed

| 構成 | USB ポート | バス速度 | フラップ |
|---|---|---|---|
| ASIX AX88179 | `2-2` | SuperSpeed | **124 回 / 51h** |
| ASIX AX88179 | `1-4` → `1-1` | high-speed | 0 回 / 約 9h |
| Anker ハブ + RTL8153A | `2-2` | SuperSpeed | **15 回 / 15h** |

**異なる 2 台が同じポートで落ち、USB 2.0 では落ちなかった。**
アダプタ単体の故障という線は消えた。

**ただしこの表を過信しない。** 新アダプタは 14 時間クリーンだった後に始まっている。
「USB 2.0 で 9 時間クリーン」も、同じように**たまたま静かな窓だった可能性を排除できない。**

### 除外できたもの

- **ハブ配下の Mass Storage は無罪。** 正体は**ハブ内蔵の SD カードリーダー**で、
  `lsblk` で `sdb` / `sdc` とも **0B**（メディア未挿入）。Step 17 でリスクとして挙げたが、
  そもそも動いていない
- **RasPi は無罪。** `eth0` のリンク断は 2026-07-26 の 1 回きり。
  スイッチ全体がリセットしているわけでもない
- **落ちているのは USB リンクではなく Ethernet のキャリア。**
  再 enumerate は起きていないので、USB デバイスとしては生きたまま PHY だけが落ちている

### 残る候補と次の一手

USB ポート `2-2` の USB3 レーン / **LAN ケーブル** / **スイッチのポート** / 電源・EMI。

**次は USB 3.0 のまま LAN ケーブルとスイッチポートを替える。**
これなら 941 Mbps を保ったまま切り分けられる。

- 止まれば → ケーブルかスイッチポート
- 続けば → `2-2` の USB3 レーンか環境要因

判定は **24 時間フラップ 0**。今回のように 14 時間クリーンな窓があるので、
数時間では足りない。

### 記事ネタ

- **「アダプタを替えたら直った」と一度は思った。** 実際は 14 時間の潜伏期間があっただけで、
  翌朝に再発した。**短い観測窓で「直った」と判断する危うさ**の実例になる
- **監視の文字列に依存した確認は、ドライバが変わると壊れる。**
  `Link status is: 0`（ASIX）と `carrier off`（Realtek）で、同じ事象の表現が違う。
  自分の grep が空振りして「0 回」と報告した。w2-notes Step 15 の
  「`is` という存在しないフィールドを読んでいた」と**同じ種類の失敗を繰り返している**

## Step 19: 日中のスループット低下は輻輳ではなくフラップだった。監視頻度は据え置き

- 日付: 2026-08-03
- 「日中のスループット低下は web 会議など他デバイスの通信影響ではないか」という仮説を
  データで検証した。**支持されなかった。** iperf3 のスケジュールは**終日 30 分間隔のまま据え置く**
  （ユーザー判断）。

### 本日 46 点のうち、941 Mbps を外したのは 3 点だけ

| 時刻 | 値 |
|---|---|
| 10:00 | 18.1 Mbps |
| 15:00 | **94.1 Mbps** |
| 15:30 | **94.1 Mbps** |

**3 点とも 09:14〜15:56 のフラップ窓の中に入る。** 日中の残り（10:30〜14:30、16:00〜23:00）は
**全て 941 Mbps** で、時間帯による傾向は出ていない。

`94.1` は 941 の**ちょうど 1/10** で、**キャリア断のあと 100BASE-TX で
再ネゴシエーションした**と読める。輻輳ならこういう離散的な値にはならない。

経路の面でも、LAN の iperf3（`.102` ↔ `.101`）は**スイッチ内で完結し WAN 上りを通らない**。
web 会議のトラフィックとは経路が別である。

### pSConfig のスケジュールは cron を書けない

仮に時間帯を絞るとしても、**`repeat-cron` は pSConfig が受け付けない。**

```
JSON Path: schedules/nightly-hourly
Error: Additional properties are not allowed ('repeat-cron' was unexpected)
```

`psconfig validate` で総当たりしたところ、`schedules` が受けるのは
**`start` / `until` / `max-runs` / `repeat` / `slip` / `sliprand` の 6 つだけ**だった。

「毎日 01:00〜05:00 だけ」を書く手段は、**絶対時刻の `start` + `repeat: P1D` のタスクを
深夜の各時刻に N 本並べる**形になる（`start: "2026-08-04T01:00:00+09:00"` +
`repeat: "P1D"` は valid を確認済み）。将来必要になったときのために記録しておく。

### 頻度を落とすと注入実験が撮れなくなる

**iperf3 を深夜のみにすると、16 分の注入中にスループットのサンプルが 1 点も取れない。**
SS-04 の「スループットの谷」が成立しなくなる。頻度を触るなら、
**注入実験の直前だけ `PT5M` などに寄せて、終了後に戻す**手順とセットにする必要がある。

### USB ポートは動いていなかった

「新しい NIC を別の USB ポートに接続した」という認識だったが、**システム上は変化がない。**

- デバイスパスは `usb2/2-2/2-2.2` のまま
- MAC も `a0:ce:c8:e9:1e:a0` のまま
- **08-02 18:54:53 以降、USB の disconnect / enumerate が 1 件も無い**

USB を抜き差しすれば必ず `dmesg` に出る。**USB 側は触られていない。**
LAN ケーブルかスイッチのポートを替えた可能性が高い。

### フラップは 15:56 以降止まっている

`carrier off` は **58 回**（09:14:06〜15:56:29）。**その後 23:00 時点まで約 7 時間ゼロ。**
物理変更のログが無いのに止まっており、**間欠性・環境要因**という見立てを補強する。
判定を「24 時間フラップ 0」に置いた判断は妥当だった。

## Step 20: スイッチとケーブルを替えた。同時に RasPi 側で DNS 起因の障害が出ていた

- 日付: 2026-08-04
- 構成変更: **09:00 頃、LG Gram を RasPi / Mac mini と同じスイッチへ、別の UTP ケーブルで接続**。
  あわせて**予備の USB NIC（ASIX AX88179）を LG Gram に増設**（ケーブル未接続・リンクダウン）。
- **フラップは変更後ゼロ**（09:00〜10:15 の 1 時間 15 分）。判定にはまだ足りない。
- ただし別件で **RasPi の pScheduler が壊れていた。** こちらは修正済み。

### スイッチ・ケーブル変更の効果（暫定）

LG Gram は 08-04 06:46 に再起動している。それ以降の `carrier off` は **4 回**で、
うち 3 回は起動直後（06:50:11 / 06:50:33 / 06:50:41）、残り 1 回が
**08:59:40 = ケーブル差し替えそのもの**。**09:00 以降はゼロ。**

スループットも切り替わりが明確に出た。

| 時刻 | 101→102 |
|---|---|
| 07:00 | 13.4 Mbps |
| 07:30 | 94.1 Mbps |
| 08:00 | **0.63 Mbps** |
| 08:30 | 94.1 Mbps |
| 09:00 | 51.1 Mbps |
| **09:30** | **940.5 Mbps** |
| **10:00** | **940.7 Mbps** |

**変更前の朝は壊滅的だった。** 94.1 Mbps は 941 のちょうど 1/10 で、
これまでと同じ 100BASE-TX への再ネゴシエーションの signature である。
**旧スイッチかそのケーブルが原因だった可能性が高い。** ただし**判定は 24 時間フラップ 0** のまま。

### 増設した予備 NIC は監視 grep を汚す

`enx6c6e072b19b4`（ASIX AX88179、USB `2-1` **SuperSpeed**、ケーブル未接続）。
リンクダウンのまま `ax88179 - Link status is: 0` を吐き続けており、
**その行数がすでに 2,395 行**ある。

```
grep -c "Link status is: 0"          → 2395   ← 予備 NIC のノイズ
grep -c "enxa0cec8e91ea0: carrier off" →    4   ← 稼働 NIC の実数
```

**フラップ監視は必ずインタフェース名で絞る。** Step 18 で「ドライバが変わると
grep が壊れる」と書いたばかりだが、今度は**NIC が増えて壊れた。**

なお `2-1` も SuperSpeed で enumerate した。Step 16 で「SuperSpeed になるのは `2-2` だけ」と
書いたのは**当時の dmesg 履歴からの観察**であって、`2-1` は試していなかった。
**USB3 ポートは少なくとも 2 つある。** 「ポートかアダプタか」の切り分けに使える。

### RasPi: PoE 断の再起動で DNS が飛び、pScheduler が壊れていた

**LG Gram 主導の throughput タスク（`102 → 101`）が 07:30 以降 1 度も走っていなかった。**
`101 → 102`（RasPi 主導）は 30 分おきに走っていたので、片方向だけが欠測していた。

タスクを調べると、psconfig が 1 時間おきに作り直しているのに**毎回 `enabled=False` /
`runs=0`** で無効化されていた。

RasPi 側を見たら原因が出た。

```
Checking limits... Failed.
Limit processor is not initialized: Resolver configuration could not be read or specified no nameservers.
```

`psconfig-pscheduler-agent` は `activating` のまま、
`dns.resolver.NoResolverConfiguration` でクラッシュループしていた。

**コンテナ内の `/etc/resolv.conf` に nameserver 行が無かった。** ホスト側には
`nameserver 192.168.1.1` がある。RasPi は **PoE HAT 給電で、PoE スイッチの接続変更により
再起動**しており、**Docker がコンテナ再起動時にホストの resolv.conf を写した時点で、
まだ dhcpcd が nameserver を書いていなかった**と考えられる。Docker は一度生成した
resolv.conf を上書きしないので、そのまま固定された。

### 修正

```bash
# 即時（コンテナを作り直さずに済む）
docker exec perfsonar-testpoint sh -c 'echo nameserver 192.168.1.1 >> /etc/resolv.conf'
docker exec perfsonar-testpoint systemctl restart psconfig-pscheduler-agent
```

これで RasPi は `active` / `pScheduler appears to be functioning normally` に戻り、
LG Gram 側で作り直された throughput タスクも **`enabled=True` / `runs=1`** になった。

恒久対処として `deploy/raspi/run-testpoint.sh` に
**`-v /etc/resolv.conf:/etc/resolv.conf:ro`** を足した。`--net=host` なので
ホストの resolver が常に正しく、写しではなく実体を見ることで再発しなくなる。

### 記事ネタ

- **外から見ると健全に見える壊れ方がまた出た。** `docker ps` は `Up`、
  `pscheduler troubleshoot` も途中まで OK を返す。`Checking limits... Failed.` の 1 行と、
  `systemctl is-active` が `activating` であることだけが手がかりだった。
  w3-notes Step 10 の「LG Gram の agent がクラッシュループしていた」と**同じ構図**である
- **症状は「片方向のスループットだけが欠測」だった。** 原因は反対側のホストの DNS。
  メッシュ測定は**どちらが lead か**で障害の見え方が変わる
- **監視の grep は、ドライバが変わっても NIC が増えても壊れる。**
  Step 18 に続いて 2 回目。**対象を名前で固定していない検証は信用できない**

## Step 21: フラップは止まった。が、別の障害が残っている（片方向の TCP ストール）

- 日付: 2026-08-04（21:30 時点）
- **リンクフラップは止まった。** スイッチ・ケーブル変更（09:00）以降 **12 時間 24 分ゼロ**。
- **ただし別の障害がある。** `101 → 102`（RasPi 送信）の iperf3 だけが断続的に失敗する。

### フラップ: 09:00 以降ゼロ

`enxa0cec8e91ea0: carrier off` は**通算 4 回のみ**で、すべて 09:00 より前。

| 時刻 | 内容 |
|---|---|
| 06:50:11 / 06:50:33 / 06:50:41 | LG Gram 起動直後（06:46 boot） |
| 08:59:40 | **ケーブル差し替えそのもの** |

以降ゼロ。errors 0 / TX dropped 0、1000Mb/s Full。**旧スイッチかそのケーブルが原因**だった線が濃い。
24 時間判定まであと少し。

### 残っている障害: RasPi → LG Gram のバルク TCP がストールする

`102 → 101` は **21/21 点すべて 939.8〜941.4 Mbps** で完璧。
`101 → 102` だけが **25 点中 9 点**で異常（`0` または `52 kbps`）。

失敗した run の中身を送受信の両側から取った。

| | 値 |
|---|---|
| 送信側（RasPi）`sum_sent` | **524,288 バイト**（= 512 KiB ちょうど）/ 209,690 bps / **再送 13** |
| 受信側（LG Gram）`sum_received` | **0 バイト** / 0 bps / 20.003 秒 |
| intervals（20 個） | 先頭 1 秒だけ 4.19 Mbps、**以降 19 秒すべて 0** |

**最初の 1 ウィンドウ（送信バッファ分）を出したあと、ACK が返らずに完全停止している。**
再送 13 回も通っていない。エラーは報告されず、テストは `Finished` 扱いになる。

### 切り分け済み

- **小さいパケットは通る。** twping の RTT / latency は 1ms 前後・ロス 0 で正常
- **フルサイズのフレームも通る。** `ping -M do -s 1472` を双方向で 5 発、**両方向とも 0% ロス**
- **MTU は両側 1500** で不一致なし
- **RasPi は健全。** `vcgencmd get_throttled` = `0x0`（PoE HAT 給電だが低電圧なし）、
  59.9℃、eth0 は 1Gbps/Full、リンク断は 06:40 の 1 回（PoE 断による再起動）のみ
- **スイッチ変更で新しく出た症状ではない。** 8/3 にも同じ `94 Mbps` / `7 Mbps` が出ていた

### ただし頻度は変わった

`101 → 102` の異常点を期間別に数えた。

| 期間 | 点数 | 異常(<500Mbps) | 異常値の性格 |
|---|---|---|---|
| 08-02 12:00〜08-03 00:00 | 22 | 13 | 359 Mbps = **USB 2.0 期間**（別要因） |
| 08-03 00:00〜12:00 | 25 | 2 | 94 Mbps = **フラップ由来**の 100BASE-TX |
| 08-03 12:00〜08-04 00:00 | 24 | 3 | 同上 |
| 08-04 00:00〜09:00 | 7 | 5 | スイッチ変更前の朝。壊滅的 |
| **08-04 09:00〜21:30** | 25 | **9** | **`0` と `52 kbps`。フラップは 1 回も無い** |

**故障モードが入れ替わっている。** フラップ由来の `94 Mbps`（100BASE-TX 再ネゴ）は消えたが、
**キャリアが一度も落ちていないのに TCP がストールする**という別の症状が残った。
つまり**フラップの解決と、この障害は別問題**である。

### 次の一手（未実施）

- 手動で双方向 iperf3 を連続実行し、再現条件を絞る。**規約 2 により実行前にユーザー確認**
- 失敗時に LG Gram 側で `ss -ti` / `tcpdump` を取り、ACK が出ていないのか届いていないのかを分ける
- LG Gram の r8152 のオフロード（GRO / RX checksum）を切って再現するか見る
- **注入実験はこの障害が残っている限り実施しない。** SS-04 のベースラインが 3 回に 1 回壊れる

## Step 22: 手動 iperf3 で TCP ストールを再現。ただし途中で症状が消えた

- 日付: 2026-08-04（21:30〜23:00）
- **再現には成功した。** ただし**トリガは特定できていない。**
  検証の途中で症状が消え、本番の pscheduler 側も同時刻に正常化した。
- 検証は専用ポート（5301 / 5302）でサーバを立てて実施。**終了後に両側とも停止済み。**

### 再現したときの波形

方向を交互に切り替えて 10 秒テストを回したところ、**3 回中 2 回**で出た。

```
RasPi → LG Gram : [4, 0, 434, 945, 941, 937, 946, 941, 938, 938]   ← 先頭2秒がストール
LG Gram → RasPi : [951, 944, 941, 944, 944, 938, 945, 936, 944, 939] ← 常に full rate
```

**最初の 1 秒で約 512 KiB を出したあと丸 1 秒ゼロになり、その後 941 Mbps に復帰する。**
本番で観測した「0 バイト」「52 kbps」は、**この停止が 20 秒間続いた極端版**である。
512 KiB は送信ソケットバッファ 1 杯分で、**ACK が返らずに送信が詰まった**形と一致する。
復帰までの間隔は RTO 1 回分に相当する。

### 潰せた仮説

| 仮説 | 検証 | 結果 |
|---|---|---|
| MTU 不一致 / 大フレームが通らない | `ping -M do -s 1472` 双方向 5 発 | **両方向 0% ロス**。両側 MTU 1500 |
| 受信側の取りこぼし | 失敗前後で LG Gram の `rx_dropped` / `errors` / `missed` / `fifo` / `over` / `length` | **どれも増えない**（1 run につき +3〜4 で一定） |
| アイドル後の復帰で落ちる | 45 秒アイドル後に実行 ×2 | **clean** |
| pScheduler の一発サーバ（`-s -1`）特有 | 同じ形で ×5 | **5/5 clean** |
| 立ち上がりの急峻さ | `-b 200M` で制限 | clean（ただし比較にならない） |
| 連続実行で再現 | 間を置かずに 2 本 | **clean** |

### 残っている手がかり: EEE の非対称

| | EEE status | Tx LPI | Advertised |
|---|---|---|---|
| **RasPi**（bcmgenet・**送信側**） | enabled - inactive | **34 µs** | 100/1000baseT/Full |
| **LG Gram**（r8152・受信側） | enabled - inactive | **disabled** | Not reported |

**RasPi だけが Tx LPI を有効にしている。** そして**失敗するのは RasPi が送信する方向だけ**である。
アイドル 45 秒では再現しなかったので決め手にはならないが、方向の非対称とは合う。

### 症状が途中で消えた

手動 17 本のうちストールは**最初のバッチの 2 本だけ**で、以降は全て clean だった。
**本番側も 19:30 を最後に正常化している**（20:00 以降 847 → 941 → 941 → 941 → 941 → 941 Mbps）。

**手動検証と本番が同じ時刻に揃って正常化した。**
つまりこれは**時間帯によって出たり出なかったりする**性質のもので、
リンクフラップのバースト型と同じ振る舞いをしている。**短時間の検証では判定できない。**

### 次の一手（未実施・要判断）

**RasPi の EEE を切って、24 時間の失敗率を比較する。**

```bash
ssh unpeeled@raspi-testpoint.local 'sudo ethtool --set-eee eth0 eee off'
```

本番は 30 分間隔なので 1 日で片方向 48 点取れる。**08-04 の失敗率は 9/25（36%）**なので、
EEE を切って有意に下がれば原因と言える。設定はリンク再ネゴを伴うので一瞬切れる。
戻すのは `eee on`。

**注入実験は引き続き見送る。** 失敗率 36% では SS-04 のベースラインが成立しない。

## Step 23: RasPi の EEE を無効化。24 時間の失敗率で判定する

- 日付: 2026-08-04 23:49:59（設定変更）
- Step 22 で残った唯一の手がかり（**RasPi だけ Tx LPI が有効**）を潰しにいく。

```bash
ssh unpeeled@raspi-testpoint.local 'sudo ethtool --set-eee eth0 eee off'
```

- `EEE status: enabled - inactive` → **`disabled`**
- **リンクは 23:49:59〜23:50:02 の 3 秒間だけ落ちて再ネゴ**（`Link is Down` → `Link is Up - 1Gbps/Full`）。
  想定どおり
- 復帰後は `1000Mb/s Full` / `Link detected: yes`、psconfig エージェントも `active`

### 判定の基準

比較対象は **2026-08-04 09:00〜23:30 の `101 → 102` 方向で 9/25 点が異常（36%）**。
本番は 30 分間隔なので、**24 時間で片方向 48 点**取れる。

- **有意に下がれば EEE が原因**
- **変わらなければ EEE は無罪**で、次は失敗時の `tcpdump` / `ss -ti` に進む

判定用のコマンド:

```bash
# 異常点の数（<500Mbps）を数える。scratchpad の sfq.sh を使う
WINDOW_HOURS=24 RESOLUTION_MS=1800000 SHOW_POINTS=99 ./sfq.sh <<'Q'
bps = data('perfsonar.throughput.bps', filter=filter('ps.source','192.168.1.101')).mean(by=['ps.source']).publish(label='bps')
Q
```

### 注意: この設定は再起動で戻る

`ethtool --set-eee` は**永続しない。** RasPi は PoE 給電で、**PoE スイッチ側の操作で
簡単に再起動する**（Step 20 で実際に起きた）。**判定期間中に再起動があったら
設定が戻っていないか確認する。**

原因と確定したら、`systemd` の oneshot ユニットか `networkd-dispatcher` で永続化し、
`deploy/raspi/` に入れる。**まだ確定していないので永続化はしない。**

### 並行して継続中の判定

**LG Gram の NIC フラップは 08-04 09:00 以降ゼロ**（23:50 時点で 14 時間 50 分）。
通算 4 回はすべて 09:00 より前。**24 時間判定は 08-05 09:00 に確定する。**

## Step 24: EEE は効いた。フラップは 21 時間後に再発し、リンクが 100Mb/s に固着していた

- 日付: 2026-08-05（10:30 判定）
- 判定は **2 勝 1 敗**。EEE は当たり、フラップは不合格、そして**新しい問題が 1 つ見つかった。**

### 1. EEE 無効化は効いた（暫定・観測窓 6.5 時間）

`101 → 102` 方向の異常点（<500Mbps）を比較する。

| 期間 | 点数 | 異常 | 失敗率 |
|---|---|---|---|
| 08-04 09:00〜23:30（EEE **有効**） | 25 | 9 | **36%** |
| 08-05 00:00〜06:30（EEE **無効**） | 13 | **0** | **0%** |

**13 点連続で 940〜941 Mbps。** 前日 3 回に 1 回壊れていたものが 1 回も出ていない。
`102 → 101` 方向も 14/14 点すべて 941 Mbps。

**Step 22 で残った EEE の非対称（RasPi だけ Tx LPI 34µs）が原因だった可能性が高い。**
ただし観測窓が 6.5 時間しかない（06:27 のフラップ以降はリンクが 100Mb/s に落ちて
比較に使えなくなった）。**EEE は無効のまま維持し、フラップが止まってから本判定する。**

### 2. リンクフラップは 21 時間 27 分後に再発した

| 時刻 | 内容 |
|---|---|
| 08-04 09:00 | スイッチ・ケーブル変更 |
| 08-04 09:00〜08-05 06:26 | **21 時間 27 分クリーン** |
| **08-05 06:27:00 / 06:27:04 / 06:27:08** | **3 回連続で再発** |

**24 時間判定は不合格。** スイッチ・ケーブル交換は**発生間隔を伸ばしたが、止めてはいない。**
旧環境が 2.4 回/時だったのに対し 21 時間で 1 バーストなので、**改善はしている。**

### 3. 新しい問題: フラップ後、リンクが 100Mb/s に固着して自動復帰しない

これが一番効く発見である。

```
06:27:24  carrier on          ← フラップから復帰
10:27     Speed: 100Mb/s      ← 4 時間経っても 100BASE-TX のまま
```

**07:00 以降のスループットは両方向とも約 94 Mbps** に張り付いていた。

| 時刻 | 102→101 | 101→102 |
|---|---|---|
| 06:00 / 06:30 | 941 Mbps | 941 Mbps |
| **07:00〜10:00**（7 点） | **94 Mbps** | **94 Mbps** |

**これまで散発的に見えていた「94.1 Mbps」は、単発の再ネゴシエーションではなかった。**
**リンクが 100Mb/s に落ちたまま何時間も戻らない状態**だった。
Step 18・21 で「100BASE-TX で再ネゴした疑い」と書いたのは方向として正しかったが、
**一過性ではなく持続する**という点を捉えられていなかった。

復旧はオートネゴの再実行で足りる。

```bash
ssh dev@192.168.1.102 'sudo /usr/sbin/ethtool -r enxa0cec8e91ea0'
```

10:29:18〜10:29:21 に 3 秒落ちて **1000Mb/s Full に復帰**した。

### 監視に足りていなかったもの

**リンク速度を見ていなかった。** キャリア断の回数だけを追っていたので、
**「リンクは上がっているが 100Mb/s」という状態を検知できなかった。**
全測定が静かに 1/10 になり、Detector も `lan-throughput-degraded` が発火するだけで
原因は分からない。**日次チェックにリンク速度を入れる。**

```bash
ssh dev@192.168.1.102 'sudo /usr/sbin/ethtool enxa0cec8e91ea0 | grep Speed'   # 1000Mb/s であること
ssh dev@192.168.1.102 'sudo dmesg -T | grep -c "enxa0cec8e91ea0: carrier off"'
```

### 次の一手

**LAN ケーブルを予備 NIC（`enx6c6e072b19b4` / ASIX / USB `2-1` SuperSpeed）に挿し替える。**
Step 20 で増設済みで、ケーブルを移すだけで済む。これで
**「USB ポート `2-2` / Anker ハブが原因か、それ以外か」**が切り分けられる。

- 止まれば → `2-2` かハブが原因
- 続けば → USB3 全般か環境要因。ケーブル・スイッチは既に替えてあるので候補が尽きる

**インタフェース名が変わる**ので、netem の対象と CLAUDE.md の記載も差し替えが要る。

### 記事ネタ

- **「リンクは上がっているのに 1/10 の速度」という壊れ方。** 監視していたのは
  キャリア断の回数だけで、**速度そのものを見ていなかった。**
  `Link detected: yes` は健全の証明にならない
- 検証スクリプトのバグ（w2 Step 15）、grep 文字列の取り違え（Step 18）に続いて
  **3 回目の「見ていたつもり」**である

## Step 25: NIC を 3 枚目（元の ASIX に戻す）へ。現在は健全

- 日付: 2026-08-06 07:11:33（交換完了）
- 予備 NIC（`enx6c6e072b19b4` / ASIX / USB `2-1`）は**ケーブルを挿すと物理リンクは上がるが
  OS がリンクアップを認識せず IP を取得できなかった。** 切り分けはせず、
  **元の ASIX AX88179（MAC `a0:ce:c8:fe:08:54`）に戻した**（ユーザー判断）。
- **現在の構成は健全。** ただし判定にはまだ時間が要る。

### 現在の構成

| 項目 | 値 |
|---|---|
| インタフェース | **`enxa0cec8fe0854`** |
| MAC | `a0:ce:c8:fe:08:54` |
| ドライバ | `ax88179_178a` |
| USB | `2-2` / **SuperSpeed 5000M**（ハブ無しの直挿し） |
| リンク | **1000Mb/s Full** / Auto-negotiation on |
| IP | `192.168.1.102/23`、デフォルトルートも同 NIC |
| EEE | **not supported**（ASIX は EEE 非対応。LG Gram 側の EEE 要因は構造的に消える） |
| chrony | Stratum 2 / System time 27µs slow / Skew 0.006ppm / Leap Normal |
| リンク断 | **0 回**（07:11 以降） |

**今回は chrony が落ちなかった。** Step 17 では NIC 交換で全 NTP ソースが offline になり
LAN の測定が 37 分止まったが、今回は交換が 6 秒で済んだためか再同期の空白が出ていない。

### 測定は復旧している

- 交換完了後（直近 9 分）の run は **17/17 Finished**
- LAN RTT は 07:30 から再開（0.429 / 0.973 ms、正常値）
- 06:55〜07:23 の Failed 25 件は**交換作業そのものによる断**で、07:23 以降は出ていない

### 前 NIC（Anker ハブ + RTL8153A）の最後

**8/5 10:29 に `ethtool -r` で 1000Mb/s に戻したのに、スループットは 94 Mbps のままだった。**

| 時刻 | 102→101 |
|---|---|
| 08-05 10:00〜18:00（15 点） | **すべて 94 Mbps** |

`ethtool` の表示は 1000Mb/s に戻っていたが、**実効スループットは 100BASE-TX 相当のまま**
だった。すぐに再び落ちたのか、ネゴシエーション結果の表示が実態と食い違っていたのかは
切り分けていない。いずれにせよ**あの構成は持続的に劣化していた。**

### 監視の注意（NIC が替わるたびに壊れる）

ドライバが `r8152` から `ax88179_178a` に戻ったので、**リンク断のログ文字列も戻る。**

```bash
# ax88179 系（現在）
ssh dev@192.168.1.102 'sudo dmesg -T | grep -c "enxa0cec8fe0854: ax88179 - Link status is: 0"'
# 速度の固着チェック（1000Mb/s であること）
ssh dev@192.168.1.102 'sudo /usr/sbin/ethtool enxa0cec8fe0854 | grep Speed'
```

**必ずインタフェース名で絞る。** 取り外した予備 NIC のログがリングバッファに
**3,223 行**残っており、`grep -c "Link status is: 0"` だけだと 3223 と出る。
インタフェース名で絞れば 0 である。Step 18・20 に続いて **3 回目の同じ罠**。

### 残っている判定

| 項目 | 状態 |
|---|---|
| リンクフラップ | 07:11 以降 0 回。**24 時間判定は 08-07 07:11** |
| リンク速度の固着 | 現在 1000Mb/s。日次で確認する |
| スループットが 941 Mbps に戻るか | **次の iperf3 待ち**（30 分間隔） |
| EEE（RasPi 側）の効果 | **無効のまま維持**。フラップが止まってから本判定 |

**注入実験は 24 時間の安定を確認してから。**

## Step 26: 24 時間判定に合格。そして EEE は無罪だった（Step 24 の訂正）

- 日付: 2026-08-07 12:28
- **3 つの障害がすべて消えた。注入実験に進める。**
- あわせて **Step 24 の「EEE 無効化が効いた」という暫定結論を訂正する。**

### 判定結果

| 項目 | 結果 |
|---|---|
| リンクフラップ | **29 時間ゼロ**（交換 08-06 07:11 以降）。24 時間判定 **合格** |
| リンク速度の 100Mb/s 固着 | **1000Mb/s Full を維持**。合格 |
| 片方向 TCP ストール | 08-06 08:00〜08-07 12:28 で **108 点すべて正常**（異常 0 点）。合格 |
| RX/TX errors | **0 / 0** |
| chrony | System time 6.8µs slow / Skew 0.069ppm / Leap Normal |
| 継続中アラート | **0 件** |
| B 案チャートの 6 系列 | すべて **0.85〜1.14** の平常帯 |

### 訂正: EEE は原因ではなかった

**RasPi が 08-06 06:54 頃に再起動し、`ethtool --set-eee` の設定が失われていた。**
Step 23 で「この設定は永続しない。PoE スイッチ側の操作で簡単に再起動する」と
書いたとおりのことが起きた。

```
EEE status: enabled - inactive   ← 08-07 12:28 時点。ON に戻っている
稼働: up 1 day, 5 hours, 34 minutes  → 起動は 08-06 06:54 頃
```

つまり **EEE が有効な状態で 28.5 時間、108 点すべて正常だった。**

| 期間 | LG Gram の NIC | RasPi の EEE | `101→102` の異常率 |
|---|---|---|---|
| 08-04 09:00〜23:30 | Anker ハブ + RTL8153A | **有効** | 9/25（36%） |
| 08-05 00:00〜06:30 | Anker ハブ + RTL8153A | **無効** | 0/13（0%） |
| **08-06 08:00〜08-07 12:28** | **ASIX 直挿し** | **有効** | **0/52（0%）** |

**Step 24 で「EEE 無効化が効いた」と判断したのは交絡だった。**
観測窓が 6.5 時間しかなく、Anker ハブ構成では「14 時間クリーンのあと再発」
「21 時間クリーンのあと再発」という前例があったのに、それを踏まえずに読んだ。
**EEE を戻しても再発しない**以上、EEE は無罪である。

### 真犯人は Anker USB-C ハブ + RTL8153A の構成

3 つの症状（リンクフラップ / 100Mb/s 固着 / 片方向 TCP ストール）が、
**ASIX 直挿しに戻した瞬間にすべて同時に消えた。**

ただし**元の ASIX も 7/30〜8/2 に 124 回フラップしている。**
同じアダプタが今は健全なので、**アダプタ単体ではなく「その時の組み合わせ」が
問題だった**ことになる。この間に変わったものは 3 つある。

1. **スイッチとケーブル**（08-04 09:00 に別スイッチ・別 UTP へ）
2. **USB ハブの有無**（08-06 07:11 にハブを外して直挿しへ）
3. RasPi の PoE 接続先

**どれが効いたかは切り分けていない。** 複数を同時に変えたので確定できない。
記録としてはここまでにして、**再発したらこの 3 つに戻って切り分ける。**

### この一連の調査から

- **「直った」の判定に必要な観測窓は、故障の間隔で決まる。**
  14 時間・21 時間クリーンのあと再発した前例があるのに、6.5 時間で結論を出しかけた
- **設定変更の永続性を確認しないと、実験そのものが無効になる。**
  `ethtool --set-eee` は再起動で戻る。今回はそれが偶然「EEE 無罪」を証明したが、
  気付かなければ「EEE を切ったまま」と誤認したまま先に進んでいた
- **複数の変更を同時に入れると原因は特定できない。** 今回は切り分けより復旧を
  優先した結果そうなった。**それ自体は妥当な判断だが、記録には残す**

### 注入実験の準備状況

**すべて完了している。** 残るのは実施だけ。

| 項目 | 状態 |
|---|---|
| ダッシュボード v2 | 適用済み（SLO ビュー + ズーム版 + 復路系列） |
| イベントオーバーレイ | Detector 4 本、as-code、既定 ON。7/29 の発火で目視検証済み |
| 注入手順 | runbook Step 2.5。デッドマンスイッチはリハーサル済み |
| 撮影手順 | リハーサル 5 巡で確定。凡例・軸・書き出し方法すべて検証済み |
| netem の対象 | **`enxa0cec8fe0854`**（実行前に `ip route show default` で再確認する） |

未決の判断が 1 つ残っている。**注入時間を 16 分（7/29 との比較可能性）にするか、
25 分（ロス Detector 発火の確実性）にするか。**

## Step 27: Phase 4 は新しいセッションで開始する（引き継ぎ）

- 日付: 2026-08-07
- Phase 1〜3 と NIC 障害の切り分けで会話が長くなったため、**注入実験は新セッションで実施する。**
  **撮り直し = 再注入のやり直し**なので、実験の途中でコンテキストが尽きる риск を避ける。

### 引き継ぎのために足したもの

- `CLAUDE.md` の「現在のフェーズ」を **Phase 4 の開始手順**に書き換えた。
  準備項目の一覧、読むべき runbook、未決の判断、注入前チェックコマンドを載せてある
- **`deploy/splunk/query.sh` を新規追加。** 障害の切り分けはほぼこれで進めたが、
  scratchpad に置いていたのでセッションを跨ぐと消えていた。
  `check-charts.sh` は publish ラベル単位の集計しか出さず、
  **「どの系列が欠けているか」「どの dimension が原因か」**が分からない。
  本スクリプトは任意の SignalFlow を投げて系列の内訳と生値を時刻付きで出す

### 新セッションで最初に読むもの

1. `CLAUDE.md`（環境・規約・Phase 4 の開始手順）
2. `docs/runbook-w3-screenshots.md`（撮影台本と注入手順が一体。Step 0〜6）
3. `experiments/w3-notes.md` Step 11〜26（準備の経緯と NIC 障害の顛末）

### 未決の判断

**注入時間 16 分 / 25 分。** 判断材料は Step 13 と runbook の
「SS-05 のナラティブ分岐」に書いてある。

## Step 28: ローリングベースラインが異常を飲み込んだ。ratio では検知できない

- 日付: 2026-08-07 22:15
- **B 案チャート（SLO ビュー）の既知の弱点が、注入実験の直前に実イベントで露呈した。**
  チャートの description に書いていた注意書きが、そのまま現実になった形である。

### きっかけは Splunk の AI Assistant の報告

ユーザーが AI Assistant に確認したところ、こう返ってきた。

> 主系列が **約 13 倍台** で推移したあと、**11:00 前後に急低下**しています。
> 他の系列は概ね 1 倍前後の平常域にあり、主な変動は特定のパスに集中しています。

**「急低下 = 回復」と読める報告だが、実際には回復していなかった。**

### 生値を見ると話が逆だった

| path.id | 現在の RTT | 24h ベースライン | ratio |
|---|---|---|---|
| **wan-cloudflare** | **118.1 ms** | **117.1 ms** | **1.01** |
| **wan-blog** | **116.5 ms** | **116.7 ms** | **1.00** |
| wan-google（8.8.8.8） | 8.0 ms | 8.35 ms | 0.98 |
| wan-sinet-tokyo | 8.3 ms | 8.21 ms | 1.02 |
| wan-riken-tsukuba | 9.8 ms | 9.90 ms | 0.99 |
| lan-wired | 0.73 ms | 0.80 ms | 0.98 |

**ratio が 1.0 に戻ったのは「復旧したから」ではない。「劣化した値がベースラインになったから」である。**
平常 9ms に対して、Cloudflare と自ブログは**いまも 116〜118 ms**。事象は継続中だった。

`base = rtt.median(over='24h')` なので、**12 時間級の異常は 24 時間かけて中央値に取り込まれる。**
経過は次のとおり。

| 時刻 | wan-cloudflare の ratio |
|---|---|
| 08-06 22:30 | 4.93 倍（立ち上がり） |
| 08-06 23:00〜08-07 09:30 | **12.4〜12.9 倍で高止まり** |
| 08-07 10:00 | 4.31 倍 |
| 08-07 10:30 以降 | **1.0 前後**（← ベースラインが追いついただけ） |

AI Assistant が「11:00 前後に急低下」と言ったのは、**RTT の低下ではなくベースラインの追随**だった。
**ratio しか見ない限り、この 2 つは区別できない。**

### 切り分けそのものは設計どおり機能した

**8.8.8.8 は無傷、SINET も理研も無傷、LAN も無傷。**
跳ねたのは Cloudflare と自ブログの 2 経路だけである。

`charts/wan-rtt.json` の description に書いたとおりの使い方が効いた。
「1.1.1.1 と 8.8.8.8 は同じ ping・同じ 5 分間隔にしてあり、**片方だけが跳ねたら
『自宅ではなくその経路が悪い』と切り分けられる**」。

Step 9 で「参照パスが Cloudflare 1 本だけでは切り分け不能」と気付いて 8.8.8.8 を足したが、
**その判断が 2 度目の実イベントで報われた。**
自ブログ（8091.info）も同時に跳ねているので、経路が Cloudflare を共有している可能性が高い。

### T-30min チェックに欠陥があった

runbook は「**B 案チャートで 6 系列すべてが 0.9〜1.1 に収まっていること**」を
注入の前提条件にしていた。**いまの状態はこのチェックを通過してしまう。**
ratio は全系列 0.97〜1.02 だからである。

**ベースラインが汚染されていると、ratio による平常判定は機能しない。**
runbook を修正し、**生値（`now_ms`）が平常レンジに入っていることを主条件**にした。
確認用のクエリと各パスの平常値の表も載せてある。

### 注入実験への影響

- **LAN は完全に健全**なので、実験そのものは成立する
- ただし **SS-01（キービジュアル）で `wan-cloudflare` と `wan-blog` は使えない。**
  ベースラインが 117ms なので、注入で 217ms になっても ratio は 1.85 程度にしかならず、
  他パスの 12 倍と並ばない
- **残り 4 系列**（`lan-wired` / `wan-google` / `wan-sinet-tokyo` / `wan-riken-tsukuba`）
  で絵は成立する。該当 2 パスは「別事象で劣化中」と注記する

締切（8/9 公開）を考えると、ISP 事象の復旧とベースラインの正常化
（復旧後さらに 12〜24 時間）を待つ余裕はない。**注記して撮る方針とする。**

### 記事ネタ

- **「ローリングベースラインは長時間の異常を平常に見せてしまう」を実イベントで示せる。**
  チャートの description に予防的に書いていた注意書きが、記事の締切直前に現実になった。
  **設計時の但し書きが実測で裏付けられた**という、めったに撮れない材料である
- **AI に聞いたら『回復した』と読める答えが返ってきた。** AI が間違えたのではなく、
  **ratio という指標がその区別を持っていない。** 指標の設計が問いの答えを規定する
- **平常判定を正規化した値だけで行ってはいけない。** 生値を併せて見る。
  検証スクリプトのバグ（w2 Step 15）、grep 文字列の取り違え（Step 18）、
  NIC 増設による grep 汚染（Step 20）に続いて、**4 回目の「見ていたつもり」**である

### 追記: traceroute で真因が特定できた（Cloudflare 網の内側）

ユーザーから「Cloudflare OS の公開（https://blog.cloudflare.com/cloudflare-os/）の
影響ではないか」という問いがあり、確認した。**無関係だった。**
公開は 2026-08-05、内容は**社内向けの AI エージェント / ワークスペース基盤を
OSS 化した**という話で、エッジの再起動・ドレイン・PoP 入れ替えといった
**ネットワーク展開作業への言及は無い。** 劣化の開始は 08-06 22:30 で時期も合わない。

代わりに **traceroute が答えを出した。**

```
=== 1.1.1.1 ===
 6  27.85.134.14      10.909 ms     ← 国内 ISP。ここまで正常
 7  103.22.201.36    126.545 ms     ← +115ms。Cloudflare 網に入った瞬間
 8  1.1.1.1          119.753 ms

=== 8.8.8.8（対照） ===
 6  8.8.8.8            8.782 ms     ← 国内で受けている。無傷
```

`103.22.201.36` は **Cloudflare（AS13335）のアドレス帯**である。つまり、

- **自宅と ISP は無罪。** hop 6 まで 10.9ms で完全に正常
- **Cloudflare のネットワークに入った直後で +115ms 跳ねている**
- 8.8.8.8 は同じ ISP を通って 8.8ms → **切り分けが完全に成立した**

**Cloudflare 側が、国内で受けたトラフィックを遠方の PoP へ運んでいる**状態と読める。
遅延が ±0.7ms で極めて安定していること（輻輳ならジッタが出る）も経路の問題を裏づける。

### これは 7/30 の事象の再発である

`deploy/psconfig/home-lab-mesh.json` の `wan-google` グループにこう書いてある。

> 2026-07-30 に Cloudflare だけが **8.9→122ms** へ遠回りする事象が起きて露呈した

**今回は 9→118ms。ほぼ同じ値で、同じ事象が 1 週間で 2 度起きた。**
Step 9 でこれを見て 8.8.8.8 を足したので、**今回は即座に切り分けられた。**
設計判断が 2 度目の実イベントで報われた形である。

### 見えた設計の限界: ホップ数だけでは追えなかった

**Splunk のデータだけでは「どこで跳ねているか」が分からなかった。**
`bridge/psotel/convert.py` は trace から `perfsonar.trace.hops`（ホップ数）しか出しておらず、
**実際ホップ数は 8 のまま変わっていない**（08-05 22:30 以降ずっと 8、たまに 9 に揺れる程度）。

**経路長は変わっていないのに遅延だけが 13 倍になった**ので、
ホップ数の時系列を見ても異常として立ち上がらない。手で traceroute を叩いて初めて分かった。

**ホップごとの RTT を保存していれば自動で分かった。**
保存しない判断自体は妥当（`intervals[]` と同じくサイズが大きい）だが、
**「何を捨てたか」がそのまま「何が見えないか」になる**という例である。

### 記事ネタ

- **参照パスを 2 本にした判断が、2 度目の実イベントで報われた。**
  1 本なら「自宅が悪いのか相手が悪いのか」を今回も切り分けられなかった。
  Step 9 で設計の穴に気付いて直したものが、1 週間で 2 度効いた
- **AI に聞いたら「回復した」と読める答えが返り、traceroute を叩いたら真因が出た。**
  ratio → 生値 → traceroute と、**降りていく順序そのものが記事になる**
- **保存しなかったデータが、見えなかった範囲を決めた。** ホップ数は残したが
  ホップごとの RTT は捨てた。だから「経路長は同じなのに遅い」という状態を
  ダッシュボードでは説明できなかった。**サンプリング設計の話として書ける**

## Step 29: Cloudflare 事象は復旧した。が、今度はベースラインが「高いまま」残った

- 日付: 2026-08-08 05:11〜05:30（Phase 4 の T-30min 事前確認）

### 事前確認の結果

`docs/runbook-w3-screenshots.md` Step 2.5 の事前確認を実施した。**生値の合格条件はすべて通った。**

| 項目 | 結果 | 判定 |
|---|---|---|
| NIC 名 | `enxa0cec8fe0854`（交換なし） | — |
| Speed / Duplex / Link | 1000Mb/s / Full / yes | 合格 |
| `ax88179 - Link status is: 0` の件数 | **0** | 合格 |
| qdisc | `fq_codel` | 合格 |
| chrony System time | 17.3 µs fast | 合格 |
| chrony Skew | 0.077 ppm | 合格 |
| pscheduler タスク | **12 / retry-policy 欠落 0** | 合格 |

`now_ms` の生値も全系列が平常レンジに収まった。

| path.id | `now_ms`(last) | 平常レンジ | 判定 |
|---|---|---|---|
| lan-wired | 0.806 | 0.7〜1.1 | 合格 |
| wan-cloudflare | 8.668 | 8〜10 | 合格 |
| wan-blog | 8.756 | 8〜10 | 合格 |
| wan-google | 8.272 | 8〜10 | 合格 |
| wan-sinet-tokyo | 8.722 | 8〜9 | 合格 |
| wan-riken-tsukuba | 10.056 | 9〜10 | 合格（上端） |

### Cloudflare 事象は 08-08 02:50 に復旧していた

5 分解像度で追うと、**`wan-cloudflare` と `wan-blog` が同時刻に落ちている。**

| 時刻 | wan-cloudflare | wan-blog |
|---|---|---|
| 08-08 02:45 | 119.212 | 117.378 |
| **08-08 02:50** | **9.482** | **9.146** |
| 08-08 03:45 | 8.836 | 8.780 |

2 経路が同じ 5 分バケットで戻ったので、Step 28 の traceroute の結論
（**Cloudflare 網の内側**、hop 7 の `103.22.201.36` で +115ms）と整合する。
**自宅側では何もしていない。** 事象の総継続は 08-06 22:30 → 08-08 02:50 の約 28 時間。

### そして Step 28 の鏡像が起きた

**生値は平常に戻ったのに、ratio が 0.076 になった。**

`base = rtt.median(over='24h')` が **117.5ms のまま**だからである。
28 時間のプラトーが 24h 窓を埋め尽くしていて、復旧から 2 時間ではまだ抜けない。

| 時刻 | wan-cloudflare の ratio |
|---|---|
| 08-07 10:30〜08-08 02:45 | 1.00〜1.02（← 劣化中なのに平常に見える。Step 28） |
| **08-08 03:00 以降** | **0.076〜0.083**（← 平常なのに異常に見える） |

**Step 28 は「劣化したまま ratio 1.0」、Step 29 は「平常なのに ratio 0.076」。**
同じ 1 本のローリングベースラインが、**復旧の前後で正反対の嘘をついた。**
片方だけなら「たまたま」だが、**両方向に振れたことで指標の性質として確定した。**

### 注入実験への影響: このまま撃つと SS-01 が逆向きに読める

注入すると `wan-cloudflare` は 9 → 109ms になる。base が 117.5 なので **ratio ≈ 0.93**。

- 平常帯: **0.076**（watermark 1.0 の遥か下）
- 注入中: **0.93**（1.0 に近づく）

つまり 2 系列で、**「異常な低位から正常へ上昇した」という絵になる。**
キービジュアルの筋（平常 1.0 → 跳ねる → 復旧）と真逆である。
残り 4 系列（`lan-wired` / `wan-google` / `wan-sinet-tokyo` / `wan-riken-tsukuba`）は健全。

### ベースラインの回復時刻

復旧が 02:50 なので、

- **14:50 JST**: 24h 窓の過半が低値になり、中央値が反転する（交差点。前後は不安定）
- **08-09 02:50 JST**: 窓から 117ms が完全に抜ける。**ここから 24h ショット（SS-08 / SS-09）も成立する**

### 判断: リハーサル（今）＋ 本番（08-09 04:00 以降）の 2 回撃つ

8/10 のコンテスト締切に向けて記事の執筆を止めたくないので、ユーザーの判断で 2 段構えにした。

1. **今すぐリハーサル注入**を実施し、仮画像を `docs/article/images/provisional/` に取得する。
   記事の構成・キャプション・図版配置を先に確定させる
2. **08-09 04:00 以降に本番注入**を行い、`docs/article/images/raw/` の最終版に差し替える

**リハーサル注入が本番のベースラインを汚す心配は無い。**
16 分 ÷ 24h = **1.1%** の汚染率であり、`median(over='24h')` は 50 パーセンタイルなので
1.1% の外れ値では動かない。本番時の 24h 窓（08-08 04:00〜08-09 04:00）に
リハーサルが含まれても ratio への影響はゼロである。
**これは Step 28/29 で見た「12 時間級なら飲み込まれる」の裏返しで、
短時間の異常はベースラインを動かせない**という同じ性質の別の側面である。

リハーサルには副次的な利点もある。SS-05a（Active alerts は発火中しか撮れない）の
タイミング、AI Assistant の疎通（リハーサルで 1 回落ちている）、Export の絶対レンジ落ち、
といった**撮り逃し要因を本番前に実地で潰せる。**

### 記事ネタ

- **同じベースラインが、復旧の前と後で正反対に嘘をついた。** 劣化中は「平常」、
  平常になったら「異常」。**指標の設計が問いの答えを規定する**という Step 28 の主張が、
  対称な 2 例で裏付けられた。片方向だけの観測では「たまたま」で片付けられていた
- **「異常の継続時間」と「ベースラインの窓幅」の比が、その指標の使える/使えない を決める。**
  16 分（1.1%）は無視される。28 時間（>100%）は平常として取り込まれる。
  **その中間に、指標が壊れる帯域がある**

## Step 30: リハーサル注入を実施。4 Detector 全発火、そして片方向注入が指標を方向で割った

- 日付: 2026-08-08 05:22〜06:54
- 位置づけ: **本番ではない。** Step 29 の判断により、8/10 のコンテスト締切に向けて
  記事の構成を先に固めるための**仮画像取得**。本番は 08-09 04:00 以降

### 実施記録

| 項目 | 値 |
|---|---|
| 注入開始 | **2026-08-08T05:22:20+09:00** |
| 注入解除 | **2026-08-08T05:38:26+09:00** |
| 実注入時間 | **16 分 06 秒** |
| パラメータ | `netem delay 100ms loss 3%`（`enxa0cec8fe0854` egress） |
| デッドマン | `--on-active=1200`（05:42:09 発火予定）→ 解除時に停止、0 timers |
| 解除後 qdisc | `fq_codel`（`noqueue` ではない。正常） |
| chrony（解除後） | System time 4.5µs / Skew 0.074 ppm（注入で乱れていない） |

Mac 側からの裏取り。**注入は対象ノードだけに効いた。**

| 宛先 | avg RTT | ロス |
|---|---|---|
| 192.168.1.102（注入対象） | **101.728 ms** | 0% |
| 192.168.1.101 RasPi（対照） | 0.588 ms | 0% |
| 1.1.1.1（Mac の WAN・対照） | 8.779 ms | 0% |

20 発でロス 0 だが、3% × 20 発 = 期待 0.6 発なので `0.97^20 = 54%` の確率で起きる。異常ではない。

### 全 6 パスが同時に崩れた（同一 NIC の設計どおり）

| path.id | 平常 | 注入中 | 倍率 |
|---|---|---|---|
| lan-wired | 0.81 ms | **101.3 ms** | 126x |
| wan-cloudflare | 9.04 | 109.2 | 12.1x |
| wan-blog | 8.84 | 109.6 | 12.4x |
| wan-google | 8.71 | 109.1 | 12.5x |
| wan-sinet-tokyo | 8.21 | 108.8 | 13.3x |
| wan-riken-tsukuba | 10.05 | 110.2 | 11.0x |

### 4 Detector が全部発火した。ロス Detector の未決分岐が決着した

**Step 13 で集約キーを直した `packet-loss` が、16 分の注入で発火した。**

| Detector | 発火 | 値 |
|---|---|---|
| lan_throughput_degraded | 05:30 | **1,303,994 bps（1.30 Mbps）** |
| lan_rtt_degraded | 05:35 | 3 |
| **packet_loss_sustained** | **05:33（wan-blog）/ 05:37（lan-wired）** | 2 |
| wan_rtt_sudden_change | 05:34（sinet / riken）/ 05:38（google） | 108.8〜110.2 |

Active alerts の severity は **Critical 0 / Major 2 / Minor 3 / Warning 1**。

これで `docs/runbook-w3-screenshots.md` Step 4 の未決分岐が**「発火した」側に確定した。**
**本番を 25 分に伸ばす必要は無い。** 記事は
「見逃し → 集約キーの設計ミスを究明 → 修正 → 撃って確かめた」で書ける。
ただし発火は 05:33 / 05:37 と**窓の終盤**であり、12 分窓が狭いという構造自体は残っている。

### ベースライン汚染が Detector の検知漏れとしても実証された

`wan_rtt_sudden_change` が発火したのは **google / sinet / riken の 3 本だけ**で、
**`wan-cloudflare` と `wan-blog` は発火しなかった。**
両者のベースラインが 117ms のままなので、**109ms は「逸脱」に見えない。**

**同一の 100ms 注入を、6 本中 4 本が検知し 2 本が見逃した。**
Step 29 で「ratio チャートが壊れる」と予測したものが、**Detector の発火側にも同じ形で出た。**
チャートの見た目の問題ではなく、**検知能力そのものが失われていた**ことになる。

SS-01b（ズーム、Y 軸 0〜15）でも該当 2 系列は底に張り付いて動かない。目視でも確認済み。

### 片方向注入が、指標を方向で真っ二つに割った（今回いちばんの収穫）

netem は egress にしか効かない。その帰結が**3 つの指標で別々の形**に出た。

**1. RTT — 方向が分からない**

`twping` の RTT は**両方向とも約 101ms** に上がった。応答パケットが netem を通るため。
**RTT だけ見ていると、どちら側で何が起きたのか特定できない。**

**2. 片道遅延 — 注入方向だけが欠測した**

| バケット | 102→101（注入方向） | 101→102（逆方向） |
|---|---|---|
| 05:20 | 0.39 | 0.57 |
| 05:25 | 0.37 | 0.63 |
| **05:30** | **欠測** | 0.65 |
| **05:35** | **欠測** | 0.62 |
| **05:40** | **欠測** | 0.54 |
| 05:45 | 0.34 | 0.68 |

`DELAY_CEILING_MS['lan-wired'] = 5` のゲートに引っかかり、**注入方向の 3 点だけが捨てられた。**
逆方向は 0.54〜0.65ms で**まったく無傷**。clock_error も 300〜500µs で 10ms ゲートに触れていない。

**「欠測が方向を教えた」** ことになる。runbook が想定していた
「OWD が欠測する一方 RTT は連続」より一段強い。

**3. スループット — 720 倍の方向非対称**

| 方向 | 05:30（注入中） | 06:30 |
|---|---|---|
| 102→101（注入方向、バルクが netem を通る） | **1.30 Mbps** | 941.4 Mbps |
| 101→102（逆方向、ACK だけが netem を通る） | **940.5 Mbps** | 940.8 Mbps |

バルクデータが netem を通る方向だけ TCP が崩壊した。逆方向は ACK しか通らないので、
3% の ACK ロスは累積 ACK で吸収され、100ms の RTT 増も window 自動調整で吸収されて**無傷**。

7/29 の 240.8 Mbps と比べて桁が違うが、7/29 は Lima VM が対象で構成が異なる。**単純比較はできない。**

### 撮影結果と、本番までに直すこと

仮画像 13 枚 + AI Assistant 転記 1 件を `docs/article/images/provisional/` に取得。
SS-01〜09 は全て揃った。**SS-05a（Active alerts 一覧）は発火中に撮れており、
これが撮れた時点でリハーサルの主目的は達成している。**

Export の既知の罠（絶対レンジ落ち）は**踏まなかった**。SS-06 のヘッダに
`08/08/2026 04:52:00 am to 08/08/2026 05:52:00 am` が保持され、
イベントオーバーレイ 4 本もヘッダに並んでいる。

**本番（08-09）までに直すこと:**

| # | 問題 | 対処 |
|---|---|---|
| 1 | 時刻レンジが **04:52〜05:52**（注入開始 ±30min）だった。runbook の指定は「**開始の30分前〜解除の30分後**」で、正しくは 04:52〜06:08。復旧の裾が切れている | レンジ指定を修正 |
| 2 | **SS-02 で片道遅延の欠測が読めない。** RTT が 100ms に振れて Y 軸が自動で 0〜100ms になり、0.4ms の OWD が底に潰れる。**今回いちばんの発見が図で読めない** | Y 軸を絞ったズーム版チャートを追加 |
| 3 | パケットロスチャートの凡例が **`See all` に畳まれている**（w6）。SLO ビューで直したのと同じ問題 | w12 に変更 |
| 4 | スループットは iperf3 が 30 分間隔のため、**16 分の窓に 1 点しか入らない**。谷にならず斜めの直線になる。方向非対称を主題にするなら逆方向系列も見せたい | レンジを広げる（04:00〜07:00 等） |
| 5 | SS-01 と SS-01b の**ファイル中身が入れ替わっていた** | リネーム済み |
| 6 | SS-08 のファイル名に**空白と日本語**が入っていた | `SS-08-wan-owd.png` にリネーム済み |

**2 と 3 はダッシュボード定義の変更を伴う。** runbook は「撮影が完全に終わるまで
`apply.sh --only dashboard` を流すな」と書いているが、
**リハーサルと本番の間である今が、まさに流してよい唯一のタイミング**である。

### #2 と #3 を修正して適用した（2026-08-08 07:20 頃）

**#2: `charts/twamp-delay-gated-zoom.json` を新設した**（chart ID `HPJF0cVCIAo`）。
**ただし 1 回目の設計は失敗し、作り直した。**

**1 回目**: 本体と同じ programText（`delay` / `rtt` / `clock_error` の 6 系列）のまま
左軸を 0〜2ms に固定し、凡例の次元を `ps.source` にした。
SLO ビューの本体/ズームと同じ「同一 programText・軸だけ違う 2 枚」の型を踏襲したつもりだった。

**描かせてみたら読めなかった。** 凡例が `192.168.1.101` / `192.168.1.102` の
繰り返しになり、**どの線が片道遅延でどれが RTT / clock_error なのか区別できない。**
`dimensionInLegend` は 1 次元しか出せないので、
**「メトリック」と「方向」を同時に表せない**という制約に正面からぶつかった。
SLO ビューでこの型が成立していたのは、系列が `path.id` 1 次元で識別できたからである。
**型を借りたが、前提が違っていた。**

**2 回目（採用）**: 片道遅延 2 系列だけに絞り、**折れ線ではなく棒**にした。

- 系列が 2 本だけなので `ps.source` = 方向が**一意に決まる**
- 棒なら**欠測は「棒が無い」**として描かれ、折れ線の補間有無に左右されない
- 左軸 0〜1.5ms 固定（実測 0.34〜0.68ms に対し 2.2 倍の余裕）
- **RTT の連続性と clock_error は本体 SS-02 が持っているので重複させない**

**1 枚のチャートに 1 つの主張だけを持たせる**、に落ち着いた。
ズーム版を「同じものの軸違い」と考えたのが誤りで、**別の問いに答える別のチャート**だった。

**#3: パケットロスを w6 → w12 にした。** 系列が 11 本
（`path.id` × 方向 × `ps.test.type`）あり、実測で 1 項目あたり約 90px なので
11 × 90 = 990px。w6（約 640px）では 6 本で畳まれ、w12 なら収まる。

ダッシュボードの行番号を組み替えた（ズーム追加でひとつずつ後ろへ）。
`trace-hops` は行末で単独になるため w12 にして穴を埋めた。

適用後の `check-charts.sh` は全チャートにデータあり。本体チャートは
**`delay` 132 点 / `rtt` 146 点**で、**ゲートで捨てられた 14 点の差がそのまま出ている。**

**#3 は 1 回で通った。** 適用後のスクリーンショットで凡例 11 項目が
`See all` なしに全部並ぶことを目視確認済み。

**#1（レンジ）と #4（スループットの間隔）は未対処。** どちらもチャート定義ではなく
**撮影時の時刻レンジ指定の問題**なので、本番の撮影時に対処する。

### AI Assistant は今回も逆の結論を出した（SS-07）

「現在発生中のアラートを確認して、想定原因を説明して下さい」に対する回答（全文は
`docs/article/images/provisional/SS-07-ai-assistant.md`）。**3 点で誤っていた。**

| # | AI の記述 | 実際 |
|---|---|---|
| 1 | 「**LAN RTT (twping) は相対的に安定**しており、WAN 側ほどの急騰は見えていません」 | LAN は **0.81 → 101.3ms（126 倍）**。**全パス中で最大の逸脱**だった |
| 2 | 「まずは**端末や LAN 内部より WAN 側の確認**を優先するのがよさそうです」 | 障害は**測定ノード自身の NIC egress**。切り分け方向が**完全に逆** |
| 3 | 「**wan-rinet-tsukuba** を中心に」 | そんな `path.id` は無い（`wan-riken-tsukuba`）。**ホスト名の捏造** |

さらに、**`wan-cloudflare` と `wan-blog` だけが発火していない**という
今回いちばん重要な異常には**まったく言及しなかった**。

**Step 28 に続いて 2 回目である。** 前回は「ratio が回復に見える」という
**指標側の欠陥**を AI がそのまま反映した例だった。今回は**指標は正しく出ていたのに
AI が読み違えた。** 原因が別なので、2 例で「AI の失敗の仕方」が 2 種類そろったことになる。

### 記事ネタ

- **片方向の故障を、3 つの指標が 3 通りに映した。** RTT は両方向に等しく反応して
  方向を消し、片道遅延は**欠測という形で**方向を示し、スループットは 720 倍の差で
  方向を示した。**「何を測るか」が「何が分かるか」を決める**の、これ以上ない実例
- **欠測がいちばん多くを語った。** 品質ゲートが捨てた 3 点が、
  「どちら向きの経路が壊れたか」という、残ったデータでは答えられない問いに答えた。
  `docs/schema.md` の「欠測は『壊れた』ではなく『捨てた』」がここで回収される
- **ベースラインの汚染が、チャートの見た目ではなく検知能力を奪った。**
  同じ注入を 6 本中 4 本が検知し 2 本が見逃した。**Detector は無言で失敗する**
- **AI の誤り方が 2 種類そろった。** 指標の欠陥をそのまま反映した Step 28 と、
  正しい指標を読み違えた Step 30。**「AI が間違えた」で片付けると、
  この 2 つは区別できない**
- **凡例に出せる次元が 1 つ、という制約が設計を決めた。** 「メトリック × 方向」を
  1 次元で表せないので、**チャートを分けるしかなかった**。
  SLO ビューで通用した「軸だけ違うズーム版」の型をそのまま持ち込んで失敗している。
  **型の再利用は前提の再利用でもある**という、地味だが実務的な失敗例

## Step 31: 本番注入を新しいセッションに分ける（引き継ぎ）

- 日付: 2026-08-08 20:40
- Step 27 と同じ理由。**本番注入は画像の読み込みが多くコンテキストを大きく使う**ため、
  リハーサルと記事執筆で 50% を消費した現セッションでは分ける。

### このセッションで確定したこと

| 項目 | 内容 |
|---|---|
| リハーサル注入 | 08-08 05:22:20〜05:38:26（16分06秒）。4 Detector すべて発火 |
| 注入時間の未決分岐 | **16 分で決着**。`packet-loss` が発火したので 25 分に延ばす必要なし |
| チャート修正 | `twamp-delay-gated-zoom` を新設（片道遅延のみ・棒・0〜1.5ms）、`packet-loss` を w12 化 |
| 記事 | タイトル・構成・本文 8,336字 が確定。レビュー 3 回反映済み |
| 図版 | Cloudflare 事象の 3 枚（`raw-wide` / `ratio-wide` / `ratio-narrow`）は確定・差し替え不要 |
| リポジトリ | **public 化完了**。`CLAUDE.md` と `docs/review/` は履歴から除去 |

### 本番でやることは差し替えだけ

**記事の主張はリハーサルのデータで確定している。** 本番で変わるのは数値と図版だけで、
論の構造は動かない。もし本番注入が事故っても、リハーサルのデータで記事は成立する
（ただし SS-01 系の比率チャートは 2 系列が沈んだままになる）。

### 新セッションでの入り口

`CLAUDE.md` の「次にやること: Phase 4 本番の注入と撮影」に、実施時刻・判断の根拠・
撮影後の手順まで書いた。**まずそこを読み、次に `docs/runbook-w3-screenshots.md` を読む。**

**事前確認で最も重要なのは、合否を `now_ms` の生値で判定すること。**
比率が 0.9〜1.1 でも平常の証明にならないというのは Step 28/29 で 2 度実証しており、
記事の主題そのものでもある。ここを比率で済ませると、記事と矛盾した手順を踏むことになる。

## Step 32: 本番の事前確認で 20.5 時間のデータ欠測を発見。原因は Collector が握った失効トークン

- 日付: 2026-08-09 05:50〜06:10

Phase 4 本番の事前確認（`docs/runbook-w3-screenshots.md` Step 2.5）で、**`now_ms` が
全系列 0 点**であることが分かった。注入は延期せず、原因を潰してから撃つ判断をした。

### 症状と原因

| 項目 | 内容 |
|---|---|
| 症状 | Collector が ingest で `HTTP Status Code 401` を返され `Dropping data` |
| 最終データ点 | **08-08 09:20 JST**（401 の初出 08-08 09:21 と一致） |
| 欠測 | 約 20.5 時間 |
| 原因 | Collector コンテナ内の `SPLUNK_ACCESS_TOKEN`（末尾 `RnKQ`）が `.env` の現行値（末尾 `B-4A`）と不一致 |

コンテナは 11 日前に起動しており、**その後 `.env` のトークンがローテートされたが
コンテナは起動時の環境変数を保持し続けていた。** 旧トークンが 08-08 09:21 に失効した
時点でパイプラインが切れた。`.env` の両トークンは検証したところ現時点で有効
（ingest 200 / API 200）なので、失効したのはコンテナ側が握っていた旧い値のほうである。

### 切り分けの順序

1. `now_ms` 0 点 → bridge のログを見ると `PUT /archive 200 OK` が並んでいる。**受信は生きている**
2. collector のログに 401。`otlp_http/splunk` exporter が `not retryable error` で drop
3. `.env` のトークンを直接 curl で叩くと 200 → **トークン自体は有効**
4. `docker inspect` でコンテナ内の値と `.env` を突き合わせて不一致を確認

**bridge が 200 を返していることが誤誘導になる。** ブリッジは perfSONAR からの
PUT を受けて OTLP に流すところまでしかやらないので、その先の Splunk 送信が
落ちていても bridge のログは正常に見える。**切り分けは collector のログまで見ないと届かない。**

### 対処

```bash
set -a; . ./.env; set +a
docker compose -f deploy/mac/compose.yaml up -d collector   # 環境変数が変わるので recreate される
```

drop されていたデータは `not retryable` なのでキューに失うものはない。再作成後、
コンテナ内トークンが `.env` と一致することを `docker inspect` で確認した。
**06:01 から Splunk 側に点が入り始めた**（復旧 05:54 の約 7 分後。測定間隔 + 反映遅延）。

### `base_24h_ms` が「平常」に見えていた

これが今回いちばん危なかった点である。欠測中にもかかわらず、`base_24h_ms` は
全系列が平常帯を返していた（LAN 0.797 / WAN 8.2〜9.9ms）。

**24h 窓に停止前の 3.3 時間分（08-08 06:00〜09:20）が残っていただけ**で、
復旧の証拠ではない。**`median(over='24h')` は直近にデータが無くても値を返し続ける。**

Step 28/29 は「ベースラインが異常を飲み込んで ratio が 1.0 に戻る」ケースだったが、
今回は「**測定が止まっているのにベースラインだけが平常値を返す**」という別バージョンである。
どちらも **ratio や集約値では検知できず、生値を見るまで分からない。**
runbook が `now_ms` の生値で判定する手順になっていなければ、
データが入っていないまま注入していた。

### 事前確認の結果（全項目合格）

| 項目 | 結果 |
|---|---|
| 対象 NIC | `enxa0cec8fe0854`（`ip route show default`） |
| リンク速度 | 1000Mb/s Full / Link detected: yes |
| ax88179 リンクダウン | 0 件 |
| qdisc | `fq_codel`（`noqueue` ではない） |
| chrony | System time 2.2µs fast / Skew 0.068ppm |
| pSConfig | タスク 12 / retry-policy 欠落 0 |
| testpoint | Up 4 days |

復旧後の生値（08-09 06:00〜06:05）:

| path.id | `now_ms` | 合格レンジ | 判定 |
|---|---|---|---|
| `lan-wired` | 0.829 / 0.878 | 0.7〜1.1 | 合格 |
| `wan-cloudflare` | 8.691 / 8.707 | 8〜10 | 合格 |
| `wan-google` | 8.356 / 8.378 | 8〜10 | 合格 |
| `wan-blog` | 8.675 / 8.892 | 8〜10 | 合格 |
| `wan-sinet-tokyo` | 8.335 | 8〜9 | 合格 |
| `wan-riken-tsukuba` | 9.995 | 9〜10 | 合格（上限際） |

**Cloudflare 事象（Step 29）は完全に解消した。** 117ms のまま残っていた
`wan-cloudflare` / `wan-blog` のベースライン汚染が抜け、生値・ベースラインとも 8〜9ms 帯に戻っている。
**Phase 4 を 08-09 まで待った理由はこれで解消された。**

### 注入時刻を 07:30 に決めた理由

技術的にはこの時点で撃てる。ベースラインの点数は今も 1 時間後も約 40 点で変わらない
（旧データが窓から抜ける分を新データが埋める）。決め手は**図版の見栄え**である。

撮影レンジは注入 ±30 分なので、06:20 に撃つとレンジ左端（05:50〜）に
**20.5 時間の欠測の切れ目が写り込む。** SS-01 のキャプションで注記が必要になり、
記事の論旨と関係のない説明が 1 つ増える。07:30 なら レンジは 07:00〜08:16 で、
欠測明け（06:05）から約 1 時間離れるため切れ目は写らない。
Detector の 12 分窓も新データだけで埋まる。

### 教訓（運用に残す）

**`.env` のトークンをローテートしたら、コンテナを recreate するまで反映されない。**
`docker compose up -d` は環境変数の変更を検知して recreate するが、
**ローテートした人が compose を流し直さなければコンテナは古い値のまま動き続ける。**
しかも旧トークンが失効するまでは正常に見えるので、**ローテートと障害発生の間に時間差が空く。**
今回は失効まで気付かなかった。

パイプラインの死活は bridge のログでは分からない。**`docker logs psotel-collector | grep "Dropping data"` を
死活確認の定番にする。**

## Step 33: Phase 4 本番注入を実施。4 Detector 全発火、AI は「正しく引いてから読み違えた」

- 日付: 2026-08-09 07:29:44〜07:45:38（15 分 54 秒）

事前確認で見つけた欠測（Step 32）を潰したうえで本番注入を実施した。**リハーサルの再演であり、
記事の主張は変わらない。** 変わったのは数値と、AI Assistant の失敗の質である。

### 実施記録

| 項目 | 値 |
|---|---|
| 注入開始 | **2026-08-09T07:29:44+09:00** |
| 注入解除 | **2026-08-09T07:45:38+09:00** |
| 注入時間 | **15 分 54 秒** |
| パラメータ | `netem delay 100ms loss 3%` / `enxa0cec8fe0854` egress |
| 解除後 qdisc | `fq_codel`（正常復帰） |
| デッドマン | 07:49:39 武装 → 正常解除が先行し**未発動**。timer 残存 0 件 |

Mac からの裏取り（7/29・8/08 と同じ対照構成）:

| 対象 | RTT avg | 期待 | 結果 |
|---|---|---|---|
| LG Gram（注入対象） | **101.790 ms** | +100ms | 一致 |
| RasPi（対照） | 0.613 ms | 無変化 | 一致 |
| Mac → 1.1.1.1（対照） | 8.691 ms | 無変化 | 一致 |

対照 2 系統が動いていないので、**劣化が LG Gram の egress に限定されている**ことが外部から裏付けられた。

### Detector は 4 つとも発火した。ただし同時ではない

| 発火時刻 | Detector | 対象 | 値 | 注入開始からの経過 |
|---|---|---|---|---|
| 07:37 | `packet-loss` | lan-wired 101→102 | 2 | **7 分** |
| 07:38 | `packet-loss` | lan-wired 102→101 / 101→102 | 2 | 8 分 |
| 07:45 | `lan-rtt-degraded` | 101→102 / 102→101 | 3 | **15 分** |
| 07:47 | `wan-rtt-sudden-change` | wan-sinet-tokyo / wan-riken-tsukuba | 108.831 / 110.236 | **17 分（解除後）** |
| 08:00 | `lan-throughput-degraded` | 101→102 | 229 Mbps | **30 分（解除後）** |

**発火が 23 分にわたって階段状に並んだ。** 同じ 1 つの注入に対して、指標ごとに検知の遅れが違う。
そのため **4 種類が同時に Active alerts に並ぶ瞬間は存在しない。**
SS-05a を 6 回撮って確かめた（07:41 は packet-loss のみ、07:48 は lan-rtt + wan-rtt、
08:08 は throughput のみ）。

**記事に足せる論点**: 「Detector は無言で失敗する」（リハーサルの論点）に対して、
**「検知できても、いつ気づくかは指標ごとにバラバラ」**という層が重なる。
運用者が最初のアラートを見た時点で見えている世界は、事象の全体像ではない。

### AI Assistant は「正しく引いてから読み違えた」

**前半と後半で質が違う。** 冒頭のアラート列挙は Incident ID・Detector 名・発生時刻・
観測値・方向まで**完全に正確**だった。誤りはすべて後半の「想定原因」に出た。

| # | 本番の記述 | 実際 | リハーサルとの対応 |
|---|---|---|---|
| 1 | 「**WAN 側の RTT 逸脱が主因**」「`wan-sinet-tokyo` が最も急峻に悪化」 | LAN が 0.81→101.3ms（**126 倍**）で最大の逸脱。WAN は約 12 倍 | 同型（リハーサルは「LAN は安定」） |
| 2 | 「`wan-sinet-tokyo` に紐づく**経路品質の悪化**」「WAN 経路混雑」 | 原因は測定ノード自身の NIC egress。**切り分け方向が逆** | 同型 |
| 3 | 「**`wan-kiren-tsukuba`**」 | 捏造（正しくは `wan-riken-tsukuba`）| 同型だが**綴りが違う**（リハーサルは `wan-rinet-tsukuba`） |

**リハーサルより強い材料が 1 つ増えた。** AI が冒頭で列挙した 4 件は
**すべて `path.id: lan-wired`** である（LAN RTT 劣化 2 件 + パケットロス 2 件）。
WAN の Detector は 1 件も挙げていない。**それなのに結論は「WAN 側が主因」。**
自分が並べた証拠と結論が矛盾している。

これで **AI の失敗が 3 類型そろった。**

| 類型 | 事例 | 何が原因か |
|---|---|---|
| 指標側の欠陥をそのまま反映 | Step 28（ratio が回復に見える） | **指標が壊れていた** |
| 正しい指標を読み違えた | Step 30（リハーサル） | **読解が壊れていた** |
| **正しく引いた証拠と矛盾する結論を出した** | **Step 33（本番）** | **推論が壊れていた** |

**「AI が間違えた」で片付けると、この 3 つは区別できない。**

回答全文は `docs/article/images/provisional/SS-07-ai-assistant-2026-08-09 7.46.06.md`。

### スループットの方向非対称は再現しなかった（測定間隔の問題）

| 方向 | 実測時刻 | 値 | 注入区間との関係 |
|---|---|---|---|
| 102→101（**データ**が netem を通る） | **07:29** | 941 Mbps | 注入開始 07:29:44 の**直前**。影響なし |
| 101→102（**ACK** が netem を通る） | **07:45** | 229 Mbps | 解除 07:45:38 と重なる。**部分的にしか効いていない** |
| 102→101 | 08:01 | 941 Mbps | 解除後 |

`iperf3` は約 30 分間隔（06:57 → 07:29 → 08:01）で、**16 分の注入ではどちらの方向も
区間中央を捉えられない。** リハーサルが 723 倍差（941 → 1.3 Mbps）を出せたのは
05:30 の測定がたまたま注入のど真ん中に入ったからで、**再現性が無かった。**

**本番値は 941 → 229 Mbps（4.1 倍）。** 追加注入（30 分以上）で再現は可能だが、
実施しない判断をした。理由は 3 つ。

1. 方向非対称の主張は**片道遅延の欠測（SS-02b）が本命**で、スループットは補強材料。
   SS-02b は今回きれいに撮れている
2. 941 vs 229 でも方向性は出ている
3. 他の図版はすべて 07:00〜08:16 レンジで撮影済み。**スループットだけ別時刻になると整合が崩れる**

**記事は「720 倍」を使わず 4.1 倍に更新する。** 測定間隔の制約は注記で説明する。
なお 5 分解像度では実測時刻が丸められて見えるので、
**この切り分けには `RESOLUTION_MS=60000` が要る**（既定 300000 では 07:29 が 07:30 に見える）。

### 図版の品質

SS-01〜08 を 07:00〜08:16 の絶対レンジで取得。`docs/article/images/provisional/` に保存。

- **SS-02b が主題どおりに撮れた。** 注入区間で緑（192.168.1.102 発 = 注入方向）の棒だけが消え、
  灰色（192.168.1.101 発）は残り続けている。**欠測が方向を持つ**ことがそのまま読める
- **SS-01b で watermark ラベルが重なっている。** `+50%` と `ベースライン (1.0)` が近接し、
  左端で重なる。読めないほどではないがキービジュアルなので記録しておく
- `alerts.png` には **07:48:48 のショットを使う**。LAN と WAN が同時に発火しており
  severity も 2 段階写る

## Step 34: 発火が割れた原因を特定。Detector は窓内の「最小値」で判定していた

- 日付: 2026-08-09 14:00〜15:10

Step 33 で「5 経路すべてが 4σ 閾値を 10 倍以上超えたのに 2 経路しか発火しなかった。原因は未解明」と
書いた件を追い切った。**原因は特定できた。記事に断定で書ける。**

### 発端: 測定間隔が経路ごとに違うという指摘

ユーザーが WAN RTT チャートを見て「学術機関の 2 経路だけ測定間隔が違うのではないか」と指摘した。
pSConfig のタスク定義（一次情報）で裏を取ったところ、そのとおりだった。

| 経路 | tool | interval | slip |
|---|---|---|---|
| `wan-riken-tsukuba` / `wan-sinet-tokyo` | twping | **PT15M** | PT3M |
| `wan-google` / `wan-cloudflare` / `wan-blog` | ping | **PT5M** | PT2M |
| （traceroute / iperf3） | — | PT30M | PT5M |

**発火した 2 経路が 15 分間隔、発火しなかった 3 経路が 5 分間隔で、完全に一致した。**

pscheduler の実行記録で、注入区間（UTC 22:29:44〜22:45:38）に実際に走った測定を特定した。

| 経路 | 注入区間内の実行時刻 | 回数 | 発火 |
|---|---|---|---|
| `wan-sinet-tokyo` | 22:42:43 | **1 回** | ○ |
| `wan-riken-tsukuba` | 22:43:21 | **1 回** | ○ |
| `wan-google` | 22:33:10 / 22:37:58 / 22:42:51 | **3 回** | × |
| `wan-cloudflare` | 22:32:51 / 22:37:21 / 22:43:09 | **3 回** | × |
| `wan-blog` | 22:32:08 / 22:37:01 / 22:42:56 | **3 回** | × |

**密に測っていた 3 経路が鳴らず、注入中に 1 点しか取れなかった 2 経路が鳴った。**

### 外れた仮説（記録として残す）

当初「注入中のデータが `historical_window` に流れ込んで σ を押し上げ、閾値が跳ね上がった」
という自己汚染仮説を立てた。**これは誤りである。**

`against_recent.detector_mean_std` の実装（SignalFx が `signalfx/signalflow-library` で公開）では、
`historical_window` は `current_window` 分だけ `timeshift` したストリームに対して計算される。
**両者は隣接していて重ならない。**

- 判定 22:47:40 → current: [22:27:40, 22:47:40] / historical: [18:27:40, 22:27:40]
- **注入開始 22:29:44 は historical 窓の終端 22:27:40 より後**。汚染されようがない

粗い計算で twping 側の数値が合わなかったのは精度の問題ではなく、**モデルの立て方自体が違っていた**サインだった。

### 実際のメカニズム: 発火条件は平均ではなく「最小値」

`against_recent.flow` は `streams.recent_extrema` を呼び、`orientation='above'` の発火条件は
**`recent_min > f_top`** である。

```
recent_min = stream.min(over=current_window)
```

**`current_window` の平均ではなく最小値で判定している。つまり窓の中の全点が異常でなければ発火しない。**

| 間隔 | 20 分窓に入る点数 | 注入 16 分との関係 | min の挙動 |
|---|---|---|---|
| **5 分** | 常に約 4 点 | **窓の中に必ず正常点が残る** | 平常値に張り付いたまま |
| **15 分** | 1〜2 点 | 注入中の 1 点だけが窓を占める時間が約 10 分できる | 108ms へ跳ねる |

### 実測による裏付け

`min(over='20m')` を 5 経路で描かせた（`RESOLUTION_MS=60000`、07:00〜08:15 JST）。

| 経路 | 間隔 | 07:00〜07:45 | **07:50 / 07:55** | 08:00 以降 | 発火 |
|---|---|---|---|---|---|
| `wan-sinet-tokyo` | 15分 | 8.18〜8.45 | **108.831** | 8.196 | ○ |
| `wan-riken-tsukuba` | 15分 | 9.82〜10.04 | **110.236** | 9.998 | ○ |
| `wan-google` | 5分 | 8.05〜8.38 | 8.384 / 8.198 | 8.109 | × |
| `wan-cloudflare` | 5分 | 8.39〜9.15 | 8.876 / 9.431 | 9.161 | × |
| `wan-blog` | 5分 | 8.72〜8.86 | 8.876 / 8.78 | 8.78 | × |

**生値は 5 経路とも 108〜110ms に上がっていたのに、`min(over='20m')` は 5 分間隔の 3 経路で
一度も跳ねなかった。** 15 分間隔の 2 経路だけが跳ね、その時刻は発火 07:47:40 と整合する。

### 記事にとっての意味: 1 章と 2 章が同じ弱点の裏表になる

| 章 | 窓の壊れ方 | 汚染される統計量 |
|---|---|---|
| 1 章（指標） | 窓が**長すぎる**と、異常が窓を占有し尽くして平常に飲み込まれる | `median(over='24h')` |
| 2 章（検知） | 窓に**正常値が混入する**と、異常と判定されない | `min(over='20m')` |

**同じ移動窓という道具が、窓長・イベント継続時間・サンプリング間隔の関係次第で
正反対の壊れ方をする。**

リハーサル（Step 30）の「Cloudflare 汚染を受けた経路が鳴らなかった」は**偶然の外部要因に依存した観測**
だった。本番で得たこちらは**設計に内在する構造**であり、一般性が高い。しかも SignalFx の
公開実装で裏が取れているので**断定して書ける**。

### 教訓（運用に残す）

- **Detector の閾値だけ見ても発火条件は分からない。** `against_recent` は窓内の最小値で判定する。
  「閾値を超えたのに鳴らない」は、値ではなく**窓の純度**の問題でありうる
- **サンプリング間隔と検知窓の比が検知能力を決める。** 密に測るほど安心とは限らない。
  `current_window` に対してサンプル間隔が細かいほど、短時間の異常は「窓が異常だけで埋まる」条件を
  満たせなくなる
- **SignalFlow の組み込み Detector は実装が GitHub に公開されている。** 挙動が読めないときは
  `signalfx/signalflow-library` のソースを読むのが速い

## Step 35: 40 分の追試で方向非対称を測り直した。記事の「逆方向は無傷」は誤りだった

- 日付: 2026-08-09 15:09:34〜15:50:02（40 分 28 秒）

### なぜ追試したか

記事のスループット節を本番値に更新しようとして、**記事に誤りがあることに気づいた。**

記事は「逆方向は 940.5 Mbps で無傷」と書いていた。リハーサル（08-08 05:22:20〜05:38:26）の
iperf3 測定時刻を調べると、こうなっていた。

| 方向 | 測定時刻 | 値 | 注入区間との関係 |
|---|---|---|---|
| 102→101（データが netem を通る） | **05:28** | 1.30 Mbps | 区間のど真ん中 |
| 101→102（ACK が netem を通る） | 05:16 | 940.5 Mbps | **注入開始 05:22:20 より前** |
| 101→102 | 05:44 | 941.2 Mbps | 解除 05:38:26 より後 |

**「逆方向の注入中の値」として書いていた 940.5 Mbps は、注入が始まる 6 分前の測定だった。**
リハーサルでは逆方向の測定が注入区間に一度も入っていない。

本番（08-09 07:29:44〜07:45:38）は逆で、逆方向だけが区間内に入り 229 Mbps を記録した。
**2 回とも片方向しか捉えられておらず、「方向によって 720 倍の差」は成立しない。**

iperf3 は約 30 分間隔で、2 方向が約 15 分ずれて交互に走る（`PT30M` / slip `PT5M`）。
**16 分の注入では、構造上どちらか一方しか区間に入らない。**

### 実施記録

測定サイクルを読んでから開始時刻を決めた（当日 13:00〜15:00 の実測）。

- 101→102: 13:14 → 13:46 → 14:12 → 14:42（次は約 15:12）
- 102→101: 13:28 → 13:58 → 14:29 → 15:02（次は約 15:33）

40 分注入なら slip ±5 分を見ても両方向が確実に入る。

| 項目 | 値 |
|---|---|
| 注入開始 | **2026-08-09T15:09:34+09:00** |
| 注入解除 | **2026-08-09T15:50:02+09:00** |
| 注入時間 | **40 分 28 秒** |
| パラメータ | `netem delay 100ms loss 3%` / `enxa0cec8fe0854` egress |
| デッドマン | 2700 秒で武装（15:54:28）。正常解除が先行し**未発動** |
| 解除後 qdisc | `fq_codel`（正常復帰） |
| chrony | System time 19.4µs slow / Skew 0.061ppm |
| 裏取り ping | LG Gram 101.694ms / RasPi 0.586ms（無変化） |

### 結果: 両方向とも落ちる。ただし 210 倍違う

**狙いどおり両方向が注入区間に入った。**

| 方向 | 測定時刻 | 平常 | 注入中 | 低下 |
|---|---|---|---|---|
| 102→101（**バルクデータ**が netem を通る） | **15:30** | 941.4 Mbps | **1.10 Mbps** | **860 倍** |
| 101→102（**確認応答**だけが netem を通る） | **15:12** | 940.9 Mbps | **230.0 Mbps** | **4.1 倍** |

- **注入方向の 1.10 Mbps は、リハーサルの 1.30 Mbps とほぼ一致した。** 40 分に延ばしても同じ値に
  落ちるので、この数字には再現性がある
- **逆方向は無傷ではなかった。** 230.0 Mbps まで落ちる。確認応答が 100ms 遅れれば、
  送信側は次を送る判断をその分待たされる。3% のロスは累積確認応答にかなり吸収されるが、
  遅延の影響までは消えない
- **方向差は 210 倍**（230.0 / 1.10）

記事は「720 倍」を「**210 倍**」に訂正し、「逆方向は無傷」を「4 分の 1 まで落ちる」に直した。

### 教訓（記事にも書いた）

**測定間隔より短い現象は、測定間隔が決める窓からこぼれる。**

Step 34 の Detector の話（20 分窓 vs 5 分間隔）と同じ構造が、ここでも出た。
あちらは「窓に正常値が混ざって検知が漏れる」、こちらは「測定が区間に入らず現象を取りこぼす」。
**どちらもサンプリング間隔とイベント継続時間の関係が、見えるものを決めている。**

危なかったのは、**取りこぼしが「無傷」という誤った結論として読めてしまう**ことである。
欠測なら気づくが、区間外の正常値は正常値として表示される。
Step 32 の「測定が止まっているのにベースラインだけ平常値を返す」と同じ危険である。

### 副作用の記録

40 分注入なので 24 時間ベースラインに 40 分ぶんの異常データが入った（40/1440 = 2.8%）。
`median(over='24h')` への影響は小さいが、しばらく `base_24h_ms` がわずかに上振れする。
**撮影済みの図版はすべて 07:00〜08:16 レンジなので影響しない。**

## Step 36: 記事を公開し、コンテストに応募した。Phase 4 完了

- 日付: 2026-08-10

Zenn 記事『自宅ネットワークでSLOを運用中、壊れたのはネットワークではなく指標だった』を
公開し、Splunk Observability 部門へ応募した（締切 2026-08-10）。

### 本番注入をやった意味

Phase 4 の当初の目的は**図版の撮り直しだけ**だった（CLAUDE.md の引き継ぎ）。
「主張そのものはリハーサルで確定しており変わらない」という前提で始めた。
**その前提は 2 つとも崩れた。**

| 発見 | リハーサルのままなら |
|---|---|
| **検知章の因果が成立しない**（Step 34） | 「ベースライン汚染が検知を殺した」という**誤った因果**を公開していた |
| **「逆方向は無傷」が誤り**（Step 35） | 注入前の測定値を「注入中の値」として提示したままだった |

どちらも**リハーサルのデータだけでは気づけなかった。** 本番で条件を変えて撃ち直したこと、
そして数値を更新しようとして測定時刻まで遡って確かめたことで表に出た。

**結果として記事は当初案より強くなった。** 「汚染が検知を殺す」（偶然の外部要因に依存）が
「窓の純度が検知を殺す」（設計に内在し、SignalFx の公開実装で裏が取れる）に置き換わり、
1 章（指標）と 2 章（検知）が**同じ移動窓の裏表**として繋がった。

### 記事に入った本番由来の要素

- 注入 07:29:44〜07:45:38（15分54秒）、RTT 表、片道遅延の欠測 3 点、クロック誤差
- `recent_min` のメカニズムと `min(over='20m')` の実測表（5 経路）
- スループット 860 倍 / 4.1 倍 / 方向差 210 倍（40 分の追試で取得）
- 4 Detector の階段状発火（23 分）
- AI Assistant の 3 類型目（正しく引いた証拠と矛盾する結論）
- インフォグラフィック 2 枚（3 指標の対比 / 移動窓の 2 方向の壊れ方）

### 積み残し（急がない）

- `docs/article/images/provisional/` のファイル名にスペースが残っている
  （macOS スクショの既定命名）。runbook Step 6 の規約は
  `raw/` に `ss-<連番>-<略称>-<内容>.png`。**公開を優先して後回しにした**
- 40 分の追試により 24h ベースラインに 40 分ぶんの異常データが入っている（2.8%）。
  08-10 中に窓から抜ける
