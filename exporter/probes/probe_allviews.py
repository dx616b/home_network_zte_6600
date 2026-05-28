#!/usr/bin/env python3
"""Extract menu tree and probe ALL views for traffic counters."""
import hashlib, re, time, os, json
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
    return http_req("/")

html = login()

# Extract menuTreeJSON from position 63798
m = re.search(r'var\s+menuTreeJSON\s*=\s*(\[.*?\]);\s*\n', html, re.DOTALL)
if not m:
    # Try to find the end of the JSON array
    idx = html.find('var menuTreeJSON = [')
    if idx >= 0:
        # Find matching closing bracket
        start = html.index('[', idx)
        depth = 0
        end = start
        for i in range(start, min(start + 50000, len(html))):
            if html[i] == '[':
                depth += 1
            elif html[i] == ']':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        raw = html[start:end]
        menu = json.loads(raw)
    else:
        print("ERROR: could not find menuTreeJSON")
        exit(1)
else:
    menu = json.loads(m.group(1))

# Collect ALL view IDs recursively
def collect_views(items, path=""):
    views = []
    for item in items:
        name = item.get("name", "")
        full_path = f"{path}/{name}" if path else name
        vid = item.get("id", "")
        if vid:
            views.append((vid, full_path))
        for child in item.get("children", []):
            cname = child.get("name", "")
            cfull = f"{full_path}/{cname}" if cname else full_path
            cvid = child.get("id", "")
            if cvid:
                views.append((cvid, cfull))
            for gc in child.get("children", []):
                gname = gc.get("name", "")
                gfull = f"{cfull}/{gname}" if gname else cfull
                gvid = gc.get("id", "")
                if gvid:
                    views.append((gvid, gfull))

    return views

all_views = collect_views(menu)
print(f"Total views: {len(all_views)}\n")

# Already explored views
explored = {"ethWanConfig", "ponopticalinfo", "ponInfo", "ponLoid", "ponSn",
            "statusMgr", "localNetStatus", "ethWanStatus", "internetStatus",
            "homePage", "voipStatus", "voipRegStatus"}

# Probe each unexplored view
for vid, path in all_views:
    if vid in explored:
        print(f"[SKIP] {vid}: {path}")
        continue
    try:
        ts = int(time.time())
        page = http_req(f"/?_type=menuView&_tag={vid}&Menu3Location=0&_={ts}")
        lua_tags = list(set(re.findall(r'_tag=(\w+_lua\.lua)', page)))
        if not lua_tags:
            continue
        
        for tag in lua_tags:
            try:
                xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
                fields = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
                # Check for traffic/byte fields
                traffic = [f for f in fields if any(k in f.lower() for k in 
                    ["byte", "packet", "traffic", "counter", "rx", "tx", "throughput",
                     "octet", "error", "discard", "drop", "speed", "rate", "bps"])]
                if traffic:
                    print(f"\n*** {vid} ({path}) -> {tag}")
                    print(f"    Traffic fields: {sorted(set(traffic))}")
                    # Show first instance
                    for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL)[:2]:
                        names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
                        raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
                        vals = [(a or b).strip() for a, b in raw]
                        row = dict(zip(names, vals))
                        inst = row.get("_InstID", "?")
                        print(f"    Instance: {inst}")
                        for tf in sorted(set(traffic)):
                            v = row.get(tf, "")
                            if v:
                                print(f"      {tf} = {v}")
            except Exception as e:
                pass
    except Exception as e:
        pass

print("\nDone.")
