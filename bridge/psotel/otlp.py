"""Metric を OTLP/JSON に組んで Collector へ送る。

OpenTelemetry SDK の Gauge 計測器は記録時刻を自動で打つため、測定時刻
（run.end-time）を観測時刻として指定できない。docs/schema.md はその分離を
要求しているので、OTLP のペイロードを直接組む。
"""

import json
import urllib.request

from .convert import Metric

SERVICE_NAME = "perfsonar-otel-bridge"


def build_payload(metrics: list[Metric]) -> dict:
    """Metric のリストを OTLP/JSON の metrics ペイロードにする。"""
    if not metrics:
        return {"resourceMetrics": []}

    entries = [
        {
            "name": m.name,
            "unit": m.unit,
            "gauge": {
                "dataPoints": [
                    {
                        "asDouble": m.value,
                        # OTLP/JSON は 64bit 整数を文字列で運ぶ
                        "timeUnixNano": str(m.time_unix_nano),
                        "attributes": [
                            {"key": k, "value": {"stringValue": v}} for k, v in m.attributes.items()
                        ],
                    }
                ]
            },
        }
        for m in metrics
    ]
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": SERVICE_NAME}}
                    ]
                },
                "scopeMetrics": [{"scope": {"name": "psotel-bridge"}, "metrics": entries}],
            }
        ]
    }


def create_emitter(endpoint: str):
    """Collector の /v1/metrics へ POST する emit 関数を返す。"""

    def emit(metrics: list[Metric]) -> None:
        payload = build_payload(metrics)
        if not payload["resourceMetrics"]:
            return
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()

    return emit
