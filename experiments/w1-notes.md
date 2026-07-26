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
