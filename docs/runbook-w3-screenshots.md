# Runbook W3-SS: 記事用スクリーンショット取得（再注入セッション一体型）

目的: 再注入実験（100ms/3%、LG Gram egress）と同一セッションで、記事に使う全スクショを
絶対時刻レンジ + イベントオーバーレイ付きで取得する。**撮り直しは再注入のやり直しを意味する**ため、
本 runbook は「撮影台本」として実験前に全項目を準備してから注入する。

- 実施条件: ダッシュボード v2 適用済み / B チャートに **6 系列**（`lan-wired` + `wan-*` 5 本）が
  24h 分のベースラインで表示されている。WAN 公開ホスト 2 台の起点が 2026-07-30 22:52 JST
  なので、**7/31 22:52 以降**に撮影する
- 実行主体: 準備(Step 1-2.5)は Claude Code、撮影(Step 4-6)はユーザー（ブラウザ操作）
- タイムボックス: 準備 1h + 実験・撮影 1h

## Step 0: 撮影環境の統一（ユーザー・5分）

すべてのスクショで以下を揃える。混在すると記事の図版の質感がバラつく。

- [ ] ブラウザズーム **100%**、ウィンドウ幅は**固定**（推奨: 1600px 前後。Zenn 本文幅への縮小で文字が潰れない下限）
- [ ] O11y のユーザープロファイルでタイムゾーンが **Asia/Tokyo** になっていることを確認
      （キャプションの JST 表記とチャート軸を一致させる。設定はユーザーメニュー → プロファイル）
- [ ] テーマはダークのまま（既定方針）
- [ ] スクショは Retina 解像度で取得（macOS 標準 `Cmd+Shift+4` → スペースでウィンドウ単位、
      または範囲選択。註釈は後工程で入れるので素材は無加工で保存）
- [ ] 保存先: `docs/article/images/raw/`、命名は `ss-<連番>-<チャート略称>-<内容>.png`
      例: `ss-01-slo-injection.png`

### 撮り方（2026-08-01 のリハーサル 3 巡で確定。ブラウザは Safari）

**OS のスクリーンショットではなく、Splunk の書き出し機能を使う。**
ブラウザ枠も Splunk のアカウント表示名も一切写らない。

| ショット | 手順 |
|---|---|
| チャート単体<br>（SS-01・01b・02・03・04・08） | チャート右上の 3 点リーダー → **`Download chart as image`** |
| ダッシュボード全景<br>（SS-06・SS-09） | ダッシュボード右上の 3 点リーダー → **`Export`** → ファイルフォーマットに **image** を指定 |
| AI Assistant（SS-07） | ダッシュボードを `View fullscreen` にして右ペインに開き、`Cmd+Shift+4` |
| Alerts（SS-05） | **fullscreen が無い。** `Cmd+Shift+4` でウィンドウ単位に撮る |

**書き出した画像は必ず軸を目視で確認する。** 落とし穴が 2 つある。

- **チャート単体の Download は絶対レンジを保持する**（実測で確認済み）
- **ダッシュボードの Export は絶対レンジを落とすことがある。** リハーサルでは
  14:00〜16:00 を指定したのに 24 時間表示で書き出された。Export の前に
  Absolute を入れ直し、**書き出した画像の時刻軸を見て確かめる**

保存後は**ファイル名も確認する。** リハーサルでは 9 件に先頭スペースが、
1 件に `.png.png` の二重拡張子が混入していた。

### 凡例はチャート定義側で出す（as-code）

**`Download chart as image` には Splunk 標準の凡例パネルが含まれない。** 5 系列ある
WAN RTT や、`delay` / `rtt` / `clock_error` が重なる Chart 6 は、これでは読めなかった。

`options.onChartLegendOptions` で**チャート内に凡例を描かせる**ことで解決してある。

```json
"onChartLegendOptions": { "showLegend": true, "dimensionInLegend": "path.id" }
```

`dimensionInLegend` は必須で、省略すると
`Default dimension to show on chart legend missing.` で 400 になる。
**表示できる次元は 1 つだけ**なので、チャートごとに主役の次元を選んである。

| チャート | 凡例に出す次元 | 備考 |
|---|---|---|
| SLOビュー / ズーム / WAN RTT / パケットロス / ホップ数 | `path.id` | |
| Chart 6 / WAN 片道遅延 | `sf_streamLabel` | `delay` / `rtt` / `reverse` / `clock_error` |
| LAN RTT | `sf_streamLabel` | `mean` / `max` |
| スループット / TCP 再送 | `ps.source` | |

