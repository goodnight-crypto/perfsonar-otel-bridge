# CHANGES: ダッシュボード v2（SLOビュー追加 + WAN非対称チャート改良）

Claude Code への指示書。2 ファイルを `deploy/splunk/` の既存 as-code 形式に統合し、`apply.sh` で反映する。

## 変更内容

| ファイル | 種別 | 対象 |
|---|---|---|
| chart-slo-baseline-ratio.json | **新規チャート** | ダッシュボード先頭（row0 全幅 w12 h1、既存チャートは 1 行繰り下げ） |
| chart-wan-owd-asymmetry-v2.json | **既存チャート更新** | 「WAN 片道遅延と経路非対称 — SINET 東京 / 理研つくば」の programText / publishLabelOptions / description を置換 |

> 注意: この 2 ファイルは API エクスポート互換のチャートモデルで書いてある。
> `deploy/splunk/` の実際のファイル形式（キー構成・ID 管理方法）と差異があれば、
> **repo 側の形式を正としてフィールドを移植**すること。programText と
> publishLabelOptions / axes / description が本質、他は器。

## 適用前の確認（SignalFlow の要検証ポイント）

1. `median(over='24h')` が SignalFlow で受理されるか。拒否される場合は
   `percentile(pct=50, over='24h')` に置換（同義）
2. C 案の `(rtt - delay)` は両ストリームが同一の group-by キー
   （path.id, ps.destination）で相関することが前提。プレビューで
   wan-sinet / wan-riken / wan-icepp の 3 系列に reverse が出ることを確認
3. B 案は **各パス 24h 分のデータが溜まるまで系列が出ない**。
   WAN 公開ホスト 3 パスは 2026-07-30 22:52 追加なので、7/31 深夜以降に確認

## 適用後の検証チェックリスト

- [ ] B: 平常時に全パス（lan-wired + wan-* 5 本）が 0.9〜1.1 のバンド内に収まっている
- [ ] B: watermark 2 本（1.0 / 1.5）が表示されている
- [ ] C: reverse 系列が往路 delay と乖離して見える（非対称の可視化が成立）
- [ ] C: reverse に恒常的な負値が出ていない（瞬間的な負値は許容。恒常的なら
      平滑化窓を 15m → 30m に広げる）
- [ ] 既存 Detector に影響なし（チャート変更はメトリクスに影響しないはずだが、
      apply.sh 実行ログで detector 系リソースに触れていないことを確認）
- [ ] エクスポートを取り直して repo にコミット（as-code の正を更新）

## 再注入実験（A 案スクショ）との関係

- B のチャートは **8/1 以降の再注入実験**でキービジュアル素材になる
  （注入区間で lan-wired が ~100 倍、wan-* が ~10 倍に跳ね、1 枚で全パス劣化が写る）
- 再注入時は B チャートに関連 Detector をリンクし、イベントオーバーレイ
  （発火マーカー）を有効化した状態でスクショを撮る
- 既知の限界として記事に書く: 注入中、LAN の片道遅延は
  `DELAY_CEILING_MS['lan-wired'] = 5` に弾かれて欠測になる
  （ceiling は実劣化とクロックのゴミを区別できない）。ゲートは緩めず、
  この挙動自体を Chart 6 の物語の続きとして記録する
