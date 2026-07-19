# bridge (W2 で実装)

pScheduler HTTP archiver の POST を受け、OTel メトリクスに変換して Collector へ OTLP push する FastAPI アプリ。

- 変換仕様: ../docs/schema.md
- エンドポイント: PUT/POST /archive
- 実装開始条件: W1 Exit Criteria 達成（docs/samples/ に 4 テスト種の実 JSON があること）
