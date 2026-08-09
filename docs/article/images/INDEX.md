# 図版インデックス

`docs/runbook-w3-screenshots.md` Step 4 のショットリストと実ファイルの突合表。

**2026-08-10 に記事を公開して確定した。** 以下は最終状態の記録である。

## 状態

| ディレクトリ | 内容 | 状態 |
|---|---|---|
| `provisional/` | **リハーサル注入（08-08 05:22:20〜05:38:26）と本番注入（08-09 07:29:44〜07:45:38）**の両方 | **確定**。本番分は `-2` / `-3` / 時刻 4 桁で区別 |
| `raw/` | — | **未使用のまま終わった。** provisional で確定したため |
| `annotated/` | 注釈入り | **未着手のまま終わった。** 注釈なしで公開に至ったため不要 |
| `rehearsal/` | 2026-07-31〜08-01 の撮影手順リハーサル。実験データではない | 参考のみ |
| `verify/` | ダッシュボード適用の検証ショット | 参考のみ |

**本番注入のレンジは 07:00〜08:16 JST**（注入 ±30分）。リハーサルは 04:52〜05:52 で、
runbook の指定（開始30分前〜解除30分後）から終端が外れていた。本番で修正した。

## 記事に採用した図版（8 枚）

公開先: `/Users/dev/src/blog/zenn/images/home-network-slo/`

| 記事のファイル名 | 由来 | 内容 |
|---|---|---|
| `injection-ratio.png` | `SS-01b-slo-baseline-ratio-zoom-2.png` | SLO ビュー（Y軸0〜15固定）。注入区間で 6 系列すべてが跳ねる |
| `owd-gated.png` | `SS-02b-twamp-delay-gated-zoom-3.png` | 片道遅延（棒・0〜1.5ms固定）。**注入方向の棒だけが 3 本消える** |
| `alerts.png` | `SS-05a-active-alerts-0748.png` | Active alerts。LAN RTT 劣化 2 件 + WAN RTT 逸脱 1 件 |
| `raw-wide.png` | `SS-10a-cloudflare-raw.png` | Cloudflare 事象の生値。118ms のプラトーが 28 時間 |
| `ratio-wide.png` | `SS-10b-cloudflare-ratio.png` | 同レンジの比率。12.9倍 → 1.0 へ収束 |
| `ratio-narrow.png` | `SS-10c-cloudflare-ratio-narrow.png` | 復旧時に 1.0 → 0.076 へ落ちる崖 |
| `three-metrics.png` | **生成（ChatGPT）** | 3 指標の対比。`docs/article/infographic-1-three-metrics.md` |
| `window-breaks.png` | **生成（ChatGPT）** | 移動窓の 2 方向の壊れ方。`docs/article/infographic-2-window-breaks.md` |

**`alerts.png` に 07:48 を選んだ理由**: 4 Detector は 23 分かけて階段状に発火したため、
**4 種類が同時に並ぶ瞬間が存在しない**。07:48 は LAN と WAN が同時に出ており、
severity も 2 段階（Major / Minor）写る唯一のショットだった。

## 本番注入の全ショット（08-09）

撮影レンジは断りのない限り **07:00〜08:16 JST**。

