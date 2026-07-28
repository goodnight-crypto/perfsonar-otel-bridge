from psotel.convert import convert


def find(metrics, name):
    found = [m for m in metrics if m.name == name]
    assert found, f"{name} が出力されていない。出力: {[m.name for m in metrics]}"
    return found[0]


def test_trace_yields_hop_count(sample):
    metrics = convert(sample("trace-1.1.1.1-"))

    m = find(metrics, "perfsonar.trace.hops")
    assert m.value == 8
    assert m.unit == "{hops}"


def test_throughput_uses_receiver_side_bits(sample):
    # iperf3 の慣習で receiver 側を正とする（docs/schema.md）
    metrics = convert(sample("throughput-192.168.1.104-"))

    m = find(metrics, "perfsonar.throughput.bps")
    assert m.value == 939753602.196996
    assert m.unit == "bit/s"


def test_retransmits_is_emitted_as_a_metric(sample):
    # 再送数も測定ごとに変わるため dimension にすると時系列が増え続ける
    metrics = convert(sample("throughput-192.168.1.104-"))

    m = find(metrics, "perfsonar.throughput.retransmits")
    assert m.value == 7
    assert m.unit == "{retransmits}"


def test_retransmits_is_not_a_dimension(sample):
    metrics = convert(sample("throughput-192.168.1.104-"))

    for m in metrics:
        assert "ps.retransmits" not in m.attributes
