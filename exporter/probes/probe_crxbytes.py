#!/usr/bin/env python3
"""Get wan_internetstatus_lua.lua with pageType=1 to see all fields including cRxBytes/cTxBytes."""
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

# Get WAN status with pageType=1
ts = int(time.time())
http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
xml = http_req(f"/?_type=menuData&_tag=wan_internetstatus_lua.lua&_={ts}&TypeUplink=2&pageType=1")

for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL):
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
    raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
    vals = [(a or b).strip() for a, b in raw]
    row = dict(zip(names, vals))
    name = row.get("WANCName", row.get("_InstID", "?"))
    print(f"[{name}]:")
    for k, v in sorted(row.items()):
        if v:
            print(f"  {k} = {v}")
    print()

# Compare cRxBytes vs RxBytes for internet connection
print("=" * 60)
# Also get from config endpoint for comparison
xml2 = http_req(f"/?_type=menuData&_tag=wan_internet_lua.lua&_={ts}&TypeUplink=2&pageType=1")
for block in re.findall(r"<Instance>(.*?)</Instance>", xml2, re.DOTALL):
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
    raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
    vals = [(a or b).strip() for a, b in raw]
    row = dict(zip(names, vals))
    if row.get("WANCName") == "internet":
        rx = row.get("RxBytes", "?")
        tx = row.get("TxBytes", "?")
        print(f"wan_internet_lua.lua (config): RxBytes={rx} TxBytes={tx}")

# Now let's also scrape 3 times with 5 second interval to see rate
print("\n=== Rate check over 10 seconds ===")
snapshots = []
for i in range(3):
    ts = int(time.time())
    http_req(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
    xml = http_req(f"/?_type=menuData&_tag=wan_internetstatus_lua.lua&_={ts}&TypeUplink=2&pageType=1")
    for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL):
        names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
        raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
        vals = [(a or b).strip() for a, b in raw]
        row = dict(zip(names, vals))
        if row.get("WANCName") == "internet":
            t = time.time()
            rx = int(row.get("RxBytes", "0") or "0")
            tx = int(row.get("TxBytes", "0") or "0")
            crx = row.get("cRxBytes", "?")
            ctx = row.get("cTxBytes", "?")
            snapshots.append((t, rx, tx, crx, ctx))
            print(f"  t={t:.1f} RxBytes={rx} TxBytes={tx} cRxBytes={crx} cTxBytes={ctx}")
    if i < 2:
        time.sleep(5)

if len(snapshots) >= 2:
    dt = snapshots[-1][0] - snapshots[0][0]
    drx = snapshots[-1][1] - snapshots[0][1]
    dtx = snapshots[-1][2] - snapshots[0][2]
    print(f"\n  Over {dt:.0f}s: RxBytes delta={drx:,} ({drx*8/dt/1e6:.2f} Mbps), TxBytes delta={dtx:,} ({dtx*8/dt/1e6:.2f} Mbps)")
