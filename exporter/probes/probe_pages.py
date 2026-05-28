#!/usr/bin/env python3
"""Load the localNetStatus page to find WLAN traffic data tags."""

import hashlib, re, time, sys, os, json
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

def parse_instances(xml_text):
    rows = []
    for block in re.findall(r"<Instance>(.*?)</Instance>", xml_text, re.DOTALL):
        names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
        raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
        vals = [(a or b).strip() for a, b in raw]
        if names:
            rows.append(dict(zip(names, vals)))
    return rows

login()
print("Logged in\n")

# 1. Load the Local Network Status page (it shows LAN, WLAN, and client info)
print("="*70)
print("LOADING localNetStatus PAGE")
print("="*70)
ts = int(time.time())
html = http_req(f"/?_type=menuView&_tag=localNetStatus&Menu3Location=0&_={ts}")
print(f"Page size: {len(html)} chars")

# Extract all data tags from this page
lua_tags = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html)))
hidden_tags = sorted(set(re.findall(r'hiddenData[^"\']*_tag=([a-zA-Z0-9_]+)', html)))
menu_data = sorted(set(re.findall(r'menuData[^"\']*_tag=([a-zA-Z0-9_]+)', html)))
all_tags_raw = sorted(set(re.findall(r'_tag[=:]["\']\s*([a-zA-Z0-9_]+)', html)))

print(f"\nLua data tags: {lua_tags}")
print(f"Hidden data tags: {hidden_tags}")
print(f"menuData tags: {menu_data}")
print(f"All tag refs: {all_tags_raw}")

# Find WLAN-related content
wlan_lines = []
for line in html.split("\n"):
    ll = line.lower()
    if any(w in ll for w in ["wlan", "ssid", "radio", "wifi", "wireless"]):
        s = line.strip()
        if 10 < len(s) < 500:
            wlan_lines.append(s)

print(f"\nWLAN-related lines ({len(wlan_lines)}):")
for line in wlan_lines[:30]:
    print(f"  {line}")

# 2. Probe EVERY lua data tag found in the page
print(f"\n{'='*70}")
print(f"PROBING {len(lua_tags)} DATA TAGS FROM localNetStatus PAGE")
print(f"{'='*70}")

for tag in lua_tags:
    ts = int(time.time())
    xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        login()
        ts = int(time.time())
        http_req(f"/?_type=menuView&_tag=localNetStatus&Menu3Location=0&_={ts}")
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    
    instances = parse_instances(xml)
    if instances:
        print(f"\n  {tag}: {len(instances)} instances")
        for i, inst in enumerate(instances):
            print(f"    Instance {i}:")
            for k, v in sorted(inst.items()):
                if v:
                    print(f"      {k} = {v}")
    else:
        print(f"  {tag}: empty")

# 3. Also load the WLAN config pages
print(f"\n{'='*70}")
print("LOADING wlanBasic PAGE")
print(f"{'='*70}")
ts = int(time.time())
html2 = http_req(f"/?_type=menuView&_tag=wlanBasic&Menu3Location=0&_={ts}")
print(f"Page size: {len(html2)} chars")

lua2 = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html2)))
hidden2 = sorted(set(re.findall(r'hiddenData[^"\']*_tag=([a-zA-Z0-9_]+)', html2)))
print(f"Lua tags: {lua2}")
print(f"Hidden tags: {hidden2}")

for tag in lua2:
    ts = int(time.time())
    xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        login()
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    instances = parse_instances(xml)
    if instances:
        print(f"\n  {tag}: {len(instances)} instances")
        for i, inst in enumerate(instances[:3]):
            print(f"    Instance {i}:")
            for k, v in sorted(inst.items()):
                if v:
                    print(f"      {k} = {v}")
            if i == 2 and len(instances) > 3:
                print(f"    ... and {len(instances)-3} more")
    else:
        print(f"  {tag}: empty")

# 4. Load wlanAdvanced page
print(f"\n{'='*70}")
print("LOADING wlanAdvanced PAGE")
print(f"{'='*70}")
ts = int(time.time())
html3 = http_req(f"/?_type=menuView&_tag=wlanAdvanced&Menu3Location=0&_={ts}")
print(f"Page size: {len(html3)} chars")
lua3 = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html3)))
print(f"Lua tags: {lua3}")

for tag in lua3:
    ts = int(time.time())
    xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        login()
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    instances = parse_instances(xml)
    if instances:
        print(f"\n  {tag}: {len(instances)} instances")
        for i, inst in enumerate(instances[:3]):
            print(f"    Instance {i}:")
            for k, v in sorted(inst.items()):
                if v:
                    print(f"      {k} = {v}")
    else:
        print(f"  {tag}: empty")

# 5. Try ethWanStatus - might have different data than ethWanConfig
print(f"\n{'='*70}")
print("LOADING ethWanStatus PAGE")
print(f"{'='*70}")
ts = int(time.time())
html4 = http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
print(f"Page size: {len(html4)} chars")
lua4 = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html4)))
print(f"Lua tags: {lua4}")

for tag in lua4:
    ts = int(time.time())
    xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        login()
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    instances = parse_instances(xml)
    if instances:
        print(f"\n  {tag}: {len(instances)} instances")
        for i, inst in enumerate(instances):
            name = inst.get("WANCName", inst.get("Name", inst.get("_InstID", f"inst{i}")))
            print(f"    [{name}]:")
            for k, v in sorted(inst.items()):
                if v and any(w in k.lower() for w in ["byte", "packet", "rx", "tx", "error", "status",
                                                       "rate", "speed", "conn", "uptime", "name", "type",
                                                       "ip", "gateway", "dns", "mask"]):
                    print(f"      {k} = {v}")
    else:
        print(f"  {tag}: empty")
