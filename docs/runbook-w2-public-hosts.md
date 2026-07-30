# Runbook W2-PH: 公開 perfSONAR ホスト選定と WAN パス追加

目的: 自宅 → インターネット区間の RTT/ロス定点観測のため、公開 perfSONAR ホストを 2 台選定し、
pSConfig に `wan-*` パスを追加する。

- **タイムボックス: 半日**。疎通まで到達しなければ本タスクを打ち切り、LAN 構成のまま W3（執筆）へ進む
- **スコープ**: RTT 系（twamp、フォールバック rtt）のみ。**公開ホストへの throughput (iperf3) 測定は行わない**
- 実行主体: Claude Code。ただし **Step 1 の候補リストアップはユーザーがブラウザで実施する**（後述のとおり機械的な取得手段が無い）

> **2026-07-30 追記（W3 での実行時に判明した修正）**
> Step 1 の取得手段、Step 2/3 の実行ノード、Step 3 のコマンド、Step 4 の間隔を実測に基づいて
> 改訂した。改訂の理由は各 Step の引用ブロックに記す。実行ログは `experiments/public-hosts.md`。

## 選定基準（優先順）

| # | 基準 | 判定方法 | 合格ライン |
|---|---|---|---|
| 1 | 地理的・ネットワーク的な近さ | stats.perfsonar.net の所在地 + `pscheduler task rtt` の実測 | 日本国内（なければ APAC）。RTT が経路として妥当（国内なら目安 <50ms） |
| 2 | pScheduler 応答 | `pscheduler ping <host>` | 応答あり |
| 3 | latency 系テストの受け入れ可否 | `pscheduler task latency --protocol=twamp --dest <host>` が limits に拒否されず完走 | twamp 完走。不可なら rtt (ping) で代替可か確認 |
| 4 | 安定性 | 候補に対し 30〜40 分間隔で 3 回測定 | 全回応答・ロス 0% 近辺 |
| 5 | 運用主体の明確さ | ホスト名のドメインから組織を確認 | 研究網・大学・NREN 等の恒常運用ホストを優先 |

## Step 1: 候補リストアップ（5〜8 台）【ユーザー作業】

1. http://stats.perfsonar.net/ を**ブラウザで**開き、地図またはホスト一覧から **Japan** 所在のホストを抽出する
   - 見るべき情報: ホスト名（FQDN）、組織、所在地、登録されているサービス（pscheduler / owamp / twamp）
   - **必須なのは FQDN だけ**。他は分かる範囲でよい
   - 国内候補が 3 台未満の場合は APAC（韓国・台湾・シンガポール・豪州）まで広げる
2. 候補を `experiments/public-hosts.md` に以下の表形式で記録する

```markdown
| # | FQDN | 組織 | 所在地 | 登録サービス | メモ |
|---|------|------|--------|--------------|------|
```

> **なぜユーザー作業なのか（2026-07-30 実測）**
>
> - **stats.perfsonar.net は Grafana の SPA で、JavaScript の実行が必要。** HTTP 200 は返るが、
>   本文は `Grafana has failed to load its application files` のみ。`curl` や WebFetch の類では
>   ホスト一覧を取れない。
> - **Lookup Service には GET の検索 API が無い。** `https://ls.perfsonar.net/lookup/records` は
>   **POST 専用**（`allow: POST`。GET は 405）の**登録用**エンドポイントであり、検索はできない。
>   グローバルレジストリ `http://ps1.es.net:8096/lookup/activehosts.json` が指す先も、
>   結局この 1 つのエンドポイントだった。
> - したがって**機械的な取得は断念し、ブラウザ経由に一本化する**。

> 注意: stats.perfsonar.net は Lookup Service 登録情報の反映であり、実際には停止中のホストも
> 載っている。次 Step の実測でふるいにかける前提でリストアップは機械的に行ってよい。

## Step 2: 生存確認と pScheduler 応答【候補全台に実施】

**実行ノードは LG Gram（192.168.1.102）の testpoint コンテナ。**

> **VM から LG Gram へ変更した理由（2026-07-30）**
>
> - LG Gram の testpoint は **pSConfig 未投入で定期タスクを持たない**。手動テストが本番
>   スケジュールと衝突しない（VM は 6 タスクが 5 分間隔で回っており、割り込ませたくない）。
> - **LG Gram が切替後の本番ノード**なので、選定の実測がそのまま本番構成の実測になる。
> - USB 100M NIC 由来の上乗せは RTT +0.35ms・片道 +0.94ms。**WAN の RTT は 10〜50ms 想定**
>   なので、ホスト選定の判断には影響しない。

```bash
for h in <host1> <host2> ...; do
  echo "=== $h ==="
  # 2-1. DNS 解決と ICMP 到達性
  ssh dev@192.168.1.102 "docker exec perfsonar-testpoint ping -c 3 $h"
  # 2-2. pScheduler 応答（これが本命の生存確認）
  ssh dev@192.168.1.102 "docker exec perfsonar-testpoint pscheduler ping $h"
done
```

