# W2 検証メモ

ハマりポイント・判断の記録。記事の一次情報になるため、失敗もそのまま残す。

## テンプレート
- 日付:
- やったこと:
- 結果 / エラー:
- 判断・回避策:

## Step 0: LAN 基準線の測定方式を再決定（twamp 片道遅延 → rtt + twping）

- 日付: 2026-07-27
- やったこと: W1 で確定した「LAN 基準線は twamp(latency)」という設計が実測と食い違っていたため再検討。
  fable5 モデルにセカンドオピニオンを求め、その示唆を実機で検証した。
- 結果 / エラー:
  - `docs/samples/latency-twamp-*.json` の中身を確認したところ `max-clock-error: 27.47`、
    `histogram-latency` は 89 ビン全てが **-11.71 〜 -11.86 ms の負値**。片道遅延が負になるのは
    物理的にあり得ず、VM ゲストのクロックオフセットがそのまま出ている。
  - 設計済みの品質ゲート（`max-clock-error` 閾値超過で欠測扱い）を実装すると、LAN 区間の遅延
    メトリクスは常時ゲートアウトされ Splunk に 1 件も届かない状態だった。
  - さらに w1-notes.md:42 に **`max-clock-error` が 0.0ms と報告されながら片道遅延が
    中央値 -4.62ms / 最小 -23.92ms と壊れていた**記録があり、ゲート自体に偽陰性の実例がある。
  - fable5 の指摘: TWAMP は Sender-Reflector 間の4タイムスタンプ(T1-T4)から
    `(T4-T1)-(T3-T2)` でクロック非依存の RTT を算出できるはずで、pScheduler の `latency`
    テストに RTT が無いのはプロトコルの限界ではなく pScheduler 側の出力仕様ではないか。
  - 実機検証: VM コンテナ内で `twping -c 10 192.168.1.101` を直接実行したところ、
    **`round-trip time min/median/max = 0.777/1/1.16 ms` と two-way jitter が出力された**。
    同じ測定の中で `send time` は -0.874/-0.8/-0.525 ms と負に壊れている。
    つまり片道遅延が壊れていても RTT は正しい。仮説は当たり。
  - さらに `pscheduler plugins` で確認すると **`twping` の対応テストは `['latency','rtt']` の2つ**。
    `pscheduler task --tool twping rtt --source ... --dest ...` を実行すると、
    **ICMP ping 版の `rtt` と完全に同一スキーマ**（`mean`/`min`/`max`/`stddev`/`loss`/`roundtrips[]`）
    で RTT が返った（平均 0.944ms、20パケット、ロス0%）。
- 判断・回避策:
  - **LAN 基準線の RTT は `rtt` テストを `--tool twping` で取得する。** ICMP ping の追加は不要。
    docs/schema.md のマッピングがそのまま使えるためブリッジの追加実装ゼロ。ICMP と違い
    レート制限・優先度低下の影響も受けない。
  - `latency`(twamp) は参考値に降格し、`max-clock-error` 品質ゲートの実演材料として残す。
    ゲート閾値の初期値は 5.0ms（正常時 0.0ms / 異常時 27.47ms の中間）。
  - 「クロックオフセットが一定なら変化量で片道遅延を救える」案は不採用。w1-notes:71 の
    codex:rescue 所見の通り、Lima hostagent の 10秒周期 `settimeofday` と chronyd の競合で
    断続的なステップ補正が入るため、tc netem の注入分と区別できない。ただし netem 実験で
    「RTT では 100ms がくっきり見えたが片道遅延はゲートで欠測になった」という**対比のデモ**
    としてなら正直に使える。
  - tc netem 実験の手順に、注入前後の `chronyc tracking` 記録ステップを追加すること（PROJECT.md 済）。
  - サンプル保存: `docs/samples/rtt-twping-192.168.1.101-20260727-193317.taskoutput.json`
    （`.taskoutput` サフィックスは archiver 封筒無しの `pscheduler task --format json` 出力の意味）
  - 副産物: archiver 封筒に `reference` キーが実在（手動 task では `null`）→ `path.id` は
    `.reference["path.id"]` で確定。`ps.tool` の取得元は `.task.tool` ではなく **`.tool.name`**。

### 記事ネタ

同じ TWAMP 測定でも、pScheduler の `latency` テストで実行すると `twping` が計算した RTT と
two-way jitter は捨てられ、`histogram-latency`（片道）しか JSON に残らない。`rtt` テストで
実行すれば RTT が得られる。「TWAMP＝片道遅延」という思い込みと、仮想化ゲストのクロック限界に
ぶつかってこの解に辿り着いた過程はそのまま1節になる。

## Step 1: OTel Collector → Splunk O11y 疎通確認

- 日付: 2026-07-27
- やったこと: ブリッジ実装前に Collector 単体で Splunk への着弾を確認。以降の失敗を
  ブリッジ側のバグと切り分けられる状態を作るのが目的。
- 結果 / エラー:
  1. **Mac の Docker Desktop が起動していなかった**（`docker.sock` が無い）。`open -a Docker` で起動、約20秒。
  2. まず切り分けのため Collector を通さず ingest API へ直接 curl → **HTTP 200 `"OK"`**。
     realm(`jp0`)・INGEST トークンともに有効と確定。
  3. Collector をコンテナ起動 → 受信は HTTP 200 だが exporter が
     **`401 Unauthenticated` で Dropping data**。直接 curl は通るのに Collector だけ落ちる。
  4. 原因: **`.env` の `SPLUNK_ACCESS_TOKEN` 行にインラインコメントが付いていた。**
     shell の `. ./.env` は 22文字と解釈するが、`docker --env-file` は
     **コメントごと 67文字**の値として渡す。`.env.example` の
     `SPLUNK_ACCESS_TOKEN=changeme   # INGEST token...` という書式を実 `.env` が踏襲したため。
     busybox に同じ `--env-file` を渡して `${#VAR}` を比較して確定（22 vs 67）。
- 判断・回避策:
  - `.env` は規約により編集しない。**トークンは shell 経由で渡す**方式を採用:
    ```bash
    set -a; . ./.env; set +a
    docker run -e SPLUNK_REALM -e SPLUNK_ACCESS_TOKEN ...
    ```
  - `.env.example` からインラインコメントを排除し、この罠を注記（再発防止）。
  - Collector 設定の非推奨エイリアスを修正: `otlphttp` → **`otlp_http`**（0.157 で非推奨警告）。
  - イメージを `otel/opentelemetry-collector-contrib:0.157.0` に固定（`:latest` は再現性を損なう）。
  - **検証結果（最終）**: 起動時の警告・エラーゼロ、
    `otelcol_receiver_accepted_metric_points = 1` / `otelcol_receiver_refused = 0` /
    `otelcol_exporter_sent_metric_points{exporter="otlp_http/splunk"} = 1`、送信失敗ゼロ。
    OTLP JSON → Collector → Splunk ingest の経路が通った。
  - 送ったメトリクスは実測値を使用: `perfsonar.rtt.mean = 0.944 ms`、属性
    `ps.source=192.168.1.104` / `ps.destination=192.168.1.101` / `ps.test.type=rtt` /
    `ps.tool=twping` / `stage=collector-selftest`。
  - **未確認**: Splunk UI 側での目視確認（Metric Finder で `perfsonar.rtt.mean` を検索）は未実施。
    `.env` には INGEST トークンしか無く API 経由でのクエリができないため。
  - 副次的な確認: **Docker 経由ならリスニングソケットを掴めた**（ポートを bind するのは
    Docker デーモンでサンドボックス化されたプロセスではないため）。ブリッジも compose 経由で動かす方針。
  - **2026-07-27 追記: Splunk の Metric Explorer で `perfsonar.rtt.mean` の表示を確認済み。**

