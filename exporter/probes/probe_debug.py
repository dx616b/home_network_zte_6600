#!/usr/bin/env python3
"""Debug ZTE session flow step by step."""

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
    body = None
    headers = {}
    if data:
        body = parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = request.Request(url, data=body, headers=headers, method="POST" if data else "GET")
    with opener.open(req, timeout=15) as resp:
        text = resp.read().decode("utf-8", errors="replace")
        print(f"  [{resp.status}] {path[:80]} -> {len(text)} chars")
        return text

def print_cookies():
    for h in opener.handlers:
        if hasattr(h, "cookiejar"):
            for c in h.cookiejar:
                print(f"  Cookie: {c.name}={c.value[:60]}")

if not ZTE_PASS:
    print("Set ZTE_PASSWORD"); sys.exit(1)

# Step 1
print("Step 1: Get sess_token")
text = http_req("/?_type=loginData&_tag=login_entry")
m = re.search(r'"sess_token"\s*:\s*"([^"]+)"', text)
session = m.group(1) if m else "NONE"
print(f"  sess_token = {session[:40]}...")

# Step 2
print("\nStep 2: Get login_token")
text2 = http_req("/?_type=loginData&_tag=login_token")
try:
    root = ET.fromstring(text2)
    token = root.text.strip() if root.text else ""
except Exception:
    m2 = re.search(r">(\d+)<", text2)
    token = m2.group(1) if m2 else ""
print(f"  login_token = {token}")

# Step 3
print("\nStep 3: Login")
digest = hashlib.sha256((ZTE_PASS + token).encode()).hexdigest()
result = http_req("/?_type=loginData&_tag=login_entry", {
    "action": "login",
    "Username": ZTE_USER,
    "Password": digest,
    "_sessionTOKEN": session,
})
print(f"  result: {result[:300]}")
print_cookies()

# Step 4
print("\nStep 4: Load main page /")
main = http_req("/")
print(f"  main page length: {len(main)}")
print_cookies()

# Step 5 — try the WAN fetch
print("\nStep 5: menuView ethWanConfig")
ts = int(time.time())
r1 = http_req(f"/?_type=menuView&_tag=ethWanConfig&Menu3Location=0&_={ts}")
timeout1 = "SessionTimeout" in r1
print(f"  SessionTimeout: {timeout1}")
if not timeout1:
    print(f"  response: {r1[:200]}")

print("\nStep 6: menuData wan_internet_lua.lua")
ts = int(time.time())
r2 = http_req(f"/?_type=menuData&_tag=wan_internet_lua.lua&_={ts}&TypeUplink=2&pageType=0")
timeout2 = "SessionTimeout" in r2
print(f"  SessionTimeout: {timeout2}")
if not timeout2:
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", r2)
    print(f"  Fields ({len(names)}): {names[:20]}")
    # Print all instances with byte/rx/tx data
    for block in re.findall(r"<Instance>(.*?)</Instance>", r2, re.DOTALL):
        bnames = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
        bvals = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
        bvals = [(a or b).strip() for a, b in bvals]
        row = dict(zip(bnames, bvals))
        print(f"\n  Instance: {row.get('WANCName', '?')}")
        for k in sorted(row):
            if any(w in k.lower() for w in ["byte", "rx", "tx", "packet", "name", "type", "error", "multi"]):
                print(f"    {k} = {row[k]}")

# Step 7 — try PON optical (also known working)
print("\nStep 7: PON optical info")
ts = int(time.time())
http_req(f"/?_type=menuView&_tag=ponopticalinfo&Menu3Location=0&_={ts}")
r3 = http_req(f"/?_type=menuData&_tag=optical_info_lua.lua&_={ts}")
timeout3 = "SessionTimeout" in r3
print(f"  SessionTimeout: {timeout3}")
if not timeout3:
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", r3)
    vals = re.findall(r"<ParaValue>([^<]*)</ParaValue>", r3)
    for n, v in zip(names, vals):
        print(f"    {n} = {v}")
