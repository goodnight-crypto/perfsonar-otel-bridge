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
    pSConfig 本番化で両方向を通す。
