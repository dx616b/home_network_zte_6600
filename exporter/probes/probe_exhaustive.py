#!/usr/bin/env python3
"""Exhaustive probe: try all menu tree views to find traffic/statistics lua tags."""
import hashlib, re, time, os
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from urllib import parse, request

ZTE_URL = os.environ.get("ZTE_URL", "http://192.168.1.1")
ZTE_PASS = os.environ.get("ZTE_PASSWORD", "")
opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))

def http_req(path, data=None):
    url = f"{ZTE_URL}{path}"
    body = None; headers = {}
    if data:
        body = parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = request.Request(url, data=body, headers=headers, method="POST" if data else "GET")
    with opener.open(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")

def login():
    text = http_req("/?_type=loginData&_tag=login_entry")
    session = re.search(r'"sess_token"\s*:\s*"([^"]+)"', text).group(1)
    text2 = http_req("/?_type=loginData&_tag=login_token")
    try: token = ET.fromstring(text2).text.strip()
    except: token = re.search(r">(\d+)<", text2).group(1)
    digest = hashlib.sha256((ZTE_PASS + token).encode()).hexdigest()
    http_req("/?_type=loginData&_tag=login_entry", {
        "action": "login", "Username": "root", "Password": digest, "_sessionTOKEN": session,
    })
    html = http_req("/")
    return html

html = login()
print("Logged in\n")

# Extract menu tree
m = re.search(r'var\s+menuTreeJSON\s*=\s*"(.*?)";', html)
if not m:
    print("ERROR: no menuTreeJSON found")
    exit(1)

menu_json = m.group(1).replace('\\"', '"').replace("\\/", "/")
import json
menu = json.loads(menu_json)

# Collect all view IDs
def collect_views(items, path=""):
    views = []
    for item in items:
        view_id = item.get("viewId", "")
        name = item.get("name", "")
        current_path = f"{path}/{name}" if path else name
        if view_id:
            views.append((view_id, current_path))
        children = item.get("children", [])
        if children:
            views.extend(collect_views(children, current_path))
    return views

all_views = collect_views(menu)
print(f"Total views in menu: {len(all_views)}\n")

# Keywords that suggest traffic/byte counters
traffic_keywords = [
    "traffic", "statistic", "counter", "throughput", "bandwidth",
    "byte", "packet", "rate", "speed", "flow", "usage",
    "snmp", "diagnostic", "monitor"
]

# Filter views that might contain traffic data based on name
interesting = []
for view_id, path in all_views:
    lowpath = path.lower()
    lowid = view_id.lower()
    if any(kw in lowpath or kw in lowid for kw in traffic_keywords):
        interesting.append((view_id, path))

# Also add views we haven't explored yet
explored = {"ethWanConfig", "ponopticalinfo", "ponInfo", "ponLoid", "ponSn",
            "statusMgr", "localNetStatus", "ethWanStatus", "internetStatus",
            "homePage", "voipStatus"}

unexplored_interesting = []
for view_id, path in all_views:
    if view_id not in explored:
        lowpath = path.lower()
        lowid = view_id.lower()
        # Broader filter: networking, WAN, LAN, status related
        if any(kw in lowpath or kw in lowid for kw in [
            "traffic", "statistic", "counter", "throughput", "bandwidth",
            "byte", "packet", "rate", "speed", "flow", "usage",
            "snmp", "diagnostic", "monitor", "status", "info", "wan",
            "network", "eth", "port", "interface", "bridge", "route",
            "nat", "firewall", "qos", "igmp"
        ]):
            unexplored_interesting.append((view_id, path))

print(f"Keyword-matching views: {len(interesting)}")
for v, p in interesting:
    mark = " [EXPLORED]" if v in explored else ""
    print(f"  {v}: {p}{mark}")

print(f"\nUnexplored interesting views: {len(unexplored_interesting)}")
for v, p in unexplored_interesting:
    print(f"  {v}: {p}")

# Now probe each unexplored interesting view for lua data tags
print("\n" + "=" * 70)
print("PROBING UNEXPLORED VIEWS FOR TRAFFIC DATA")
print("=" * 70)

for view_id, path in unexplored_interesting:
    try:
        ts = int(time.time())
        html_page = http_req(f"/?_type=menuView&_tag={view_id}&Menu3Location=0&_={ts}")
        lua_tags = re.findall(r'_tag=(\w+_lua\.lua)', html_page)
        hidden_tags = re.findall(r'_type=hiddenData&_tag=(\w+)', html_page)
        
        if not lua_tags and not hidden_tags:
            continue
            
        print(f"\n--- {view_id} ({path}) ---")
        print(f"  Lua tags: {lua_tags}")
        if hidden_tags:
            print(f"  Hidden tags: {hidden_tags}")
        
        # Fetch each lua tag and look for byte/traffic/counter fields
        for lua_tag in set(lua_tags):
            try:
                xml = http_req(f"/?_type=menuData&_tag={lua_tag}&_={ts}")
                # Look for traffic-related field names
                field_names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
                traffic_fields = [f for f in field_names if any(
                    kw in f.lower() for kw in ["byte", "packet", "traffic", "counter", "rate", "throughput", "speed", "error", "discard", "drop", "rx", "tx", "in", "out"]
                )]
                if traffic_fields:
                    print(f"  {lua_tag}: TRAFFIC FIELDS FOUND: {sorted(set(traffic_fields))}")
                    # Show values for first instance
                    for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL)[:2]:
                        names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
                        raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
                        vals = [(a or b).strip() for a, b in raw]
                        row = dict(zip(names, vals))
                        for f in sorted(set(traffic_fields)):
                            if row.get(f):
                                print(f"    {f} = {row[f]}")
            except Exception as e:
                print(f"  {lua_tag}: ERROR {e}")
    except Exception as e:
        print(f"  {view_id}: ERROR {e}")

print("\n\nDone.")
