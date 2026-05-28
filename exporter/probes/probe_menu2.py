#!/usr/bin/env python3
import hashlib, re, time, os
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

# Find viewId references
for pat in ["menuTree", "viewId", "menuJSON"]:
    idx = html.find(pat)
    if idx >= 0:
        print(f"{pat} found at index {idx}")
        snippet = html[max(0, idx-20):idx+80]
        print(f"  Context: {repr(snippet)}")

# If no viewId found, show what we have
if "viewId" not in html:
    print("No viewId found. Showing first 1000 chars:")
    print(html[:1000])