**同じラベルが 2 つ並ぶのは正常である。** Chart 6 は往復 2 方向、WAN 片道遅延は
宛先 2 拠点あり、`sf_streamLabel` はそこを区別しない。色で分かれるので、
キャプションで「同じラベルが 2 本なのは 2 方向 / 2 拠点」と補う。

**凡例が横に収まらないと末尾が `See all` に畳まれる。** SLO ビューを w6 で置いていた
ときは 6 系列のうち 5 つしか出ず、`wan-sinet-tokyo` が隠れた。**w12 h2 に変更済み**。

## Step 1: イベントオーバーレイの準備【Claude Code】

Detector の発火マーカーをチャート上に出す。**as-code とUIの2経路があり、as-code を正とする。**

**2026-07-31 に as-code 化して適用済み。** 以下は確定したスキーマと、残っている目視検証の手順。

`deploy/splunk/dashboard-network-slo.json` の `eventOverlays` に **Detector のキーだけ**を書き、
`apply.sh` が `.ids.json` から ID を、`detectors/<key>.json` から表示名を引いて展開する。
定義ファイルに ID を直書きしないので、Detector を作り直しても追従する。

```json
"eventOverlays": [
  { "detector": "lan-rtt-degraded", "label": "LAN RTT 劣化" },
  { "detector": "lan-throughput-degraded", "label": "LAN スループット劣化" },
  { "detector": "wan-rtt-sudden-change", "label": "WAN RTT 逸脱" },
  { "detector": "packet-loss", "label": "パケットロス継続" }
]
```

展開後の API モデルはこの形になる。`eventType` に指定できるのは
**`detectorEvents` と `eventTimeSeries` の 2 値だけ**で、Detector の発火を出すなら前者。
後者は自前でイベント API に投げたイベント用である。

```json
{ "eventColorIndex": 0, "eventLine": true, "label": "LAN RTT 劣化",
  "eventSignal": { "detectorId": "...", "eventSearchText": "<Detector の name>",
                   "eventType": "detectorEvents" }, "sources": [] }
```

`selectedEventOverlays` も `apply.sh` が全件 ON で生成する。**撮影時にトグルし忘れると
発火マーカーが写らない**ので、既定 ON にしてある。

なお `apply.sh` は detectors をダッシュボードより先に流すよう順序を入れ替えた。
overlay が Detector の ID を要求するためで、`--only dashboard` の挙動は変わっていない。

### 残っている検証（ユーザー・ブラウザ）

1. B チャート（SLO ビュー）の `showEventLines: true` を確認（設定済み）
2. ダッシュボード上部の **Event Overlay** バーに 4 本が並んでいることを確認
3. 7/29 の実験レンジを開き、既知の発火の位置にマーカーが立つことを目視で確認する

   ```
   https://app.jp0.signalfx.com/#/dashboard/HOWdHgXCEAI?startTime=1785327000000&endTime=1785329400000
   ```

   | 時刻 | Detector | 値 |
   |---|---|---|
   | 21:23 | lan-throughput-degraded | 240.8 Mbps |
   | 21:28 | lan-rtt-degraded | 106.391 ms |
   | 21:31 | lan-rtt-degraded | 104.203 ms |
   | 21:35 | wan-rtt-sudden-change | 115.469 ms（1.1.1.1） |
   | 21:36 | wan-rtt-sudden-change | 115.312 ms（8091.info） |
   | 21:40 | lan-rtt-degraded | 値 2 |

   マーカーの元データは `/v2/detector/<id>/events` で、6 件とも取得できることは
   `check-alerts.sh` で確認済み。**これが通れば再注入当日の表示は保証される。**

## Step 2: 撮影台本の確定【Claude Code が下書き→ユーザー確認】

再注入のタイムラインを先に固定する（実験と撮影を同じ台本で回す）:

| 時刻(目安) | アクション |
|---|---|
| T-30min | 平常データ確認。Step 1 のオーバーレイ ON を再確認 |
| T+0 | `tc netem` 注入開始（100ms / 3%、LG Gram egress）。**開始時刻を秒まで記録** |
| T+5〜10min | Detector 発火を Alerts 画面で確認 → **発火中に SS-05, SS-06 を撮影** |
| T+10min | AI Assistant にアラート調査をさせる → **SS-07 を撮影**（W3 積み残しの回収） |
| T+16min | 注入解除。**解除時刻を秒まで記録** |
| T+30min〜 | 全系列の復旧確認後、絶対時刻レンジで SS-01〜04, 08 を撮影 |

