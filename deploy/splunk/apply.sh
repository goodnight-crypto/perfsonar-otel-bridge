#!/usr/bin/env bash
#
# deploy/splunk/ の定義を Splunk Observability Cloud に冪等に投入する。
#
#   ./deploy/splunk/apply.sh              # チャート・ダッシュボード・Detector を全部
#   ./deploy/splunk/apply.sh --dry-run    # 送信せず差分だけ表示
#   ./deploy/splunk/apply.sh --only charts
#
# 作成した ID は deploy/splunk/.ids.json に記録する。ID は秘密ではないので commit してよい。
# トークンは環境変数から Python に渡すだけで、コマンド引数にも出力にも出さない（CLAUDE.md 規約1）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "エラー: $ROOT/.env が無い" >&2
  exit 1
fi
set -a; . "$ROOT/.env"; set +a

: "${SPLUNK_REALM:?SPLUNK_REALM が .env に無い}"
: "${SPLUNK_API_TOKEN:?SPLUNK_API_TOKEN が .env に無い（INGEST トークンでは API を叩けない）}"

SPLUNK_DEFS_DIR="$HERE" exec python3 - "$@" <<'PY'
import json, os, sys, urllib.error, urllib.request

HERE = os.environ["SPLUNK_DEFS_DIR"]
REALM = os.environ["SPLUNK_REALM"]
TOKEN = os.environ["SPLUNK_API_TOKEN"]
BASE = f"https://api.{REALM}.signalfx.com"
IDS_PATH = os.path.join(HERE, ".ids.json")

GROUP_NAME = "perfSONAR home lab"

args = sys.argv[1:]
DRY = "--dry-run" in args
ONLY = None
if "--only" in args:
    ONLY = args[args.index("--only") + 1]


def api(method, path, payload=None):
    """トークンはヘッダにだけ載せる。プロセス引数にもログにも出さない。"""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("X-SF-TOKEN", TOKEN)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def load_ids():
    if os.path.exists(IDS_PATH):
        with open(IDS_PATH) as f:
            return json.load(f)
    return {}


def save_ids(ids):
    if DRY:
        return
    with open(IDS_PATH, "w") as f:
        json.dump(ids, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def exists(kind, oid):
    """記録済み ID が実在するか。UI で消された場合に POST へ倒すため。"""
    if not oid:
        return False
    status, _ = api("GET", f"/v2/{kind}/{oid}")
    return status == 200


def upsert(kind, key, body, ids):
    """記録済みなら PUT、無ければ POST。返り値は ID。"""
    slot = ids.setdefault(kind, {})
    oid = slot.get(key)
    if exists(kind, oid):
        if DRY:
            print(f"  [dry-run] PUT  {kind}/{oid}  ({key})")
            return oid
        status, res = api("PUT", f"/v2/{kind}/{oid}", body)
        action = "updated"
    else:
        if DRY:
            print(f"  [dry-run] POST {kind}  ({key})")
            return None
        status, res = api("POST", f"/v2/{kind}", body)
        action = "created"
    if status not in (200, 201):
        print(f"  失敗 {kind}/{key}: HTTP {status}\n    {res}", file=sys.stderr)
        raise SystemExit(1)
    oid = res["id"]
    slot[key] = oid
    print(f"  {action:8} {kind:14} {oid}  {body.get('name', key)}")
    return oid


def ensure_group(ids):
    oid = ids.get("dashboardgroup")
    if exists("dashboardgroup", oid):
        return oid
    if DRY:
        print(f"  [dry-run] POST dashboardgroup ({GROUP_NAME})")
        return None
    status, res = api("POST", "/v2/dashboardgroup", {
        "name": GROUP_NAME,
        "description": "perfsonar-otel-bridge が as-code で管理する。正は deploy/splunk/",
    })
    if status not in (200, 201):
        print(f"  dashboardgroup 作成に失敗: HTTP {status}\n    {res}", file=sys.stderr)
        raise SystemExit(1)
    ids["dashboardgroup"] = res["id"]
    print(f"  created  dashboardgroup {res['id']}  {GROUP_NAME}")
    return res["id"]


def read_defs(subdir):
    d = os.path.join(HERE, subdir)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            with open(os.path.join(d, fn)) as f:
                out.append((fn[:-5], json.load(f)))
    return out


ids = load_ids()

if ONLY in (None, "charts", "dashboard"):
    print("charts:")
    for key, body in read_defs("charts"):
        upsert("chart", key, body, ids)
    save_ids(ids)

if ONLY in (None, "dashboard"):
    print("dashboard:")
    with open(os.path.join(HERE, "dashboard-network-slo.json")) as f:
        dash = json.load(f)
    layout = dash.pop("layout")
    missing = [c["chart"] for c in layout if c["chart"] not in ids.get("chart", {})]
    if missing and not DRY:
        print(f"  チャート ID が未解決: {missing}", file=sys.stderr)
        raise SystemExit(1)
    dash["charts"] = [
        {
            "chartId": ids.get("chart", {}).get(c["chart"]),
            "row": c["row"],
            "column": c["column"],
            "width": c["width"],
            "height": c["height"],
        }
        for c in layout
    ]
    gid = ensure_group(ids)
    if gid:
        dash["groupId"] = gid
    upsert("dashboard", "network-slo", dash, ids)
    save_ids(ids)

if ONLY in (None, "detectors"):
    defs = read_defs("detectors")
    if defs:
        print("detectors:")
        for key, body in defs:
            upsert("detector", key, body, ids)
        save_ids(ids)

if not DRY:
    did = ids.get("dashboard", {}).get("network-slo")
    if did:
        print(f"\nダッシュボード: https://app.{REALM}.signalfx.com/#/dashboard/{did}")
PY
