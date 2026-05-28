#!/usr/bin/env python3
"""Probe ZTE F6600P for WLAN interface traffic/byte counters."""

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
    try: token = ET.fromstring(text2).text.strip()
    except: token = re.search(r">(\d+)<", text2).group(1)
    digest = hashlib.sha256((ZTE_PASS + token).encode()).hexdigest()
    http_req("/?_type=loginData&_tag=login_entry", {
        "action": "login", "Username": ZTE_USER, "Password": digest, "_sessionTOKEN": session,
    })
    http_req("/")

def fetch(view, tag, extra=""):
    ts = int(time.time())
    http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
    q = f"&{extra}" if extra else ""
    xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}{q}")
    if "SessionTimeout" in xml:
        login()
        ts = int(time.time())
        http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}{q}")
    return xml

def fetch_hidden(tag, extra=""):
    ts = int(time.time())
    q = f"&{extra}" if extra else ""
    xml = http_req(f"/?_type=hiddenData&_tag={tag}&_={ts}{q}")
    if "SessionTimeout" in xml:
        login()
        ts = int(time.time())
        xml = http_req(f"/?_type=hiddenData&_tag={tag}&_={ts}{q}")
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

def print_instances(rows, label):
    print(f"\n{'='*70}")
    print(f"{label}: {len(rows)} instances")
    print(f"{'='*70}")
    for i, row in enumerate(rows):
        print(f"\n  Instance {i}:")
        for k, v in sorted(row.items()):
            if v:
                print(f"    {k} = {v}")

login()
print("Logged in\n")

# =====================================================
# WLAN ENDPOINTS TO PROBE
# =====================================================
wlan_endpoints = [
    # WLAN basic info / status
    ("wlanBasicConf", "wlan_basic_lua.lua", "", "WLAN basic"),
    ("wlanAdvConf", "wlan_advance_lua.lua", "", "WLAN advanced"),
    ("wlanStatus", "wlan_status_lua.lua", "", "WLAN status"),
    ("wlanStatistic", "wlan_statistic_lua.lua", "", "WLAN statistic"),
    ("wlanStats", "wlan_stats_lua.lua", "", "WLAN stats"),
    ("wlanInfo", "wlan_info_lua.lua", "", "WLAN info"),
    ("wlanStat", "wlan_stat_lua.lua", "", "WLAN stat"),
    ("wlanIfInfo", "wlan_if_info_lua.lua", "", "WLAN if info"),
    ("wlanSSID", "wlan_ssid_lua.lua", "", "WLAN SSID"),
    ("wlanRadio", "wlan_radio_lua.lua", "", "WLAN radio"),

    # WLAN 5GHz variants
    ("wlan5gBasicConf", "wlan5g_basic_lua.lua", "", "WLAN5G basic"),
    ("wlan5gAdvConf", "wlan5g_advance_lua.lua", "", "WLAN5G advanced"),
    ("wlan5gStatus", "wlan5g_status_lua.lua", "", "WLAN5G status"),

    # Multi-SSID
    ("wlanMultiSSID", "wlan_multi_ssid_lua.lua", "", "WLAN multi-SSID"),
    ("wlanGuestSSID", "wlan_guest_ssid_lua.lua", "", "WLAN guest"),
    ("wlanMBSSID", "wlan_mbssid_lua.lua", "", "WLAN MBSSID"),
    ("wlanSSIDStatus", "wlan_ssid_status_lua.lua", "", "WLAN SSID status"),

    # AP / access point
    ("wlanAP", "wlan_ap_lua.lua", "", "WLAN AP"),
    ("wlanAPInfo", "wlan_ap_info_lua.lua", "", "WLAN AP info"),

    # Associated stations (per-client traffic)
    ("wlanAssocDev", "wlan_assoc_dev_lua.lua", "", "WLAN assoc dev"),
    ("wlanAssocDevInfo", "wlan_assoc_dev_info_lua.lua", "", "WLAN assoc dev info"),
    ("wlanClientList", "wlan_client_list_lua.lua", "", "WLAN client list"),
    ("wlanStationList", "wlan_station_list_lua.lua", "", "WLAN station list"),

    # Homepage with WLAN data
    ("wlanHomePage", "wlan_homepage_lua.lua", "", "WLAN homepage"),

    # WiFi traffic
    ("wlanTraffic", "wlan_traffic_lua.lua", "", "WLAN traffic"),
    ("wlanCounter", "wlan_counter_lua.lua", "", "WLAN counter"),
]