注入開始/解除時刻は `experiments/w3-notes.md` に記録し、図版キャプションの一次情報にする。

## Step 2.5: 注入手順（LG Gram）【Claude Code】

W2 の手順（`docs/runbook-w2.md` Step 7）は Lima VM の `lima0` 前提だった。**W3 以降は対象が
LG Gram の `enxa0cec8fe0854` に変わる。** 7/29 との決定的な違いが 2 つある。

1. **LAN も WAN も同一 NIC を通る**（`default via 192.168.1.1 dev enxa0cec8fe0854`）。
   egress に入れると **LAN 3 本と WAN 全パスが同時に崩れる**。1 枚で全パス劣化が撮れる
2. **SSH 自体が注入対象 NIC を通る。** 7/29 は `limactl shell` のローカル実行だったので
   この問題が無かった。解除コマンドが届かない事態への保険が要る

パラメータは 7/29 と同じ **100ms / 3%**、注入時間 **16 分**。比較可能性を優先する。

### 事前確認（T-30min）

```bash
# ノード状態。qdisc が fq_codel であること（noqueue なら異常）
ssh dev@192.168.1.102 'ip route show default; /sbin/tc qdisc show dev enxa0cec8fe0854'
ssh dev@192.168.1.102 'chronyc tracking | grep -E "System time|Frequency|Skew|Last offset"'

# retry-policy の反映確認。pscheduler-tasks は **展開後の完全な spec** を出すので、
# ホスト側ファイルの grep より強い（全12タスクの archives に retry-policy が入る）
ssh dev@192.168.1.102 'docker exec perfsonar-testpoint psconfig pscheduler-tasks' \
  | python3 -c "import json,sys; t=json.load(sys.stdin); \
print('タスク', len(t), '/ retry-policy 欠落', \
len([x for x in t if not any('retry-policy' in a.get('data',{}) for a in x['archives'])]))"
```

`retry-policy` が無いと注入中の PUT 失敗で測定結果が消える（`docs/schema.md` の
「archiver の retry-policy」節）。**「タスク 12 / retry-policy 欠落 0」でなければ注入しない。**

**WAN パスのヘルスチェック。** WAN 側は自宅ラボの制御外である。注入前から平常を外れていると、
B 案の「平常帯 1.0 → 跳ねる → 復旧」という絵が成立しない。

> **ratio だけを見てはいけない。必ず生値も見る。**
> B 案の `base` は `median(over='24h')` のローリングベースラインなので、
> **12 時間級の異常は 24 時間かけてベースラインに取り込まれ、ratio が 1.0 に戻る。**
> 「劣化したまま平常に見える」状態が作れてしまう。
> 2026-08-07 に実際に起きた（`wan-cloudflare` / `wan-blog` が 9ms → 118ms のまま
> ratio 1.00〜1.01。experiments/w3-notes.md Step 28）。
> **ratio が 0.9〜1.1 に収まっていることは、平常である証明にならない。**

```bash
# ratio と生値を同時に出す。base と now が乖離していなくても、
# **now が平常値そのものか**を見る（LAN 0.8ms / WAN 8〜10ms が平常）
WINDOW_HOURS=1 ./deploy/splunk/query.sh <<'Q'
rtt  = data('perfsonar.rtt.mean', filter=filter('path.id', '*')).mean(by=['path.id'])
base = rtt.median(over='24h').publish(label='base_24h_ms')
now  = rtt.publish(label='now_ms')
Q
```

**合格条件**（両方を満たすこと）:

| path.id | `now_ms` の平常値 |
|---|---|
| `lan-wired` | 0.7〜1.1 ms |
| `wan-cloudflare` / `wan-google` / `wan-blog` | 8〜10 ms |
| `wan-sinet-tokyo` | 8〜9 ms |
| `wan-riken-tsukuba` | 9〜10 ms |

1. **`now_ms` が上表のレンジに収まっている**（これが主。ratio では検知できない）
2. B 案チャートで 6 系列が 0.9〜1.1（従。ベースライン汚染があると当てにならない）

外れていれば実施を延期する。**ただし ISP 側など制御外の事象で長期化する場合は、
該当パスを「別事象で劣化中」と注記した上で残りの系列で撮る**判断もある。
その場合は SS-01 のキャプションに必ず書く。

### デッドマンスイッチ（注入より先に仕込む）

