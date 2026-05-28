#!/usr/bin/env python3
"""Look at ethWanStatus JS for cRxBytes logic and any other data tags."""
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
    http_req("/")

login()

ts = int(time.time())
html = http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")

# Find all JS code that mentions cRxBytes or cTxBytes
lines = html.split('\n')
for i, line in enumerate(lines):
    if 'cRxBytes' in line or 'cTxBytes' in line or 'RxBytes' in line or 'TxBytes' in line:
        # Print surrounding context
        start = max(0, i-2)
        end = min(len(lines), i+3)
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"{marker} {j+1}: {lines[j].rstrip()}")
        print("---")

# Also look for any timer/refresh patterns and data fetch URLs
print("\n=== Data fetch patterns ===")
for i, line in enumerate(lines):
    if '_tag=' in line and 'lua' in line.lower():
        print(f"  {i+1}: {line.strip()}")

# Also look for any statistics or traffic page references
print("\n=== Other interesting refs ===")
for i, line in enumerate(lines):
    lowline = line.lower()
    if any(w in lowline for w in ['statistic', 'throughput', 'bandwidth', 'counter', 'pon_', 'gpon']):
        print(f"  {i+1}: {line.strip()[:200]}")
