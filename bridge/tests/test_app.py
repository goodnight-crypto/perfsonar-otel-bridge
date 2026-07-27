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


def test_throughput_intervals_are_not_emitted_as_metrics(sample):
    # 95KB の intervals[] を取り込まないことの確認
    client, recorder = client_with_recorder()

    client.put("/archive", json=sample("throughput-192.168.1.104-"))

    assert [m.name for m in recorder.batches[0]] == ["perfsonar.throughput.bps"]
