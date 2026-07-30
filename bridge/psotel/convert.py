"""pScheduler の archiver JSON を OpenTelemetry メトリクスに変換する。

変換仕様の正は ../../docs/schema.md。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

# max-clock-error がこの値を超えたら片道遅延を信頼しない（docs/schema.md）。
#
# 当初は 5.0 だった（「正常時 0.0ms / 異常時 27.47ms の中間」という根拠）。
# その後 VM のクロックが収束し、正常時が 0.0 ではなく 4.67〜4.88ms だと判明したため
# 根拠が崩れた。健全域(〜4.88)と既知の異常(27.47)の対数中間 √(4.88×27.47)≒11.6 に近い
# 10.0 へ引き上げた。異常サンプルは n=1 なので、これは検証済みの境界ではなく発見的な値。
CLOCK_ERROR_THRESHOLD_MS = 10.0

# 片道遅延の値そのものに対する妥当性の上限（ms）。path.id ごとに経路の実態で分ける。
#
# max-clock-error のゲートだけでは不十分だと実測で判明したため追加した。
# 誤差 0.23ms と自己申告しながら片道遅延 102ms を返す run が実在し、
# ゲートを通過した約55件のうち少なくとも15件が物理的にありえない値だった
# （experiments/w2-notes.md Step 5-2）。
#
# 当初は全経路一律 50.0 だったが、これは LAN ペア専用の値であり、WAN を測り始めると
# 二重に間違う: LAN には緩すぎ、WAN では実在する輻輳を無言で捨てる。
#
# LAN を 5.0 に絞っても iperf3 とは衝突しない。throughput は `exclusive`、rtt は
# `background`、latency は `normal` で、**pScheduler は iperf3 実行中に自分の他の測定を
# 走らせない**（experiments/w2-notes.md:303-305 の実測）。30分ごとの iperf3 に押し上げられた
# 片道遅延が誤ってゲートに落ちる経路は設計上塞がれている（測定は失われず slip する）。
DELAY_CEILING_MS = {
    "lan-wired": 5.0,  # 実測 0.2〜0.64ms。GbE 化後の精度の床を踏まえ厳しくする
    "wan-sinet-tokyo": 200.0,  # 平常 3.9ms。ICEPP で観測した 80〜90ms の輻輳も残す
    "wan-riken-tsukuba": 200.0,  # 平常 4.7ms
}
# path.id が無い手動タスク用。経路が分からない以上、緩めも締めもできない
DEFAULT_DELAY_CEILING_MS = 50.0


@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    unit: str
    attributes: dict[str, str] = field(default_factory=dict)
    time_unix_nano: int = 0


def parse_duration_ms(value: str) -> float:
    """ISO8601 duration 文字列をミリ秒に変換する。

    float で 1000 倍すると誤差が出る（0.001301 * 1000 = 1.3010000000000002）ため
    Decimal で桁移動してから float に落とす。
    """
    seconds = Decimal(value.removeprefix("PT").removesuffix("S"))
    return float(seconds * 1000)


def build_attributes(envelope: dict) -> dict[str, str]:
    """全メトリクスに付ける共通 attributes を組む。"""
    test = envelope["test"]
    spec = test["spec"]
    attributes = {
        # rtt/trace の spec には source が無いため participants[0] にフォールバックする
        "ps.source": spec.get("source") or envelope["participants"][0],
        "ps.destination": spec["dest"],
        "ps.test.type": test["type"],
        "ps.tool": envelope["tool"]["name"],
    }
    # pSConfig の reference 機能が path.id を埋める。手動 task では null
    reference = envelope.get("reference") or {}
    if "path.id" in reference:
        attributes["path.id"] = reference["path.id"]
    # 測定ごとに値が変わる数値（max-clock-error / retransmits）は attribute にしない。
    # Splunk は dimension の組み合わせごとに時系列を作るため、値が変わるたびに
    # 新しい時系列が生まれて際限なく増える。実際 packet.loss.ratio が1日で269系列に
    # 膨らんだ（experiments/w2-notes.md Step 8）。これらは Gauge メトリクスとして出す
    return attributes


def weighted_median(histogram: dict[str, int]) -> float:
    """{"遅延ms": 個数} 形式のヒストグラムから重み付き中央値を求める。"""
    bins = sorted((float(delay), count) for delay, count in histogram.items())
    total = sum(count for _, count in bins)
    cumulative = 0
    for delay, count in bins:
        cumulative += count
        if cumulative >= total / 2:
            return delay
    raise ValueError("ヒストグラムが空")


def convert(envelope: dict) -> list[Metric]:
    """archiver 封筒 1 件をメトリクスのリストに変換する。"""
    result = envelope["result"]
    attributes = build_attributes(envelope)
    # 送信遅延と測定時刻を分離するため run.end-time を観測時刻に使う
    observed_at = datetime.fromisoformat(envelope["run"]["end-time"])
    time_unix_nano = int(observed_at.timestamp() * 1_000_000_000)
    metrics: list[Metric] = []

    def add(name: str, value: float, unit: str) -> None:
        # メトリクスごとに独立した dict を持たせる。共有すると将来
        # 属性を出し分けたときに同じ封筒の全メトリクスへ波及する
        metrics.append(Metric(name, value, unit, dict(attributes), time_unix_nano))

    test_type = envelope["test"]["type"]

    if test_type == "rtt":
        # 測定失敗時、統計キーは null ではなく省略される。0 を代入すると
        # 「遅延 0ms の健全なリンク」として可視化されるため、キーが無ければ出力しない
        if "mean" in result:
            add("perfsonar.rtt.mean", parse_duration_ms(result["mean"]), "ms")
        if "max" in result:
            add("perfsonar.rtt.max", parse_duration_ms(result["max"]), "ms")
        if "loss" in result:
            add("perfsonar.packet.loss.ratio", float(result["loss"]), "1")

    elif test_type == "latency":
        # latency に loss フィールドは無い。パケット数から算出する
        sent = result["packets-sent"]
        add("perfsonar.packet.loss.ratio", result["packets-lost"] / sent, "1")
        # クロック誤差が大きいと片道遅延は負値になるなど信頼できない。
        # ロス率はクロック非依存なので落とさず、遅延だけをゲートする。
        #
        # 0.0 は「誤差なし」ではなく「推定できていない」を意味しうるため通さない。
        # TWAMP の Error Estimate は Multiplier × 2^Scale 形式で、同期機構が見積もりを
        # 提供できないと Multiplier が 0 のまま埋まる実装がある。実際 w1-notes.md:42 に
        # 0.0 報告なのに片道遅延が中央値 -4.62ms と壊れていた例がある
        clock_error = result["max-clock-error"]
        # 遅延がゲートで落ちた理由を追えるよう、誤差そのものを時系列として残す
        add("perfsonar.twamp.clock_error", clock_error, "ms")
        median = weighted_median(result["histogram-latency"])
        # 自己申告のクロック誤差は当てにならないので、値そのものの妥当性も見る。
        # 負の片道遅延は物理的にありえず、LAN で数十msも同様。
        # 上限は経路依存なので path.id で引く（未知の path.id も既定値に落ちる）
        ceiling = DELAY_CEILING_MS.get(attributes.get("path.id"), DEFAULT_DELAY_CEILING_MS)
        if 0 < clock_error <= CLOCK_ERROR_THRESHOLD_MS and 0 < median <= ceiling:
            add("perfsonar.twamp.delay.median", median, "ms")

    elif test_type == "trace":
        add("perfsonar.trace.hops", len(result["paths"][0]), "{hops}")

    elif test_type == "throughput":
        # intervals[] と diags は変換しない（サイズが大きく集計値のみで足りる）
        summary = result["summary"]["summary"]
        add("perfsonar.throughput.bps", summary["receiver-throughput-bits"], "bit/s")
        if summary.get("retransmits") is not None:
            add("perfsonar.throughput.retransmits", summary["retransmits"], "{retransmits}")

    else:
        # 黙って捨てると測定が消えたことに誰も気付けない
        logger.warning("未対応のテスト種別のため変換しない: %s", test_type)

    return metrics
