from psotel.convert import Metric
from psotel.otlp import build_payload


def metrics_in(payload):
    return payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]


def test_metric_becomes_gauge_datapoint_with_measurement_timestamp():
    m = Metric("perfsonar.rtt.mean", 9.059, "ms", {"ps.source": "192.168.1.104"}, 1785131127000000000)

    entry = metrics_in(build_payload([m]))[0]

    assert entry["name"] == "perfsonar.rtt.mean"
    assert entry["unit"] == "ms"
    point = entry["gauge"]["dataPoints"][0]
    assert point["asDouble"] == 9.059
    # OTLP/JSON は 64bit 値を文字列で運ぶ
    assert point["timeUnixNano"] == "1785131127000000000"


def test_attributes_are_rendered_as_otlp_key_value_pairs():
    m = Metric("perfsonar.rtt.mean", 1.0, "ms", {"ps.source": "a", "ps.tool": "twping"}, 1)

    point = metrics_in(build_payload([m]))[0]["gauge"]["dataPoints"][0]

    assert {"key": "ps.source", "value": {"stringValue": "a"}} in point["attributes"]
    assert {"key": "ps.tool", "value": {"stringValue": "twping"}} in point["attributes"]


def test_each_metric_name_becomes_its_own_entry():
    batch = [
        Metric("perfsonar.rtt.mean", 1.0, "ms", {}, 1),
        Metric("perfsonar.packet.loss.ratio", 0.0, "1", {}, 1),
    ]

    entries = metrics_in(build_payload(batch))

    assert [e["name"] for e in entries] == ["perfsonar.rtt.mean", "perfsonar.packet.loss.ratio"]


def test_empty_batch_produces_no_resource_metrics():
    # 遅延がゲートされて何も残らない場合、空の封筒を送らない
    assert build_payload([])["resourceMetrics"] == []
