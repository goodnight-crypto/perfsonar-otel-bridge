# 公開 perfSONAR ホストの選定ログ

`docs/runbook-w2-public-hosts.md` の Step 1〜4（候補選定の実測）の作業ログ。
Step 5（pSConfig への組み込み）は予告どおり GbE NIC 切替作業にまとめ、**2026-07-30 に完了した**
（→ 末尾「Step 5 の実施結果」・`experiments/w3-notes.md` Step 10）。

- 開始日: 2026-07-30
- 実行ノード: **LG Gram（192.168.1.102）の testpoint コンテナ**
- 目的: WAN 区間の RTT・ロスの定点観測先を 2 台選ぶ。twamp が通れば**片道遅延と経路非対称**も取る

## なぜ今やるのか

この Runbook は W2 に書いたが、**今日の作業を経て価値が上がった。**
当時は Lima VM のクロック上書きで片道遅延が測れず、WAN パスを足しても ICMP RTT が
増えるだけだった。bare metal 化と両端の chrony 統一により、いまは**片道遅延が測れる**
（中央値 0.230ms、負値 0 発、`max-clock-error` 0.32ms。`w3-notes.md` Step 4・5）。

公開 perfSONAR ホストは TWAMP responder を持つので、**WAN 区間の片道遅延と経路非対称**が
取れる可能性がある。LAN で見つけた 0.94ms の非対称は USB NIC 由来だったが、
**インターネット区間の非対称は経路由来**であり、記事の主張を一段強くする。

## 実行前の調査: Runbook の前提が 2 つ崩れていた

| Runbook の記述 | 実際 | 対応 |
|---|---|---|
| Step 1「stats.perfsonar.net を開いて抽出」 | **Grafana の SPA で JavaScript が要る。** WebFetch では `Grafana has failed to load its application files` しか取れない（HTTP 200 は返る） | **ユーザーがブラウザで実施**（Runbook 冒頭が既に許容している形） |
| Lookup Service から機械的に引く | `ls.perfsonar.net/lookup/records` は **POST 専用**（`allow: POST`、GET は 405）。登録用エンドポイントであり検索 API ではない。グローバルレジストリ `ps1.es.net:8096/lookup/activehosts.json` が指す先もここ 1 つ | 機械的な取得は**断念**。ブラウザ経由に一本化 |

Runbook 本体にもこの 2 点を追記済み。

## 着手前チェック: LG Gram の testpoint

```
$ ssh dev@192.168.1.102 'docker exec perfsonar-testpoint pscheduler troubleshoot'
Looking for pScheduler... OK.
Checking clock... OK.
Exercising API... Archivers... Contexts... Tests... Tools... OK.
Checking services... Ticker... Scheduler... Runner... Archiver... OK.
Idle test.... 8 seconds... Finished... Checking archiving... OK.
pScheduler appears to be functioning normally.
```

コンテナは `Up About an hour`。**pSConfig 未投入のため定期タスクを持たない**ので、
手動テストが本番スケジュールと衝突しない。

## Step 1: 候補リストアップ

ユーザーが stats.perfsonar.net をブラウザで開き、Japan 所在のホスト 55 件を CSV で取得した。
生データ: [`perfsonar_Japan_Host name-data-2026-07-30 17_18_18.csv`](<perfsonar_Japan_Host name-data-2026-07-30 17_18_18.csv>)

### 55 件から 8 台に絞った基準

**除外したもの**

- **FQDN を持たない生 IP のみのエントリ**（`150.100.212.x`、`157.82.116.x`、`202.13.202.x` など計 22 件）。
  ドメインから運用主体を確認できず、選定基準 5（運用主体の明確さ）を満たさない
- **`172.50.0.1`** — 明らかな誤登録。到達性を問うまでもない
- **同一組織・同一地点の重複**（`perf-tokyo` と `perf-tokyo-1g` など、`-1g` 付きと無しの対）。
  片方だけを候補に残した

**残した 8 台**（**6 組織**にまたがるよう経路多様性を優先）

| # | FQDN | 組織 | 所在地 |
|---|------|------|--------|
| 1 | `perf-tokyo.sinet.ad.jp` | SINET（NII） | 東京 |
| 2 | `perf-osaka.sinet.ad.jp` | SINET（NII） | 大阪 |
| 3 | `perfsonar2.cc.kek.jp` | KEK | つくば |
| 4 | `perfsonar1.icepp.jp` | ICEPP（東京大学） | 東京 |
| 5 | `ps-tkb-100g.riken.jp` | 理化学研究所 | つくば |
| 6 | `ps-ykh-100g.riken.jp` | 理化学研究所 | 横浜 |
| 7 | `nms5.jp.apan.net` | APAN | － |
| 8 | `163-220-229-67.v4.coe.ad.jp` | coe.ad.jp | － |