- 結果（OK / NG / エラー内容）を public-hosts.md の表に列追加で記録
- `pscheduler ping` NG のホストはこの時点で脱落

## Step 3: latency テスト受け入れ確認【Step 2 通過ホストに実施】

> **コマンドの修正（2026-07-30）**: **`pscheduler task twamp` は誤り。** `twamp` という
> test type は存在せず、`latency` テストの `--protocol=twamp` として指定する
> （`deploy/psconfig/README.md` の「ハマりどころ」で確定済みの知見）。
> また **WAN 宛に `--source` は付けない**（既存の `wan-rtt` タスクと同じ形。
> NAT 内のプライベート IP を source に書いても相手からは意味を持たない）。

```bash
# 3-1. latency / twamp（本命）
ssh dev@192.168.1.102 "docker exec perfsonar-testpoint \
  pscheduler task --format json latency --protocol=twamp --dest <host>"

# 3-2. twamp が limits 拒否 or ツール不在の場合のフォールバック
ssh dev@192.168.1.102 "docker exec perfsonar-testpoint \
  pscheduler task --format json rtt --dest <host>"
```

判定と記録:
- twamp 完走 → 「twamp 可」。片道遅延・`max-clock-error`・ロスを表に記録
- 「Run rejected」「no tool」等 → **エラーメッセージ全文**を `experiments/public-hosts.md` に記録し、rtt で代替
- rtt も失敗 → 脱落
- **注意**: 相手先の limits ポリシーに拒否された場合はリトライで粘らない（先方の設定意図を尊重）

> **NAT 越えのリスク**: TWAMP はクライアントが制御・試験パケットの両方を発信し、リフレクタが
> 送信元へ返す構造なので NAT と相性が良いはずだが、**実際に通るかは実測するまで分からない。**
> 通らなければ rtt で代替し、「自宅 NAT 環境では WAN の片道遅延が取れない」という結果自体を
> 記事の材料にする。

## Step 4: 安定性確認と 2 台選定

1. Step 3 通過ホストに対し、**30〜40 分間隔で計 3 回** twamp（or rtt）を実行

   > **間隔を「2 時間以上」から短縮した理由（2026-07-30）**: 半日のタイムボックスに収めるため。
   > 日中帯の変動しか見られないが、**「完全に死んでいるホストを除く」という Step 4 の目的には
   > 十分**。選定後は 15 分間隔の本番測定で安定性を見続けられる。
   > 時間帯差まで見たい場合は本番測定の蓄積後に評価する。

2. 3 回の RTT 中央値・ばらつき・ロスを表に追記
3. 以下の優先で 2 台選定:
   - 1 台目: 国内・twamp 可・RTT 最小・安定
   - 2 台目: 1 台目と**別組織/別経路**のホスト（経路多様性を確保。RTT がやや大きくても可）
4. 選定理由を public-hosts.md 末尾に 3〜5 行で明文化（→ 記事にそのまま使う）

## Step 5: pSConfig への組み込み

> **2026-07-30 の実行では Step 5 を GbE NIC 切替作業にまとめ、ここでは実施しない。**
> `home-lab-mesh.json` を二度触らずに済み、Splunk のデータにも断絶が出ないため。
> 切替時にやることは `experiments/w3-notes.md` Step 6 の「GbE NIC 到着後にやること」に集約する。

1. `deploy/psconfig/` のテンプレートに追加:
   - addresses に選定 2 ホスト
   - tasks に `wan-<拠点名>-twamp`（twamp 不可のホストは rtt タスク）
   - schedule: **PT15M**（LAN の 5 分より粗く。公開リソースへの配慮）
   - reference: `path.id: wan-<拠点名>`
2. `psconfig validate` → testpoint へ配布 → スケジュール登録確認:
   ```bash
   docker exec perfsonar-testpoint pscheduler schedule --filter-test latency
   ```
3. ブリッジ経由で Splunk にメトリクス着弾を確認（`ps.destination` に公開ホストが現れること）
4. Splunk ダッシュボードに「LAN vs WAN」重ね合わせチャートを追加
5. CLAUDE.md の環境インベントリに選定ホストを追記

## 運用上の注意（CLAUDE.md 規約に準ずる）

- 公開ホストへのテストは latency 系のみ。**throughput は絶対に張らない**
- 間隔は 15 分より短くしない
- 相手ホストが応答しなくなった場合はタスクを無効化して様子を見る（連打しない）

## Exit Criteria

- [ ] public-hosts.md に候補一覧・実測結果・選定理由が記録されている
- [ ] 2 台選定済み（うち 1 台以上で twamp が通ることが望ましい）
- [ ] pSConfig に wan パス 2 本が追加され、15 分間隔で自動測定が回っている
- [ ] Splunk に `path.id: wan-*` のメトリクスが着弾し、ダッシュボードに表示されている
- [ ] （打ち切りの場合）打ち切り判断と理由が experiments/ に記録されている
