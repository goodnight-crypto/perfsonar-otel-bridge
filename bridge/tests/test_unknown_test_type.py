import logging

from psotel.convert import convert


def unknown_envelope(test_type="dns"):
    return {
        "test": {"type": test_type, "spec": {"dest": "192.168.1.101"}},
        "participants": ["192.168.1.104"],
        "tool": {"name": "dnspy"},
        "reference": None,
        "run": {"end-time": "2026-07-28T00:00:00+00:00"},
        "result": {"succeeded": True},
    }


def test_unknown_test_type_produces_no_metrics():
    assert convert(unknown_envelope()) == []


def test_unknown_test_type_is_logged_with_its_name(caplog):
    # 黙って捨てるとデータが消えたことに誰も気付けない
    with caplog.at_level(logging.WARNING, logger="psotel.convert"):
        convert(unknown_envelope("dns"))

    assert "dns" in caplog.text
