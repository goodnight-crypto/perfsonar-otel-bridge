# RasPi キッティング手順書

対象: Raspberry Pi 4B 4GB — perfSONAR testpoint #2（有線）
前提: 長期間電源停止で保管していたため、SDカードの再フラッシュ（最新版 Raspberry Pi OS）からやり直す。
実行主体: **ユーザー**（物理作業・OS書き込み）。完了後、CLAUDE.md の環境インベントリと本手順の結果を反映するのは Claude Code 側。

## 準備するもの

- Raspberry Pi 4B 本体、USB-C電源、有線LANケーブル（ルーター/スイッチの空きポート）
- microSDカード（16GB以上推奨）。**既存カードを再利用する場合は書き込み時に中身が消えるため、必要なデータがないか事前確認**
- microSDカードリーダー（Mac側、USB接続）
- Raspberry Pi Imager（Mac用）

## Step A: OSイメージ書き込み（Mac側作業）

```bash
brew install --cask raspberry-pi-imager
```

1. Raspberry Pi Imager を起動
2. デバイス選択: **Raspberry Pi 4**
3. OS選択: **Raspberry Pi OS Lite (64-bit)**
   - 理由: Bookworm（Debian 12）ベースは cgroup v2 がデフォルト有効。runbook-w1.md Step 1-2 のチェック項目（`cgroup2fs`）を素通しできる
   - 旧 Bullseye ベースは cgroup v1 がデフォルトのため、Docker のコンテナ実行で追加設定が必要になり非推奨
   - GUI 不要（testpoint はヘッドレス運用）のため Lite を選択
4. ストレージ選択: 対象の microSD カード（**誤って別ドライブを選択していないか再確認**。既存データがある場合は上書きされる旨の警告が出る）
5. 詳細設定（歯車アイコン、または `Ctrl+Shift+X`）で事前設定:
   - hostname: `raspi-testpoint`（仮。決定したら CLAUDE.md に反映）
   - SSH を有効化 → **公開鍵認証を選択** → 使用中の公開鍵（例: `~/.ssh/id_ed25519.pub`）を登録。パスワード認証は無効のままでよい
   - ユーザー名 / パスワードを設定（パスワードは緊急時のコンソールログイン用。通常運用は鍵認証）
   - ロケール: `Asia/Tokyo`、キーボードレイアウト: `jp`
   - Wi-Fi設定は**スキップ**（有線運用のため設定不要。誤って自宅Wi-Fiのパスワードをイメージに焼き込まないよう注意）
6. 書き込み実行 → ベリファイ完了まで待機

## Step B: 初回起動

1. SDカードをRasPiに挿入
2. 有線LANケーブルをルーター/スイッチに接続（VMとのLANブリッジ到達性が要件のため、必ず同一LANセグメント）
3. 電源投入。初回起動は1〜2分程度
4. 疎通確認:
   ```bash
   ping raspi-testpoint.local
   ```
   mDNS (`.local`) が自宅ネットワーク環境で解決できない場合は、ルーターの管理画面（DHCPクライアント一覧）からホスト名 `raspi-testpoint` を検索してIPを確認する
5. SSH接続確認:
   ```bash
   ssh <user>@raspi-testpoint.local
   # または
   ssh <user>@<確認したIP>
   ```

**チェックポイント**: パスワードなしでSSHログインできる。

## Step C: IP固定化（推奨）

VMとRasPiが相互到達する構成が要件のため、IPアドレスが変動しないことが望ましい。

- **推奨**: ルーターのDHCP予約機能でRasPiのMACアドレスに固定IPを割り当てる
  - ※ CLAUDE.md の規約により、自宅ルーター側の設定変更自体はスコープ外（Claude Codeは操作しない）。この手順は**ユーザーが実施**する
- **代替**（ルーター操作を避けたい場合）: RasPi側で `nmcli` により静的IP設定（Bookwormは NetworkManager が標準）
  ```bash
  nmcli con mod "Wired connection 1" ipv4.addresses <固定IP>/24 ipv4.gateway <GW> ipv4.dns <DNS> ipv4.method manual
  nmcli con up "Wired connection 1"
  ```

## Step D: runbook-w1.md Step 1 へ合流

ここまで完了したら、通常の `docs/runbook-w1.md` Step 1（1-1〜1-6: uname -m確認 → cgroup v2確認 → Docker導入 → NTP確認 → testpoint起動 → troubleshoot）に進む。

完了後、以下を確定・更新すること:
- CLAUDE.md 環境インベントリの `<TODO: user>@<TODO: raspi-ip>` を実際の接続情報に置き換え
- `experiments/w1-notes.md` にキッティング結果（使用OSイメージのバージョン、つまずいた点）を記録

## つまずきやすいポイント（記事ネタ候補）

- microSDの相性・書き込み不良で初回起動しないケース → 別カードで再試行
- `.local` 名前解決がMac側のネットワーク環境（VPN常時接続など）で失敗することがある → 有線接続なのでルーターのクライアント一覧からの確認が確実な代替手段
- Bullseye→Bookworm移行でcgroup v2がデフォルト化した経緯は、Docker on RasPiの技術背景として記事で触れる価値がある
- 長期保管後のRTC（リアルタイムクロック非搭載モデルのため）ズレ → NTP同期確認（runbook Step 1-4）で必ず潰す。twampはクロック非依存だが、ログのタイムスタンプ相関に影響するため軽視しない
