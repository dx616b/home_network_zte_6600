#!/usr/bin/env python3
"""Find all viewId references in the main page to build the menu tree."""
import hashlib, re, time, os, json
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
    return http_req("/")

html = login()
print(f"HTML size: {len(html)}")

# Find the JSON data that initializes the menu tree
# Look for patterns like: new MenuTreeClass([...])  or  MenuTreeClass("[...]")
m = re.search(r'new\s+MenuTreeClass\s*\(\s*["\'](.+?)["\']\s*\)', html, re.DOTALL)
if m:
    raw = m.group(1).replace('\\"', '"').replace("\\/", "/")
    menu = json.loads(raw)
    print(f"Menu items: {len(menu)}")
else:
    # Try finding escaped JSON string passed to MenuTreeClass
    m2 = re.search(r'MenuTreeClass\s*\(\s*"(.+?)"\s*\)', html, re.DOTALL)
    if m2:
        raw = m2.group(1).replace('\\"', '"').replace("\\/", "/")
        print(f"Found MenuTreeClass data: {len(raw)} chars")
        menu = json.loads(raw)
        print(f"Menu items: {len(menu)}")
    else:
        # Look for a large JSON array in the page near menuTree
        idx = html.find("MenuTreeClass")
        if idx >= 0:
            context = html[idx:idx+200]
            print(f"MenuTreeClass context: {repr(context)}")
        
        # Also search for where the JSON is passed
        # Could be: var obj = new MenuTreeClass(varname)
        m3 = re.search(r'new\s+MenuTreeClass\s*\(\s*(\w+)\s*\)', html)
        if m3:
            varname = m3.group(1)
            print(f"MenuTreeClass takes variable: {varname}")
            # Find the variable definition
            m4 = re.search(rf'var\s+{varname}\s*=\s*["\'](.+?)["\']', html, re.DOTALL)
            if m4:
                raw = m4.group(1).replace('\\"', '"').replace("\\/", "/")
                menu = json.loads(raw)
                print(f"Menu items: {len(menu)}")
            else:
                # Try without var keyword
                m5 = re.search(rf'{varname}\s*=\s*["\'](.{{100}})', html)
                if m5:
                    print(f"Variable {varname} starts with: {repr(m5.group(1))}")

# Just extract all unique _tag= references from the entire page
print("\nAll _tag= references in main page:")
all_tags = re.findall(r'_tag=(\w+)', html)
unique = sorted(set(all_tags))
for t in unique:
    print(f"  {t}")

# Extract all _type=menuView references
print(f"\nAll menuView tags: {[t for t in unique if t not in ('login_entry', 'login_token')]}")