`ssh host 'cmd &'` + `nohup` は使わない。stdin をリダイレクトしないと、
**バックグラウンドの子プロセスが exec チャネルの stdin を握ったまま残り、ssh 側が
`sleep` の時間だけブロックして返ってこない。** これが起きるとタイマーだけ進んで注入が
始まらず、実験そのものが壊れる。systemd のトランジェントタイマーに委譲して、
SSH のライフサイクルから完全に切り離す。

```bash
# 20分後に自動解除する保険
ssh dev@192.168.1.102 'sudo systemd-run --on-active=1200 --unit=deadman-tc-del \
  /sbin/tc qdisc del dev enxa0cec8fe0854 root'
ssh dev@192.168.1.102 'systemctl list-timers deadman-tc-del --all --no-pager'
```

**2026-07-31 にリハーサル済み**（`--on-active=60` で仕込み → `list-timers` に出ることを
確認 → `systemctl stop` でキャンセル）。ssh は **0.042 秒で返り**、停止後はユニットごと
消えた（`could not be found`）。`systemd-run` は `/usr/bin/systemd-run` にあり、
`sudo -n` は NOPASSWD で通る。

### 注入（T+0）

```bash
ssh dev@192.168.1.102 'date -Is; \
  sudo /sbin/tc qdisc add dev enxa0cec8fe0854 root netem delay 100ms loss 3%; \
  /sbin/tc qdisc show dev enxa0cec8fe0854'
```

**開始時刻を秒まで記録する。** 続けて Mac 側から外部の裏取りを取る（7/29 と同じ対照）。

```bash
ping -c 20 192.168.1.102     # 注入対象 → +100ms になること
ping -c 20 192.168.1.101     # RasPi（対照）→ 変化がないこと
ping -c 20 1.1.1.1           # Mac の WAN（対照）→ 変化がないこと
```

### 解除（T+16min）

```bash
ssh dev@192.168.1.102 'date -Is; \
  sudo /sbin/tc qdisc del dev enxa0cec8fe0854 root; \
  /sbin/tc qdisc show dev enxa0cec8fe0854'
ssh dev@192.168.1.102 'sudo systemctl stop deadman-tc-del.timer deadman-tc-del.service'
ssh dev@192.168.1.102 'systemctl list-timers deadman-tc-del --all --no-pager'
ssh dev@192.168.1.102 'chronyc tracking | grep -E "System time|Frequency|Skew|Last offset"'
```

解除後の qdisc は既定の `fq_codel` に戻る。**`noqueue` になった場合は異常**なので記録する。
`list-timers` が 0 件であることまで確認して終わり。

### 記事に書く実験条件の注記

- **netem は egress にしか効かない。** RasPi → LG Gram 方向の遅延は LG Gram の応答パケットに
  乗るので RTT は +100ms になるが、**片方向注入である**ことを明記する
- **注入中は `fq_codel` が外れる**（netem が root に入るため）。スループット低下が netem 由来か
  AQM 喪失由来かは分離していない。7/29 も同条件なので比較可能性は保たれる
- 品質ゲート（`DELAY_CEILING_MS['lan-wired'] = 5`）は**緩めない**。注入中に LAN の片道遅延が
  欠測する挙動をそのまま撮る（SS-02）

## Step 3: 絶対時刻レンジの設定方法（共通操作）

1. ダッシュボード/チャート右上の時刻ピッカー → タブを **Absolute**（カレンダー指定）に切替
2. 開始・終了を分単位で入力。**本実験の標準レンジは「注入開始の30分前 〜 解除の30分後」**
   （例: 注入 21:20–21:36 なら 20:50–22:06。前後の平常区間が写ることで異常のコントラストが立つ）
3. チャート単体を撮る場合はチャートをクリックして拡大ビューにし、同様に Absolute 指定
4. URL に時刻がクエリとして入るので、**撮影に使った URL を w3-notes.md に貼っておく**
   （撮り直し・レンジ再現が一発でできる）

### URL の形式と、記録するときに落とすもの

実物はこの形になる（Phase 3 の検証で使ったもの）。

```
https://app.jp0.signalfx.com/#/dashboard/HOWdHgXCEAI
  ?groupId=HOWc2kfCIAA&configId=HOWdHgfCMAA
  &startTimeUTC=1785327600000&endTimeUTC=1785331200000
  &selectedEventOverlays=nfendE&selectedEventOverlays=Vt74qr
  &selectedEventOverlays=86r5Xr&selectedEventOverlays=F0fPyN
```

