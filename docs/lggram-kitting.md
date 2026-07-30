# LG Gram 13Z970 キッティング手順書（Windows 10 → Ubuntu）

対象: LG Gram 13Z970 — perfSONAR testpoint #1（**Lima VM の置き換え**）
実行主体: **ユーザー**（物理作業・BIOS 操作・OS インストール）。完了後の Docker / testpoint / 時刻源の設定は Claude Code が SSH 経由で実施する。
終端: **Mac から鍵認証で SSH ログインできる**状態。そこから `docs/runbook-w1.md` Step 1 に合流する。

## なぜ入れ替えるのか

Lima のホストエージェントがゲストのクロックを約68秒に1回、drift 中央値 123ms で強制上書きしており、
TWAMP の片道遅延が測定不能になっている。Lima 2.2.0 に無効化する設定は無く、設計意図どおりの動作なので、
**測定ノードを Lima の外に出す**しかない。経緯は `deploy/vm/README.md`「これで直るのは2つのうち1つだけ」を参照。

RTT・ロス率・スループット・ホップ数はクロック非依存のため、現在のパイプラインは正しく動いている。
この入れ替えで取り戻すのは**片道遅延だけ**である。

### 受け入れる制約

LG Gram は RJ45 を内蔵せず、USB Ethernet アダプタを使う。USB NIC はハードウェアタイムスタンプに
対応しないのが通例で、その分だけ精度が落ちる。記事執筆用データの短期収集が目的なので許容する。
**Step E-4 で実測値を記録し、「bare metal でも USB NIC ではここが限界」という材料にする。**

## 準備するもの

- LG Gram 13Z970 本体と AC アダプタ（**常時給電で運用するため必須**）
- USB メモリ 4GB 以上 1本。**インストーラ書き込み時に中身が消える**ため、必要なデータがないか事前確認
- USB Ethernet アダプタ（手持ちのもの）と LAN ケーブル
- ルーター/スイッチの空きポート。RasPi と**同一 LAN セグメント**であること
- Mac（ISO のダウンロードと USB メモリへの書き込み）

## Step A: 事前確認と退避【Windows 上で実施】

全消去するため、後から Windows 側のデータは取り出せない。

- **A-1** Windows に残したいファイルが無いか確認し、あれば外部ストレージへ退避する
- **A-2** バッテリーの状態を目視で確認する。2017年発売の機体なので膨張の可能性がある

  次のいずれかに当てはまるときは**作業を中止してユーザー判断を仰ぐ**。膨張したリチウムイオン電池は
  発火の危険がある。
  - タッチパッドやキーボードが下から押し上げられて浮いている
  - 底面が平らな机の上でがたつく
  - 蓋が最後まで閉じない

- **A-3** 現在の構成を控える。BIOS バージョンとストレージの型番は、後で問題が出たときの切り分けに使う

  ```
  msinfo32
  ```

  「BIOS バージョン/日付」と「システムモデル」の2行をメモしておく。

## Step B: インストール USB の作成【Mac 上で実施】

### B-1 ISO のダウンロード

<https://ubuntu.com/download/server> から **Ubuntu Server 24.04 LTS (amd64)** を取得する。
ページ内の「Option 2 - Manual server installation」のリンクが該当する。

24.04 を選ぶ理由は2つある。

1. Lima VM と同じ系統なので、`deploy/vm/chrony-home-lab.conf` をそのまま流用できる
2. LTS であり、短期運用中に予期しない仕様変更を踏まない

**ダウンロードしたファイル名（point release の番号を含む）を控えておく。**
後で `experiments/` に記録し、記事の再現性の根拠にする。

### B-2 チェックサムの照合

```bash
shasum -a 256 ~/Downloads/ubuntu-24.04.*-live-server-amd64.iso
```

ダウンロードページの `SHA256SUMS` に載っている値と一致することを確認する。

### B-3 USB メモリへの書き込み

**この手順で最も危険なのはディスク番号の取り違えである。** 誤ると Mac 側のディスクを破壊する。

```bash
# 1. USB メモリを挿す前に一度実行し、出力を控える
diskutil list

# 2. USB メモリを挿してもう一度実行し、増えた行が対象
diskutil list
```

増えた行の `IDENTIFIER`（例: `disk4`）と `SIZE` が USB メモリの容量と一致することを確認する。
**内蔵ディスクは `disk0` / `disk1` なので、この番号が出たら手を止める。**

```bash
# 3. アンマウント（取り出しではない）
diskutil unmountDisk /dev/disk4

# 4. 書き込み。of= は r 付きの rdisk を指定するとおよそ10倍速い
#    if= は B-1 で実際にダウンロードしたファイル名に置き換える
sudo dd if=~/Downloads/ubuntu-24.04.X-live-server-amd64.iso of=/dev/rdisk4 bs=4m

# 5. 完了後に取り出す
diskutil eject /dev/disk4
```