## Step 2: ブリッジ実装（TDD）

- 日付: 2026-07-27
- やったこと: 規約の Step 0（既存実装調査）→ TDD で `bridge/` を実装。
- 結果 / エラー:
  - **既存実装の調査結果: perfSONAR → OpenTelemetry のブリッジは GitHub に存在しない。**
    `gh search repos` で "perfsonar opentelemetry" / "perfsonar otel" / "pscheduler prometheus" /
    "perfsonar exporter metrics" いずれも 0 件。ヒットするのは Grafana デモ
    （`luanrios/perfsonar-grafana-demo`、perfSONAR 自前の Esmond/OpenSearch 前提）と
    perfSONAR 公式の ansible-role-grafana のみで、OTel 経路のものは無い。**記事の独自性の根拠**。
    流用元が無いため自作した。
  - テスト 29 件、すべて `docs/samples/` の実測 JSON をフィクスチャに使用（モックなし）。
  - **TDD の失敗を1件記録**: 100%ロス時にキーが省略される挙動のテストを書いたら即座に通った。
    先に `if "mean" in result` のガードを書いてしまっていたため。ガードを外して赤を確認したところ
    **`perfsonar.rtt.mean = 0.0` が送信される**ことが判明。100%ロスのリンクが
    「遅延0msの健全なリンク」としてダッシュボードに出る危険なバグで、テストが実際に
    これを捕まえることを確認してからガードを戻した。テストを先に書かないと
    「通ることは確認できても、バグを捕まえられるかは確認できない」の実例。
  - **設計判断: OTLP を OpenTelemetry SDK ではなく手組みした。** SDK の Gauge 計測器は
    記録時刻を自動で打つため、`run.end-time`（測定時刻）を観測時刻に指定できない。
    schema.md はブリッジ到着時刻ではなく測定時刻を使うことを要求しているので、
    OTLP/JSON を直接組んで POST する方式にした。`opentelemetry-sdk` 依存は削除。
  - **E2E 検証**: 実 Collector に対して全6サンプルをブリッジ経由で流し、
    Collector のカウンタが **11/11 送信・拒否0・失敗0・エラーログ0行**であることを確認。
    実行時の挙動も設計通り:
    - `latency-twamp`: ロス率のみ（`max-clock-error 27.47` > 閾値5.0 で遅延はゲートアウト）
    - `rtt-FAILED`: ロス率のみ（`mean`/`max` キー欠落で遅延を出力しない）
    - `throughput`: bps のみ（95KB の `intervals[]` は変換しない）
- 判断・回避策:
  - `pscheduler task --format json` の出力（`.taskoutput.json`）は封筒が無いためブリッジには
    通せない。E2E では除外した。
  - **残っている既知の弱点**（W2 の後続で対処）:
    1. 未知のテスト種別（dns/http 等）は空リストを返して黙って捨てる。設定した4種以外を
       流すとデータが消えるが警告が出ない。
    2. `emit` が同期 I/O のまま async ハンドラ内で動くのでイベントループを塞ぐ。
       5分間隔・1リクエストずつの現構成では実害が無いため放置している。
    3. `rtt` + `twping` の**archiver 封筒付きサンプルが未取得**。合成データでしか
       `ps.tool=twping` を検証していない。pSConfig 本番化時に実物で確認する。
       → **Step 3 で解消**（実物を捕獲して `docs/samples/rtt-twping-192.168.1.101-archiver.json` に保存）。

## Step 3: compose 化と archiver 実経路の疎通

- 日付: 2026-07-27
- やったこと: ブリッジと Collector を `deploy/mac/compose.yaml` にまとめ、VM の testpoint から
  実際の pScheduler archiver 経由でメトリクスを流した。
- 結果 / エラー:
  - **ホスト側ポート 8000 が使えなかった。** Hermes Agent 系の `honcho-api` コンテナが
    `127.0.0.1:8000` を、別の Python プロセスが `*:8000` を掴んでいた。他人の稼働サービスなので
    触らず、**ブリッジの公開ポートを 8088 にずらした**（コンテナ内は 8000 のまま）。
    archiver の `_url` もこのポートを指す。
  - Mac の LAN IP は **192.168.0.1**（`/22` なので 192.168.1.x の VM/RasPi と同一セグメント）。
    testpoint コンテナから 0.331ms で到達。
  - `pscheduler task --archive=@/tmp/archiver.json --tool twping rtt ...` で実経路が通った。
    ブリッジのログに `PUT /archive HTTP/1.1" 200 OK`、Collector のカウンタが
    **1 → 4（rtt の3メトリクス増）**、エラー0行。
  - **実データが浮動小数点のバグを炙り出した。** 捕獲した実封筒の `PT0.001301S` を変換すると
    `1.3010000000000002 ms` になった。`float(x) * 1000` の乗算誤差。それまでのサンプル
    （9.059 等）はたまたま正確に出ていただけで、テストも通っていた。
    **`Decimal` で桁移動してから float に落とす**よう修正。実経路を通さなければ見つからなかった。
- 判断・回避策:
  - archiver 定義はインライン JSON だと多段シェルで引用符が壊れるため、コンテナ内のファイルを
    `--archive=@/tmp/archiver.json` で参照する方式（W1 の既知の落とし穴どおり）。
  - 封筒の捕獲は W1 と同じく、`do_PUT` するだけの使い捨て HTTP サーバをコンテナで立てて
    別ポート(8089)に archiver を向ける方式。検証後に削除した。
  - compose は `env_file` を使わない。`.env` のインラインコメント問題（Step 1）を踏むため、
    `${SPLUNK_ACCESS_TOKEN:?}` でシェル環境から補間する。起動前に
    `set -a; . ./.env; set +a` が必須で、忘れると compose がエラーで止まる（黙って 401 にならない）。
  - **未実施**: RasPi 側 testpoint からの archiver 経路は未確認（VM からのみ確認）。
    pSConfig 本番化で両方向を通す。→ **Step 4 で解消**。

## Step 4: pSConfig 本番化

- 日付: 2026-07-27
- やったこと: `deploy/psconfig/home-lab-mesh.json` を本番定義として書き、VM と RasPi の両方に配置。
- 結果 / エラー:
  - **エージェントが 7/26 からクラッシュループしていたことが判明。** `run-testpoint.sh` はホストの
    `~/psconfig` を `/etc/perfsonar/psconfig` にマウントするが、**ホスト側が空だとイメージ既定の
    `pscheduler-agent.json` と `pscheduler-agent-logger.conf` が隠れる**。エージェントは設定を
    見つけられず `status=1/FAILURE` で再起動を繰り返していた（RasPi 側の再起動カウンタは 3354）。
    W1 では手動 task しか使っていなかったため気付かなかった。
    → 既定ファイルをイメージから取り出して `deploy/psconfig/` に取り込み、両ノードに配置して解消。
  - **`psconfig validate` が実エラーを2件捕まえた:**
    1. `latency` の spec に `protocol` を書くと `Additional properties are not allowed
       ('protocol' was unexpected)`。**`"schema": 4` が必須**だった。`validate.py:490` が
       `"$ref": "#/local/v%s" % json.get("schema", 1)` で、省略すると v1 が使われる。
       `protocol` は v4 でしか定義されていない。手動 task の実サンプルには `schema: 4` が
       入っていたが、テンプレートに書き写す際に落としていた。
    2. `psconfig remote add` は URL を `--quiet` より先に置かないと `unrecognized arguments`。
  - **pSConfig の schedule は `repeat-cron` に非対応。** pScheduler 単体は `--repeat-cron` を持つが、
    pSConfig の `ScheduleSpecification` は `start`/`repeat`/`slip`/`sliprand`/`until`/`max-runs` のみで
    `additionalProperties: False`。「6時間ごと、ただし深夜帯だけ」が表現できないため、
    iperf3 は絶対時刻 `start: 2026-07-27T18:00:00Z`（= 翌 03:00 JST）+ `repeat: P1D` +
    `slip: PT30M` とした。pScheduler 上で **03:00 JST 開始・最遅 03:30 JST** を実測確認し、
    CLAUDE.md 規約2（02:00-06:00 JST）を満たすことを確定。
  - **`path.id` が確定した（W1 からの持ち越し課題）。** タスク定義だけでなく、実際に archiver が
    送る封筒に `"reference": {"path.id": "lan-wired"}` が乗ることを捕獲して確認。ブリッジが
    3メトリクスすべてに `path.id` 属性を付けることも実データで検証済み。
    なお pSConfig 経由だと `reference` には `psconfig.created-by`（uuid / agent-hostname）も
    同時に入るが、ブリッジは `path.id` キーのみ見るので影響しない。
  - **生成タスク: VM 6 / RasPi 3。** mesh グループが LAN を双方向に展開し、WAN タスクは
    a-address が `vm` のため RasPi 側では正しくスキップされた。
    - VM: rtt/twping・latency/twping・throughput/iperf3（→RasPi）、rtt/ping ×2・trace（→WAN）
    - RasPi: rtt/twping・latency/twping・throughput/iperf3（→VM）
  - **両ノードからブリッジへの流入を確認。** Collector 13 → 21（+8メトリクス）、
    PUT 3 → 7（+4アーカイブ）。rtt が3メトリクス、latency が1メトリクス（遅延はクロックゲートで
    落ちる）で計算が合う。拒否0・失敗0・エラーログ0行。
