#!/usr/bin/env python3
"""Probe for PON/GPON traffic byte counters on the ZTE F6600P."""

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

# 1. Load PON-related menu pages and extract their JS data tags
pon_views = ["ponopticalinfo", "ponInfo", "ponLoid", "ponSn"]
for view in pon_views:
    ts = int(time.time())
    html = http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
    if "SessionTimeout" in html:
        login()
        html = http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
    if len(html) > 500:
        lua_tags = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html)))
        hidden_tags = sorted(set(re.findall(r'hiddenData[^"\']*_tag=([a-zA-Z0-9_]+)', html)))
        print(f"{view} ({len(html)} chars): lua={lua_tags} hidden={hidden_tags}")
        
        # Probe each discovered data tag
        for tag in lua_tags:
            xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
            if "SessionTimeout" in xml:
                login()
                xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
            instances = parse_instances(xml)
            flat_names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
            flat_vals = re.findall(r"<ParaValue>([^<]*)</ParaValue>", xml)
            flat = dict(zip(flat_names, flat_vals))
            
            all_fields = {}
            for inst in instances:
                all_fields.update(inst)
            if not instances:
                all_fields = flat
            
            if all_fields:
                print(f"  {tag}: {len(all_fields)} fields")
                for k, v in sorted(all_fields.items()):
                    if v:
                        print(f"    {k} = {v}")
    else:
        print(f"{view}: small/empty ({len(html)} chars)")

# 2. Load the WAN status page (ethWanStatus) — different from ethWanConfig
print(f"\n{'='*70}")
print("WAN STATUS PAGE (ethWanStatus)")
print(f"{'='*70}")
ts = int(time.time())
html = http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
if "SessionTimeout" in html:
    login()
    html = http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
print(f"Page size: {len(html)} chars")
lua_tags = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html)))
print(f"Lua tags: {lua_tags}")

for tag in lua_tags:
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
                if v:
                    print(f"      {k} = {v}")

# 3. Load the internetStatus page
print(f"\n{'='*70}")
print("INTERNET STATUS PAGE (internetStatus)")
print(f"{'='*70}")
ts = int(time.time())
html = http_req(f"/?_type=menuView&_tag=internetStatus&Menu3Location=0&_={ts}")
if "SessionTimeout" in html:
    login()
    html = http_req(f"/?_type=menuView&_tag=internetStatus&Menu3Location=0&_={ts}")
print(f"Page size: {len(html)} chars")
lua_tags = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html)))
hidden_tags = sorted(set(re.findall(r'hiddenData[^"\']*_tag=([a-zA-Z0-9_]+)', html)))
print(f"Lua tags: {lua_tags}")
print(f"Hidden tags: {hidden_tags}")

# 4. Try homePage for any PON traffic info
print(f"\n{'='*70}")
print("HOME PAGE DATA")
print(f"{'='*70}")
ts = int(time.time())
html = http_req(f"/?_type=menuView&_tag=homePage&Menu3Location=0&_={ts}")
if "SessionTimeout" in html:
    login()
    html = http_req(f"/?_type=menuView&_tag=homePage&Menu3Location=0&_={ts}")
lua_tags = sorted(set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', html)))
print(f"Lua tags in homePage: {lua_tags}")

for tag in lua_tags:
    ts = int(time.time())
    xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        login()
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    instances = parse_instances(xml)
    flat_names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
    flat_vals = re.findall(r"<ParaValue>([^<]*)</ParaValue>", xml)
    flat = dict(zip(flat_names, flat_vals))
    
    all_fields = flat if not instances else {}
    for inst in instances:
        all_fields.update(inst)
    
    # Look for byte/traffic fields
    traffic = {k: v for k, v in all_fields.items() 
               if any(w in k.lower() for w in ["byte", "packet", "traffic", "octet", "counter",
                                                 "rx", "tx", "upload", "download", "throughput"])}
    if traffic:
        print(f"\n  *** {tag}: TRAFFIC DATA ***")
        for k, v in sorted(traffic.items()):
            print(f"    {k} = {v}")
    elif all_fields:
        # Check for large numbers
        large = {k: v for k, v in all_fields.items() if v and v.replace(".", "").isdigit() and len(v) > 6}
        if large:
            print(f"  {tag}: large numbers: {large}")
