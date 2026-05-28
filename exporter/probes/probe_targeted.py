#!/usr/bin/env python3
"""Targeted ZTE F6600P probe — check all WAN types, LAN, and find menu tree."""

import hashlib, re, time, sys, os
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from urllib import parse, request

ZTE_URL = os.environ.get("ZTE_URL", "http://192.168.1.1").rstrip("/")
ZTE_USER = os.environ.get("ZTE_USERNAME", "root")
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
    try:
        token = ET.fromstring(text2).text.strip()
    except Exception:
        token = re.search(r">(\d+)<", text2).group(1)
    digest = hashlib.sha256((ZTE_PASS + token).encode()).hexdigest()
    http_req("/?_type=loginData&_tag=login_entry", {
        "action": "login", "Username": ZTE_USER, "Password": digest, "_sessionTOKEN": session,
    })
    http_req("/")

def fetch(view, data_tag, extra=""):
    ts = int(time.time())
    http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
    q = f"&{extra}" if extra else ""
    xml = http_req(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")
    if "SessionTimeout" in xml:
        login()
        ts = int(time.time())
        http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
        xml = http_req(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")
    return xml

def parse_instances(xml_text):
    rows = []
    for block in re.findall(r"<Instance>(.*?)</Instance>", xml_text, re.DOTALL):
        names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
        raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
        vals = [(a or b).strip() for a, b in raw]
        if names:
            rows.append(dict(zip(names, vals)))
    return rows

def print_instance(row, prefix=""):
    for k, v in sorted(row.items()):
        if v:
            print(f"{prefix}  {k} = {v}")

login()
print("Logged in\n")

# =====================================================
# 1. WAN with ALL TypeUplink values
# =====================================================
print("=" * 70)
print("1. WAN CONNECTIONS — ALL TYPE UPLINK VALUES")
print("=" * 70)

for uplink in range(5):
    for page_type in range(3):
        extra = f"TypeUplink={uplink}&pageType={page_type}"
        xml = fetch("ethWanConfig", "wan_internet_lua.lua", extra)
        instances = parse_instances(xml)
        if instances:
            print(f"\n--- TypeUplink={uplink}, pageType={page_type} ({len(instances)} instances) ---")
            for inst in instances:
                name = inst.get("WANCName", "?")
                wtype = inst.get("wantype", inst.get("TransType", "?"))
                rx = inst.get("RxBytes", "")
                tx = inst.get("TxBytes", "")
                print(f"  [{name}] type={wtype} RxBytes={rx} TxBytes={tx}")
                # Print ALL fields for instances with byte data
                if rx or tx:
                    for k, v in sorted(inst.items()):
                        if k not in ("WANCName", "wantype", "TransType", "RxBytes", "TxBytes") and v:
                            print(f"    {k} = {v}")

# =====================================================
# 2. LAN port counters
# =====================================================
print(f"\n{'='*70}")
print("2. LAN PORT COUNTERS")
print("=" * 70)

xml = fetch("localNetStatus", "status_lan_info_lua.lua")
instances = parse_instances(xml)
for inst in instances:
    port = inst.get("_InstID", "?")
    status = inst.get("Status", "?")
    speed = inst.get("Speed", "?")
    in_b = inst.get("InBytes", "")
    out_b = inst.get("OutBytes", "")
    in_p = inst.get("InPkts", "")
    out_p = inst.get("OutPkts", "")
    print(f"  Port {port}: Status={status} Speed={speed} InBytes={in_b} OutBytes={out_b} InPkts={in_p} OutPkts={out_p}")

# =====================================================
# 3. Try other menu pages — look for the full menu tree
# =====================================================
print(f"\n{'='*70}")
print("3. LOOKING FOR MENU STRUCTURE IN MAIN PAGE")
print("=" * 70)

main = http_req("/")
# The main page is 206K — look for menu items
menus = re.findall(r'(?:menuItem|_tag|menuView|menuData|_type)[^"\'<>]*?([a-zA-Z][a-zA-Z0-9_]+(?:_lua\.lua)?)', main)
# Also look for URL patterns with page names
pages = re.findall(r'(?:href|src|url|page|view|menu)[^"\'<>]*?=\s*["\']?([a-zA-Z]\w+)', main, re.I)
# Extract from all script blocks
scripts = re.findall(r'<script[^>]*>(.*?)</script>', main, re.DOTALL)
all_tags = set()
for script in scripts:
    tags = re.findall(r'_tag[=:]\s*["\']?([a-zA-Z]\w+)', script)
    all_tags.update(tags)
    # Look for menu tree data structures
    if "menu" in script.lower() or "tree" in script.lower():
        # Print first 500 chars for context
        if len(script) > 100:
            print(f"\n  Menu/tree script ({len(script)} chars):")
            print(f"    {script[:500]}...")

print(f"\n  Tags from scripts: {sorted(all_tags)}")

# =====================================================
# 4. Try known ZTE endpoint patterns that the existing exporter uses
# =====================================================
print(f"\n{'='*70}")
print("4. PROBING KNOWN ZTE ENDPOINT PATTERNS")
print("=" * 70)

known_endpoints = [
    # WAN variants
    ("ethWanConfig", "wan_internet_lua.lua", ""),
    ("wanConnConfig", "wan_conn_lua.lua", ""),
    ("wanConfig", "wan_config_lua.lua", ""),
    # Interface/traffic stats
    ("ifStatistic", "if_statistic_lua.lua", ""),
    ("trafficStatistic", "traffic_statistic_lua.lua", ""),
    ("ethStatistic", "eth_statistic_lua.lua", ""),
    ("ethIfStatistic", "eth_if_statistic_lua.lua", ""),
    # PON / GPON stats
    ("ponStatistic", "pon_statistic_lua.lua", ""),
    ("gponStatistic", "gpon_statistic_lua.lua", ""),
    ("ponGemPort", "pon_gemport_lua.lua", ""),
    ("gemPortStatistic", "gemport_statistic_lua.lua", ""),
    # WAN connection status
    ("wanConnStatus", "wan_conn_status_lua.lua", ""),
    ("wanConStatus", "wan_con_status_lua.lua", ""),
    ("pppoeStat", "pppoe_stat_lua.lua", ""),
    ("pppoeStatus", "pppoe_status_lua.lua", ""),
    # IP/routing
    ("ipIfStats", "ip_if_stats_lua.lua", ""),
    ("ipStatistic", "ip_statistic_lua.lua", ""),
    # General
    ("networkDiag", "network_diag_lua.lua", ""),
    ("diagNetInfo", "diag_net_info_lua.lua", ""),
    ("netStatus", "net_status_lua.lua", ""),
    # Bandwidth
    ("bwMonitor", "bw_monitor_lua.lua", ""),
    ("bandwidthMonitor", "bandwidth_monitor_lua.lua", ""),
    # Multi-WAN
    ("multiWan", "multi_wan_lua.lua", ""),
    ("wanStatus", "wan_status_lua.lua", ""),
]

for view, tag, extra in known_endpoints:
    ts = int(time.time())
    # Try without menuView first (faster)
    try:
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    except Exception:
        continue
    if "SessionTimeout" in xml:
        login()
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")

    instances = parse_instances(xml)
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
    
    if instances:
        print(f"\n  {view} -> {tag}: {len(instances)} instances, {len(names)} fields")
        for inst in instances:
            has_bytes = any("byte" in k.lower() or "octet" in k.lower() or "packet" in k.lower() for k in inst)
            if has_bytes:
                print(f"    Instance with traffic data:")
                print_instance(inst, "      ")
            else:
                name = inst.get("WANCName", inst.get("_InstID", inst.get("Name", "?")))
                print(f"    Instance: {name} ({len(inst)} fields)")
    elif names:
        print(f"  {view} -> {tag}: flat data, {len(names)} fields")
        traffic_fields = {k: v for k, v in zip(names, re.findall(r"<ParaValue>([^<]*)</ParaValue>", xml))
                         if any(w in k.lower() for w in ["byte", "packet", "traffic", "rate", "counter"])}
        if traffic_fields:
            print(f"    Traffic: {traffic_fields}")
    else:
        pass  # No data

# =====================================================
# 5. Try WAN without filter — raw XML dump for the internet connection
# =====================================================
print(f"\n{'='*70}")
print("5. RAW WAN XML FOR 'internet' CONNECTION")
print("=" * 70)

xml = fetch("ethWanConfig", "wan_internet_lua.lua", "TypeUplink=2&pageType=0")
# Find the internet instance block
for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL):
    if "internet" in block:
        print(f"  Raw XML ({len(block)} chars):")
        print(block[:3000])

# =====================================================
# 6. Check if modem exposes any interface via TR-069 / CWMP style
# =====================================================
print(f"\n{'='*70}")
print("6. TRYING TR-069 STYLE ENDPOINTS")
print("=" * 70)

tr069_tags = [
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1",
    "InternetGatewayDevice.WANDevice.1.WANCommonInterfaceConfig",
    "Device.Ethernet.Interface",
    "Device.IP.Interface",
]
for tag in tr069_tags:
    ts = int(time.time())
    try:
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    except Exception:
        continue
    if xml and "SessionTimeout" not in xml and len(xml) > 250:
        print(f"  {tag}: {len(xml)} chars")
        print(f"    {xml[:300]}")