- 進捗は無表示のまま数分かかる。`Ctrl+T` を押すと途中経過が1行出る
- 書き込み後に「セットしたディスクは、このコンピュータで読み取れないディスクでした」と出るのは正常。
  **「初期化」を押さずに「無視」を選ぶ**

## Step C: BIOS 設定

### C-1 BIOS に入る

起動時の `F2` 連打でも入れるが、キー入力のタイミングに賭けたくないので Windows 側から入る。

「設定 → 更新とセキュリティ → 回復 → PC の起動をカスタマイズ → 今すぐ再起動」
→ 「トラブルシューティング → 詳細オプション → UEFI ファームウェアの設定 → 再起動」

### C-2 変更する項目

| 項目 | 設定値 | 理由 |
|---|---|---|
| Secure Boot | **無効** | 有効のままでもインストールはできるが、サードパーティドライバや DKMS の導入で詰まる余地を残さない |
| SATA / ストレージ動作モード | **AHCI** | **最重要。** RAID や Intel RST になっていると Ubuntu インストーラから SSD が見えない |
| Fast Boot | 無効 | USB メモリを起動デバイスとして拾わせるため |
| Boot order | USB を内蔵ディスクより上に | — |

**SATA モードを RAID から AHCI に変えると Windows は起動しなくなる。** 全消去するので問題ないが、
Step A のデータ退避が終わっていることを先に確認する。

> この機種で最も多い詰まり方が「インストーラの Storage 画面にディスクが1台も出ない」である。
> 原因はほぼ SATA モードなので、C-2 を飛ばさない。

### C-3 USB から起動

設定を保存して再起動し、`F10` で起動デバイスの選択画面を出して USB メモリを選ぶ。
`F10` で出ないときは BIOS の Boot order で USB を最優先にして再起動する。

## Step D: Ubuntu Server のインストール

対話式インストーラを上から順に進める。判断が要る画面だけ挙げる。

| 画面 | 選択 | 理由 |
|---|---|---|
| Language | **English** | エラーメッセージをそのまま検索できる |
| Keyboard | **Japanese** | 物理キーボードに合わせる |
| Type of install | Ubuntu Server（Minimized ではない） | Minimized は後から入れ直す手間が増える |
| Network | USB NIC が `enx` で始まる名前で見え、DHCP で IP が取れること | **ここで NIC が見えなければ先に進まない**。別ポートに挿し替えて再試行する |
| Storage | **Use an entire disk**。LVM は使わない。**暗号化は選ばない** | 暗号化すると起動のたびにパスフレーズ入力が必要になり、無人再起動ができなくなる |
| Profile | ユーザー名 `dev` / ホスト名 `lggram-testpoint` | ユーザー名を VM と揃えると、既存の手順やメモがそのまま通る |
| SSH Setup | **Install OpenSSH server にチェック** | 必須。ここを忘れると本体キーボードでの作業に戻ることになる |
| Snaps | **何も選ばない** | 測定ノードに不要な常駐を増やさない |

SSH 公開鍵は「Import SSH identity」を使わず、Step E-1 で Mac 側から配置する。

インストール完了後、**USB メモリを抜いてから**再起動する。

> **蓋を開けたままにしておくこと。** 既定では蓋を閉じるとサスペンドし、SSH が切れる。
> Step E-2 を終えるまで閉じない。

## Step E: ラップトップ固有の後始末

E-1 だけ Mac から実施する。E-2 以降は本体のコンソールでも SSH 経由でも実施できる。

### E-1 SSH 鍵の配置【Mac 上で実施】

再起動後の画面に表示される IP アドレス、または本体で `ip -4 addr` を実行して IP を確認する。

```bash
ssh-copy-id dev@<IPアドレス>
ssh dev@<IPアドレス>
```

**チェックポイント**: パスワードなしで SSH ログインできる。

> **`lggram-testpoint.local` は引けない。** RasPi と違い、Ubuntu Server は `avahi-daemon` を
> 既定で導入しないため mDNS が動かない。IP で接続するか、`sudo apt install -y avahi-daemon` を
> 入れて RasPi と揃える。Step F で IP を固定するので、入れなくても運用はできる。

### E-2 蓋を閉じてもサスペンドしない

```bash
sudo sed -i 's/^#*HandleLidSwitch=.*/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
sudo sed -i 's/^#*HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
```

### E-3 サスペンド・ハイバネート自体の無効化

蓋の設定だけでは、アイドル時のサスペンドが残る。

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

**チェックポイント**: 蓋を閉じて1分待ち、Mac から SSH でつながり続けている。

### E-4 USB NIC の実力測定

**記事の材料になるので、出力をそのまま `experiments/` に貼れる形で控える。**

```bash
lsusb                                   # チップの型番（RTL8153 / AX88179 など）
ip -br link                             # インターフェース名
sudo ethtool -i <IF名>                  # ドライバ名
sudo ethtool <IF名> | grep -i speed     # 1000Mb/s であること
sudo ethtool -T <IF名>                  # タイムスタンプ対応
```

`ethtool -T` の読み方は次のとおり。

