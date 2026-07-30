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

#### 未確認（要実測）

`ethtool` のフル出力で `Supported link modes` を見ていない。**1000baseT が
サポートに含まれていれば、アダプタは GbE でケーブルかスイッチポート側の問題**という
可能性が残る。切り分けてから NIC の買い足しを確定させる。