時刻のパラメータは `startTime` / `endTime` ではなく **`startTimeUTC` / `endTimeUTC`**
（エポックミリ秒）である。

**`selectedEventOverlays` は記録用 URL から落とす。** ここに入る `overlayId` は
**ダッシュボードを PUT するたびにサーバが振り直す。** 上の 4 個は
ズームチャートを追加した時点で無効になり、`EwrMfn` / `4WHJzp` / `lPXi59` / `VVAHJr` に
変わった。**`overlayId` を含む URL は再現性が無い。**

落としても困らない。`apply.sh` が `selectedEventOverlays` を**全件 ON で生成する**ので、
URL に書かなくても 4 本とも表示される。記録には
`?groupId=...&configId=...&startTimeUTC=...&endTimeUTC=...` だけを残す。

> **撮影が完全に終わるまで `apply.sh --only dashboard` を流さない。**
> 流すと `overlayId` が変わり、撮影中に開いていたタブの URL も再現しなくなる。
> チャート定義の変更が必要になった場合は `--only charts` で止める。

## Step 4: ショットリスト（記事構成案の章に対応）

| # | 素材 | チャート/画面 | 時刻レンジ | 必須要素 | 使用章 |
|---|---|---|---|---|---|
| SS-01 | **キービジュアル** | `charts/slo-baseline-ratio.json`（単体拡大） | 絶対: 注入±30min | 全パスが 1.0 帯 → lan が急騰・wan が連動 → 復旧 / **Detector 発火マーカー** / watermark 1.0・1.5 | 冒頭・6章 |
| SS-01b | キービジュアルのズーム版 | `charts/slo-baseline-ratio-zoom.json`（**Y軸 0〜15 固定**） | SS-01 と同一レンジ | WAN の 12 倍級の全振幅とベースライン帯・watermark が同時に読める。LAN は振り切れてよい | 冒頭・6章 |
| SS-02 | ゲートの物語・続編 | `charts/twamp-delay-gated.json` | 絶対: 注入±30min | 注入中に **OWD が欠測**する一方 **RTT は連続**して劣化を描く / ceiling 5ms の watermark | 6章 |
| SS-03 | 注入の生値詳細 | `charts/lan-rtt.json` + `charts/wan-rtt.json`（2枚 or 並置） | 絶対: 注入±30min | 0.9→105ms / 9→115ms の段差 | 6章 |
| SS-04 | スループット/ロス | `charts/throughput.json` + `charts/packet-loss.json` | 絶対: 注入±30min | 940→241Mbps の谷 / ロス系列の断続性 | 6章 |
| SS-05a | Detector 発火（一覧） | Alerts の Active alerts | **発火中にライブ撮影（撮り逃し不可）** | severity のカウントと Rule name の行 | 5-6章 |
| SS-05b | Detector 発火（詳細） | アラート詳細 1 件 | 事後で可 | 検知時刻 JST・閾値・Alert ID・Data links | 5-6章 |
| SS-06 | 発火中のダッシュボード全景 | ダッシュボード全体 | 発火中にライブ撮影（相対 1h） | 複数チャートが同時に崩れている全景 + イベントマーカー | 6章 |
| SS-07 | AI Assistant 調査 | AI Assistant 会話画面 | 発火中〜直後 | 質問文と回答全文（複数スクロールなら分割撮影） | 6章 |
| SS-08 | 経路非対称（平常時） | `charts/wan-owd.json` | 絶対: 平常な直近 24h | 往路/復路/RTT の 3 系列が乖離して見える | 5章 or 7章 |
| SS-09 | ダッシュボード全景（平常時） | ダッシュボード全体 | 相対 24h | v2 レイアウト（SLO ビューが先頭） | 5章 |

### SS-01b の撮り方（対数軸が使えないための代替）

v2 の chart API に対数軸のフィールドが無い（`experiments/w3-notes.md` Step 11）。
LAN が 100 倍級に跳ねると、線形軸ではベースライン帯も WAN の 10 倍級も潰れる。
Phase 3 の検証ショットで、**watermark 1.0 と 1.5 が軸の底で重なってラベルが読めなく
なる**ことを実際に確認した。SS-01b は必須である。

**ズーム版は独立したチャート定義にしてある**（`charts/slo-baseline-ratio-zoom.json`、
`axes[0].max = 3`）。ダッシュボード row0 に本体と並べて置いてあるので、
**SS-01 と同じく 3 点リーダー → `View fullscreen` でそのまま撮れる。**