- 判断・回避策:
  - **コンテナは作り直していない。** `/etc/perfsonar/psconfig` はホストのバインドマウントなので、
    ファイルを配ってエージェントを `systemctl restart` するだけで反映される（規約4の
    「stop で state が消える」問題を回避）。
  - pSConfig エージェントは初回巡回を終えるまで `psconfig pscheduler-tasks` が
    `Unable to find last guid ...` を返す。RasPi では 20 秒ほどかかった。落ちているのと
    区別しづらいので、判断は `systemctl is-active` とログの両方で行うこと。

## Step 5: VM のクロックが収束し、品質ゲートの閾値が不適切になった

- 日付: 2026-07-27（runbook-w2.md 執筆中に発見）
- やったこと: netem 実験の前提確認で `chronyc tracking` を見たところ、W1 と値が全く違っていた。
- 結果 / エラー:
  - **W1 で問題視していた VM のクロックが収束していた。**

    | 項目 | W1（2026-07-26） | 現在（2026-07-27） |
    |---|---|---|
    | chrony Frequency | 10061.376 ppm | **2.894 ppm** |
    | chrony Skew | 43.566 ppm | **0.142 ppm** |
    | System time | — | 0.00037 秒 slow |
    | TWAMP max-clock-error | 27.47 ms | **4.67〜4.88 ms** |
    | 片道遅延 | -11.71〜-11.86 ms（負値） | **+1.37〜+6.66 ms（正常）** |

    codex:rescue が指摘した「Lima hostagent の settimeofday と chronyd の競合」は、
    時間が経って chronyd 側が収束したことで解消したように見える。W1 の 10061 ppm は
    やはり定常状態の値ではなく、収束途上の見かけ上の推定値だった可能性が高い。
  - **その結果、品質ゲートの閾値 5.0ms が不適切になった。** 直近10 run の max-clock-error は
    4.67 / 4.67 / 4.73 / 4.76 / 4.79 / 4.79 / 4.79 / 4.85 / 4.88 / 4.88 ms と密集しており、
    閾値まで **0.12〜0.33ms しか余裕がない**。全 run が現状ゲートを通過しているが、
    わずかに悪化しただけで片道遅延メトリクスが消え、Splunk 上で系列が断続する。
  - 閾値 5.0 の当初の根拠は「正常時 0.0ms / 異常時 27.47ms の中間」だったが、
    **正常時が 0.0ms ではなく約 4.8ms だと判明したため根拠が崩れている。**
- 判断・回避策:
  - **未対応。閾値の見直しはオーナー判断待ち。** 推奨は 10.0ms への引き上げ。
    観測された正常域（〜4.88ms）と明確な異常（27.47ms）の間に十分な余裕を取れる。
  - 「正常時 0.0ms」という W1 の観測自体、experiments/w1-notes.md:42 の偽陰性
    （0.0ms 報告なのに片道遅延が壊れていた）と整合しない。**`max-clock-error` が 0.0 を返すのは
    「誤差が無い」ではなく「推定できていない」を意味する可能性がある。** 閾値を見直すなら
    0.0 を「良好」ではなく「不明」として扱う分岐も併せて検討する価値がある。
  - 記事的には、W1 で「クロックが壊れているから片道遅延は使えない」と判断した後、
    W2 で収束して使えるようになり、しかし今度は閾値の根拠が崩れる、という一連の流れが
    「実測に基づく設計は動く標的である」という具体例になる。

## Step 5-訂正: 「クロックが収束した」は誤り。標本の偏りだった

- 日付: 2026-07-28
- **Step 5 の「VM のクロックが収束した」という結論は誤りだったので訂正する。**
- 何が起きたか: Step 5 では直近10 run の `max-clock-error` を見て 4.67〜4.88ms に密集していると
  報告した。しかしこれは **21:05〜21:52 JST という安定していた一区間だけを切り取った標本**であり、
  1日分（約130 run）を全件確認すると全く違う姿だった。
- 実態: `max-clock-error` は **0.00 〜 785.16 ms** の間を大きく振れ、片道遅延は
  **-942 ms 〜 +2045 ms** まで振れる。LAN の RTT が約0.9msであることを考えると、
  これらは全て物理的にありえない値。安定した区間（0.1〜0.25ms程度）と
  荒れた区間が数十分〜数時間おきに交互に現れる。
  W1 で codex:rescue が指摘した「Lima hostagent の周期的な settimeofday と chronyd の競合」
  という診断のほうが、収束仮説より実態に合っている。
- **iperf3 との因果は無い。** 30分間隔化の前後で荒れ方は変わらず、荒れた区間は
  iperf3 が走っていない時間帯にも等しく現れる。スケジュール変更は原因ではない。
- 教訓: **短い連続標本から定常性を結論しない。** 周期的に状態が変わる系では、
  10点の密集は「収束した」ではなく「たまたま安定区間を見た」でしかない。

## Step 5-2: max-clock-error は品質ゲートとして機能しない

- 日付: 2026-07-28
- やったこと: 上記の全件データで、ゲートを通過した run の片道遅延が妥当かを確認した。
- 結果: **ゲートを通過した約55件のうち、少なくとも15件（約27%）が物理的にありえない値だった。**

  | 時刻 | max-clock-error | 片道遅延 | 判定 |
  |---|---|---|---|
  | 22:16-22:25 | 4.37〜4.40 | **+104.9〜105.8 ms** | 通過（LAN で105msはありえない） |
  | 01:50-01:55 | 0.23〜0.24 | **+101.8〜102.3 ms** | 通過 |
  | 06:25:24 | 9.83 | **+125.7〜132.1 ms** | 通過 |
  | 06:46:31 | 1.38 | **-33.3〜-17.7 ms** | 通過（負値） |
  | 00:21-00:50 | 0.10〜0.15 | **-0.8〜-0.2 ms** | 通過（負値） |

- **結論: `max-clock-error` に閾値を置く設計そのものが不十分。** 閾値を何 ms にしても、
  誤差 0.23ms と自己申告しながら片道遅延 102ms を返すデータは止められない。
  W1 で見つけた偽陰性（w1-notes.md:42）は例外ではなく常態だった。
