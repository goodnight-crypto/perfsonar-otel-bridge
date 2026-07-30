from psotel.convert import convert


def names(metrics):
    return [m.name for m in metrics]


def find(metrics, name):
    found = [m for m in metrics if m.name == name]
    assert found, f"{name} が出力されていない。出力: {names(metrics)}"
    return found[0]


def latency_envelope(*, max_clock_error, histogram, path_id=None):
    """clock error・ヒストグラム・path.id だけを変えた latency 封筒を組む。

    path_id を省略すると reference は null（手動 task 相当）になる。
    """
    return {
        "test": {"type": "latency", "spec": {"dest": "192.168.1.101", "source": "192.168.1.104"}},
        "participants": ["192.168.1.104"],
        "tool": {"name": "twping"},
        "reference": {"path.id": path_id} if path_id else None,
        "run": {"end-time": "2026-07-27T05:46:15+00:00"},
        "result": {
            "packets-sent": 100,
            "packets-lost": 0,
            "max-clock-error": max_clock_error,
            "histogram-latency": histogram,
        },
    }


def test_loss_ratio_is_computed_from_packet_counts(sample):
    # latency には loss フィールドが無く packets-lost / packets-sent から算出する
    metrics = convert(sample("latency-twamp-192.168.1.101-"))

    assert find(metrics, "perfsonar.packet.loss.ratio").value == 0.0


def test_loss_ratio_reflects_lost_packets():
    envelope = latency_envelope(max_clock_error=0.1, histogram={"1.0": 100})
    envelope["result"]["packets-lost"] = 3

    metrics = convert(envelope)

    assert find(metrics, "perfsonar.packet.loss.ratio").value == 0.03


def test_delay_median_is_weighted_median_of_histogram():
    envelope = latency_envelope(max_clock_error=0.5, histogram={"1.0": 1, "2.0": 1, "3.0": 1})

    m = find(convert(envelope), "perfsonar.twamp.delay.median")

    assert m.value == 2.0
    assert m.unit == "ms"


def test_delay_median_is_gated_out_when_clock_error_exceeds_threshold(sample):
    # 実サンプルは max-clock-error 27.47ms。閾値 5.0ms を超えるので遅延は信頼できない
    metrics = convert(sample("latency-twamp-192.168.1.101-"))

    assert "perfsonar.twamp.delay.median" not in names(metrics)


def test_loss_ratio_survives_the_clock_gate(sample):
    # ゲートは遅延系だけを落とす。ロス率はクロックに依存しないので残す
    metrics = convert(sample("latency-twamp-192.168.1.101-"))

    assert "perfsonar.packet.loss.ratio" in names(metrics)


def test_delay_median_survives_the_observed_healthy_clock_error():
    # クロック収束後の実測は 4.67〜4.88ms。旧閾値 5.0 では余裕が 0.12ms しか無く系列が断続する
    envelope = latency_envelope(max_clock_error=7.0, histogram={"1.0": 1, "2.0": 1, "3.0": 1})

    assert "perfsonar.twamp.delay.median" in names(convert(envelope))


def test_delay_median_is_gated_when_clock_error_is_reported_as_zero():
    # 0.0 は「誤差なし」ではなく「推定できていない」を意味しうる。
    # w1-notes.md:42 に 0.0 報告なのに片道遅延が中央値 -4.62ms と壊れていた実例がある
    envelope = latency_envelope(max_clock_error=0.0, histogram={"1.0": 1, "2.0": 1, "3.0": 1})

    assert "perfsonar.twamp.delay.median" not in names(convert(envelope))


def test_delay_median_is_still_gated_at_the_known_broken_clock_error():
    # W1 で観測した壊れた状態。閾値を上げても落とし続けること
    envelope = latency_envelope(max_clock_error=27.47, histogram={"-11.8": 1, "-11.7": 1})

    assert "perfsonar.twamp.delay.median" not in names(convert(envelope))


