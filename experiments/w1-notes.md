# W1 検証メモ

ハマりポイント・判断の記録。記事の一次情報になるため、失敗もそのまま残す。

## テンプレート
- 日付:
- やったこと:
- 結果 / エラー:
- 判断・回避策:

## Step 0: Splunk O11y Free Edition 取得
- 日付: 2026-07-22
- やったこと: Free Edition（14日間トライアルではない方）にサインアップ。Access Tokens 画面で `perfsonar` という名前の INGEST token を発行（scope: INGEST、Permission: Only admins can read、Expiration: 2026-08-21 = デフォルト30日）。realm は `jp0` と確定。`.env` に realm / トークンを記入
- 結果 / エラー: 問題なく完了。Access Tokens 一覧の ID 列（例: `HN04gZrCIFc`）は短い識別子でトークン実体ではない。実トークン値はどの画面にも表示せずスクリーンショット4枚（作成ウィザードのStep1-3 + 一覧画面）はすべて機密情報を含まないことを確認済み
- 判断・回避策: INGEST トークンの有効期限がデフォルト30日（2026-08-21失効）である点に注意。W3執筆・公開までは十分だが、運用を継続する場合は expiration 延長 or 無期限トークンの再発行を検討する

## Step 1: RasPi 準備
- 日付: 2026-07-26
- やったこと: raspi-kitting.md 通りに microSD 再フラッシュ（Raspberry Pi OS Lite 64-bit, Bookworm）→ 有線LAN接続で初回起動 → SSH鍵認証で接続確認 → `run-testpoint.sh` 実行 → `pscheduler troubleshoot` まで通し実行
- 結果 / エラー: 全項目OK（API level 6、clock OK、Ticker/Scheduler/Runner/Archiver OK、idle test正常終了・archiving OK）。エラーなし。troubleshoot出力中 `Checking that host "raspi-testpoint" resolves... 127.0.1.1` という行が出るが、これはDebian系標準の `/etc/hosts` ループバック割当でLAN到達性には無関係（記事で誤解されやすいポイントとしてメモ）
- 判断・回避策: 接続情報は `unpeeled@raspi-testpoint.local`（mDNS）で確定し CLAUDE.md に反映済み。raspi-kitting.md Step C の固定IP化は未実施 — Step 2 の VM 構築時に相互到達性で問題が出れば実施を検討する
- 補足（2026-07-26 Step2作業中に判明）: RasPiのSSHバナーが `OpenSSH_10.0p2 Debian-7+deb13u4` で、raspi-kitting.mdが想定していたBookworm(Debian 12)ではなくDebian 13(trixie)ベースの模様。Raspberry Pi OSイメージがKitting手順書作成時点から更新されたと推測。cgroup v2はtroubleshoot結果からも問題なし、動作に支障はない。**記事ネタ**: Bookworm前提で書いた手順が、実施時点では次のDebianリリースに置き換わっていた — Raspberry Pi Imagerで都度最新を選ぶ場合の再現性の難しさとして触れられる