- 判断・回避策（未実装、オーナー判断待ち）:
  - **値そのものの妥当性検査を足すべき。** 最低限「片道遅延の中央値が正であること」は
    物理的な必要条件で、これだけで負値のケースは全て落とせる。
    加えて LAN 区間なら上限（例: 50ms）を置けば +102ms 系も落とせる。
  - SLO の主指標は `rtt`+`twping` に移してあるので、この問題は主要メトリクスには影響しない。
    片道遅延の役割は「データ品質ゲートの実演」であり、**その実演の内容が
    『プロトコル自身の誤差見積もりは信用できず、値の妥当性検査が要る』に変わる**だけ。

### 記事ネタ

TWAMP の `max-clock-error` はプロトコルが提供する品質指標なので、これを信じてゲートを作るのは
自然な設計に見える。しかし実測すると、誤差 0.23ms と申告しながら LAN で片道遅延 102ms を返す。
**「計測系が自己申告する品質指標を検証せずに信じてはいけない」**という具体例として書ける。
あわせて「10点の連続標本を見て収束したと誤判断した」という自分の失敗も、
標本の取り方の教訓として使える。

## Step 6: iperf3 の通信影響を実測し、時間帯限定を解除

- 日付: 2026-07-28
- やったこと: 「iperf3 が家族のネット利用に影響する」という CLAUDE.md 規約2 の前提を実測で検証した。
  手動実行は追加せず、**スケジュール済みの本番 run（03:06:42-03:07:13 JST）を外部から観測**した。
- 測定設計:
  - **pScheduler のスケジューリングクラスを確認したのが出発点。** throughput は `exclusive`、
    rtt は `background`、latency は `normal`。**つまり pScheduler は iperf3 実行中に自分の他の測定を
    走らせない。**自前のメトリクスを見ても影響は写らない設計なので、外部からの独立観測が必要だった。
  - Mac から 1 秒間隔で 2 経路に ping（各2700発、45分間）。
    WAN = 1.1.1.1（家族のインターネット利用の代理）、LAN = 192.168.1.101（iperf3 が飽和させる経路）。
- 結果:

  | 経路 | 区間 | n | 中央値 | p95 | max |
  |---|---|---|---|---|---|
  | WAN (1.1.1.1) | 実行前 | 2085 | 8.795 | 9.888 | 46.426 ms |
  | | **実行中** | 35 | **9.506** | 10.677 | 13.419 ms |
  | | 実行後 | 580 | 8.846 | 10.157 | 13.823 ms |
  | LAN (RasPi) | 実行前 | 2083 | 0.554 | 0.662 | 1.594 ms |
  | | **実行中** | 35 | **1.326** | 1.463 | 1.510 ms |
  | | 実行後 | 582 | 0.549 | 0.667 | 4.349 ms |

  - **パケットロスは両経路とも 2700発中 0。**
  - iperf3 側: 939.9 Mbps、再送11。
  - 生データを見ると**遅延が上がったのは 18:06:46-18:07:04 UTC の約19秒だけ**で、
    設定した `duration: PT20S` と一致。run 全体の31秒のうち残りはセットアップと後片付け。
  - ブリッジの受信ログでも iperf3 前後に測定の空白は無かった（`exclusive` による他測定の
    ブロックは実害として観測されず）。
- 判断・回避策:
  - **時間帯限定（02:00-06:00 JST）を解除し、終日30分間隔に変更。** WAN の RTT が +0.71ms（+8%）、
    ロス0 では家族のネット利用が体感できるレベルではない。家庭用ルーターが LAN 内スイッチングを
    ハードウェア処理しているため WAN 側にほぼ波及しない、という想定どおりの結果だった。
  - **5分間隔にはしなかった。** 理由は2つ。(1) 有線GbEのスループットは 929〜940Mbps と
    変動1%程度で極めて安定しており、高頻度サンプリングの情報量が小さい。
    (2) throughput は `exclusive` クラスなので、同じく5分間隔の `latency` と頻繁に衝突して
    測定時刻が乱れる（失われはせず slip するが系列が汚れる）。
  - **手動実行前のユーザー確認という規約は維持。**頻度をさらに上げる場合は再度実測すること。
  - スケジュール変更に伴い `nightly-0300jst` は不要になったので削除し、既存の `every-30min` を流用。
    repeat-cron 非対応の知見は deploy/psconfig/README.md と Step 4 に残っている。

### 記事ネタ

「iperf3 は帯域を食うから深夜に限定」というのは直感的に正しそうに見えるが、**実測すると
LAN 内の GbE 飽和は WAN 側にほとんど波及しない**（家庭用ルーターがハードウェアスイッチングする限り）。
制約を実測で検証して緩めた例として書ける。同時に「pScheduler の `exclusive` クラスのせいで
自分の測定では影響が見えない」という落とし穴も含められる。

## Step 7: 片道遅延に値の妥当性検査を追加

- 日付: 2026-07-28
- やったこと: Step 5-2 で判明した「max-clock-error 単体ではゲートにならない」問題への対処。
- 結果 / エラー: 判定条件を2段にした。

  ```
  0 < max-clock-error <= 10.0    （クロック誤差のゲート）
  0 < 片道遅延の中央値 <= 50.0    （値の妥当性）
  ```

  実データ141 run で比較:

  | ゲート方式 | 出力数 | うち異常値 | 汚染率 |
  |---|---|---|---|
  | 旧（誤差 ≤ 5.0） | 64 | 22 | 34.4% |
  | 中間（0 < 誤差 ≤ 10.0） | 57 | 17 | 29.8% |
  | 新（誤差 + 値の妥当性） | **40** | **0** | **0.0%** |

  57→40 で除かれた17件がちょうど汚染分と一致し、正常な40件は失われていない。
- 判断・回避策:
  - 上限 50ms は LAN ペア（RTT 約0.9ms）前提。WAN で `latency` を使うなら要変更。
  - 評価の厳密性: 負値の排除は判定条件と評価基準が同じなので自明。上限側は判定50ms・
    評価20msと異なり、その間に該当標本が無かったので循環していない。

## Step 8: カーディナリティ爆発。API トークンで初めて見えた欠陥

- 日付: 2026-07-28
- やったこと: `.env` に User API Access Token を追加してもらい、Splunk 側を API で初めて確認した。
- 結果 / エラー:
  - まず正常性の確認は取れた。本番6メトリクスすべてが GAUGE として登録され、
    `path.id` / `ps.source` / `ps.destination` / `ps.test.type` / `ps.tool` の全 dimension が到達していた。
  - **その上で重大な欠陥が見つかった。時系列（MTS）が異常に多い。**

    | メトリクス | 実際の系列数 | あるべき数 |
    |---|---|---|
    | perfsonar.packet.loss.ratio | **269** | 6 |
    | perfsonar.twamp.delay.median | **64** | 2 |

  - 原因: **`ps.max_clock_error` と `ps.retransmits` を attribute にしていた。**
    これらは測定ごとに値が変わる数値で、Splunk は dimension の組み合わせごとに別々の
    時系列を作る。つまり **1 run ごとに新しい時系列が生まれ続ける**。
    latency は5分間隔×双方向で1日約576 run なので、日々数百ずつ無制限に増える。
  - 実害2点: (1) Free Edition のカスタムメトリクス枠を圧迫する。
    (2) **ダッシュボードが成立しない。**「`path.id` 別にロス率を表示」すると269本の線が引かれる。
  - **この欠陥は Collector のカウンタからもブリッジのテスト32件からも見えなかった。**
    Splunk の `/v2/metrictimeseries` を API で覗いて初めて分かった。