SINET は同一組織で東京・大阪の 2 地点を残した。**同じ運用主体でも距離が違えば経路が違う**ので、
「RTT が距離に素直に比例するか」を見る対照になる。

## Step 2: 生存確認（`ping` / `pscheduler ping`）

実行: 2026-07-30 17:20 JST 前後、LG Gram の testpoint から。

| # | FQDN | ICMP `ping -c 3` | `pscheduler ping` | 判定 |
|---|------|------------------|-------------------|------|
| 1 | `perf-tokyo.sinet.ad.jp` | 0% loss / avg **10.30ms** | alive | 通過 |
| 2 | `perf-osaka.sinet.ad.jp` | 0% loss / avg **16.22ms** | alive | 通過 |
| 3 | `perfsonar2.cc.kek.jp` | **100% loss** | **Failed to connect ... port 443 after 2703 ms: Connection timed out** | **脱落** |
| 4 | `perfsonar1.icepp.jp` | 0% loss / avg **9.91ms** | alive | 通過 |
| 5 | `ps-tkb-100g.riken.jp` | 0% loss / avg **11.33ms** | alive | 通過 |
| 6 | `ps-ykh-100g.riken.jp` | 0% loss / avg **10.19ms** | alive | 通過 |
| 7 | `nms5.jp.apan.net` | 0% loss / avg **8.87ms** | alive | 通過 |
| 8 | `163-220-229-67.v4.coe.ad.jp` | 0% loss / avg **10.20ms** | alive | 通過 |

**7/8 通過。** KEK のみ ICMP・pScheduler API（443）とも到達せず、この時点で脱落した。
ICMP だけを止めているホストに備えて ICMP 不通でも `pscheduler ping` を試したが、KEK は
443 も閉じていた。Runbook の注意書き（「Lookup Service には停止中のホストも載る」）が
実際に当たった 1 例。

## Step 3: latency テストの受け入れ確認

**結論: TWAMP は自宅 NAT を越えた。7 台中 5 台で片道遅延が取れた。**

これは事前に最大のリスクと見ていた点だった。TWAMP はクライアントが制御・試験パケットの
両方を発信し、リフレクタが送信元へ返す構造なので NAT と相性が良いはず、という理屈は
立っていたが、実測するまで分からなかった。**通った。**

| # | FQDN | latency `--protocol=twamp` | 片道遅延 中央値 | ロス | `max-clock-error` | 判定 |
|---|------|---------------------------|----------------|------|-------------------|------|
| 1 | `perf-tokyo.sinet.ad.jp` | 完走 | **3.71 ms** | 0/100 | 0.2 ms | **twamp 可** |
| 2 | `perf-osaka.sinet.ad.jp` | 完走 | **7.84 ms** | 0/100 | 0.3 ms | **twamp 可** |
| 4 | `perfsonar1.icepp.jp` | 完走 | **3.70 ms** | 0/100 | 0.3 ms | **twamp 可** |
| 5 | `ps-tkb-100g.riken.jp` | 完走 | **4.54 ms** | 0/100 | 0.22 ms | **twamp 可** |
| 6 | `ps-ykh-100g.riken.jp` | 完走 | **3.81 ms** | 0/100 | 0.57 ms | **twamp 可** |
| 7 | `nms5.jp.apan.net` | 起動するが **100/100 ロス** | Not Reported | 100% | Not Reported | rtt へ切替 |
| 8 | `163-220-229-67.v4.coe.ad.jp` | 起動するが **100/100 ロス** | Not Reported | 100% | Not Reported | rtt へ切替 |

### 7・8 は「拒否」ではなく「無応答」だった

**`Run rejected` は 1 台も出なかった。** 7・8 の 2 台はテスト自体は起動し、100 発送って
0 発返る形で終わっている。**制御チャネル（TCP 861/443）は通り、TWAMP の試験パケット（UDP）
だけが返ってこない**という切り分けになる。先方のファイアウォールが UDP の試験ポート範囲を
開けていないか、TWAMP responder が動いていないかのいずれか。

limits ポリシーによる拒否ではないが、**方針どおりリトライはしていない**。rtt に切り替えた。

| # | FQDN | rtt フォールバック | 判定 |
|---|------|-------------------|------|
| 7 | `nms5.jp.apan.net` | 0% loss / **8.914 ms** (min 8.456 / max 9.424 / sd 0.307) | **rtt のみ可** |
| 8 | `163-220-229-67.v4.coe.ad.jp` | 0% loss / **10.249 ms** (min 9.907 / max 10.835 / sd 0.335) | **rtt のみ可** |