## Step 2: Mac側 Linux VM (Lima) 構築
- 日付: 2026-07-26
- やったこと: `brew install lima socket_vmnet` → bridged networking構築 → `deploy/mac/lima-testpoint.yaml` 作成 → `limactl start` → Docker/RasPi相互到達性確認
- ハマりポイント①: Homebrew版 `socket_vmnet` は `limactl sudoers` に**明示的に拒否される**（keg-onlyでuser-writableな場所に置かれるため、root所有必須というLima v1.0.0以降のセキュリティ要件を満たさない）。`brew uninstall socket_vmnet` → GitHub本家をclone → `sudo make install.bin` で `/opt/socket_vmnet`（root所有）にソースビルドしてインストールし直した
- ハマりポイント②: `~/.lima/_config/networks.yaml` の `group`（socket_vmnetのsocket-group、v2.2.0でデフォルトが`everyone`→`admin`に変更されたセキュリティ修正）は、direnv的にnetwork単位のフィールドだと誤解しがちだが**実際はトップレベルのフィールド**。network単位に書くと「unknown field "group"」でstrict YAMLエラーになる
- ハマりポイント③: `limactl sudoers` が生成した設定を `sudo install -o root -m 440` でインストールしたところ、`limactl start` が `can't read /private/etc/sudoers.d/lima: permission denied` で失敗。**理由**: `limactl`はsudoersの内容を非特権ユーザーとして直接読み取り「既にインストール済みか」を確認する仕様のため、実行ユーザー（wheel未所属）には440(root:wheelのみ読み取り可)では読めない。`-m 644`（world-readable, root書き込みのみ）に変更して解決。sudoersファイル自体に秘匿情報は無いため644で実害はない
- ハマりポイント④: VM側のDocker導入で、Lima公式の`docker.yaml`テンプレートは**rootless Docker**をセットアップするが、`run-testpoint.sh`は`--net=host`・`--cgroupns host`・`CAP_NET_RAW`を前提にしており、rootless dockerでは`--net=host`が実ホストのネットワーク名前空間を共有しない（rootless dockerd自身の名前空間に閉じる）ため不適合。公式の`docker-rootful.yaml`テンプレート（get.docker.com導入 + systemd socket の `SocketUser` オーバーライドで sudo 不要化）を土台に採用
- ハマりポイント⑤: `base: template:ubuntu-lts` は現在 `_images/ubuntu-26.04` を指す（Lima 2.2.0時点）。runbookの方針「Ubuntu 24.04 arm64」の再現性を保つため `template:_images/ubuntu-24.04` を明示指定
- 結果 / エラー: `limactl start --tty=false --name=perfsonar-vm deploy/mac/lima-testpoint.yaml` で正常起動。VMは2つのIPを持つ: `eth0`(192.168.5.15/24, Lima標準のuser-mode NAT, metric 200) と `lima0`(192.168.1.104/23, socket_vmnet bridged、metric 100 = デフォルトルート)。`docker ps`がsudoなしで実行可能（SocketUserオーバーライド成功）。RasPi(192.168.1.101) ⇔ VM(192.168.1.104) 相互pingで到達性確認（VM→RasPiはIPv6優先で解決されたため`-4`指定でIPv4疎通も別途確認）。`run-testpoint.sh` をVM内で実行（リポジトリがホストと同一パスでマウントされているためscp不要）→ `pscheduler troubleshoot` 全項目OK（RasPiと同じくAPI level 6、idle test含め正常）
- 判断・回避策: CLAUDE.mdのVM接続情報を `limactl shell perfsonar-vm`（内部IP 192.168.1.104, ユーザー dev）に更新。`docker-rootful.yaml`ベースのため、W2以降で`daemon.json`のcontainerd-snapshotter設定等が必要になった場合は追加検討

## Step 3: 手動疎通テスト（twamp / rtt / trace）
- 日付: 2026-07-26
- やったこと: VM側testpointコンテナから3種を実行。iperf3(throughput)はCLAUDE.md規約により深夜〜早朝限定・実行前ユーザー確認が必要なため本ステップでは未実施（別途タイミング調整）
- ハマりポイント: runbook-w1.mdに書いていた `pscheduler task twamp ...` は**存在しないテスト名でエラー**（`Could not find test twamp on server`）。pSchedulerには独立した"twamp"テストは無く、**"latency"テストの `--protocol=twamp` オプション**として実装されている（`pscheduler-test-latency`パッケージ）。runbook-w1.mdのコマンド例を `pscheduler task latency --protocol=twamp --source <vm-ip> --dest <raspi-ip>` に修正済み
- 結果:
  - **latency(twamp) VM→RasPi**: 100パケット送信、ロス0%、重複/順序入れ替えなし。One-way Delay: 中央値0.67ms / 最小0.37ms / 最大0.95ms / 標準偏差0.10ms。Max Clock Error 0.0ms（twampなので両端クロック同期不要という設計通りの結果）
  - **rtt → 8091.info**: 0% loss, RTT mean 9.71ms（Cloudflare 104.21.24.217へ解決）
  - **rtt → 1.1.1.1**: 0% loss, RTT mean 9.16ms
  - **trace → 1.1.1.1**: hop1でISP機器 `ntt.setup`(192.168.1.1, 1.5ms) → hop2-5は応答なし(ISPコア機器のICMPフィルタと推測) → hop6以降Cloudflare網に到達、hop9(1.1.1.1)で17.7ms
- 判断・回避策: twamp/rtt/traceの3種は正常。iperf3(throughput)実行タイミングをユーザーと相談してからStep3完了とする