- 判断・回避策:
  - 測定ごとに変わる数値は Gauge メトリクスに移した。
    `ps.max_clock_error` → `perfsonar.twamp.clock_error`（ms）
    `ps.retransmits` → `perfsonar.throughput.retransmits`（{retransmits}）
  - 情報は失われず、むしろクロック誤差が時系列になったので**品質ゲートの挙動を
    1枚のチャートで見せられる**（誤差が跳ねた時刻に片道遅延が欠測する対比）。
  - 修正後の確認: `perfsonar.twamp.clock_error` は **2系列**（方向ごと）で
    `ps.max_clock_error` が dimension から消えた。ロス率も新規は**11系列**
    （うち本番6、残り5は開発中の手動テスト残骸）に収まり増殖が止まった。
    旧261系列は凍結され時間とともに非アクティブになる。
  - 記事のスクリーンショット前に整理したいもの: 疎通確認で作った
    `perfsonar.bridge.selftest`、`path.id` が null の手動テスト由来系列。

### 記事ネタ

**「メトリクスが届いていること」と「メトリクスが使えること」は別**という具体例。
Collector のカウンタは 2500件送信・失敗0 と健全そのものを示し、ブリッジのテストも全通過。
それでもダッシュボードは作れない状態だった。OTel の attribute はそのまま Splunk の
dimension になるので、**attribute に何を置くかがコスト構造と可視化可能性を直接決める**。
「変わる数値は metric、変わらない識別子は attribute」という原則を、
269系列という実測値付きで書ける。

## Step 9: ログによるディスク圧迫の点検

- 日付: 2026-07-28
- やったこと: 過去の perfSONAR 運用でログがディスクを圧迫した経験があるとのことで、
  現構成のログ増加を実測で点検した。
- 結果 / エラー:
  - **perfSONAR 側（VM / RasPi）は testpoint イメージ側で対策済みだった。**
    - `logrotate.timer` が稼働（点検時点で4時間前に実行、次回19時間後）
    - `/etc/logrotate.d/` に `pscheduler-server` `rsyslog` `apache2` `postgresql-common` 等
    - `lsregistrationdaemon.log` が `.1` `.2` と世代管理されており、実際に回っている
    - pSConfig エージェントのログは Python の `RotatingFileHandler` で **16MB × 7世代**の上限
      （`deploy/psconfig/pscheduler-agent-logger.conf`。リポジトリにコミット済み）
    - 実測: コンテナ内 `/var/log` 合計 **19MB**（2日稼働）。syslog 6.3MB / messages 6.1MB /
      apache2 3.1MB / perfSONAR 関連 572KB
  - ディスク余裕: VM 4.6G/96G (5%)、**RasPi 9.0G/30G (33%、`/dev/mmcblk0p2` = SDカード)**。
    RasPi が構造的に一番弱いが、19G空きとローテートが効いており当面問題なし。
  - pScheduler DB: 15MB、run 1328件、2.5日分。デーモン設定は全てデフォルト（空）で
    pScheduler 本来の内部メンテナンスに任せる形。**まだ purge が働くほど古くなっていないだけ**
    なので、1週間後に再度サイズを見て頭打ちになるか確認すること。
  - **問題: Mac 側の compose に上限が無かった（自分で作り込んだ欠陥）。**
    `psotel-bridge` / `psotel-collector` とも json-file ドライバで
    `max-size` / `max-file` 未設定。`~/.docker/daemon.json` にも既定の `log-opts` 無し。
    実測サイズは 8.9KB / 1.9KB と小さかったが上限が無い。
- 判断・回避策:
  - `deploy/mac/compose.yaml` に YAML アンカーで `max-size: 10m` / `max-file: 3` を両サービスへ適用。
    1コンテナ最大30MBで頭打ち。直近30MBは残るので障害調査には足りる。
  - **危険なのは平常時ではなく異常時**という点を設定にコメントで残した。
    ブリッジは平常時 1アーカイブ1行で日に100KB未満だが、W2 Step 1 の 401 ループのように
    エクスポート失敗が続くと Collector が1リクエストごとに複数行のエラーを吐く。
    今回入れた「変換失敗を例外ログに残す」修正も、pScheduler の JSON 形状が変われば
    全リクエストで発火するので同じ性質を持つ。
  - 適用後の確認: 両コンテナに `max-file:3 max-size:10m` が入り、
    PUT 4件・エラー0行・拒否0でパイプラインは正常。

### 記事ネタ

自宅ラボや小規模構成では「動いた」で終わりがちだが、**定点観測は動き続けることが前提**なので
ログとDBの増加は最初に潰しておく箇所。perfSONAR 公式イメージは logrotate まで
面倒を見てくれている一方、**自分で足した compose の側に穴があった**という対比が書ける。
RasPi は SD カードなので特に効く話。

## Step 10: archiver に retry-policy が無く、1回の失敗で測定結果が消えていた

- 日付: 2026-07-29
- やったこと: netem 障害注入実験（Step 7）の前提を点検していて、
  `home-lab-mesh.json` の `archives.otel-bridge.data` に `retry-policy` が無いことに気づいた。
  VM 上の http archiver プラグインの実装を読んで挙動を確認した。
- 結果 / エラー:
  - `/usr/lib/pscheduler/classes/archiver/http/archive` の 204-208 行:

    ```python
    if "retry-policy" in json['data']:
        policy = pscheduler.RetryPolicy(json['data']['retry-policy'], iso8601=True)
        retry_time = policy.retry(json["attempts"])
        if retry_time is not None:
            result["retry"] = retry_time
    return result
    ```

  - **`retry-policy` が設定されているときだけ `result["retry"]` が返る。** 未設定なら
    `{"succeeded": False, "error": ...}` だけが返り、pScheduler は再送せずその run の結果を捨てる。
  - つまりこれまでは、ブリッジの再起動・Mac のスリープ・LAN の一時断のたびに、
    その間の測定が**無音で失われていた**。エラーはブリッジ側にもリポジトリ側にも残らない。
  - netem は測定経路とテレメトリ経路が同一（`lima0`）なので、この状態で注入すると
    「劣化を検知した」と「テレメトリが届かず欠測した」が区別できず、実験の信頼性が崩れる。
- 判断・回避策:
  - `retry-policy: [{attempts:3, wait:"PT30S"}, {attempts:4, wait:"PT5M"}]` を追加。
    合計7回・最大約21分。5分間隔のタスクに対して十分で、注入区間（15分程度）をまたげる長さ。
  - VM / RasPi 双方のホスト `~/psconfig` へ配布 → `psconfig validate` OK →
    `systemctl restart psconfig-pscheduler-agent` で反映。
  - **ハマり: 反映には30秒ほどかかる。** 再起動直後に `psconfig pscheduler-tasks` を叩くと
    まだ旧定義（retry-policy 無し）が返り、「配布に失敗した」と誤解する。RasPi で実際に踏んだ。
  - **観察: pSConfig は archive 定義が変わると別タスクとして作り直す。** 旧タスクは
    `until`（作成時 +24h）が切れるまで並存する。実測で lan-wired の rtt は
    retry あり2本 + retry なし3本が同時に見えた。データ点数は 24h で n≈288（= 5分間隔ぶん）
    なので pScheduler 側で重複 run は落ちており、測定頻度は増えていない。
    旧タスクは当日中に自然消滅するため放置してよい。

## Step 11: ダッシュボードと Detector を as-code で構築（UI 作業は不要だった）

- 日付: 2026-07-29
- やったこと: runbook Step 5 の「`.env` には INGEST トークンしか無く API から
  ダッシュボードを作れないため UI 作業になる」という前提を実地で検証した。
