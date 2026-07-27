from psotel.convert import convert


def metric(metrics, name):
    found = [m for m in metrics if m.name == name]
    assert found, f"{name} が出力されていない。出力: {[m.name for m in metrics]}"
    return found[0]


def test_rtt_sample_yields_mean_in_milliseconds(sample):
    metrics = convert(sample("rtt-1.1.1.1-"))

    m = metric(metrics, "perfsonar.rtt.mean")
    assert m.value == 9.059
    assert m.unit == "ms"


def test_rtt_sample_yields_max_in_milliseconds(sample):
    metrics = convert(sample("rtt-1.1.1.1-"))

    m = metric(metrics, "perfsonar.rtt.max")
    assert m.value == 9.783
    assert m.unit == "ms"


def test_rtt_sample_yields_loss_ratio(sample):
    metrics = convert(sample("rtt-1.1.1.1-"))

    m = metric(metrics, "perfsonar.packet.loss.ratio")
    assert m.value == 0.0
    assert m.unit == "1"
