"""pScheduler の archiver JSON を OpenTelemetry メトリクスに変換する。

変換仕様の正は ../../docs/schema.md。
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

# max-clock-error がこの値を超えたら片道遅延を信頼しない（docs/schema.md）。
# 実測は正常時 0.0ms / 異常時 27.47ms でその中間に置いた。
CLOCK_ERROR_THRESHOLD_MS = 5.0


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
    result = envelope["result"]
    # TWAMP が埋めるクロック誤差見積もり。ゲートで落とした理由を追えるよう属性に残す
    if "max-clock-error" in result:
        attributes["ps.max_clock_error"] = str(result["max-clock-error"])
    retransmits = result.get("summary", {}).get("summary", {}).get("retransmits")
    if retransmits is not None:
        attributes["ps.retransmits"] = str(retransmits)
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
        metrics.append(Metric(name, value, unit, attributes, time_unix_nano))

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
        # ロス率はクロック非依存なので落とさず、遅延だけをゲートする
        if result["max-clock-error"] <= CLOCK_ERROR_THRESHOLD_MS:
            add("perfsonar.twamp.delay.median", weighted_median(result["histogram-latency"]), "ms")

    elif test_type == "trace":
        add("perfsonar.trace.hops", len(result["paths"][0]), "{hops}")

    elif test_type == "throughput":
        # intervals[] と diags は変換しない（サイズが大きく集計値のみで足りる）
        add("perfsonar.throughput.bps", result["summary"]["summary"]["receiver-throughput-bits"], "bit/s")

    return metrics
