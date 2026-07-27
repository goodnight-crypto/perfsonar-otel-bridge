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

## Step 3: 手動疎通テスト（twamp / rtt / trace / throughput）
- 日付: 2026-07-26
- やったこと: VM側testpointコンテナから4種すべてを実行。throughput(iperf3)はCLAUDE.md規約により実行前にユーザーへ確認した上で日中に手動実行（規約上「スケジュール実行」を深夜帯に限定しており、確認済みの手動実行は対象外という運用で対応）
- ハマりポイント①: runbook-w1.mdに書いていた `pscheduler task twamp ...` は**存在しないテスト名でエラー**（`Could not find test twamp on server`）。pSchedulerには独立した"twamp"テストは無く、**"latency"テストの `--protocol=twamp` オプション**として実装されている（`pscheduler-test-latency`パッケージ）。runbook-w1.mdのコマンド例を `pscheduler task latency --protocol=twamp --source <vm-ip> --dest <raspi-ip>` に修正済み
- ハマりポイント②: throughputの1回目実行は `Run did not complete: Missed` で失敗。2回目（コマンドをそのまま再実行）は成功。原因未特定だが、タスク登録直後のスケジューリング窓に間に合わなかった一過性の事象と推測（記事では「初回missedは再実行で解消するケースがある」注意点として触れる）
- 結果:
  - **latency(twamp) VM→RasPi**: 100パケット送信、ロス0%、重複/順序入れ替えなし。One-way Delay: 中央値0.67ms / 最小0.37ms / 最大0.95ms / 標準偏差0.10ms。Max Clock Error 0.0ms
  - **latency(twamp) RasPi→VM（逆方向）**: 100パケット送信、ロス0%だが One-way Delay が**中央値-4.62ms / 最小-23.92ms / 最大2.49ms / 分散31.46ms**と大きく負に振れ、ジッタも異常に大きい。Max Clock Errorは0.0msと報告されるが実態と矛盾
  - **rtt → 8091.info**: 0% loss, RTT mean 9.71ms（Cloudflare 104.21.24.217へ解決）
  - **rtt → 1.1.1.1**: 0% loss, RTT mean 9.16ms
  - **trace → 1.1.1.1**: hop1でISP機器 `ntt.setup`(192.168.1.1, 1.5ms) → hop2-5は応答なし(ISPコア機器のICMPフィルタと推測) → hop6以降Cloudflare網に到達、hop9(1.1.1.1)で17.7ms
  - **throughput(iperf3) VM→RasPi**: 平均929.30Mbps（受信側939.84Mbps）、再送7回/10秒
  - **throughput(iperf3) RasPi→VM（逆方向）**: 平均941.81Mbps（受信側926.61Mbps）、再送0回。往路より安定
