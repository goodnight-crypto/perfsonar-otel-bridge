## 現在発生中のアラート（フィルタ適用結果・未解決）

1. **Incident ID: HPNtq8ECIAw**
   - **Detector:** perfSONAR: LAN RTT が劣化している
   - **ステータス:** Active（未解決）
   - **重大度:** **Major（高）**
   - **発生時刻:** 2026-08-08T22:45:00+00:00
   - **概要:** LAN RTT が **5ms超** の状態が継続（平常時中央値 **0.94–0.98ms**）。  
     - 観測値（入力）: rtt.min(over=12m) **100.919ms**、rtt.count(over=12m) **3**
     - 対象: ps.source **192.168.1.102** → ps.destination **192.168.1.101**（path.id: lan-wired）
   - **リンク:** [perfSONAR: LAN RTT が劣化している](https://app.jp0.observability.splunkcloud.com/olly/#/modern-dashboards/alert-details/HPO8KVfCIAA?orgId=HNu0FGPCMAA)

2. **Incident ID: HPNsoFVCEAA**
   - **Detector:** perfSONAR: パケットロスが継続している
   - **ステータス:** Active（未解決）
   - **重大度:** **Major（高）**
   - **発生時刻:** 2026-08-08T22:38:19+00:00
   - **概要:** ロス率 **1%超** が継続（単発スパイクは除外済み）。  
     - 観測値（入力）: loss.min(over=12m) **0.02**（=2%）、loss.count(over=12m) **2**
     - 対象: ps.source **192.168.1.101** → ps.destination **192.168.1.102**（path.id: lan-wired、ps.test.type: latency）
   - **リンク:** [perfSONAR: パケットロスが継続している](https://app.jp0.observability.splunkcloud.com/olly/#/modern-dashboards/alert-details/HPO7frKCMAA?orgId=HNu0FGPCMAA)

3. **Incident ID: HPNsrNRCIAA**
   - **Detector:** perfSONAR: パケットロスが継続している
   - **ステータス:** Active（未解決）
   - **重大度:** **Major（高）**
   - **発生時刻:** 2026-08-08T22:38:37+00:00
   - **概要:** ロス率 **1%超** が継続（単発スパイクは除外済み）。  
     - 観測値（入力）: loss.min(over=12m) **0.02**（=2%）、loss.count(over=12m) **2**
     - 対象: ps.source **192.168.1.102** → ps.destination **192.168.1.101**（path.id: lan-wired、ps.test.type: latency）
   - **リンク:** [perfSONAR: パケットロスが継続している](https://app.jp0.observability.splunkcloud.com/olly/#/modern-dashboards/alert-details/HPO7frsCEAA?orgId=HNu0FGPCMAA)

4. **Incident ID: HPNtq8ECIAs**
   - **Detector:** perfSONAR: LAN RTT が劣化している
   - **ステータス:** Active（未解決）
   - **重大度:** **Major（高）**
   - **発生時刻:** 2026-08-08T22:45:00+00:00
   - **概要:** LAN RTT が **5ms超** の状態が継続（平常時中央値 **0.94–0.98ms**）。  
     - 観測値（入力）: rtt.min(over=12m) **101.334ms**、rtt.count(over=12m) **3**
     - 対象: ps.source **192.168.1.101** → ps.destination **192.168.1.102**（path.id: lan-wired）
   - **リンク:** [perfSONAR: LAN RTT が劣化している](https://app.jp0.observability.splunkcloud.com/olly/#/modern-dashboards/alert-details/HPO8KQECMAA?orgId=HNu0FGPCMAA)**要点**

現在のアラートは、**WAN 側の RTT 逸脱が主因**と読むのが自然です。特に **`wan-sinet-tokyo`** が 07:35 頃に大きく跳ね上がっており、同じ時間帯に **WAN RTT** と **LAN RTT** も上振れしています。したがって、想定原因は **特定経路の遅延増大、またはネットワーク経路の不安定化** です。

**何が起きているか**

- **`wan-sinet-tokyo`** が最も急峻に悪化しています。
- **WAN RTT** は平均・最大ともに上昇しており、経路全体で遅延が増えています。
- **LAN RTT** も同時刻に上がっているため、影響は WAN だけに閉じず、観測区間全体で遅延が広がっています。
- 選択中の **Event overlay** のタイミングとも重なっているので、アラート発生区間として整合しています。

**想定原因**

見えている情報だけで言うと、原因候補は **`wan-sinet-tokyo` に紐づく経路品質の悪化** です。  
つまり、**その WAN パスの遅延が急増し、結果として RTT ベースの SLO が崩れた**、という説明が最も筋が通ります。

**補足**

`wan-sinet-tokyo` の急上昇が突出しているので、まず見るべきなのはその経路の前後時刻のログやトレースです。  
ただし、ここから **障害原因を断定** はできません。確認できるのは、**特定 WAN 経路の RTT 逸脱がアラートの直接の根拠** だという点です。## 想定原因

現在のアラートは、**`wan-sinet-tokyo` を含む WAN 経路の RTT 劣化**が中心です。  
直近 1 時間で **07:30〜07:40 頃**に複数系列が同時に上がっており、特に **`wan-sinet-tokyo` が突出して急上昇**しています。あわせて **WAN RTT** と **LAN RTT** も上向いているため、単一の点だけではなく、**ネットワーク経路全体の遅延悪化**として見るのが自然です。

## 何が根拠か

- **`wan-sinet-tokyo`** が最も大きく跳ねており、ベースライン比で大幅な逸脱があります。  
- **WAN RTT** が **最大およそ 100ms** 付近まで上昇しています。  
- **LAN RTT** も上昇しているので、WAN だけの局所問題というより、**往復遅延の悪化が広く出ている状態**です。  
- 選択中の **イベントオーバーレイ** の時刻と、RTT 悪化のタイミングが重なっています。

## いまの見立て

このページの範囲で言える想定原因は、**`wan-sinet-tokyo` 系の経路品質低下、またはその周辺の WAN 経路混雑・遅延増加**です。  
少なくとも、**アプリ単体の障害というよりネットワーク遅延の異常**が主因に見えます。

## 次に見るとよい点

- **`wan-sinet-tokyo`** の同時刻帯のログや経路情報
- **パケットロス継続** が同じ時間帯で強まっていないか
- 他の WAN 系系列（`wan-google`, `wan-cloudflare`, `wan-blog`, `wan-kiren-tsukuba`）との差分があるか

必要なら次に、**「このアラートが WAN 側なのか LAN 側なのか」を1分で切り分ける見方**まで整理します。