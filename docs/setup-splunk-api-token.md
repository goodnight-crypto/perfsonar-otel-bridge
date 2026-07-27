# Splunk O11y API トークンの用意（ユーザー作業）

Claude Code から Splunk Observability Cloud の管理 API を叩けるようにする手順。
**所要 5 分程度。トークンの値は Claude に見せず、自分で `.env` に書き込む。**

## なぜ必要か

現在 `.env` にあるのは **INGEST トークン**で、これは「データを送る」専用。
ダッシュボードや Detector の作成・確認、メトリクスの検索には使えない。
別種類の **User API Access Token** が要る。

これがあると Claude Code 側で次のことができるようになる。

- 送ったメトリクスが本当に着弾しているかを API で確認する（今は Collector のカウンタまでしか見えず、
  Splunk 側の確認は毎回ユーザーの目視に頼っている）
- Detector をコードから定義してリポジトリで管理する（UI 手作業だと記事の再現性が落ちる）
- ダッシュボードの定義を JSON で出力してリポジトリに残す
- 利用可能な dimension 一覧を引いて、schema.md の記述と実データの突き合わせをする

## トークンの種類（間違えやすい）

| 種類 | 用途 | 今の状態 |
|---|---|---|
| Org Access Token（INGEST） | データ送信専用 | `.env` の `SPLUNK_ACCESS_TOKEN`。設定済み |
| **User API Access Token** | 管理 API（Detector / ダッシュボード / メトリクス検索） | **これから用意する** |

データ送信には org トークンが必須で、User API トークンでは送れない。逆に管理 API は
User API トークンを使う。役割が排他なので、両方を別々に持つ。

## 手順

### 1. realm を確認する

Settings → 上部のユーザー名 → **Organizations** タブに realm・API エンドポイント・
organization ID が表示される。このプロジェクトは `jp0` のはず。

### 2. User API Access Token を取得する

左ナビの **Settings** → 自分のプロフィール名 → **Show User API Access Token**

**有効期限に注意**: ここで表示されるトークンは **ログアウト時、または 30 日後のいずれか早い方**で失効する。
ブラウザでログアウトすると Claude Code 側の API アクセスも止まる。

ログアウトで失効させたくない場合は `v2/session` エンドポイントで作る（30 日の期限は同じ）:

```bash
# realm と自分のログイン情報を使う。出力の accessToken が長命トークン
curl -X POST "https://api.jp0.signalfx.com/v2/session" \
  -H "Content-Type: application/json" \
  -d '{"email":"<自分のメールアドレス>","password":"<パスワード>"}'
```

パスワードをシェル履歴に残したくない場合は、`-d @file` でファイルから渡して後で消す。

### 3. `.env` に追記する

**Claude には値を貼らないこと。**自分で `.env` を開いて次の行を足す。

```
SPLUNK_API_TOKEN=<取得したトークン>
```

**インラインコメントを付けないこと。** `docker --env-file` がコメントごと値として読み込み、
認証が壊れる（W2 Step 1 で実際に踏んだ。experiments/w2-notes.md 参照）。

ついでに、既存の `SPLUNK_ACCESS_TOKEN` の行にインラインコメントが残っていれば消しておくと
compose 周りの事故が減る。

### 4. 動作確認

```bash
cd /Users/dev/src/perfsonar-otel-bridge
set -a; . ./.env; set +a

# 自分の組織情報が返れば成功
curl -s -H "X-SF-TOKEN: ${SPLUNK_API_TOKEN}" \
  "https://api.${SPLUNK_REALM}.signalfx.com/v2/organization" | head -c 300; echo
```

401 が返る場合はトークンの種類が違う（INGEST トークンを入れていないか確認）。

送っているメトリクスが Splunk 側に登録されているかの確認:

```bash
curl -s -H "X-SF-TOKEN: ${SPLUNK_API_TOKEN}" \
  "https://api.${SPLUNK_REALM}.signalfx.com/v2/metric?query=perfsonar.*" | head -c 500; echo
```

## エンドポイントの形式

2026-03-24 以降、新旧2系統が併存している。どちらでも動く。

| | 旧（legacy） | 新 |
|---|---|---|
| API | `https://api.jp0.signalfx.com` | `https://api.jp0.observability.splunkcloud.com` |
| Ingest | `https://ingest.jp0.signalfx.com` | `https://ingest.jp0.observability.splunkcloud.com` |

現在の Collector 設定（`deploy/mac/otel-collector-config.yaml`）は legacy 形式を使っている。
動作確認済みなので当面変更しない。

**realm を省略すると `us0` として解釈される**ので、必ず `jp0` を含めること。

認証ヘッダはどちらのトークンも `X-SF-TOKEN`。

## セキュリティ

- `.env` は `.gitignore` 済み。`.env.*` と `*.swp` も除外済み。
- トークンをコード・設定・ドキュメント・コミットメッセージに書かない（CLAUDE.md 規約1）。
- 30 日で失効するので、記事公開（8/9-8/10 予定）までは有効だが、それ以降も使うなら再発行が要る。
  INGEST トークンの期限は 2026-08-21。

## 出典

- [API access tokens | Splunk Observability Cloud](https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/api-access-tokens)
- [View your realm, API endpoints, and organization](https://help.splunk.com/en/splunk-observability-cloud/administer/org-reference-info/view-your-realm-api-endpoints-and-organization)
- [Developer Guide for Splunk Observability Cloud](https://dev.splunk.com/observability/docs/)
