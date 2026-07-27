"""実 archiver が送った rtt+twping の封筒に対する characterization test。

TDD で駆動したものではなく、実経路を通した実物で既存の変換挙動を固定するためのもの。
"""

from psotel.convert import convert


def find(metrics, name):
    found = [m for m in metrics if m.name == name]
    assert found, f"{name} が出力されていない。出力: {[m.name for m in metrics]}"
    return found[0]


def test_twping_rtt_yields_the_same_metrics_as_icmp_rtt(sample):
    metrics = convert(sample("rtt-twping-192.168.1.101-archiver"))

    assert find(metrics, "perfsonar.rtt.mean").value == 0.976
    assert find(metrics, "perfsonar.rtt.max").value == 1.301
    assert find(metrics, "perfsonar.packet.loss.ratio").value == 0.0


def test_tool_attribute_distinguishes_twamp_from_icmp(sample):
    # LAN 基準線が TWAMP 由来か ICMP 由来かをダッシュボード側で判別できること
    twamp = convert(sample("rtt-twping-192.168.1.101-archiver"))
    icmp = convert(sample("rtt-1.1.1.1-"))

    assert twamp[0].attributes["ps.tool"] == "twping"
    assert icmp[0].attributes["ps.tool"] == "ping"


def test_twping_rtt_takes_source_from_spec(sample):
    # ICMP rtt の spec には source が無いが、twping 版には存在する
    metrics = convert(sample("rtt-twping-192.168.1.101-archiver"))

    assert metrics[0].attributes["ps.source"] == "192.168.1.104"
