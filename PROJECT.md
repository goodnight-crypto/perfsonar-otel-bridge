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
- 差別化要素: macOS 上で perfSONAR を正しく動かす知見 / **仮想化ゲスト（Lima vz VM）のクロック精度限界を実測で切り分け、TWAMP を片道遅延ではなく two-way(RTT) で使う測定設計に到達した過程** / tc netem 障害注入 → Detector 発火 → AI Assistant による調査、の一連のデモ

### 測定マトリクス

| パス | テスト | ツール | 間隔 | 狙い |
|---|---|---|---|---|
| Mac VM ↔ RasPi | RTT+ロス | `rtt` (`--tool twping`) | 5分 | **LAN 基準線**。TWAMP の two-way 測定なのでクロック非依存 |
| Mac VM ↔ RasPi | 片道遅延 | `latency` (twamp) | 5分 | 参考値。`max-clock-error` 品質ゲートの実演材料 |
| Mac VM ↔ RasPi | スループット | iperf3 | **30分間隔（終日）** | GbE 有線区間のスループット定点観測（実測929〜940Mbps、理論値近傍。W1実施前は旧Pi/USB Ethernet由来の~300Mbps上限を想定していたが、Pi4BはPCIe直結GbEのためその制約は非該当と判明） |
| Mac VM → 8091.info | RTT | `rtt` (ping) | 5分 | 自ブログのエッジ到達性。対向に TWAMP responder が無いため ICMP |
| Mac VM → 1.1.1.1 | RTT+経路 | `rtt` (ping) / `trace` | 5分/30分 | ISP 品質の定点観測。同上 |
| RasPi 有線 vs 無線 | RTT+ロス | `rtt` (`--tool twping`) | 5分 | Wi-Fi 品質比較（余力があれば） |

> **設計判断（W2 着手時に確定）**: LAN 区間の RTT は `latency`(twamp) ではなく **`rtt` テストを `--tool twping` で実行**して取得する。
> pScheduler の `twping` ツールは `latency` と `rtt` の両テストに対応しており（`pscheduler plugins` で確認）、
> `rtt` 側で実行すると ICMP ping 版と**完全に同一の JSON スキーマ**（`mean`/`min`/`max`/`stddev`/`loss`/`roundtrips[]`）で
> クロック非依存の RTT が得られる。ブリッジの追加実装は不要。ICMP と違いレート制限・優先度低下の影響も受けない。
> 詳細な経緯は docs/schema.md「rtt を twping で実行する場合」を参照。

> **iperf3 の実行頻度を「終日30分間隔」に変更（2026-07-28、実測に基づく）**:
> 当初は「深夜帯のみ」の制約下で、pSConfig が `repeat-cron` に対応しない
> （`ScheduleSpecification` は `start`/`repeat`/`slip`/`sliprand`/`until`/`max-runs` のみ、
> `additionalProperties: false`）ため、絶対時刻 `start` + `repeat: P1D` で 03:00 JST 固定にしていた。
>
> その後、実行中に Mac から外部 ping で影響を実測した。**WAN(1.1.1.1) の RTT 中央値は
> 8.795→9.506ms（+0.71ms、+8%）、LAN は 0.554→1.39ms、パケットロスは 2700発中 0。**
> 影響が出るのは `duration: PT20S` に対応する約20秒間のみ。家庭用ルーターが LAN 内スイッチングを
> ハードウェア処理しているため WAN 側にほぼ波及しないという想定どおりの結果で、時間帯限定を解除した。
>
> 5分間隔にしなかった理由: 有線GbEのスループットは極めて安定しており（929〜940Mbps、変動1%程度）
> 高頻度サンプリングの情報量が小さい。加えて throughput は `exclusive` スケジューリングクラスなので、
> 同じく5分間隔の `latency` テストと頻繁に衝突して測定時刻が乱れる。

### メトリクススキーマ（詳細: docs/schema.md）

`perfsonar.rtt.mean/.max`（rttテスト） `perfsonar.twamp.delay.median/.mean`（twamp one-way delay、`ps.max_clock_error`で品質ゲート） `perfsonar.packet.loss.ratio` `perfsonar.throughput.bps` `perfsonar.trace.hops`
共通 attributes: `ps.source` `ps.destination` `ps.test.type` `ps.tool` `path.id`

> **設計判断（W1 Step3 → W2着手時に更新）**: pSchedulerの`latency`(twamp)テストはRTTを返さず、one-way delayが主指標。
> 仮想化ゲスト(Lima VM)のクロック精度問題によりone-way delayが信頼できないため、**LAN基準線のRTTは
> `rtt`テストを`--tool twping`で実行して取得する**（上記マトリクス参照）。`latency`テストは参考値に降格し、
> 生JSONの`max-clock-error`をブリッジ側で見て閾値超過時は欠測扱いにする。
>
> ただし**この品質ゲートには偽陰性の実例がある**: `max-clock-error`が0.0msと報告されながら片道遅延が
> 中央値-4.62ms/最小-23.92msと壊れていたケースを実測済み（experiments/w1-notes.md:42）。
> ゲートは「壊れたデータを完全に排除する仕組み」ではなく「明らかに壊れた区間を落とすベストエフォート」
> として扱い、この限界を記事にも明記する。RTT/ロス率/スループットの主要SLO指標はこの問題の影響を受けない。