- 結果 / エラー:
  - **前提が誤りだった。** `.env` には `SPLUNK_API_TOKEN` があり、Free Edition でも
    `/v2/chart` `/v2/dashboard` `/v2/dashboardgroup` `/v2/detector` は POST/PUT とも通る。
  - **カスタム Detector の作成も可能**（ハンドオフの未解決事項1）。
    捨てる前提のプローブを1本 POST → `ACTIVE` で作成成功 → DELETE 204、で確認してから本作業に入った。
  - Splunk O11y の API 構造: **チャートを個別に POST してから、その ID を
    ダッシュボードの `charts[]` に row/column/width/height 付きで並べる。**
    ダッシュボードにチャートをインラインで書く形式は無い。グリッドは12カラム。
  - `POST /v2/detector/validate` が 204 を返せば SignalFlow の構文は妥当。投入前に潰せる。
  - **ハマり: `/v1/timeserieswindow` は連投すると
    `"Your role doesn't let you perform this action."` を HTTP 200 の本文で返す。**
    権限の問題に見えるが実体はレート制限で、数秒空ければ同じクエリが通る。
    調査スクリプトには待って再試行する分岐を入れた。
- 判断・回避策:
  - 定義の正を `deploy/splunk/` に置き、`apply.sh` で冪等に投入する形にした。
    生成 ID は `.ids.json` に記録し、2回目以降は同じ ID に PUT する（実際に2回流して確認）。
    UI で消された場合は GET が 404 になるので POST に倒れる。
  - **トークンは `curl -H` ではなく Python の urllib でヘッダに載せている。**
    `curl -H "X-SF-TOKEN: $TOKEN"` はプロセス引数に載るので `ps` で他ユーザーから見える。
  - チャートの programText は全て `.mean(by=[...])` で集約した。Step 8 のカーディナリティ爆発の
    残骸（旧 dimension を持つ系列が114本）があっても系列が増えず、放置で済む。

### 記事ネタ

- 「Free Edition だから UI でポチポチするしかない」は**確かめずに書いた思い込み**だった。
  ハンドオフ文書に残っていた前提を実地で1本叩いて潰す、という手順そのものが書ける。
- **`lasting()` ではなく `min(over='12m')` で「2データポイント連続」を表現した**話。
  `lasting()` は欠測区間で直前の値を引き延ばすため、5分間隔の疎な測定系列では意図と合わない。
  「窓内の全データポイントが閾値超え = 連続」という言い換えは、疎な系列の Detector 全般に効く。
- **スループットの静的閾値は妥協ではなかった。** 実測 936.7–941.3 Mbps・変動0.5%未満。
  「異常検知が常に上位互換」ではなく、**対象の分散を測ってから選ぶ**という話にできる。
- **TCP 再送数が方向で完全非対称**（104→101 は常に 11-12、101→104 は常に 0、80回で一度も逆転なし）。
  原因は未究明。定点観測を始めると「気づいてしまう」ものの例。

## Step 12: 再送は効いた。それでも Splunk のグラフは埋まらなかった

- 日付: 2026-07-29
- やったこと: Step 10 で入れた retry-policy が実際に効くかを、ブリッジを12分停止して検証した
  （停止 11:08:37 / 復旧 11:20:38）。停止区間のデータ点が後から埋まれば成功、という判定条件。
- 結果 / エラー:
  - **pScheduler 側では完璧に動いた。** run ごとの archivings 診断:

    ```
    run 11:09:48  archived=True  attempts=6
       11:09:53 succeeded=False retry=PT30S
       11:10:23 succeeded=False retry=PT30S
       11:10:53 succeeded=False retry=PT30S
       11:11:23 succeeded=False retry=PT5M
       11:16:23 succeeded=False retry=PT5M
       11:21:23 succeeded=True          ← 6回目で成功
    run 11:15:10  archived=True  attempts=5  → 11:21:46 に成功
    run 11:20:53  archived=True  attempts=1  → 11:20:58 に成功（復旧直後）
    ```

  - ブリッジは3件とも受信（PUT 200）。Collector も accepted 4884 / sent 4884 / **失敗0**。
  - **にもかかわらず Splunk に残ったのは 11:20:53 の run だけ。** 11:09:48 と 11:15:10 は
    どこにも無い。VM→RasPi と RasPi→VM の双方向で完全に同じ結果だった。
  - 切り分け: ブリッジは `run.end-time` を観測時刻に使っている（convert.py:90-92）ので
    タイムスタンプは測定時刻のまま。Collector も送出成功。**落ちているのは Splunk の ingest。**
  - **原因の切り分けに使い捨てメトリクスを投げた**（`lab.ingest.ordering.probe`）:
    - A: 新規 MTS に **10分前の点を単独で**送る → **着弾した**
    - B: 新規 MTS に「現在」→「5分前」の順で送る → MTS 自体が現れず（プローブとしては不成立）
  - A が通ったので「**古すぎるから落ちた」ではない**。実際に落ちた点は 6.6 分前のもので、
    しかも同じ MTS に既に新しい点（11:20:53）が書かれた後だった。
    **順序逆転で捨てられている**というのが最も整合する説明。ingest は HTTP 200 "OK" を返すので
    送信側からは一切見えない。
- 判断・回避策:
  - **これは構造的な現象。** pScheduler は5分段の再送で古い run を復旧するので、
    復旧点は必ず「その間に成功した新しい点」より後に届く。長い再送段を持つ限り必ず起きる。
  - 30秒段を 3回 → **8回（= 4分）**に変更した。タスク間隔の5分より前に復旧を終わらせれば
    順序が保たれ、Splunk にも載る。**4分以内の障害は救えるようになった。**
  - それより長い障害では、測定値は pScheduler の DB には残るが Splunk 側は欠測のまま。
    5分段の再送は「run を archived にして pScheduler 側の記録を閉じる」意味しか無い。
  - **障害注入実験（Step 7）の一次証拠を Splunk のグラフから
    pScheduler の archivings 診断へ変更した。** 全試行の時刻・成否・次の retry 間隔が残るので、
    「メトリクスが届かない」と「メトリクスが劣化を示す」の区別はむしろこちらのほうが厳密。
  - 検証用に作った `lab.ingest.ordering.probe` は使い捨て。無操作で MTS が期限切れになるのを待つ。

### 記事ネタ

- **「再送を入れたから欠測は埋まる」は成り立たない。** 3層（pScheduler / ブリッジ+Collector /
  Splunk ingest）すべてが成功を報告しているのに、データは消えている。
  各層が「自分の担当範囲では成功した」と正しく報告した結果、誰も嘘をついていないのに
  エンドツーエンドでは失われる、という可観測性そのものの話にできる。
- **ingest が 200 OK を返しながら黙って捨てる**のが一番効く。送信側のメトリクス
  （`otelcol_exporter_send_failed_metric_points` = 0）を信じると必ず見落とす。
  「送った数」と「見える数」を突き合わせる習慣が要る。
- 再送間隔を**タスク間隔より短く設計する**という結論は、時系列 DB 一般に効く設計原則として書ける。
  再送は「いつか届けばいい」ではなく「次の点より前に届かないと意味が無い」。
- 判定条件を満たさなかったので計画のゲートで止めて報告した、という進め方自体も書ける。
  止めた理由（retry-policy が効いていない）は誤りで、実際は1層下流の問題だった。

### Step 12 追記: 修正後の再検証（30秒段8回）

- 日付: 2026-07-29
- やったこと: 30秒段を8回に増やしたうえで、ブリッジを**3分だけ**停止して再検証した
  （11:46:31〜11:49:52）。
- 結果:
  - rtt タスクは実行間隔の隙間に入ってしまい再送が発生しなかった（テストとしては空振り）。
    代わりに他の2タスクが再送経路を通った:

    ```
    latency lan-wired  run 11:49:11  attempts=2  → 11:49:54 に成功
    trace wan-cloudflare run 11:46:32 attempts=8 → 11:50:17 に成功（30秒×7回失敗）
    ```

  - **どちらも Splunk に着弾した。** 決定的なのは trace で、
    **3.5分遅れて届いたのに 11:47（測定時刻）に格納されている**。11:50 ではない。
  - つまり「遅れて届いた点が捨てられる」のではなく、
    **「同一 MTS に既に新しい点が書かれた後に届いた点が捨てられる」**。
    Step 12 本文の推論が実測で裏づけられた。