- 判断・回避策①: **PROJECT.mdの測定マトリクスにある「RasPiのARM上限(~300Mbps)」という想定は誤り**。この~300Mbpsという数値はRaspberry Pi 3系やUSB接続イーサネットアダプタでの制約であり、Raspberry Pi 4BはGbE NICがUSBではなくPCIe直結のため理論値(940Mbps)近くまで出る。双方向とも同水準。**記事ネタ**: 「事前の想定と実測が食い違った」好例として使える。PROJECT.md訂正済み
- 判断・回避策②（要フォローアップ、原因判明・恒久対処は未実施）: **twampは"クロック非依存"という理解は不正確だった**。パケットロス数・往復の疎通確認自体はクロックに依存しないが、one-way delayの内訳（片道遅延）はTWAMPでも両端の時計同期に依存する。当初RasPi側を疑ったが、実際に調査すると原因は**VM(Lima)側**だった:
  - RasPi: `timedatectl timesync-status` で offset -488μs、jitter 1.1ms、7時間安定同期（chronyc未導入・systemd-timesyncd使用、問題なし）
  - VM: `timedatectl timesync-status` で **offset +216.602ms**、`Frequency: +500.000ppm`（systemd-timesyncdの最大スルーレート）に張り付いたまま1時間21分経過しても収束せず。ホストMacとVMの時刻を直接比較しても150-200ms程度のズレを実測で確認
  - 検証のためVM内の`systemd-timesyncd`を停止 → 直後の逆方向twampは**-173.82ms（ジッタは小さく安定）**という結果に。ジッタは消えたが恒常的な大オフセットが露呈。これは「稼働中のtimesyncdが収束しきれない大きなドリフトと戦い続けて不安定な補正結果を出していた」ことを示唆（timesyncd停止後はどの補正もかからず素のクロック誤差がそのまま出た）
  - `systemd-timesyncd`を元に戻して終了（暫定措置。恒久対処は未実施）
  - **仮説**: Lima(vzドライバ)配下のゲストクロックは、起動時に一度だけホストと同期される(hostagentログの"Time sync: guest clock adjusted"）が、その後の継続的なドリフト補正が systemd-timesyncd の最大スルーレート(500ppm ≒ 174msの補正に約6分)を上回るペースで発生している可能性がある。Mac自体のスリープ・CPU出力制御等でVMプロセスが一時的にスケジューリングされない時間帯が影響しているかもしれない
  - **記事ネタ**: 「twampを使えばクロック同期を気にしなくていい」という安易な理解は誤りで、実際には計測環境（特に仮想化ゲスト）のクロック品質を検証する必要があるという教訓

### 追加調査（2026-07-26夜）: 真因はホストMac自体の時刻誤差だった
- VMにchronyを導入（`makestep 0.1 -1`：閾値100ms・無制限にステップ補正）して再検証したところ、chronyc trackingの`Frequency`が`+500.000ppm`（timesyncdの上限に張り付き）ではなく、より大きな値で安定し始めた。これはVM自体の時計品質というより**参照点（ホスト）がそもそもズレている**ことを疑うきっかけになった
- `sntp time.apple.com` でホストMacの時刻を直接検証 → **ホストMacが実際のNTP時刻より約+249ms遅れていた**（`+0.249446 +/- 0.009221`）。Network Timeは「オン」設定だったにもかかわらず実際には大きくズレていた
- `sudo sntp -sS time.apple.com` でホストを強制再同期 → 誤差は249ms→約14ms（`-0.013550 +/- 0.009482`）まで改善
- ホスト補正後、VM側chronyの`System time`も0.023秒（23ms）まで収束、`Skew`も1,000,000ppm(未収束)→43.566ppmまで改善。ただし`Frequency`は**10061.376ppm**（約1%）という非常に大きな値で安定 — 実ハードウェアの水晶発振子ドリフト(通常<100ppm)としては異常な大きさで、vzハイパーバイザー配下のゲストクロックそのものの周波数精度に構造的な問題がある可能性を示唆
- ホスト補正後の逆方向twamp再テスト: One-way Delay 中央値**+103.37ms**（範囲72.38〜150.19ms）。-216msからは大幅改善したが、まだLAN内としては異常に大きく、ジッタも約78msの幅がある
- **現状のまとめ**: (1)ホストMacの時刻ズレ(249ms)が根本原因の大部分 → 解消済み。(2)VM(Lima/vz)ゲスト自体のクロック周波数精度が非常に悪い(1%規模)という別問題が残存 → chronyの補正が収束しきるまで時間がかかる、または vz 特有の制約の可能性があり未解決
- **要対応(W2までに、優先度順)**:
  1. chronyをこのまま数十分〜数時間稼働させ、Skew/Frequencyがさらに収束するか再確認（`chronyc tracking`で`Skew`が一桁ppmまで下がるか）
  2. 収束しない場合、vzドライバ特有の既知issueがないかLima GitHub issueで確認
  3. 最終手段として、one-way delay精度が必要な計測はVMを経由しない構成（RasPi同士、または将来的にネイティブLinux機）に絞ることも検討
  - ロス率・スループットの定点観測には影響しないため、W1のExit Criteria自体はブロックしない

### 結論（2026-07-27）: 恒久対処は諦め、データ品質ゲートで運用する方針に決定
- `codex:rescue`でセカンドオピニオンを取得。要旨: 「vzやP/Eコア固有の既知障害というより、Limaのホストエージェントが10秒周期でゲストへ時刻を送りsettimeofdayする機構とchronydの補正が競合している可能性が高い。10061ppmという値は実クロックのドリフトというより、外部からの断続的なステップ補正を追いかけた結果の見かけ上の推定値。Lima側にこの同期を無効化する設定項目は無い。TWAMP片道遅延の精度が必要なら仮想化を介さない裸のLinux同士を推奨」
- 対応コストと記事のスコープ（差別化要素はmacOSでのperfSONAR構築知見・tc netem障害注入デモであり、one-way delayのサブms精度ではない）を踏まえ、**VM(Lima)のクロック精度そのものを直す恒久対処は行わないと決定**
- 代わりに、pSchedulerのtwamp(latency)テストの生JSON構造を確認したところ判明した重要な事実: **このテストにRTTフィールドは存在せず、one-way delay(`histogram-latency`)が主指標**。つまり「ズレを許容する」は「one-way delay自体を実質使えなくする」に近い。ただし生JSONには`max-clock-error`フィールド（TWAMPプロトコルが両端のクロック誤差見積もりを埋め込む仕組み）があり、これをデータ品質ゲートとして使える
- **採用した設計**（PROJECT.mdのメトリクススキーマ節に反映済み）:
  1. RTTは`rtt`テスト（ICMPベース、クロック非依存）由来の値を正とする。ロス率・スループットと合わせてSLOダッシュボードの主軸はこの3指標
  2. twamp(latency)のone-way delayは補助指標とし、ブリッジ(W2)で`max-clock-error`を見て閾値超過時は欠測扱い/品質フラグ付き出力にする
  3. VMが絡まないパス（RasPi有線↔無線、実装する場合）は両端クロック良好のためone-way delayも信頼できる区別として扱う
- **記事ネタ**: 「厳密さを追求して仮想化環境の限界にぶつかり、指標自体を諦めるのではなくデータ品質ゲートを設計して現実的に折り合いをつけた」というエンジニアリング判断の実例として使える
