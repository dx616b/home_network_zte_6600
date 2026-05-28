#!/usr/bin/env python3
"""Find menuTreeJSON by searching all occurrences in the main page."""
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

# Find ALL occurrences of menuTreeJSON
for m in re.finditer(r"menuTreeJSON", html):
    pos = m.start()
    ctx = html[max(0, pos-10):pos+200]
    print(f"\nAt {pos}: {repr(ctx[:100])}")

# Also look for viewId anywhere
viewid_matches = list(re.finditer(r"viewId", html))
print(f"\nTotal 'viewId' occurrences: {len(viewid_matches)}")
if viewid_matches:
    first = viewid_matches[0].start()
    print(f"First at {first}: {repr(html[max(0,first-20):first+100])}")
    last = viewid_matches[-1].start()
    print(f"Last at {last}: {repr(html[max(0,last-20):last+100])}")

# Check if the menu is loaded from a separate request/AJAX
# Look for XHR/fetch references that might load menu data
ajax_refs = re.findall(r'(?:ajax|fetch|getJSON|load)\s*\(\s*["\']([^"\']+)["\']', html)
print(f"\nAJAX/fetch references: {ajax_refs[:20]}")

# Look for menuData or menuView in inline scripts
menu_data_refs = re.findall(r'_type=menu\w+', html)
print(f"menuData/View refs: {sorted(set(menu_data_refs))}")