- `hardware-transmit` / `hardware-receive` が出れば NIC 側でタイムスタンプを打てる（期待していない）
- `software-transmit` / `software-receive` だけなら、カーネルがパケットを処理した時刻を使う。
  **USB NIC はこちらになるのが通例で、これが今回受け入れる精度低下の正体である**

### E-5 バッテリー充電上限

満充電での常時給電は膨張を早める。Linux には LG 製ノート向けの `lg-laptop` ドライバがあり、
対応していれば充電上限を 80% に設定できる。

```bash
ls /sys/devices/platform/lg-laptop/
```

`battery_care_limit` があれば設定する。

```bash
cat /sys/devices/platform/lg-laptop/battery_care_limit    # 現在値（80 か 100）
echo 80 | sudo tee /sys/devices/platform/lg-laptop/battery_care_limit
```

再起動で戻るため、恒久化する。

```bash
echo 'w /sys/devices/platform/lg-laptop/battery_care_limit - - - - 80' \
  | sudo tee /etc/tmpfiles.d/lg-battery.conf
```

**この機種でドライバが有効になるかは実機で確認するまで分からない。**
ディレクトリごと存在しなければ設定を諦め、AC 常時接続のまま運用する。
その場合は Step A-2 の目視確認を運用中も週1回程度続ける。**結果はどちらでも記録する。**

## Step F: IP アドレスの確定【ユーザー作業】

RasPi と同じく、ルーターの DHCP 予約で固定する。

- **F-1** USB NIC の MAC アドレスを控える

  ```bash
  ip -br link
  ```

- **F-2** ルーターの管理画面で、その MAC に固定 IP を予約する

  ※ CLAUDE.md の規約により、ルーター側の設定変更は Claude Code のスコープ外。**ユーザーが実施する**

- **F-3** リースを取り直して確認する

  ```bash
  sudo systemctl restart systemd-networkd
  ip -4 addr
  ```

  予約した IP に変わらないときは再起動する。ルーターによっては古いリースの期限切れまで
  反映しないことがある。

- **F-4** **確定した IP を Claude Code に伝える。** `deploy/psconfig/home-lab-mesh.json` の
  `addresses` と CLAUDE.md の環境インベントリを Claude 側で書き換える

> **USB NIC を別のアダプタに差し替えると MAC が変わり、予約が外れる。** 差し替えたら F-1 からやり直す。
> Ubuntu Server は NetworkManager ではなく netplan + systemd-networkd を使うため、
> RasPi 手順書にある `nmcli` は通用しない。静的 IP にするなら `/etc/netplan/` を編集する。

## Step G: runbook-w1 Step 1 へ合流

ここから先は Claude Code が SSH 経由で実施する。`docs/runbook-w1.md` Step 1 の 1-1〜1-6 に相当する。

| 手順 | 内容 | LG Gram での期待値 |
|---|---|---|
| 1-1 | `uname -m` | **`x86_64`**（RasPi と VM は `aarch64`。ここだけ異なる） |
| 1-2 | `stat -fc %T /sys/fs/cgroup/` | `cgroup2fs` |
| 1-3 | Docker 導入 | — |
| — | chrony 導入と `deploy/vm/chrony-home-lab.conf` の配置 | root dispersion 1ms 未満 |
| 1-5 | `deploy/raspi/run-testpoint.sh` で testpoint 起動 | — |
| 1-6 | `pscheduler troubleshoot` | 全項目 OK |

`run-testpoint.sh` の冒頭コメントは前提を `aarch64` と書いているが、実際には amd64 でも動く。
`perfsonar/testpoint` は amd64 が主系のイメージである。

## 切替時の注意

**Lima VM は削除せず、停止のまま残す。**

```bash
limactl stop perfsonar-vm    # delete ではない
```

記事の締切が 2026-08-10 と近く、LG Gram 側で問題が出たときに測定パイプラインごと止まると
立ち往生する。切替は LG Gram で実際にメトリクスが Splunk に着弾してから行う。
ロールバックは `limactl start perfsonar-vm` と `home-lab-mesh.json` の差し戻しで済む。

## つまずきやすいポイント（記事ネタ候補）

- **SATA が RAID / Intel RST モードだとインストーラからディスクが見えない。** ハードウェア故障に
  見えるが BIOS の設定1つ。この機種で最も多い詰まり方
- **USB NIC にハードウェアタイムスタンプが無い。** 「bare metal にすれば片道遅延が測れる」は
  半分しか正しくない。仮想化のクロック上書きは無くなるが、NIC 側の精度は別問題として残る。
  Lima VM との対比で語ると記事の山場になる
- **ラップトップは既定で「蓋を閉じたら寝る」。** サーバ用途との衝突で、RasPi では起きなかった問題
- **Ubuntu Server には avahi-daemon が入っていない。** RasPi 手順書の `.local` がそのままでは通用しない
- **2017年機のバッテリー膨張。** 常時給電の測定ノードとして使ううえで避けて通れない
