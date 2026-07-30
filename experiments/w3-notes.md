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

#### ブロッカー: sudo にパスワードが必要

Docker 導入・chrony 導入・タイムゾーン変更が全て `sudo` を要求し、
Claude Code の SSH（疑似端末なし）からは実行できない。
RasPi は `sudo -n true` が通る（Raspberry Pi OS の既定）ため、これまで問題にならなかった。
LG Gram は Ubuntu Server の既定でパスワードを要求する。**ユーザー判断待ち。**