found = []
for view, tag, extra, label in wlan_endpoints:
    sys.stdout.write(f"  {label:25s}... ")
    sys.stdout.flush()
    try:
        xml = fetch(view, tag, extra)
        instances = parse_instances(xml)
        if instances:
            # Check for traffic-related fields
            has_traffic = False
            for inst in instances:
                for k in inst:
                    kl = k.lower()
                    if any(w in kl for w in ["byte", "packet", "octet", "traffic",
                                              "rx", "tx", "in", "out"]):
                        has_traffic = True
                        break
            if has_traffic:
                print(f"TRAFFIC! ({len(instances)} inst)")
                found.append((label, tag, instances))
                print_instances(instances, f"  {label}")
            else:
                print(f"data ({len(instances)} inst, no traffic fields)")
                # Still show fields for debugging
                keys = set()
                for inst in instances:
                    keys.update(inst.keys())
                print(f"    Fields: {sorted(keys)}")
        else:
            print("empty")
    except Exception as e:
        print(f"error: {e}")

# Also try hiddenData for WLAN
print(f"\n{'='*70}")
print("HIDDEN DATA WLAN ENDPOINTS")
print(f"{'='*70}")

hidden_wlan = [
    ("accessdev_data", "DeveiceType=WLAN", "WLAN clients (hidden)"),
    ("wlan_data", "", "WLAN data (hidden)"),
    ("wlan_status_data", "", "WLAN status data (hidden)"),
    ("wlan_stat_data", "", "WLAN stat data (hidden)"),
    ("wlan_traffic_data", "", "WLAN traffic data (hidden)"),
]

for tag, extra, label in hidden_wlan:
    sys.stdout.write(f"  {label:30s}... ")
    sys.stdout.flush()
    try:
        xml = fetch_hidden(tag, extra)
        instances = parse_instances(xml)
        if instances:
            has_traffic = any(
                any(w in k.lower() for w in ["byte", "packet", "rx", "tx"])
                for inst in instances for k in inst
            )
            if has_traffic:
                print(f"TRAFFIC! ({len(instances)} inst)")
                found.append((label, tag, instances))
                print_instances(instances, f"  {label}")
            else:
                print(f"data ({len(instances)} inst)")
                keys = set()
                for inst in instances:
                    keys.update(inst.keys())
                print(f"    Fields: {sorted(keys)}")
        else:
            print("empty")
    except Exception as e:
        print(f"error: {e}")

# Now try fetching the WLAN homepage JS that was found
print(f"\n{'='*70}")
print("PARSING WLAN HOMEPAGE JS FOR DATA TAGS")
print(f"{'='*70}")

# The main page had wlan_homepage_lua.lua as menuData
# Let's load the wlan config page and find its JS/tags
ts = int(time.time())
for view_name in ["wlanBasicConf", "wlanAdvConf", "wlan5gBasicConf", "wlan5gAdvConf",
                   "wlanMultiSSID", "wlanSSID", "wlanRadio"]:
    try:
        html = http_req(f"/?_type=menuView&_tag={view_name}&Menu3Location=0&_={ts}")
        if "SessionTimeout" in html:
            login()
            html = http_req(f"/?_type=menuView&_tag={view_name}&Menu3Location=0&_={ts}")
        if len(html) > 500:
            # Extract data tags from this page's JS
            tags = set(re.findall(r'_tag=([a-zA-Z0-9_]+_lua\.lua)', html))
            hidden = set(re.findall(r'hiddenData[^"\']*_tag=([a-zA-Z0-9_]+)', html))
            if tags or hidden:
                print(f"  {view_name}: data_tags={sorted(tags)} hidden={sorted(hidden)}")
                # Probe each discovered tag
                for dtag in tags:
                    xml = http_req(f"/?_type=menuData&_tag={dtag}&_={ts}")
                    inst = parse_instances(xml)
                    if inst:
                        has_bytes = any(
                            any(w in k.lower() for w in ["byte", "packet", "rx", "tx"])
                            for i in inst for k in i
                        )
                        if has_bytes:
                            print(f"    *** TRAFFIC in {dtag}! ***")
                            print_instances(inst, f"    {dtag}")
                            found.append((f"from-{view_name}", dtag, inst))
                        else:
                            print(f"    {dtag}: {len(inst)} inst, fields={sorted(set(k for i in inst for k in i))}")
            else:
                print(f"  {view_name}: page loaded ({len(html)} chars) but no data tags found")
    except Exception as e:
        print(f"  {view_name}: {e}")

print(f"\n{'='*70}")
print(f"SUMMARY: {len(found)} endpoints with traffic data")
print(f"{'='*70}")
for label, tag, instances in found:
    print(f"\n  [{label}] {tag}: {len(instances)} instances")
    for inst in instances:
        name = inst.get("SSID", inst.get("Name", inst.get("_InstID", "?")))
        byte_fields = {k: v for k, v in inst.items()
                       if any(w in k.lower() for w in ["byte", "packet", "rx", "tx", "in", "out"])}
        if byte_fields:
            print(f"    {name}: {byte_fields}")
