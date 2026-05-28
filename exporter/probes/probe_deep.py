#!/usr/bin/env python3
"""Deep scan: extract ALL tags from the 206KB main page + JS, probe everything."""

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

# 1. Get the full main page
main = http_req("/")
print(f"Main page: {len(main)} chars")

# 2. Extract ALL JS file URLs and fetch them
js_urls = re.findall(r'src="(/[^"]*\.js[^"]*)"', main)
print(f"JS files: {len(js_urls)}")

all_content = main
for js_url in js_urls:
    try:
        js = http_req(js_url)
        all_content += "\n" + js
        print(f"  {js_url}: {len(js)} chars")
    except Exception as e:
        print(f"  {js_url}: ERROR {e}")

# 3. Extract ALL possible data tags
# Pattern 1: _tag=something
tag_refs = set(re.findall(r'[_&?]tag[=:]\s*["\']?([a-zA-Z_][a-zA-Z0-9_]*(?:_lua\.lua)?)', all_content))
# Pattern 2: _lua.lua references
lua_refs = set(re.findall(r'["\']([a-zA-Z0-9_]+_lua\.lua)["\']', all_content))
# Pattern 3: menuView / menuData tags
menu_view = set(re.findall(r'menuView[^"\']*?_tag=([a-zA-Z0-9_]+)', all_content))
menu_data = set(re.findall(r'menuData[^"\']*?_tag=([a-zA-Z0-9_]+)', all_content))
# Pattern 4: hiddenData tags
hidden = set(re.findall(r'hiddenData[^"\']*?_tag=([a-zA-Z0-9_]+)', all_content))
# Pattern 5: any string that looks like a tag name ending in _lua.lua
all_lua = set(re.findall(r'([a-zA-Z_][a-zA-Z0-9_]*_lua\.lua)', all_content))

# Merge all
all_tags = tag_refs | lua_refs | menu_view | menu_data | hidden | all_lua
# Filter out clearly non-tag things
all_tags = {t for t in all_tags if len(t) > 3 and not t.startswith("_")}

print(f"\nDiscovered {len(all_tags)} unique tags:")
for t in sorted(all_tags):
    print(f"  {t}")

# 4. Separate lua data tags from view tags
lua_tags = {t for t in all_tags if t.endswith("_lua.lua")}
view_tags = all_tags - lua_tags

print(f"\nLua data tags: {len(lua_tags)}")
print(f"View/other tags: {len(view_tags)}")

# 5. Probe each lua data tag
print(f"\n{'='*70}")
print(f"PROBING {len(lua_tags)} LUA DATA TAGS")
print(f"{'='*70}")

traffic_found = []
for tag in sorted(lua_tags):
    ts = int(time.time())
    try:
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    except:
        sys.stdout.write("E"); sys.stdout.flush(); continue
    if "SessionTimeout" in xml:
        login()
        try:
            xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
        except:
            continue

    instances = parse_instances(xml)
    flat_names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
    flat_vals = re.findall(r"<ParaValue>([^<]*)</ParaValue>", xml)
    flat = dict(zip(flat_names, flat_vals))

    all_fields = {}
    for inst in instances:
        all_fields.update(inst)
    if not instances and flat:
        all_fields = flat

    if not all_fields:
        sys.stdout.write("x"); sys.stdout.flush(); continue

    # Check for ANY field with byte/packet/traffic data
    interesting = {}
    for k, v in all_fields.items():
        kl = k.lower()
        if any(w in kl for w in ["byte", "octet", "packet", "traffic",
                                  "rxbyte", "txbyte", "counter", "throughput",
                                  "bitrate", "bandwidth"]):
            interesting[k] = v

    if interesting:
        print(f"\n*** {tag}: TRAFFIC FIELDS ***")
        for k, v in sorted(interesting.items()):
            print(f"    {k} = {v}")
        all_keys = sorted(all_fields.keys())
        print(f"    All fields: {all_keys}")
        traffic_found.append((tag, instances or [flat]))
    else:
        # Check for large numbers that could be counters
        large = {k: v for k, v in all_fields.items()
                 if v and v.replace(".", "").isdigit() and len(v) > 7}
        if large:
            print(f"\n  ? {tag}: large numbers: {large}")
        else:
            sys.stdout.write("."); sys.stdout.flush()