def test_delay_median_is_gated_when_negative():
    # 片道遅延が負になるのは物理的にありえない。実測 00:21-00:50 JST の区間は
    # max-clock-error 0.10〜0.15 と申告しながら -0.8〜-0.2ms を返してゲートを通っていた
    envelope = latency_envelope(max_clock_error=0.12, histogram={"-0.8": 1, "-0.5": 1, "-0.2": 1})

    assert "perfsonar.twamp.delay.median" not in names(convert(envelope))


def test_delay_median_is_gated_when_implausibly_large_for_the_lan():
    # 実測 01:50 JST: max-clock-error 0.23ms と申告しながら片道遅延 102ms。
    # LAN の RTT は約0.9msなので片道102msはありえない
    envelope = latency_envelope(
        max_clock_error=0.23, histogram={"101.83": 1, "102.0": 1, "102.29": 1}
    )

    assert "perfsonar.twamp.delay.median" not in names(convert(envelope))


def test_plausible_delay_still_passes_both_gates():
    envelope = latency_envelope(max_clock_error=4.8, histogram={"2.4": 1, "2.5": 1, "2.6": 1})

    assert find(convert(envelope), "perfsonar.twamp.delay.median").value == 2.5


def test_lan_delay_passes_at_the_observed_gbe_value():
    # GbE 化後の LAN 実測は中央値 0.220ms（experiments/w3-notes.md Step 8）。
    # 上限を 5.0 に絞っても正常値は通ること
    envelope = latency_envelope(
        max_clock_error=0.32, histogram={"0.21": 1, "0.22": 1, "0.23": 1}, path_id="lan-wired"
    )

    assert find(convert(envelope), "perfsonar.twamp.delay.median").value == 0.22


def test_lan_delay_is_gated_above_the_lan_ceiling():
    # LAN の上限は 5.0ms。旧 50.0 なら通っていた 6.0ms を落とす
    envelope = latency_envelope(
        max_clock_error=0.3, histogram={"6.0": 3}, path_id="lan-wired"
    )

    assert "perfsonar.twamp.delay.median" not in names(convert(envelope))


def test_wan_delay_survives_congestion_that_the_lan_ceiling_would_reject():
    # ICEPP で観測した 80〜90ms の輻輳は WAN では実在する値。旧 50.0 では捨てていた
    envelope = latency_envelope(
        max_clock_error=0.5, histogram={"90.0": 3}, path_id="wan-sinet-tokyo"
    )

    assert find(convert(envelope), "perfsonar.twamp.delay.median").value == 90.0


def test_delay_without_path_id_falls_back_to_the_default_ceiling():
    # 手動 task は reference が null。既定の 50.0 が効く
    envelope = latency_envelope(max_clock_error=0.5, histogram={"60.0": 3})

    assert "perfsonar.twamp.delay.median" not in names(convert(envelope))


def test_clock_error_is_emitted_as_a_metric(sample):
    # 測定ごとに変わる数値を dimension にすると、値が変わるたびに新しい時系列が作られる。
    # 実際 packet.loss.ratio が1日で269系列に膨らんだ（experiments/w2-notes.md Step 8）
    metrics = convert(sample("latency-twamp-192.168.1.101-"))

    m = find(metrics, "perfsonar.twamp.clock_error")
    assert m.value == 27.47
    assert m.unit == "ms"


def test_clock_error_is_not_a_dimension(sample):
    metrics = convert(sample("latency-twamp-192.168.1.101-"))

    for m in metrics:
        assert "ps.max_clock_error" not in m.attributes


def test_clock_error_is_emitted_even_when_the_delay_is_gated(sample):
    # 実サンプルは 27.47ms でゲートされる。なぜ欠測したかを追えるよう誤差自体は残す
    metrics = convert(sample("latency-twamp-192.168.1.101-"))

    assert "perfsonar.twamp.delay.median" not in names(metrics)
    assert "perfsonar.twamp.clock_error" in names(metrics)
