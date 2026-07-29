#!/usr/bin/env bash
#
# charts/*.json の programText を SignalFlow で実際に評価して、
# 各 publish ラベルにデータ点が返ることを確認する。
# 「ダッシュボードを開いたら空だった」を投入前に潰すための検証。
#
#   ./deploy/splunk/check-charts.sh          # 直近6時間
#   WINDOW_HOURS=24 ./deploy/splunk/check-charts.sh
#
# 注意: 読み取りに /v1/timeserieswindow は使わない。あの API は連投すると
# HTTP 200 の本文で "Your role doesn't let you perform this action." を返し、
# さらに叩くと 403 に落ちる（実体はレート制限）。SignalFlow の execute は
# チャートと同じ programText をそのまま評価できる点でも素直。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
set -a; . "$ROOT/.env"; set +a
: "${SPLUNK_REALM:?}"; : "${SPLUNK_API_TOKEN:?}"

SPLUNK_DEFS_DIR="$HERE" exec python3 - <<'PY'
import json, os, re, time, urllib.request

HERE = os.environ["SPLUNK_DEFS_DIR"]
REALM = os.environ["SPLUNK_REALM"]
TOKEN = os.environ["SPLUNK_API_TOKEN"]
HOURS = int(os.environ.get("WINDOW_HOURS", "6"))

now = int(time.time() * 1000)
start = now - HOURS * 3600 * 1000
url = (f"https://stream.{REALM}.signalfx.com/v2/signalflow/execute"
       f"?start={start}&stop={now}&resolution=300000&immediate=true")


def run(program):
    """programText を評価し、tsId -> データ点数 と tsId -> publish ラベルを返す。"""
    req = urllib.request.Request(url, data=program.encode(), method="POST")
    req.add_header("X-SF-TOKEN", TOKEN)
    req.add_header("Content-Type", "text/plain")
    counts, labels = {}, {}
    with urllib.request.urlopen(req, timeout=90) as r:
        event, buf = None, []
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data:"):
                buf.append(line[5:].lstrip())
            elif line == "":
                if event and buf:
                    try:
                        payload = json.loads("".join(buf))
                    except json.JSONDecodeError:
                        payload = None
                    if payload:
                        if event == "metadata":
                            p = payload.get("properties", {})
                            labels[payload.get("tsId")] = p.get("sf_streamLabel") or "?"
                        elif event == "data":
                            for d in payload.get("data", []):
                                counts[d["tsId"]] = counts.get(d["tsId"], 0) + 1
                event, buf = None, []
    return counts, labels


ok = True
for fn in sorted(os.listdir(os.path.join(HERE, "charts"))):
    if not fn.endswith(".json"):
        continue
    with open(os.path.join(HERE, "charts", fn)) as f:
        chart = json.load(f)
    counts, labels = run(chart["programText"])
    per_label = {}
    for ts, n in counts.items():
        per_label.setdefault(labels.get(ts, "?"), []).append(n)
    declared = [o["label"] for o in chart["options"]["publishLabelOptions"]]
    parts = []
    for lab in declared:
        series = per_label.get(lab, [])
        total = sum(series)
        if total == 0:
            ok = False
            parts.append(f"{lab}=なし")
        else:
            parts.append(f"{lab}=系列{len(series)}/点{total}")
    print(f"{fn[:-5]:24} " + "  ".join(parts))
    time.sleep(1)

print()
print(f"直近{HOURS}時間: " + ("全チャートにデータあり" if ok
                              else "!! データの無い publish ラベルがある"))
PY
