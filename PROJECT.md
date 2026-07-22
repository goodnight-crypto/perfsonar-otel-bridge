# PROJECT.md — 企画概要とロードマップ

## 目的

Zenn 記事投稿コンテスト「OpenTelemetryの知見を、記事にしよう」**Splunk Observability 部門**への応募記事を、実検証に基づいて執筆する。

- コンテストページ: https://zenn.dev/contests/splunk-opentelemetry-2026
- 締切: **2026-08-10**（期間中に新規公開された記事のみ対象。下書き応募不可）
- 部門要件: OpenTelemetry **および** Splunk Observability Cloud を主題に含むこと
- 審査基準（加点要素）: ①技術的な正確性と再現性 ②独自性 ③実用性・汎用性 ④読みやすさ ⑤熱量

## 検証コンセプト

**「perfSONAR で自宅ネットワークの品質を定点観測し、測定結果を OpenTelemetry に変換して Splunk O11y でネットワーク SLO を可視化する（DIY 版 ThousandEyes）」**

- perfSONAR の弱点（可視化・アラート・長期分析が古典的）を、OTel + Splunk で補完する構図
- 記事の核となる成果物: **pScheduler HTTP archiver → OTLP 変換ブリッジ**（本リポジトリ。記事公開時に public 化）
- 差別化要素: macOS 上で perfSONAR を正しく動かす知見 / RasPi のクロック制約を踏まえた twamp 主軸の測定設計 / tc netem 障害注入 → Detector 発火 → AI Assistant による調査、の一連のデモ

### 測定マトリクス

| パス | テスト | ツール | 間隔 | 狙い |
|---|---|---|---|---|
| Mac VM ↔ RasPi | RTT+ロス | twamp | 5分 | LAN 基準線。クロック非依存 |
| Mac VM ↔ RasPi | スループット | iperf3 | 6時間(深夜帯) | RasPi の ARM 上限(~300Mbps)自体を観測 |
| Mac VM → 8091.info | RTT | rtt | 5分 | 自ブログのエッジ到達性 |
| Mac VM → 1.1.1.1 | RTT+経路 | rtt / trace | 5分/30分 | ISP 品質の定点観測 |
| RasPi 有線 vs 無線 | RTT+ロス | twamp | 5分 | Wi-Fi 品質比較（余力があれば） |

### メトリクススキーマ（詳細: docs/schema.md）

`perfsonar.twamp.rtt.mean/.max` `perfsonar.packet.loss.ratio` `perfsonar.throughput.bps` `perfsonar.trace.hops`
共通 attributes: `ps.source` `ps.destination` `ps.test.type` `ps.tool` `path.id`

## ロードマップ

### W1（〜7/26）環境構築と疎通
- [x] Splunk O11y Free Edition 取得、realm / INGEST トークン確保
- [ ] RasPi: 64bit 確認 → Docker → testpoint 起動（設定 volume 永続化）
- [ ] Mac: Linux VM（ブリッジ接続）構築 → testpoint 起動
- [ ] twamp / rtt / iperf3 の手動疎通確認（双方向）
- [ ] HTTP archiver の生 JSON をダンプ → docs/samples/ に保存、schema.md 初版確定

### W2（〜8/2）パイプライン構築と実験
- [ ] bridge 実装（FastAPI: /archive 受信 → OTLP push）+ 単体テスト
- [ ] OTel Collector 設定 → Splunk 疎通、メトリクス着弾確認
- [ ] pSConfig テンプレート本番化（全パス・スケジュール定義）
- [ ] Splunk ダッシュボード構築（path.id 別 RTT / ロス / スループット）
- [ ] Detector 3 種（ロス静的閾値 / RTT 異常検知 / スループット劣化）
- [ ] 実験: tc netem で遅延 100ms・ロス 3% 注入 → Detector 発火 → AI Assistant に原因調査させ記録

### W3（〜8/9）執筆と公開
- [ ] Zenn 記事執筆（構成案は下記）・スクショ整理
- [ ] リポジトリ public 化（公開前チェックリスト実施）
- [ ] 記事公開 → コンテスト応募（バッファ 8/9-8/10）

## 記事構成案（ドラフト）

1. なぜ perfSONAR × OpenTelemetry × Splunk か（ネットワーク屋の課題意識）
2. アーキテクチャと設計判断（owamp を捨てて twamp にした理由 / macOS の罠）
3. 環境構築（RasPi arm64 / Mac の Linux VM / Free Edition）
4. ブリッジ実装: pScheduler JSON → OTel メトリクス変換
5. Splunk O11y でネットワーク SLO を張る（ダッシュボード / Detector）
6. 障害注入実験と AI Assistant による調査
7. 運用して見えたこと・限界・今後（Catalyst 9300 app hosting への展望）

## 公開前チェックリスト（public 化時）

- [ ] `git log` 全履歴に対する secrets scan（gitleaks 等）
- [ ] `.env` 不在確認 / `.env.example` のみ存在
- [ ] docs/samples/ 内の JSON に含まれるグローバル IP・ホスト名の扱い判断
- [ ] README のクイックスタートを第三者再現可能な状態に更新
- [ ] LICENSE (MIT) 追加

## 将来展望（記事のスコープ外）

- Catalyst 9300 App Hosting への testpoint デプロイ（Phase 2、職場ラボ）→ 続編記事候補
- 8091.info でのブログ記事化（Zenn 記事の裏話・自宅ラボ構成紹介として二次利用）
