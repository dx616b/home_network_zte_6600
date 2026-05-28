#!/usr/bin/env python3
"""Extract menu tree from the ZTE main page to find ALL page views."""

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

login()
print("Logged in\n")

main = http_req("/")
print(f"Main page: {len(main)} chars\n")

# Look for menu IDs, menu structure, and class1/class2/class3 menu items
# ZTE uses class1Menu (top level), class2Menu (sidebar), class3Menu (tabs)

# Find all MenuShow() or MenuClick calls
menu_calls = re.findall(r'MenuShow\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*(?:,\s*"([^"]*)")?', main)
print(f"MenuShow calls: {len(menu_calls)}")
for args in menu_calls[:20]:
    print(f"  MenuShow({args})")

# Find menu items with onclick handlers
menu_items = re.findall(r'onclick="[^"]*MenuShow\([^)]*\)[^"]*"[^>]*>([^<]+)<', main)
print(f"\nMenu items with onclick: {len(menu_items)}")

# Find all IDs that look like menu items
menu_ids = re.findall(r'id="(class[123]Menu[^"]*)"', main)
print(f"\nMenu element IDs: {sorted(set(menu_ids))[:30]}")

# Find all _tag references in the entire main page
all_tags = re.findall(r'_tag[=:]["\']\s*([a-zA-Z0-9_]+)', main)
print(f"\nAll _tag references: {sorted(set(all_tags))}")

# Look for MenuShow in links
links = re.findall(r'href="[^"]*_tag=([^"&]+)', main)
print(f"\nLinks with _tag: {sorted(set(links))}")

# Find the menu tree data structure — often a JSON or JS object
# Look for patterns like {id: ..., name: ..., url: ..., children: ...}
# or patterns like class1MenuData, menuTree, etc.
for pattern in [r'var\s+(\w*[Mm]enu\w*)\s*=', r'var\s+(\w*[Tt]ree\w*)\s*=',
                r'var\s+(\w*[Nn]av\w*)\s*=', r'var\s+(\w*[Pp]age\w*)\s*=']:
    matches = re.findall(pattern, main)
    if matches:
        print(f"\n  JS vars matching '{pattern}': {matches}")

# Look specifically for menuView tag names embedded in HTML/JS
# The ZTE web UI typically has menu items with data-tag or similar
menu_view_refs = re.findall(r'(?:menuView|_tag)\s*[=:]\s*["\']([a-zA-Z]\w+)["\']', main)
print(f"\nmenuView/tag refs: {sorted(set(menu_view_refs))}")

# Also look for the menu config JSON
# ZTE modems often have config like: wanConf, lanConf, etc.
config_blocks = re.findall(r'(\w+Conf)\s*=\s*JSON\.parse\s*\(\s*\'(\{[^\']{1,500})', main)
print(f"\nConfig blocks:")
for name, content in config_blocks:
    print(f"  {name}: {content[:200]}...")

# Find all HTML elements with data attributes
data_attrs = re.findall(r'data-(\w+)="([^"]+)"', main)
print(f"\ndata-* attributes: {len(data_attrs)}")
for attr, val in sorted(set(data_attrs))[:20]:
    print(f"  data-{attr}={val}")

# Look for menu/tab item text + associated view tag
# ZTE pattern: <li ... data-value="viewTag" ...>Label</li>
# or <a ... onclick="MenuShow('ClassAll','viewTag'...">Label</a>
tab_items = re.findall(r'(?:data-value|_tag|menuView)[=:]["\']\s*(\w+)["\'][^>]*>([^<]{2,30})<', main)
print(f"\nTab items (tag->label): {len(tab_items)}")
for tag, label in sorted(set(tab_items)):
    print(f"  {tag} -> {label.strip()}")

# Specifically search for any WLAN/WiFi/wireless related content
print(f"\n{'='*70}")
print("WLAN-RELATED CONTENT IN MAIN PAGE")
print(f"{'='*70}")

# Find lines containing wlan/wifi/wireless/ssid
lines = main.split("\n")
for i, line in enumerate(lines):
    ll = line.lower()
    if any(w in ll for w in ["wlan", "wifi", "wireless", "ssid"]):
        stripped = line.strip()
        if len(stripped) > 10 and len(stripped) < 300:
            if "function" in stripped or "var " in stripped or "tag" in ll or "menu" in ll or "onclick" in ll:
                print(f"  L{i}: {stripped}")

# Find the ssidConf that was spotted earlier
ssid_match = re.search(r'ssidConf\s*=\s*(\{[^;]+\});', main, re.DOTALL)
if ssid_match:
    print(f"\nssidConf ({len(ssid_match.group(1))} chars):")
    print(f"  {ssid_match.group(1)[:500]}")

# Find commConf which has menu structure hints
comm_match = re.search(r"commConf\s*=\s*JSON\.parse\s*\(\s*'(\{.*?\})'\s*\)", main, re.DOTALL)
if comm_match:
    try:
        conf = json.loads(comm_match.group(1))
        print(f"\ncommConf keys: {sorted(conf.keys())}")
        # Print items that might relate to menu/page structure
        for k, v in sorted(conf.items()):
            if isinstance(v, str) and len(v) < 200:
                print(f"  {k} = {v}")
            elif isinstance(v, bool):
                print(f"  {k} = {v}")
            elif isinstance(v, dict):
                print(f"  {k} = {json.dumps(v)[:200]}")
    except json.JSONDecodeError:
        print(f"  commConf: parse error, first 500 chars: {comm_match.group(1)[:500]}")

# Dump the full list of function names that include "menu" or "page"
funcs = re.findall(r'function\s+(\w*(?:menu|page|view|tab|nav)\w*)\s*\(', main, re.I)
print(f"\nMenu/page functions: {sorted(set(funcs))}")
