#!/usr/bin/env python3
"""Extract menuTreeJSON from ZTE main page and find all view+data tag pairs."""

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
main = http_req("/")
print(f"Main page: {len(main)} chars\n")

# Find menuTreeJSON assignment
# Pattern: var menuTreeJSON = JSON.parse('...');
match = re.search(r"var\s+menuTreeJSON\s*=\s*JSON\.parse\s*\(\s*'(.*?)'\s*\)", main, re.DOTALL)
if not match:
    # Try alternative patterns
    match = re.search(r'var\s+menuTreeJSON\s*=\s*(\[.*?\]);', main, re.DOTALL)
if not match:
    match = re.search(r'var\s+menuTreeJSON\s*=\s*(\{.*?\});', main, re.DOTALL)
if not match:
    # Search for menuTreeJSON in broader context
    idx = main.find("menuTreeJSON")
    if idx >= 0:
        context = main[idx:idx+2000]
        print(f"menuTreeJSON context:\n{context[:1000]}")
    else:
        print("menuTreeJSON not found in main page!")
    sys.exit(1)

menu_json_str = match.group(1)
print(f"menuTreeJSON: {len(menu_json_str)} chars")

try:
    menu_tree = json.loads(menu_json_str)
except json.JSONDecodeError as e:
    print(f"JSON parse error: {e}")
    print(f"First 500 chars: {menu_json_str[:500]}")
    # Try to fix common issues (escaped quotes)
    menu_json_str = menu_json_str.replace("\\'", "'")
    try:
        menu_tree = json.loads(menu_json_str)
    except:
        print("Still can't parse")
        sys.exit(1)

# Recursively extract all menu items
def extract_items(node, path=""):
    items = []
    if isinstance(node, list):
        for item in node:
            items.extend(extract_items(item, path))
    elif isinstance(node, dict):
        name = node.get("name", node.get("Name", node.get("title", node.get("label", ""))))
        tag = node.get("tag", node.get("Tag", node.get("view", node.get("url", ""))))
        page = node.get("page", node.get("Page", node.get("file", "")))
        current_path = f"{path}/{name}" if name else path
        
        if tag or page or name:
            items.append({
                "path": current_path,
                "name": name,
                "tag": tag,
                "page": page,
                "raw": {k: v for k, v in node.items() if k not in ("children", "child", "sub")}
            })
        
        # Recurse into children
        for child_key in ("children", "child", "sub", "items", "submenu"):
            if child_key in node:
                items.extend(extract_items(node[child_key], current_path))
        
        # Also check numbered keys or any list values
        for k, v in node.items():
            if isinstance(v, (list, dict)) and k not in ("children", "child", "sub", "items", "submenu"):
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    items.extend(extract_items(v, current_path))
    
    return items

items = extract_items(menu_tree)
print(f"\nExtracted {len(items)} menu items:\n")

for item in items:
    print(f"  {item['path']}")
    if item['tag']:
        print(f"    tag: {item['tag']}")
    if item['page']:
        print(f"    page: {item['page']}")
    raw = item['raw']
    for k, v in sorted(raw.items()):
        if k not in ('name', 'Name', 'tag', 'Tag', 'page', 'Page'):
            if isinstance(v, str) and v:
                print(f"    {k}: {v}")
            elif isinstance(v, (int, float, bool)):
                print(f"    {k}: {v}")

# Also look for page configuration data
# ZTE uses pageJSON for page->lua tag mappings
page_match = re.search(r"var\s+pageJSON\s*=\s*JSON\.parse\s*\(\s*'(.*?)'\s*\)", main, re.DOTALL)
if page_match:
    print(f"\n{'='*70}")
    print("pageJSON found!")
    print(f"{'='*70}")
    try:
        page_data = json.loads(page_match.group(1))
        print(json.dumps(page_data, indent=2)[:3000])
    except:
        print(page_match.group(1)[:1000])

# Look for all .lp file references (ZTE template pages)
lp_files = set(re.findall(r'([a-zA-Z0-9_]+\.lp)', main))
print(f"\n.lp template files: {sorted(lp_files)}")

# Print raw menu tree structure (first 3000 chars)
print(f"\n{'='*70}")
print("RAW MENU TREE (first 3000 chars):")
print(f"{'='*70}")
print(json.dumps(menu_tree, indent=2)[:3000])
