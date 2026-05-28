#!/usr/bin/env python3
"""Probe wan_internetstatus_lua.lua for additional WAN data."""
import hashlib, re, time, os, sys
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
    http_req("/")

login()
print("Logged in\n")

# Probe wan_internetstatus_lua.lua
ts = int(time.time())
http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
xml = http_req(f"/?_type=menuData&_tag=wan_internetstatus_lua.lua&_={ts}")

print(f"Response: {len(xml)} chars\n")

for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL):
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
    raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
    vals = [(a or b).strip() for a, b in raw]
    row = dict(zip(names, vals))
    name = row.get("WANCName", row.get("Name", row.get("_InstID", "?")))
    print(f"[{name}]:")
    for k, v in sorted(row.items()):
        if v: print(f"  {k} = {v}")
    print()

# Also try with different parameters
for extra in ["", "TypeUplink=2", "TypeUplink=2&pageType=1"]:
    ts = int(time.time())
    q = f"&{extra}" if extra else ""
    xml2 = http_req(f"/?_type=menuData&_tag=wan_internetstatus_lua.lua&_={ts}{q}")
    instances = re.findall(r"<Instance>", xml2)
    print(f"wan_internetstatus_lua.lua ({extra or 'no extra'}): {len(instances)} instances, {len(xml2)} chars")

# Also look at the JS on the ethWanStatus page for any other data fetches
ts = int(time.time())
html = http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
# Look for any byte/traffic field references in the JS
byte_refs = re.findall(r'["\'](\w*[Bb]yte\w*)["\']', html)
traffic_refs = re.findall(r'["\'](\w*[Tt]raffic\w*|[Tt]hroughput\w*|[Bb]andwidth\w*)["\']', html)
counter_refs = re.findall(r'["\'](\w*[Cc]ounter\w*|\w*[Ss]tatistic\w*)["\']', html)
print(f"\nByte-related refs in JS: {sorted(set(byte_refs))}")
print(f"Traffic refs: {sorted(set(traffic_refs))}")
print(f"Counter refs: {sorted(set(counter_refs))}")