**Step 3 は 7 台全通過**（twamp 5 台、rtt 2 台）。

### 追加測定: 同一プロトコルでの RTT（非対称の算出用）

片道遅延だけでは非対称を語れないので、**同じ TWAMP で RTT も測った**
（`pscheduler task --tool twping rtt`）。ICMP と比べるのではなく同一パケット系で比べることで、
プロトコル差の混入を避ける。

| FQDN | 片道 平均 (A) | TWAMP RTT 平均 (B) | 復路 = B − A | **非対称 = 復路 − 往路** |
|---|---|---|---|---|
| `perf-tokyo.sinet.ad.jp` | 3.73 ms | 8.324 ms | 4.59 ms | **+0.86 ms** |
| `perf-osaka.sinet.ad.jp` | 7.88 ms | 15.369 ms | 7.49 ms | **−0.39 ms** |
| `perfsonar1.icepp.jp` | 3.74 ms | 8.531 ms | 4.79 ms | **+1.05 ms** |
| `ps-tkb-100g.riken.jp` | 4.56 ms | 9.958 ms | 5.40 ms | **+0.84 ms** |
| `ps-ykh-100g.riken.jp` | 3.82 ms | 9.574 ms | 5.75 ms | **+1.93 ms** |

**重要な但し書き（記事で絶対に落とせない点）**

`w3-notes.md` Step 5 で判明したとおり、**LG Gram の USB 100M NIC は「受信方向」にだけ
約 0.94ms を上乗せする**（ホストコントローラのポーリング周期由来）。上表の「復路」は
まさに LG Gram が受信する方向なので、**+0.86〜+1.05ms の非対称は、ほぼ全部が
自分の NIC の癖で説明できてしまう。** WAN 経路の非対称とは言えない。

そのうえで、次の 2 つは NIC の癖では説明できない。

- **大阪の −0.39ms**: 受信側に +0.94ms が乗ってなお復路のほうが速い。
  **経路そのものは往路が約 1.3ms 遅い**ことになる
- **理研・横浜の +1.93ms**: NIC 分を引いてもなお約 +1.0ms 残る

さらに次の 2 点で精度が足りていない。

- 片道と RTT を**同時に測っていない**（数分ずれている）。その間の経路変動が混入する
- `max-clock-error` が 0.2〜0.57ms あり、**+0.86ms 程度の非対称は誤差と同オーダー**。
  大阪と理研・横浜の値だけが誤差より十分大きい

→ **GbE NIC 交換後の再測定が、この曖昧さを消す作業になる。** NIC 由来の 0.94ms が消えれば、
残る非対称は経路由来だと言い切れる。`w3-notes.md` Step 6 の「切り分けの好機」が
LAN だけでなく **WAN でも使える**ことになった。

## Step 4: 安定性確認（30〜40 分間隔 × 3 回）と 2 台選定

Runbook の「2 時間以上 × 3 回」を **30〜40 分間隔 × 3 回**に短縮して実施した（半日の
タイムボックスに収めるため。変更の根拠は Runbook 側に記載）。

| ラウンド | 実施時刻（JST） |
|---|---|
| Round 1 | 17:22〜17:32 |
| Round 2 | 18:05〜18:10 |
| Round 3 | 18:41〜18:46 |

### twamp 可の 5 台（片道遅延の中央値 / ms）

| FQDN | R1 | R2 | R3 | 振れ幅 | ロス | `max-clock-error` | 評価 |
|---|---|---|---|---|---|---|---|
| `perf-tokyo.sinet.ad.jp` | 3.71 | 4.06 | 4.04 | **0.35** | 0/100 全回 | 0.2〜0.4 | **最速かつ安定** |
| `perf-osaka.sinet.ad.jp` | 7.84 | 7.98 | 7.90 | **0.14** | 0/100 全回 | 0.28〜0.52 | **最も安定**。ただし遅い |
| `perfsonar1.icepp.jp` | 3.70 | **79.89** | **90.31** | **86.6** | R3 で **1/100 ロス** | 0.27〜0.56 | **脱落** |
| `ps-tkb-100g.riken.jp` | 4.54 | 4.96 | 4.70 | **0.42** | 0/100 全回 | 0.21〜0.49 | **安定** |
| `ps-ykh-100g.riken.jp` | 3.81 | 3.64 | 5.42 | **1.78** | 0/100 全回 | 0.57〜**1.18** | 振れる |

