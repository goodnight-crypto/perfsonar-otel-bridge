from psotel.convert import parse_duration_ms


def test_parses_sub_millisecond_duration_to_milliseconds():
    # 実サンプル docs/samples/rtt-1.1.1.1-*.json の .result.mean の形式
    assert parse_duration_ms("PT0.009059S") == 9.059
