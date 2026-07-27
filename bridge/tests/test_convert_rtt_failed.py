from psotel.convert import convert


def names(metrics):
    return [m.name for m in metrics]


def test_total_loss_run_yields_loss_ratio_of_one(sample):
    # succeeded:true のまま loss:1.0 になる実サンプル（schema.md「エラー/測定失敗runの扱い」）
    metrics = convert(sample("rtt-FAILED-192.0.2.1-"))

    loss = [m for m in metrics if m.name == "perfsonar.packet.loss.ratio"]
    assert len(loss) == 1
    assert loss[0].value == 1.0


def test_total_loss_run_omits_delay_metrics_entirely(sample):
    # mean/max/stddev は null ではなくキーごと省略される。0 を送ってはいけない
    metrics = convert(sample("rtt-FAILED-192.0.2.1-"))

    assert "perfsonar.rtt.mean" not in names(metrics)
    assert "perfsonar.rtt.max" not in names(metrics)