| # | ファイル | 記事採用 | 備考 |
|---|---|---|---|
| SS-01 | `SS-01-slo-baseline-ratio-2.png` | — | Y軸自動。LAN が振り切れるため 01b を採用した |
| SS-01b | `SS-01b-slo-baseline-ratio-zoom-2.png` | **採用** | `+50%` と `ベースライン(1.0)` の watermark が左端で重なる（軽微） |
| SS-02 | `SS-02-twamp-delay-gated-2.png` | — | RTT の連続性と clock_error はこちらで読める |
| SS-02b | `SS-02b-twamp-delay-gated-zoom-3.png` | **採用** | 主題どおり撮れた |
| SS-03 | `SS-03-lan-rtt-2.png` / `SS-03-wan-rtt-2.png` | — | 数値は本文の表に採用 |
| SS-04 | `SS-04-throughput-2.png` / `SS-04-packet-loss-3.png` | — | throughput は**方向差が写っていない**（下記） |
| SS-05a | `SS-05a-active-alerts-0741.png` | — | `packet_loss_sustained` × 3（Major 3） |
| SS-05a | `SS-05a-active-alerts-0743.png` | — | 同上（2 件に減少） |
| SS-05a | `SS-05a-active-alerts-0746.png` | — | 解除直後 |
| SS-05a | **`SS-05a-active-alerts-0748.png`** | **採用** | `lan_rtt_degraded` × 2 + `wan_rtt_sudden_change` × 1 |
| SS-05a | `SS-05a-active-alerts-0750.png` | — | |
| SS-05a | `SS-05a-active-alerts-0808.png` | — | `lan_throughput_degraded` のみ（Warning 1） |
| SS-05b | `SS-05b-alerts-detail-0751.png` | — | アラート詳細 |
| SS-06 | `SS-06-dashboard-2.png` | — | 発火中の全景（相対 1h） |
| SS-07 | `SS-07-ai-assistant-0746.png` + `-2.png` + `.md` | — | **回答全文の `.md` が記事の材料**。画像は未使用 |
| SS-08 | `SS-08-wan-owd-2.png` | — | 平常時の WAN 片道遅延 |

### SS-04 throughput は方向差を写せていない

**記事のスループット節は、この図ではなく 40 分の追試（15:09:34〜15:50:02）の数値を使った。**

iperf3 は約 30 分間隔で往路と復路が約 15 分ずれて交互に走るため、
**16 分の注入では両方向を同時に捉えられない。** 本番注入で区間内に入ったのは
逆方向の 1 点（229 Mbps）だけだった。経緯は `experiments/w3-notes.md` Step 35。

追試の実測: 注入方向 941.4 → **1.10 Mbps**（860倍低下）／
逆方向 940.9 → **230.0 Mbps**（4.1倍低下）／ 方向差 **210倍**。

## 撮影 URL（本番）

```
https://app.jp0.signalfx.com/#/dashboard/HOWdHgXCEAI
  ?groupId=HOWc2kfCIAA
  &startTimeUTC=1786226400000
  &endTimeUTC=1786230960000
```

- レンジ: 2026-08-09 07:00:00〜08:16:00 JST
- **`selectedEventOverlays` は意図的に落としてある。** `overlayId` はダッシュボードを
  PUT するたびにサーバが振り直すため再現性がない。`apply.sh` が全件 ON で生成するので
  URL に書かなくても 4 本のマーカーは出る

参考: リハーサルのレンジ 04:52〜05:52 = `1786132320000` 〜 `1786135920000`

## リハーサル分（08-08）— 差し替え済み

日付サフィックスのないファイル（`SS-01-slo-baseline-ratio.png` など）がリハーサル分。
**`wan-cloudflare` / `wan-blog` の 24h ベースラインが 117ms のまま汚染されており、
SS-01 系でこの 2 系列が 0.076 に沈んで動かない。** 本番注入はこれを解消するために実施した。

経緯は `experiments/w3-notes.md` Step 29〜30。

## 失敗版を「before」として保存してある

チャート設計の失敗そのものが記事の材料になるため、**差し替え前の版を消していない。**

| ファイル | 何が読めなかったか | 対になる after |
|---|---|---|
| `SS-02b-twamp-delay-gated-zoom.png` | 6系列・折れ線・凡例が `ps.source` のため、**どの線が片道遅延で どれが RTT / clock_error か区別できない。** `dimensionInLegend` は1次元しか出せず「メトリック × 方向」を同時に表せない | `SS-02b-twamp-delay-gated-zoom-2.png` → 本番 `-3` |
| `SS-04-packet-loss.png` | w6 では凡例11項目のうち6項目で **`See all` に畳まれる** | `SS-04-packet-loss-2.png` → 本番 `-3` |

どちらも「**1枚のチャートに主張を2つ載せると読めなくなる**」の実例。

## 注釈（`annotated/`）は作らなかった

当初は矢印・囲み・日本語ラベルを入れる予定だったが、**注釈なしで公開に至った。**

理由は 2 つ。チャート定義側で `onChartLegendOptions` を使って凡例をチャート内に描かせたため
系列の区別が図の中で完結したこと、そして**インフォグラフィック 2 枚を別途生成したため、
説明が必要な部分はそちらが担ったこと**である。