## ロードマップ

### W1（〜7/26）環境構築と疎通
- [x] Splunk O11y Free Edition 取得、realm / INGEST トークン確保
- [x] RasPi: 64bit 確認 → Docker → testpoint 起動（設定 volume 永続化）
- [x] Mac: Linux VM（ブリッジ接続）構築 → testpoint 起動
- [x] twamp / rtt / iperf3 の手動疎通確認（双方向）※VM(Lima)側クロック同期に要フォローアップ事項あり（w1-notes.md参照、W2までにchrony導入を検討）
- [x] HTTP archiver の生 JSON をダンプ → docs/samples/ に保存、schema.md 初版確定

### W2（〜8/2）パイプライン構築と実験
- [x] bridge 実装（FastAPI: /archive 受信 → OTLP push）+ 単体テスト
- [x] OTel Collector 設定 → Splunk 疎通、メトリクス着弾確認
- [x] pSConfig テンプレート本番化（全パス・スケジュール定義）※VM 6タスク / RasPi 3タスク稼働中
- [x] archiver に retry-policy を追加（未設定だと1回の PUT 失敗で測定結果が捨てられる。docs/schema.md）
      - **再送しても Splunk のグラフは埋まらない**。復旧点は「その間に成功した新しい点」より後に届き、
        ingest が順序逆転として黙って捨てる（HTTP は 200 OK）。実測で確認、experiments/w2-notes.md Step 12
      - 30秒段を8回（4分）にしてタスク間隔の5分より前に復旧を終わらせる設計にした。4分以内の障害は救える
      - 障害注入実験の一次証拠は Splunk のグラフではなく pScheduler の archivings 診断にする
- [x] Splunk ダッシュボード構築（path.id 別 RTT / ロス / スループット）
      - **as-code**。定義の正は `deploy/splunk/`、投入は `apply.sh`（冪等）。UI 作業なし
      - 7チャート。核は「片道遅延と品質ゲート」= clock_error が跳ねた区間で片道遅延が欠測する一方、
        同経路の RTT は連続していることを1枚で示す
- [x] Detector 3 種（ロス静的閾値 / RTT 異常検知 / スループット劣化）+ 任意の4本目（WAN の against_recent）
      - 閾値は直近24hの実測ベースラインから決定（docs/runbook-w2.md Step 6 に表）
      - 「2データポイント連続」は `lasting()` ではなく `min(over='12m')` で表現
- [x] Detector が平常運転で誤検知しないことの確認（平常運転区間 11:23〜21:20 は発火0件）
      - **当初「6時間20分・発火0件」と報告したが、根拠は誤りだった。** `check-alerts.sh` が
        `is` フィールドで判定していて常に空振りしていた（正しくは `anomalyState`）。
        実際は観測窓の冒頭に2件発火していた。experiments/w2-notes.md Step 15
      - 発火の原因はブリッジ停止リハーサルによるデータ欠測。`min(over='12m')` は窓内に
        1点しか無いとその1点で判定するため、`count(over=) >= 2` を足して修正した
      - 同じ観察窓で **VM のクロックが劣化**していた（clock_error 中央値 0.48ms → 21-23ms）。
        片道遅延の棄却率が 41% → 87% に上昇。Detector は clock 非依存なので影響なし
- [x] VM の時刻源を修復（Phase D の前提）
      - 原因は **Ubuntu 既定の `pool ntp.ubuntu.com` が RTT 256.8ms** だったこと。
        国内源（NICT / IIJ mfeed / Cloudflare）へ差し替え。設定は `deploy/vm/` として repo 化
      - root dispersion 37.7ms → 0.125ms、max-clock-error 21-23ms → **0.19ms**
      - 「VM のクロックが構造的に不安定」は**誤診**だった。experiments/w2-notes.md Step 14
      - ただし片道遅延の実測値は依然 **負値**（-0.26ms）。自己申告 0.19ms に対し実際の
        相対オフセットは 0.7ms 程度あり、**LAN の片道遅延は NTP の精度の外側**という結論
- [x] 実験: tc netem で遅延 100ms・ロス 3% 注入 → Detector 発火 → 復旧（2026-07-29 21:20〜21:36）
      - RTT 0.93→105ms、ロス 0→2〜6%、スループット 940→241Mbps、WAN RTT 9→115ms
      - Detector は RTT（双方向）・スループット・WAN 異常検知の**3種が発火**
      - **ロスだけ発火せず。** 3% ロスを20発で測ると 54% の確率でロス0になり
        「2点連続」を満たせない。閾値ではなくサンプルサイズの問題（W3 の課題）
      - 注入区間で**クロックのステップ補正なし**（Skew 0.108ppm）。Step 14 の時刻源修復により
        「遅延増が注入起因かクロック起因か」の疑いを排除できた
      - Collector は全区間で送出継続（失敗0）。archivings も全 run 1回目で成功し再送は不要だった
- [ ] AI Assistant に原因調査させて記録（W3）

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
