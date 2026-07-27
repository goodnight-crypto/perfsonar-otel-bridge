from psotel.convert import convert


def attrs(metrics):
    """全メトリクスが同一の共通 attributes を持つことを前提に1件返す。"""
    assert metrics, "メトリクスが空"
    first = metrics[0].attributes
    for m in metrics:
        assert m.attributes == first, f"{m.name} の attributes が他と異なる"
    return first


def test_source_falls_back_to_participants_when_spec_has_no_source(sample):
    # rtt テストの spec に source は存在しない（schema.md 共通構造の表）
    a = attrs(convert(sample("rtt-1.1.1.1-")))

    assert a["ps.source"] == "lima-perfsonar-vm"
    assert a["ps.destination"] == "1.1.1.1"


def test_source_uses_spec_when_present(sample):
    a = attrs(convert(sample("latency-twamp-192.168.1.101-")))

    assert a["ps.source"] == "192.168.1.104"
    assert a["ps.destination"] == "192.168.1.101"


def test_test_type_and_tool_are_attached(sample):
    a = attrs(convert(sample("latency-twamp-192.168.1.101-")))

    assert a["ps.test.type"] == "latency"
    assert a["ps.tool"] == "twping"


def test_path_id_is_absent_when_reference_is_null(sample):
    # 手動 task では .reference が null。属性を付けずに省く
    a = attrs(convert(sample("rtt-1.1.1.1-")))

    assert "path.id" not in a


def test_path_id_is_taken_from_reference_when_present():
    envelope = {
        "test": {"type": "rtt", "spec": {"dest": "192.168.1.101"}},
        "participants": ["192.168.1.104"],
        "tool": {"name": "twping"},
        "reference": {"path.id": "lan-wired"},
        "run": {"end-time": "2026-07-27T05:45:27+00:00"},
        "result": {"loss": 0.0},
    }

    a = attrs(convert(envelope))

    assert a["path.id"] == "lan-wired"