### rtt のみの 2 台（RTT 平均 / ms）

| FQDN | R1 | R2 | R3 | ロス | 評価 |
|---|---|---|---|---|---|
| `nms5.jp.apan.net` | 8.914 (sd 0.307) | **12.590 (sd 6.874, max 26.33)** | 8.935 (sd 0.274) | 0% 全回 | R2 で一時的に荒れた |
| `163-220-229-67.v4.coe.ad.jp` | 10.249 (sd 0.335) | 10.371 (sd 0.214) | 10.796 (sd 0.843) | 0% 全回 | 安定 |

### Round 2 の ICEPP 劣化は自宅の上りではない（切り分け済み）

ICEPP が **3.70ms → 79.89ms**（中央値）に跳ねた。標準偏差 17.10ms、P95−P50 は 22.91ms で、
**ロスは 0/100 のまま遅延だけが暴れる**という、典型的な輻輳（バッファ滞留）の形をしている。

自宅の上り側の問題である可能性を潰すため、**VM が 5 分間隔で 1.1.1.1 に打っている
本番タスクの実測値**を同時刻帯について引いた。

| 実行時刻（UTC） | 1.1.1.1 への RTT |
|---|---|
| 08:53:55 | 0% loss, mean 8.838 ms (sd 0.331) |
| 08:59:30 | 0% loss, mean 9.217 ms (sd 0.810) |
| **09:03:52** | 0% loss, mean 8.908 ms (sd 0.481) |
| **09:08:09** | 0% loss, mean 8.855 ms (sd 0.314) |

Round 2 は 09:05:15 UTC 開始、ICEPP のテストは 09:07 前後。**その前後を挟む 2 回とも
自宅の上りは平常値（8.9ms、ロス 0）だった。** また同じ Round 2 の中で、ICEPP の直後に
測った理研つくば（4.96ms）・理研横浜（3.64ms）も平常だった。

→ **劣化は ICEPP 側の経路に固有**と結論できる。

Round 3（18:41〜）でも ICEPP は **90.31ms**、しかも **初のパケットロス（1/100）**を出した。
40 分後も回復していないので、一時的なスパイクではない。

**これは「常時観測を持っている」ことの実演になる。** 単発の測定では「自分の回線が悪いのか
相手が悪いのか」を切り分けられない。5 分間隔で回り続けている参照パス（1.1.1.1）が
あったから、追加の測定を一切せずに切り分けられた。記事の主張としてそのまま使える。

### Step 4 を省略しなくてよかった

ICEPP は **Round 1 では 3.70ms で最速タイの優等生**だった。`max-clock-error` も 0.3ms、
ロスも 0。**1 回の測定で選んでいたら確実に掴んでいた。**

Runbook の間隔を「2 時間以上」から「30〜40 分」に短縮したことも、結果的には影響しなかった。
30 分あれば十分に捕まる程度の継続的な劣化だった。ただし**これは結果論**であり、
時間帯による差（深夜・早朝）はこの 3 回では見ていない。選定後は 15 分間隔の本番測定で
見続ける前提は変えない。

## 選定結果

| | ホスト | 組織 | 測定 | 選定理由 |
|---|---|---|---|---|
| **1 台目** | **`perf-tokyo.sinet.ad.jp`** | SINET（NII） | **twamp**（片道遅延可） | 国内・twamp 可のなかで**片道遅延が最小（3.7〜4.1ms）かつ振れ幅 0.35ms**。3 回ともロス 0、`max-clock-error` 0.2〜0.4ms |
| **2 台目** | **`ps-tkb-100g.riken.jp`** | 理化学研究所 | **twamp**（片道遅延可） | **別組織・別経路**。振れ幅 0.42ms・3 回ともロス 0 で 1 台目に次ぐ安定度、かつ twamp が通る |

### 選定理由（記事用）

3 回の実測で、**「速いホスト」と「安定したホスト」は一致しなかった。** Round 1 で最速タイ
だった ICEPP は Round 2・3 で 80〜90ms へ劣化し、Round 3 ではロスも出した。逆に最も
振れ幅が小さかったのは最も遅い大阪（0.14ms）だった。**1 回の測定で選んでいたら ICEPP を
掴んでいた**という事実が、安定性確認を省略しない理由をそのまま示している。

1 台目には片道遅延が最小かつ振れ幅 0.35ms の **SINET 東京**を選んだ。2 台目は経路多様性を
優先し、**別組織・別経路の理研つくば**を選んだ。両方 twamp が通るので、**WAN 区間でも
片道遅延と経路非対称を観測できる。** 距離の違う 2 経路（東京 3.7ms / つくば 4.7ms）を
並べれば、遅延が距離だけで決まらないことも見える。

