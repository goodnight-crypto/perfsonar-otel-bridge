# bridge

pScheduler HTTP archiver の PUT を受け、OTel メトリクスに変換して Collector へ OTLP push する FastAPI アプリ。

- 変換仕様: [../docs/schema.md](../docs/schema.md)
- エンドポイント: `PUT /archive`（archiver 既定の `op: put`）/ `POST /archive`

## 構成

| ファイル | 役割 |
|---|---|
| `psotel/convert.py` | archiver 封筒 → `Metric` の純粋変換。テストの主対象 |
| `psotel/otlp.py` | `Metric` → OTLP/JSON 組み立てと Collector への POST |
| `psotel/app.py` | 受信エンドポイント。`emit` を注入して変換と送信を分離 |
| `psotel/__main__.py` | 起動口 |

## 開発

```bash
uv sync
uv run pytest
```

テストは `../docs/samples/` の実測 JSON をフィクスチャに使う（モックではなく実データ）。

## 起動

```bash
OTLP_METRICS_ENDPOINT=http://localhost:4318/v1/metrics uv run python -m psotel
```

## 設計判断

**OTLP を SDK ではなく手組みしている。** OpenTelemetry SDK の Gauge 計測器は記録時刻を自動で
打つため、測定時刻（`run.end-time`）を観測時刻として指定できない。schema.md はブリッジ到着時刻
ではなく測定時刻を使うことを要求しているので、OTLP/JSON を直接組んで POST する。

**変換は純粋関数、送信は注入。** `convert()` は I/O を持たないので実サンプルだけでテストできる。
`create_app(emit=...)` に送信関数を渡す形にして、テストでは記録用の受け皿を差し込む。
