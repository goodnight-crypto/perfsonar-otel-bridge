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
