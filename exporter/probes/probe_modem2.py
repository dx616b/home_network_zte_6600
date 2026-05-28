#!/usr/bin/env python3
"""Probe ZTE F6600P modem — improved version that stays in one session."""

import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from urllib import parse, request

ZTE_URL = os.environ.get("ZTE_URL", "http://192.168.1.1").rstrip("/")
ZTE_USERNAME = os.environ.get("ZTE_USERNAME", "root")
ZTE_PASSWORD = os.environ.get("ZTE_PASSWORD", "")

opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))

def http(path, data=None):
    url = f"{ZTE_URL}{path}"
    body = None
    headers = {}
    if data:
        body = parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = request.Request(url, data=body, headers=headers, method="POST" if data else "GET")
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

def login():
    text = http("/?_type=loginData&_tag=login_entry")
    m = re.search(r'"sess_token"\s*:\s*"([^"]+)"', text)
    if not m:
        print(f"FATAL: no sess_token in: {text[:200]}")
        sys.exit(1)
    session = m.group(1)
    text2 = http("/?_type=loginData&_tag=login_token")
    try:
        root = ET.fromstring(text2)
        token = root.text.strip() if root.text else ""
    except:
        m2 = re.search(r">(\d+)<", text2)
        token = m2.group(1) if m2 else ""
    digest = hashlib.sha256((ZTE_PASSWORD + token).encode()).hexdigest()
    result = http("/?_type=loginData&_tag=login_entry", {
        "action": "login",
        "Username": ZTE_USERNAME,
        "Password": digest,
        "_sessionTOKEN": session,
    })
    if "login_need_refresh" not in result.lower().replace(" ", ""):
        print(f"Login failed: {result[:300]}")
        sys.exit(1)
    http("/")
    print("Login OK")

def fetch(view, data_tag, extra=""):
    ts = int(time.time())
    http(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
    q = f"&{extra}" if extra else ""
    xml = http(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")
    if "SessionTimeout" in xml:
        login()
        ts = int(time.time())
        http(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
        xml = http(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")
    return xml

def extract_all(xml_text):
    """Get all ParaName→ParaValue pairs."""
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml_text)
    raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", xml_text, re.DOTALL)
    vals = [(a or b).strip() for a, b in raw]
    return dict(zip(names, vals))

if not ZTE_PASSWORD:
    print("Set ZTE_PASSWORD env var")
    sys.exit(1)

login()

# 1. Verify known working endpoint
print("\n=== TEST: Known WAN endpoint ===")
xml = fetch("ethWanConfig", "wan_internet_lua.lua", "TypeUplink=2&pageType=0")
fields = extract_all(xml)
if fields:
    print(f"OK — {len(fields)} fields")
    for k in sorted(fields):
        if any(w in k.lower() for w in ["byte", "packet", "name", "type", "rx", "tx"]):
            print(f"  {k} = {fields[k]}")
else:
    print(f"EMPTY. Raw response ({len(xml)} chars):")
    print(xml[:500])

# 2. Try LAN endpoint
print("\n=== TEST: Known LAN endpoint ===")
xml = fetch("localNetStatus", "status_lan_info_lua.lua")
fields = extract_all(xml)
if fields:
    print(f"OK — {len(fields)} fields")
    for k in sorted(fields):
        if any(w in k.lower() for w in ["byte", "packet", "in", "out"]):
            print(f"  {k} = {fields[k]}")
else:
    print(f"EMPTY. Raw ({len(xml)} chars): {xml[:500]}")

# 3. Systematic scan of all _type=menuView tags the web UI might use.
#    Instead of guessing, let's fetch the main page JS to find registered views.
print("\n=== SCANNING MAIN PAGE FOR API ENDPOINTS ===")
main_page = http("/")
# Look for Lua script references
lua_refs = set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', main_page))
view_refs = set(re.findall(r'_tag=([a-zA-Z0-9_]+)', main_page))
print(f"Found {len(lua_refs)} lua refs, {len(view_refs)} view tags in main page")

# Try JS files
js_urls = re.findall(r'src="(/[^"]*\.js[^"]*)"', main_page)
print(f"Found {len(js_urls)} JS files")
all_lua = set()
all_views = set()
for js_url in js_urls[:20]:  # limit
    js = http(js_url)
    luas = set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', js))
    views = set(re.findall(r'menuView[^"]*_tag=([a-zA-Z0-9_]+)', js))
    views2 = set(re.findall(r'menuData[^"]*_tag=([a-zA-Z0-9_]+_lua\.lua)', js))
    all_lua |= luas | views2
    all_views |= views
    if luas:
        print(f"  {js_url}: {len(luas)} lua refs")

all_lua |= lua_refs
all_views |= view_refs

print(f"\nTotal unique lua data tags: {len(all_lua)}")
for l in sorted(all_lua):
    print(f"  {l}")
print(f"\nTotal unique view tags: {len(all_views)}")
for v in sorted(all_views):
    print(f"  {v}")

# 4. Now probe each discovered lua tag with traffic-related field search
print(f"\n=== PROBING {len(all_lua)} DISCOVERED DATA TAGS ===")
traffic_endpoints = []

for tag in sorted(all_lua):
    # Try to find the matching view from the views list
    # Use the tag itself without _lua.lua suffix as a guess for view
    base = tag.replace("_lua.lua", "")
    tried_views = set()

    # First try as data-only
    ts = int(time.time())
    xml = http(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        login()
        xml = http(f"/?_type=menuData&_tag={tag}&_={ts}")

    fields = extract_all(xml)
    traffic = {k: v for k, v in fields.items()
               if any(w in k.lower() for w in ["byte", "octet", "packet", "traffic",
                                                 "rxbyte", "txbyte", "upload", "download"])}

    if traffic:
        print(f"\n*** TRAFFIC: {tag} ***")
        for k, v in sorted(traffic.items()):
            print(f"    {k} = {v}")
        print(f"    (all {len(fields)} fields: {', '.join(sorted(fields.keys())[:15])}...)")
        traffic_endpoints.append((tag, fields))
    elif fields:
        # Has data but no traffic fields
        byte_ish = {k: v for k, v in fields.items() if v.isdigit() and len(v) > 6}
        if byte_ish:
            print(f"\n  ? {tag}: large numbers found: {dict(list(byte_ish.items())[:5])}")
        else:
            sys.stdout.write(".")
            sys.stdout.flush()
    else:
        sys.stdout.write("x")
        sys.stdout.flush()

print(f"\n\n=== SUMMARY ===")
print(f"Endpoints with traffic data: {len(traffic_endpoints)}")
for tag, fields in traffic_endpoints:
    print(f"  {tag}:")
    for k, v in sorted(fields.items()):
        print(f"    {k} = {v}")
