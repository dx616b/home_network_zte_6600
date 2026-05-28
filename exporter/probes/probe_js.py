#!/usr/bin/env python3
"""Find JS files containing the menuTreeJSON definition."""
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

# Find all JS script sources
scripts = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html)
print(f"JS files: {scripts}")

# Check each JS file for menuTreeJSON
for src in scripts:
    src_url = src if src.startswith("/") else f"/{src}"
    try:
        js = http_req(src_url)
        if "menuTreeJSON" in js or "viewId" in js:
            print(f"\nFound in {src_url} ({len(js)} chars)")
            # Extract the JSON
            m = re.search(r'menuTreeJSON\s*=\s*"(.*?)"', js, re.DOTALL)
            if m:
                raw = m.group(1).replace('\\"', '"').replace("\\/", "/")
                try:
                    data = json.loads(raw)
                    all_views = re.findall(r'"viewId":"([^"]+)"', raw)
                    print(f"Views found: {len(all_views)}")
                    for v in sorted(set(all_views)):
                        print(f"  {v}")
                except json.JSONDecodeError as e:
                    print(f"JSON parse error: {e}")
                    print(f"First 200: {raw[:200]}")
            else:
                # Try single quotes
                m2 = re.search(r"menuTreeJSON\s*=\s*'(.*?)'", js, re.DOTALL)
                if m2:
                    print(f"Found with single quotes, len: {len(m2.group(1))}")
                else:
                    # Find where menuTreeJSON is set
                    idx = js.find("menuTreeJSON")
                    if idx >= 0:
                        print(f"  Context: {repr(js[idx:idx+200])}")
    except Exception as e:
        print(f"  Error fetching {src_url}: {e}")

print("\nDone.")