# 6. Probe each non-lua tag as hiddenData
print(f"\n\n{'='*70}")
print(f"PROBING {len(view_tags)} VIEW/HIDDEN TAGS")
print(f"{'='*70}")

for tag in sorted(view_tags):
    if tag.endswith("_entry") or tag.endswith("_switch"):
        continue  # Skip action tags
    ts = int(time.time())
    # Try as hiddenData
    try:
        xml = http_req(f"/?_type=hiddenData&_tag={tag}&_={ts}")
    except:
        continue
    if "SessionTimeout" in xml:
        login()
        try:
            xml = http_req(f"/?_type=hiddenData&_tag={tag}&_={ts}")
        except:
            continue

    instances = parse_instances(xml)
    if not instances:
        continue

    interesting = {}
    for inst in instances:
        for k, v in inst.items():
            kl = k.lower()
            if any(w in kl for w in ["byte", "packet", "traffic", "rx", "tx"]):
                interesting[k] = v

    if interesting:
        print(f"\n*** HIDDEN {tag}: TRAFFIC FIELDS ***")
        for k, v in sorted(interesting.items()):
            print(f"    {k} = {v}")
        traffic_found.append((f"hidden:{tag}", instances))

# 7. Try to find WLAN-specific view pages and extract their internal data tags
print(f"\n\n{'='*70}")
print("LOADING WLAN CONFIG PAGES TO FIND INTERNAL TAGS")
print(f"{'='*70}")

# Try loading specific WLAN configuration pages that might have inline JS with data tags
wlan_views = [v for v in sorted(view_tags) if "wlan" in v.lower() or "wifi" in v.lower() or "wireless" in v.lower()]
print(f"WLAN-related views: {wlan_views}")

for view in wlan_views:
    ts = int(time.time())
    try:
        html = http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
    except:
        continue
    if "SessionTimeout" in html:
        login()
        try:
            html = http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
        except:
            continue
    if len(html) > 2000:
        inner_lua = set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html))
        inner_hidden = set(re.findall(r'hiddenData[^"\']*_tag=([a-zA-Z0-9_]+)', html))
        inner_data = set(re.findall(r'menuData[^"\']*_tag=([a-zA-Z0-9_]+)', html))
        if inner_lua or inner_hidden or inner_data:
            print(f"\n  {view} ({len(html)} chars):")
            print(f"    lua tags: {sorted(inner_lua)}")
            print(f"    hidden tags: {sorted(inner_hidden)}")
            print(f"    data tags: {sorted(inner_data)}")
            # Probe any new lua tags
            for dtag in inner_lua - lua_tags:
                xml = http_req(f"/?_type=menuData&_tag={dtag}&_={ts}")
                inst = parse_instances(xml)
                if inst:
                    print(f"    NEW: {dtag} -> {len(inst)} instances")
                    for i in inst:
                        print(f"      Fields: {sorted(i.keys())}")
                        byte_fields = {k: v for k, v in i.items()
                                       if any(w in k.lower() for w in ["byte","packet","rx","tx","in","out"])}
                        if byte_fields:
                            print(f"      *** TRAFFIC: {byte_fields}")
                            traffic_found.append((f"wlan-{view}:{dtag}", [i]))

print(f"\n\n{'='*70}")
print(f"FINAL SUMMARY: {len(traffic_found)} endpoints with traffic data")
print(f"{'='*70}")
for tag, instances in traffic_found:
    print(f"\n  {tag}: {len(instances)} instances")
    for inst in instances:
        byte_fields = {k: v for k, v in inst.items()
                       if any(w in k.lower() for w in ["byte","packet","rx","tx","in","out","traffic"])}
        if byte_fields:
            name = inst.get("SSID", inst.get("WANCName", inst.get("_InstID", inst.get("Name", "?"))))
            print(f"    {name}: {byte_fields}")