- 判断: 30秒段8回（4分）で、タスク間隔5分より短い障害は Splunk 側も救えることを確認。
  Phase A の Exit Criteria を満たしたとみなす。

## Step 13: Detector の誤検知確認（6時間）と、その間に進んだクロック劣化

- 日付: 2026-07-29
- やったこと: Detector 4本を 11:13 に投入し、17:33 まで**6時間20分**平常運転で放置して
  誤検知の有無を確認した（runbook Step 6 の Exit Criteria）。
- 結果 / エラー:
  - **発火 0 件**（4本とも ACTIVE）。閾値を実測ベースラインから決めた狙いどおり。

    ```
    lan-rtt-degraded           ACTIVE  発火 0 件
    lan-throughput-degraded    ACTIVE  発火 0 件
    packet-loss                ACTIVE  発火 0 件
    wan-rtt-sudden-change      ACTIVE  発火 0 件
    ```

  - データ流入も継続（直近6時間で rtt 127点 / loss 275点 / throughput 26点 / hops 13点）。
  - **ただし片道遅延だけが激減していた。** 同じ6時間で
    `twamp.delay.median` = **17点**に対し `rtt.mean` = 127点、`clock_error` = 126点。
    朝の同じ計測では delay 83 / rtt 141 だったので、**棄却率が 41% → 87% に上がった**。
  - 原因は測定系ではなくクロック。`clock_error` の分布が朝と別物になっている:

    | | 朝（24h ベースライン） | 17:33（直近6時間） |
    |---|---|---|
    | 中央値 | 0.48 ms | **21.4 / 23.5 ms** |
    | 10ms ゲート超過 | — | **64% / 65%**（72点中46・47点） |
    | 最大 | 189 ms | 121.6 / 109.9 ms |

  - VM の chrony も裏づけている:

    | | 11:45 | 17:33 |
    |---|---|---|
    | Frequency | 3.432 ppm slow | **2586.262 ppm slow** |
    | Skew | 1.457 ppm | **23.066 ppm** |
    | RMS offset | — | 19.1 ms |

    `Frequency 2586 ppm` は 0.26% の周波数ずれで、桁が違う。Lima(QEMU) の VM が
    ホスト（Mac）の省電力やスロットリングでクロックを取りこぼしている典型的な形。
    RasPi 側は `NTPSynchronized=yes` で問題なし。
- 判断・回避策:
  - **Detector の Exit Criteria は満たした**ので消し込む。Detector はいずれも
    rtt / ロス / スループットを見ており、クロックには依存しないので今回の劣化の影響を受けない。
  - **品質ゲートはむしろ正しく働いている。** クロックが実際に劣化したので片道遅延を捨てた。
    ゲートが無ければ 21ms 前後のオフセット込みの値を「片道遅延」として出していたことになる。
  - **Phase D（netem 注入）への影響**: 片道遅延はほぼ確実に欠測する。
    runbook Step 7 の「RTT では 100ms の跳ねが明確、片道遅延はゲート次第で欠測」という
    対比の扱いはそのままでよく、むしろ実例が強くなった。
  - VM のクロック規律そのものの改善は W2 のスコープ外。W3 以降の課題として残す。

### 記事ネタ

- **「6時間放置して誤検知0件」を確認しに行ったら、別の指標が壊れているのを見つけた**という流れ。
  Detector が黙っていることは「何も起きていない」を意味しない。Detector は自分が見ている
  指標についてしか語らない。
- **品質ゲートの価値が実データで出た。** 朝は棄却率41%、夕方は87%。同じコード・同じ閾値で
  棄却率が倍になったのは、コードではなく環境が変わったから。
  ゲートが無ければこの変化は「片道遅延が 0.7ms から 20ms に悪化した」という
  **誤った観測**として記録されていた。
- 仮想マシンのクロックは自宅ラボの片道遅延測定にとって構造的な弱点、という結論の実証データ。

## Step 14: 「VM のクロックが壊れている」は誤診だった。壊れていたのは NTP の選び方

- 日付: 2026-07-29
- やったこと: Step 13 で見つけたクロック劣化を Phase D の前に直す。まず切り分けから。
- 結果 / エラー:
  - **clocksource は正常**（`arch_sys_counter`、Apple Silicon の VM としては正しい）。
    `/dev/ptp*` は無いのでホストクロックの引き込み（`refclock PHC`）は不可。
  - **RasPi は健全だった。** `systemd-timesyncd` が `2.debian.pool.ntp.org` を国内 IPv6 に
    解決していて、RootDelay 2.75ms / RootDispersion 1.02ms / Jitter 1.48ms。劣化は VM だけ。
  - **VM の NTP 源が全部遠かった。** Ubuntu 既定の `pool ntp.ubuntu.com` は Canonical の
    欧州サーバ。Mac から実測した RTT の比較:

    | 時刻源 | RTT 中央値 | ジッタ |
    |---|---|---|
    | `ntp.ubuntu.com`（既定、8ソース中4つ） | **256.82 ms** | 17.57 ms |
    | `time.cloudflare.com` | 9.28 ms | 1.63 ms |
    | `ntp.jst.mfeed.ad.jp` | 9.37 ms | 2.80 ms |
    | `ntp.nict.jp`（stratum 1） | 18.49 ms | 2.11 ms |
    | `time.google.com` | 45.01 ms | 6.14 ms |

  - chronyd のログは falseticker 判定と参照元切り替えが数分おきに並んでいた。
    どのソースも互いに一致していなかった。
  - 国内源（NICT / IIJ mfeed / Cloudflare）に差し替えて `minpoll 4 maxpoll 6` にした結果:

    | | 変更前 | 収束後（8分） |
    |---|---|---|
    | 参照元 | 45.76.211.39（US, stratum 2） | 133.243.238.163（NICT, **stratum 1**） |
    | Root dispersion | **37.72 ms** | **0.125 ms** |
    | Root delay | 12.07 ms | 9.53 ms |
    | Skew | 19.24 ppm | **1.02 ppm** |
    | Frequency | 590〜2586 ppm slow | **2.67 ppm slow** |

  - **実測の `max-clock-error` は 21〜23ms から 0.19ms になった。** ゲート（10ms）を余裕で通る。
- 判断・回避策:
  - **Step 13 で書いた「VM のクロック規律が劣化」「vz のクロック取りこぼし」は誤診。**
    `Frequency 2586 ppm slow` はハードウェアの症状ではなく、
    **RTT 257ms・ジッタ 30ms のソースから chrony が周波数を推定しようがなかった**結果。
    ソースを替えたら 2.67ppm に収まった。ハードウェアの問題に見えたものが設定の問題だった。
  - 設定は `deploy/vm/chrony-home-lab.conf` として repo 化した（`deploy/vm/README.md` に手順）。

### それでも片道遅延は測れない — ゲートを通す先で落ちる

クロックを直した直後の実測 twamp（VM → RasPi、100発全着）:

```
max-clock-error : 0.19 ms
片道遅延 min/med/max : -0.48 / -0.26 / 0.01 ms
```

**片道遅延が負値。** 物理的にありえない。つまり:

- クロックは **0.19ms の精度を自己申告**している
- しかし VM ↔ RasPi の**実際の相対オフセットは 0.7ms 程度**ある（RTT 0.95ms に対し
  片道が -0.26ms なので）
