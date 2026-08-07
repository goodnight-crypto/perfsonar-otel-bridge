#!/usr/bin/env bash
#
# 任意の SignalFlow を評価して、**系列ごとの dimension と値**を出す調査用ツール。
#
# check-charts.sh との違い:
#   check-charts.sh は charts/*.json の programText を publish ラベル単位で集計するだけ。
#   「どの系列が欠けているか」「どの dimension が原因か」は分からない。
#   本スクリプトは任意のクエリを投げて、系列の内訳と生の値を時刻付きで出す。
#   障害の切り分けはほぼこれで進めた（experiments/w3-notes.md Step 11 以降）。
#
# 使い方:
#   ./deploy/splunk/query.sh <<'EOF'
#   loss = data('perfsonar.packet.loss.ratio').mean(by=['path.id','ps.test.type']).publish(label='loss')
#   EOF
#
# 環境変数:
#   WINDOW_HOURS=6      直近何時間か（既定 6）
#   RESOLUTION_MS       集計解像度（既定 300000 = 5分）
#   SHOW_POINTS=20      各系列の末尾 N 点を時刻付きで表示する
#   START_MS / STOP_MS  絶対時刻（エポックms）。撮影レンジの再現に使う
#
# 例: 特定期間の異常点だけ数える
#   START_MS=$(( $(date -j -f "%Y-%m-%d %H:%M:%S" "2026-08-04 09:00:00" +%s) * 1000 ))
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
set -a; . "$ROOT/.env"; set +a
: "${SPLUNK_REALM:?}"; : "${SPLUNK_API_TOKEN:?}"

PROGRAM="$(cat)"
PROGRAM="$PROGRAM" python3 - <<'PY'
import json, os, time, urllib.request
from collections import defaultdict

REALM = os.environ["SPLUNK_REALM"]; TOKEN = os.environ["SPLUNK_API_TOKEN"]
HOURS = float(os.environ.get("WINDOW_HOURS", "6"))
RES = os.environ.get("RESOLUTION_MS", "300000")
program = os.environ["PROGRAM"]

if os.environ.get("START_MS") and os.environ.get("STOP_MS"):
    start, now = int(os.environ["START_MS"]), int(os.environ["STOP_MS"])
else:
    now = int(time.time() * 1000); start = now - int(HOURS * 3600 * 1000)

# 読み取りに /v1/timeserieswindow は使わない。連投すると HTTP 200 の本文で
# "Your role doesn't let you perform this action." を返し、さらに叩くと 403 に落ちる
url = (f"https://stream.{REALM}.signalfx.com/v2/signalflow/execute"
       f"?start={start}&stop={now}&resolution={RES}&immediate=true")
req = urllib.request.Request(url, data=program.encode(), method="POST")
req.add_header("X-SF-TOKEN", TOKEN); req.add_header("Content-Type", "text/plain")

meta, vals = {}, defaultdict(list)
with urllib.request.urlopen(req, timeout=120) as r:
    event, buf = None, []
    for raw in r:
        line = raw.decode().rstrip("\n")
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data:"):
            buf.append(line[5:].lstrip())
        elif line == "":
            if event and buf:
                try: payload = json.loads("".join(buf))
                except json.JSONDecodeError: payload = None
                if payload:
                    if event == "metadata":
                        meta[payload.get("tsId")] = payload.get("properties", {})
                    elif event == "data":
                        ts = payload.get("logicalTimestampMs")
                        for d in payload.get("data", []):
                            vals[d["tsId"]].append((ts, d["value"]))
                    elif event == "error":
                        print("ERROR:", json.dumps(payload, ensure_ascii=False))
            event, buf = None, []

SKIP = {"sf_key", "sf_metric", "sf_originatingMetric", "sf_resolutionMs", "sf_type",
        "sf_isPreQuantized", "sf_organizationID", "jobId",
        "sf_singletonFixedDimensions", "sf_streamLabel"}
if not meta:
    print("(メタデータなし = 系列0)")
for ts, p in sorted(meta.items(), key=lambda kv: str(kv[1].get("sf_streamLabel"))):
    dims = {k: v for k, v in p.items() if k not in SKIP and not k.startswith("sf_")}
    pts = vals.get(ts, []); label = p.get("sf_streamLabel", "?")
    nums = [v for _, v in pts]
    stat = f" min={min(nums):.6g} max={max(nums):.6g} last={nums[-1]:.6g}" if nums else ""
    print(f"[{label}] 点{len(pts)}{stat}")
    print(f"    {json.dumps(dims, ensure_ascii=False, sort_keys=True)}")
    if os.environ.get("SHOW_POINTS"):
        for t, v in pts[-int(os.environ["SHOW_POINTS"]):]:
            print(f"      {time.strftime('%m-%d %H:%M:%S', time.localtime(t/1000))}  {v}")
PY
