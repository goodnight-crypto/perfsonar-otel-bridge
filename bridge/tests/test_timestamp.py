from psotel.convert import convert


def test_metrics_are_timestamped_with_run_end_time(sample):
    # 送信遅延と測定時刻を分離するため run.end-time を採用する（docs/schema.md）
    metrics = convert(sample("rtt-1.1.1.1-"))

    # 2026-07-27T05:45:27+00:00
    assert all(m.time_unix_nano == 1785131127000000000 for m in metrics)