- **自己申告の誤差は実際の誤差より小さく出る。** Step 5-2 で「max-clock-error は
  品質ゲートとして機能しない」と結論して値の妥当性検査（`0 < median <= 50`）を足したのは
  正しかった。今回それが効いて、この測定は落ちる

**これは NTP の限界であって設定の失敗ではない。** LAN の RTT が 0.95ms しかない区間で
片道遅延（≒0.5ms）を測るには、0.5ms よりずっと良いクロック同期が要る。
WAN 越しの NTP では原理的に届かない。PTP か GPS の領域。

### Phase D への影響（注入前に確認が要る）

netem で 100ms を入れると片道遅延は約 100ms になるが、**`DELAY_CEILING_MS = 50.0` を
超えるので今度は上限で落ちる**。この上限は「LAN ペア（RTT 約0.9ms）を前提」に置いたもの。
runbook Step 7 の「片道遅延はゲート次第で欠測」という扱いは変わらないが、
**欠測の理由が clock_error ではなく値の上限になる**点は記事で区別して書く必要がある。

### 記事ネタ

- **「VM のクロックが不安定」は誤診だった**という流れそのもの。仮想化のせいにしたくなる症状
  （Frequency 2586ppm、falseticker 連発、Skew 悪化）が、実は
  **地球の反対側の NTP サーバを見ていただけ**だった。ディストリの既定値は
  「そのディストリの利用者全体にとっての無難」であって、自分の場所にとっての最適ではない。
- **自己申告の誤差は信用できない、を実データで示せる。** max-clock-error 0.19ms と
  申告しながら、実際の相対オフセットは 0.7ms。だから値そのものの妥当性検査が要る。
  「壊れた値」は往々にして「壊れていると自己申告しない」。
- **自宅ラボの LAN では片道遅延は測れない**という結論。RTT 0.95ms の区間で
  片道 0.5ms を測るのは NTP の精度の外側。ゲートで落とすのが正しく、
  無理に出せば「片道遅延 -0.26ms」というグラフができあがる。

## Step 15: netem 注入は成功。ただし「発火0件」は自分のスクリプトのバグだった

- 日付: 2026-07-29
- やったこと: Phase D（tc netem 障害注入）を実施。VM の `lima0` に
  `delay 100ms loss 3%` を 21:20:21〜21:36:22 の16分間注入した。
- 結果 / エラー:
  - **メトリクスは劣化を明確に捉えた。**

    | | 平常時 | 注入中 |
    |---|---|---|
    | `rtt.mean`（双方向） | 0.93 ms | **104〜106 ms** |
    | `packet.loss.ratio` | 0 | **0.02〜0.06** |
    | `throughput.bps` | 940 Mbps | **241 Mbps** |
    | WAN `rtt.mean` | 9 ms | **115 ms** |

  - 外部からの裏取り: 注入中の Mac → VM は 106.8ms、Mac → RasPi（対照）は 0.52ms、
    Mac → 1.1.1.1（家庭内 WAN）は 8.45ms。**注入対象以外に影響なし。**
  - **クロックは注入区間でステップ補正なし**（Skew 0.108ppm、RMS offset 0.94ms、
    chronyd のログにも step/slew 無し）。Step 14 で時刻源を直した効果で、
    「観測された遅延増が注入起因かクロック起因か」の疑いは完全に排除できた。
  - **Collector は全区間で送出継続**（6901 → 6932 → 6963、失敗0・拒否0）。
    100ms 遅延 + 3% ロスはテレメトリ経路の TCP が吸収した。
    pScheduler の archivings も全 run が1回目で成功しており、再送は発生していない。
  - **Detector は3種が発火した。**

    ```
    lan-rtt-degraded        21:28  104→101  106.391 ms
    lan-rtt-degraded        21:31  101→104  104.203 ms
    lan-throughput-degraded 21:23  101→104  240.8 Mbps
    wan-rtt-sudden-change   21:35  1.1.1.1  115.469 ms
    wan-rtt-sudden-change   21:36  8091.info 115.312 ms
    ```

  - **ロスの Detector だけ発火しなかった。** 原因は統計。`wan-rtt` は count=10、
    LAN の rtt は count=20 で、**3% ロスなら 20発中1発も落ちない確率が
    0.97^20 ≒ 54%**。実際ロス率の系列は 0.02 / 0.00 / 0.03 / 0.05 / 0.00 …と
    ゼロが混ざり、「2点連続で閾値超え」を満たせなかった。
    **閾値の問題ではなくサンプルサイズの問題。**

### 訂正1: 「6時間・発火0件」は誤りだった（自作スクリプトのバグ）

Step 13 で「発火0件」と報告したが、これは `check-alerts.sh` のバグ。
発火判定を `events[].is == "anomalous"` で見ていたが、**実際のフィールドは
`anomalyState == "ANOMALOUS"`**。この条件は常に空振りするので、
**発火していても必ず「0件」と表示される。**

修正して取り直したところ、観測窓の冒頭に2件あった:

```
packet-loss           11:15  wan-cloudflare  0.1
wan-rtt-sudden-change 11:23  wan-cloudflare  14.373 ms
```

平常運転区間（11:23〜21:20、約6時間）は本当に0件だったので Exit Criteria 自体は
満たしているが、**「確認した」と報告した根拠は間違っていた。**
検証スクリプトが常に成功を返すなら、それは検証ではない。

### 訂正2: `min(over='12m')` は「2点連続」を表現できていなかった

上の 11:15 の誤検知を追ったら、Detector 側の設計にも欠陥があった。

```
11:04  0.000
11:05  0.100  ← 単発スパイク
（11:08〜11:20 はブリッジ停止リハーサルでデータ欠測）
11:21  0.000
```

`min(over='12m')` は「窓内の**全**データポイントが閾値超え」を意味するが、
**窓内に1点しか無ければその1点で判定する**。11:05〜11:17 の窓には 0.1 の1点しか無く、
min = 0.1 > 0.01 で発火した。

`lasting()` を避けて `min(over)` にしたのは正しかったが、**それだけでは足りなかった**。
点数も併せて要求して初めて「N点連続」になる:

```
sustained = loss.min(over='12m')
enough    = loss.count(over='12m')
detect(when(sustained > 0.01 and enough >= 2))
```

`lan-rtt-degraded` にも同じ修正を入れた。

- 判断・回避策:
  - `check-alerts.sh` を修正（`anomalyState` で判定し、継続中インシデントも出す）。
  - Detector 2本に `count(over=)` を追加して再投入。
  - ロス Detector が 3% で発火しないのはサンプルサイズの問題なので、
    閾値をいじるのではなく **`count` を増やす**（現在 LAN 20発）か、
    **より長い窓で平均を見る**のが筋。W3 の課題として残す。

### 記事ネタ

- **検証スクリプトのバグで「検証できた」と誤認した**話が一番効く。
  `is` という存在しないフィールドを読んでいたので、条件は常に偽。
  **常に「異常なし」を返す監視は、監視していないより悪い**（安心を供給するので）。
  今回は netem を撃って初めて気づいた。**「発火するはずのものを撃つ」ことでしか
  検知系のテストはできない。**
- **`min(over)` が「N点連続」にならない**話。時系列の窓集約は
  「窓に何点あるか」を保証しない。疎な測定系列（5分間隔）では特に効く落とし穴で、
  データ欠測が「継続的な劣化」に化ける。
- **ロス3%を20発で測ると54%の確率で見逃す**という統計の話。
  閾値チューニングの前にサンプルサイズを見る。
- 対比として、**注入実験そのものは教科書どおり**に決まった（RTT 0.93→105ms、
  スループット 940→241Mbps、クロックのステップ補正なし、テレメトリ経路は生存）。
  綺麗に決まった実験の裏で、検知系の欠陥が2つ見つかったという構図。
