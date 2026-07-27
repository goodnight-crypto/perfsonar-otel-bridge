import logging

from fastapi.testclient import TestClient

from psotel.app import create_app


class Recorder:
    """emit された Metric を溜めるだけの受け皿。モックの呼び出し回数ではなく実データを検証する。"""

    def __init__(self):
        self.batches = []

    def __call__(self, metrics):
        self.batches.append(metrics)


def client_with_recorder():
    recorder = Recorder()
    return TestClient(create_app(emit=recorder)), recorder


def test_archiver_put_is_accepted(sample):
    # pScheduler の http archiver は既定で op:put。PUT を受けられないと 501 になる
    client, _ = client_with_recorder()

    response = client.put("/archive", json=sample("rtt-1.1.1.1-"))

    assert response.status_code == 200


def test_archiver_post_is_also_accepted(sample):
    client, _ = client_with_recorder()

    response = client.post("/archive", json=sample("rtt-1.1.1.1-"))

    assert response.status_code == 200


def test_received_envelope_is_converted_and_emitted(sample):
    client, recorder = client_with_recorder()

    client.put("/archive", json=sample("rtt-1.1.1.1-"))

    assert len(recorder.batches) == 1
    names = [m.name for m in recorder.batches[0]]
    assert names == ["perfsonar.rtt.mean", "perfsonar.rtt.max", "perfsonar.packet.loss.ratio"]


def malformed_envelope():
    """result が欠落した封筒。pScheduler の JSON 形状が変わった場合を模す。"""
    return {
        "test": {"type": "rtt", "spec": {"dest": "192.168.1.101"}},
        "participants": ["192.168.1.104"],
        "tool": {"name": "ping"},
        "reference": None,
        "run": {"end-time": "2026-07-28T00:00:00+00:00"},
    }


def test_malformed_envelope_is_reported_as_a_failure(sample):
    # 200 を返すとデータが消えたことが archiver 側の run 詳細に残らない
    client, _ = client_with_recorder()

    response = client.put("/archive", json=malformed_envelope())

    assert response.status_code == 500


def test_malformed_envelope_is_logged_with_its_test_type(caplog):
    client, _ = client_with_recorder()

    with caplog.at_level(logging.ERROR, logger="psotel.app"):
        client.put("/archive", json=malformed_envelope())

    assert "rtt" in caplog.text


def test_non_json_body_is_reported_as_a_failure():
    client, _ = client_with_recorder()

    response = client.put(
        "/archive", content=b"not json at all", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 500


def test_malformed_envelope_is_not_emitted(sample):
    client, recorder = client_with_recorder()

    client.put("/archive", json=malformed_envelope())

    assert recorder.batches == []


def test_throughput_intervals_are_not_emitted_as_metrics(sample):
    # 95KB の intervals[] を取り込まないことの確認
    client, recorder = client_with_recorder()

    client.put("/archive", json=sample("throughput-192.168.1.104-"))

    assert [m.name for m in recorder.batches[0]] == ["perfsonar.throughput.bps"]
