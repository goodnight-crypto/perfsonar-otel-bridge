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
import json, os, urllib.request

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

total = 0
for key, oid in sorted(detectors.items()):
    d = get(f"/v2/detector/{oid}")
    events = get(f"/v2/detector/{oid}/events?limit=50")
    fired = [e for e in events if e.get("is") == "anomalous"]
    total += len(fired)
    print(f"{key:26} {d.get('status'):8} 発火 {len(fired):3} 件   {d['name']}")
    for e in fired[:5]:
        ts = e.get("timestamp")
        print(f"    - {ts}  {e.get('inputs', {})}")

print()
print(f"合計 {total} 件")
print("平常運転の確認では 0 件であること（docs/runbook-w2.md Step 6）")
PY