### 補欠と、採らなかった理由

| ホスト | 採らなかった理由 |
|---|---|
| `perf-osaka.sinet.ad.jp` | **最も安定（振れ幅 0.14ms）だが SINET で 1 台目と同一組織**。経路多様性の基準で 2 台目に劣る。ただし**唯一「NIC の癖では説明できない負の非対称（−0.39ms）」を示したホスト**であり、GbE 交換後に再測定する価値が高い。**3 本目を足すならこれ** |
| `ps-ykh-100g.riken.jp` | 振れ幅 1.78ms（R3 で +1.7ms 跳ねた）、`max-clock-error` も 1.18ms まで悪化。理研なら**つくばのほうが安定** |
| `perfsonar1.icepp.jp` | R2・R3 で 80〜90ms へ劣化、R3 でロス発生。**脱落** |
| `nms5.jp.apan.net` / `163-220-229-67.v4.coe.ad.jp` | **twamp の試験パケットが返らず rtt しか取れない**。RTT なら安定しているが、**片道遅延という今回の主目的を満たさない** |
| `perfsonar2.cc.kek.jp` | Step 2 で脱落（ICMP・443 とも到達せず） |

## Step 5 の実施結果（2026-07-30、pSConfig 切替と同時）

選定 2 台を `deploy/psconfig/home-lab-mesh.json` に投入した。詳細は `w3-notes.md` Step 10。

| path.id | 宛先 | 投入したタスク | 間隔 |
|---|---|---|---|
| `wan-sinet-tokyo` | `perf-tokyo.sinet.ad.jp` | latency(twamp) + rtt(**twping**) | PT15M |
| `wan-riken-tsukuba` | `ps-tkb-100g.riken.jp` | latency(twamp) + rtt(**twping**) | PT15M |
| `wan-google` | `8.8.8.8` | rtt(ping) + trace | PT5M / PT30M |

- **RTT を twping で取る**のは、片道遅延と同一プロトコル・同一パケット系にして
  非対称（RTT − 片道 − 片道）にプロトコル差を混入させないため。Step 3 の手動実測と同じ組
- **`wan-google` は選定作業の産物ではない。** 商用網の参照が Cloudflare 1 本しかない
  構造的な弱点への対処（`w3-notes.md` Step 9）。1.1.1.1 と同じ ping・同じ PT5M にして対照になるようにした
- **`wan-owd` の test spec は `source` を書かない形で `psconfig validate` を通った。**
  CLI の手動実測で通ったからといって pSConfig のスキーマで通るとは限らないと見ていたが、通った
- 相手先への負荷: 公開ホスト 2 台 × (100 発 + 10 発) × 4 回/時。**throughput は張っていない**

### 残っている宿題

- **GbE 化後の非対称の再測定。** 受信方向の +0.94ms は解消済み（`w3-notes.md` Step 8）なので、
  15 分間隔の本番測定が貯まれば、残る非対称は経路由来と言い切れる。**選定 2 台については
  常時観測に載ったので、あとは眺めるだけ**
- **大阪の −0.39ms の確認は未着手。** `perf-osaka.sinet.ad.jp` は補欠のままで本番に入れていない。
  NIC の癖では説明できない唯一のホストなので、3 本目を足すならこれ

## 相手先への負荷（実績）

| 内容 | 実績 |
|---|---|
| Step 2 | 候補 8 台 × (`ping` 3 発 + `pscheduler ping` 1 回) |
| Step 3 | twamp 7 台 × 100 発、rtt フォールバック 2 台 × 10 発、twping rtt 5 台 × 10 発 |
| Step 4 | twamp 5 台 × 100 発 × 2 回（R2・R3）、rtt 2 台 × 10 発 × 2 回 |
| throughput (iperf3) | **一切張っていない** |
| リトライ | **していない**（拒否・無応答とも 1 回で打ち切り） |

`Run rejected` は一度も出なかった。limits に触れる操作はしていない。

## 検証結果

| 項目 | 結果 |
|---|---|
| LG Gram の testpoint | `pscheduler troubleshoot` オールOK（着手前・作業後とも） |
| LG Gram の残留タスク | **0 件**。`pscheduler task` は単発実行で、繰り返しタスクを残さない |
| VM の本番タスク | 8 タスクが正常にスケジュール済み。**欠測なし** |
| Splunk への着弾 | `check-charts.sh` で**直近 6 時間・全 7 チャートにデータあり** |

作業中に VM・RasPi・pSConfig・Splunk の設定は一切変更していない。
