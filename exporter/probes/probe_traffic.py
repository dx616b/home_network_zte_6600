#!/usr/bin/env python3
"""Try various view names and lua tags to find traffic statistics."""
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
print(f"Logged in, main page: {len(html)} chars")

# Extract menu tree from main page
m = re.search(r'menuTreeJSON\s*=\s*"(.*?)"', html)
if m:
    import json
    raw = m.group(1).replace('\\"', '"').replace("\\/", "/")
    menu = json.loads(raw)
    
    def collect_views(items):
        views = []
        for item in items:
            vid = item.get("viewId", "")
            if vid:
                views.append((vid, item.get("name", "")))
            for child in item.get("children", []):
                cvid = child.get("viewId", "")
                if cvid:
                    views.append((cvid, child.get("name", "")))
                for gc in child.get("children", []):
                    gvid = gc.get("viewId", "")
                    if gvid:
                        views.append((gvid, gc.get("name", "")))
        return views
    
    all_views = collect_views(menu)
    print(f"Found {len(all_views)} views in menu tree")
    
    explored = {"ethWanConfig", "ponopticalinfo", "ponInfo", "ponLoid", "ponSn",
                "statusMgr", "localNetStatus", "ethWanStatus", "internetStatus",
                "homePage", "voipStatus"}
    
    for vid, name in all_views:
        if vid in explored:
            continue
        try:
            ts = int(time.time())
            page = http_req(f"/?_type=menuView&_tag={vid}&Menu3Location=0&_={ts}")
            lua_tags = re.findall(r'_tag=(\w+_lua\.lua)', page)
            if lua_tags:
                # Fetch each tag and check for byte/traffic fields
                for tag in set(lua_tags):
                    xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
                    fields = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
                    traffic = [f for f in fields if any(k in f.lower() for k in 
                        ["byte", "packet", "traffic", "counter", "rx", "tx", "throughput"])]
                    if traffic:
                        print(f"\n*** {vid} ({name}) -> {tag}: {sorted(set(traffic))}")
                        # Show first instance values
                        for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL)[:1]:
                            names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
                            raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
                            vals = [(a or b).strip() for a, b in raw]
                            row = dict(zip(names, vals))
                            for tf in sorted(set(traffic)):
                                v = row.get(tf, "N/A")
                                print(f"    {tf} = {v}")
        except Exception as e:
            pass

else:
    print("No menuTreeJSON found, trying known potential views...")
    
    # Try direct lua tags that might have traffic data
    direct_tags = [
        "wan_traffic_lua.lua", "wan_statistics_lua.lua",
        "eth_statistics_lua.lua", "eth_stat_lua.lua",
        "port_statistics_lua.lua", "traffic_statistics_lua.lua",
        "interface_statistics_lua.lua", "network_statistics_lua.lua",
        "pon_statistics_lua.lua", "pon_traffic_lua.lua",
        "gpon_statistics_lua.lua", "gpon_traffic_lua.lua",
        "wan_stat_lua.lua", "lan_stat_lua.lua",
        "if_statistics_lua.lua", "ifconfig_lua.lua",
        "status_wan_traffic_lua.lua", "status_traffic_lua.lua",
    ]
    
    for tag in direct_tags:
        try:
            ts = int(time.time())
            xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
            if len(xml) > 100 and "SessionTimeout" not in xml:
                fields = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
                print(f"{tag}: {len(xml)} chars, fields: {fields[:20]}")
        except:
            pass

print("\nDone.")
