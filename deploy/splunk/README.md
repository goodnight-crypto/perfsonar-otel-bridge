# Splunk Observability Cloud の定義（as-code）

このディレクトリが**正**。ダッシュボード・チャート・Detector は UI で触らず、
ここのファイルを直して `apply.sh` を流す。

```bash
./deploy/splunk/apply.sh --dry-run       # 送信せず差分だけ表示
./deploy/splunk/apply.sh                 # チャート → ダッシュボード → Detector
./deploy/splunk/apply.sh --only charts
./deploy/splunk/apply.sh --only detectors
./deploy/splunk/check-alerts.sh          # Detector の状態と発火履歴
```

| ファイル | 役割 |
|---|---|
| `charts/*.json` | チャート定義。ファイル名が `.ids.json` のキーになる |
| `dashboard-network-slo.json` | ダッシュボード。`layout` がチャートを**ファイル名**で参照する |
| `detectors/*.json` | Detector 定義 |
| `apply.sh` | 冪等な投入。既存なら PUT、無ければ POST |
| `check-alerts.sh` | 発火履歴の確認 |
| `.ids.json` | 生成された ID の記録。**commit する**（ID は秘密ではない） |

## Free Edition でも API で作れる

以前 `docs/runbook-w2.md` には「INGEST トークンしか無いので UI 作業」と書いてあったが誤り。
`.env` の `SPLUNK_API_TOKEN` で `/v2/chart` `/v2/dashboard` `/v2/detector` とも
POST/PUT が通る（**カスタム Detector の作成も可**。実地で確認済み）。
トークンの取得手順は `docs/setup-splunk-api-token.md`。

## トークンの扱い

`apply.sh` は `.env` から読んだトークンを **Python の urllib でヘッダにだけ載せる**。
`curl -H` を使わないのは、トークンがプロセス引数（`ps` で見える）に載るのを避けるため。
出力にもトークンは出さない（CLAUDE.md 規約1）。

## API の構造上の注意

- **チャートは個別に POST してから、その ID をダッシュボードの `charts[]` に
  `row` / `column` / `width` / `height` 付きで並べる。** ダッシュボードにチャートを
  インラインで書く形式は無い。グリッドは12カラム。
- `apply.sh` は `.ids.json` の ID を GET して実在を確認してから PUT する。
  UI で消された場合は 404 になるので POST に倒れ、`.ids.json` が更新される。
- Detector は投入前に `POST /v2/detector/validate`（204 が成功）で
  SignalFlow の構文を検証できる。

## 「2データポイント連続」の書き方

`lasting()` ではなく `min(over='12m')` を使っている。理由は
`docs/runbook-w2.md` Step 6 を参照。
