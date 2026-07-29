#!/usr/bin/env bash
#
# deploy/splunk/detectors/ で作った Detector の状態と発火履歴を出す。
# 平常運転で誤検知していないことの確認に使う（docs/runbook-w2.md Step 6）。
#
#   ./deploy/splunk/check-alerts.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
set -a; . "$ROOT/.env"; set +a
: "${SPLUNK_REALM:?}"; : "${SPLUNK_API_TOKEN:?}"

SPLUNK_DEFS_DIR="$HERE" exec python3 - <<'PY'
import datetime, json, os, urllib.request

HERE = os.environ["SPLUNK_DEFS_DIR"]
REALM = os.environ["SPLUNK_REALM"]
TOKEN = os.environ["SPLUNK_API_TOKEN"]
BASE = f"https://api.{REALM}.signalfx.com"


def get(path):
    req = urllib.request.Request(BASE + path)
    req.add_header("X-SF-TOKEN", TOKEN)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


ids_path = os.path.join(HERE, ".ids.json")
if not os.path.exists(ids_path):
    raise SystemExit("先に apply.sh を実行すること（.ids.json が無い）")

detectors = json.load(open(ids_path)).get("detector", {})
if not detectors:
    raise SystemExit("Detector が未投入。./deploy/splunk/apply.sh --only detectors")

JST = datetime.timezone(datetime.timedelta(hours=9))


def when(ms):
    if not ms:
        return "?"
    return datetime.datetime.fromtimestamp(ms / 1000, JST).strftime("%m-%d %H:%M")


total = 0
active = 0
for key, oid in sorted(detectors.items()):
    d = get(f"/v2/detector/{oid}")
    # 発火は events[].anomalyState == "ANOMALOUS"。
    # v2 の一部レスポンスにある "is" フィールドで判定してはいけない（常に空振りする）。
    events = get(f"/v2/detector/{oid}/events?limit=100")
    fired = [e for e in events if e.get("anomalyState") == "ANOMALOUS"]
    incidents = get(f"/v2/detector/{oid}/incidents")
    live = [i for i in incidents if i.get("active")]
    total += len(fired)
    active += len(live)
    print(f"{key:26} {d.get('status'):8} 発火 {len(fired):3} 件 / 継続中 {len(live)} 件   {d['name']}")
    for e in sorted(fired, key=lambda x: x.get("timestamp") or 0, reverse=True)[:6]:
        keys = {}
        for v in (e.get("inputs") or {}).values():
            keys.update(v.get("key") or {})
            val = v.get("value")
        label = " ".join(f"{k}={v}" for k, v in sorted(keys.items())
                         if k in ("path.id", "ps.source", "ps.destination"))
        print(f"    発火 {when(e.get('timestamp'))}  {label}  値={val}")
    for i in live:
        print(f"    継続中 {when(i.get('anomalyStateUpdateTimestamp'))}  {i.get('displayBody')}")

print()
print(f"合計 発火 {total} 件 / 継続中 {active} 件")
print("平常運転の確認では 0 件であること（docs/runbook-w2.md Step 6）")
PY