軸をチャートビルダーでいじる運用にしなかったのは、**ビルダーがブラウザ枠ごと写ってしまう**
のと、実験中に「保存せずに破棄」を要求するのが事故のもとだからである。

1. `slo-baseline-ratio` を fullscreen にして SS-01 を撮る（Y 軸自動。LAN の急騰が主役）
2. 戻って `slo-baseline-ratio-zoom` を fullscreen にし、**同一の絶対レンジ**で SS-01b を撮る
3. LAN が上に振り切れるのは想定どおり。実値は SS-01 側で読ませる

### SS-05 は一覧が最優先（撮り逃すと再注入しかない）

リハーサルで **Active alerts は継続中のインシデントしか出さない**と分かった。
`check-alerts.sh` が発火 15 件を返す状態でも、画面は `No data found` で
全 severity が 0 だった。**解消した瞬間に一覧から消える。**

- **SS-05a（一覧）は発火中にしか撮れない。** 注入中の最優先ショットにする
- **SS-05b（詳細）は事後で撮れる。** Resolved なアラートでも、検知時刻・閾値・
  Alert ID・Data links が揃った画面が開く（リハーサルで 7/29 のアラートを撮れた）
- 撮影前に **「Get the most out of alerts」バナーを × で閉じる**

### AI Assistant は失敗しうる（SS-07）

リハーサルでは `I couldn't complete metric discovery right now. Please retry again later.`
で落ちた。SignalFlow: Finalizing まで進んでから失敗している。

**注入直後（T+2 目安）に 1 回投げて疎通を確かめる。** 失敗したら T+10 の本番投入までに
リトライしておく。16 分の窓で 1 回しか試さないと撮り逃す。

### SS-05 のナラティブ分岐（Phase 1-6 の調査結果を反映）

7/29 の「ロス Detector が発火しなかったのはサンプルサイズが原因」という説明は**誤り**だと
分かった（`experiments/w3-notes.md` Step 11）。実際は Detector の集約キーが
`ps.test.type` を含まないため、20 発の `lan-rtt-task` と 100 発の `lan-owd-task` が
1 本の系列に平均で潰れていた。**この集約キーは 7/31 に直してある**（Step 13）。

**それでも発火は確実ではない。** 直ったのは「ロス率が半減する」問題までで、
**16 分の注入に対して 12 分窓が狭い**という制約は残っている。5 分間隔なので注入区間に入る
測定点は 3 点ほどしかなく、`min(over='12m')` が閾値を超えられるのは最後の 1 点だけになる。

- **発火の確実性を上げたいなら、注入を 25 分程度まで伸ばす**（測定点が 5 点になる）。
  16 分は 7/29 との比較可能性のために選んだ値なので、**当日どちらを取るか決める**
- **発火した場合**: SS-05 に含める。「見逃し → 原因究明 → 修正 → 撃って確かめた」という
  筋で書く。集約キーの設計ミスが本題になる
- **発火しなかった場合**: LAN は 12 分窓の狭さ、WAN は 15 分間隔で窓に 2 点入らない構造
  （実測で `count(over='12m')` は常に 1）と、**理由を書き分ける。**
  7/29 の「サンプルサイズ」一本槍の説明はそのままでは使わない

## Step 5: 撮影時の品質チェック（各ショット共通）

- [ ] 凡例が読める（path.id が見えている。IP 裸の系列名が主役になっていない）
- [ ] watermark ラベルが切れていない
- [ ] イベントマーカーが対象レンジ内に表示されている（SS-01, 06）
- [ ] 時刻軸の目盛が JST で、キャプション予定の時刻と一致
- [ ] ツールチップ・ホバー UI が写り込んでいない（意図して出す場合を除く）

## Step 6: 撮影後の整理【Claude Code】

1. `docs/article/images/raw/` の連番・命名規則を検査
2. ショットリストとの突合表を `docs/article/images/INDEX.md` に生成
   （ファイル名 / 対応章 / キャプション案 / 撮影レンジ URL）
3. 注釈（矢印・囲み・日本語ラベル）が要るショットに TODO を付ける
   （注釈入りは `images/annotated/` に別保存。raw は残す）

## Exit Criteria

- [ ] SS-01〜09 が raw で揃っている（欠番がある場合は理由を w3-notes.md に記録）
- [ ] 注入開始/解除の秒単位時刻と、各撮影 URL が w3-notes.md に記録されている
- [ ] AI Assistant の調査記録（SS-07 + テキスト転記）が experiments/ に保存されている
- [ ] INDEX.md が生成され、記事構成案の章と図版の対応が確定している
