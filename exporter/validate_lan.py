#!/usr/bin/env python3
"""Quick LAN counter validation: snapshot before/after a short iperf."""

import hashlib, re, time, sys, os, subprocess
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
    try:
        token = ET.fromstring(text2).text.strip()
    except Exception:
        token = re.search(r">(\d+)<", text2).group(1)
    digest = hashlib.sha256((ZTE_PASS + token).encode()).hexdigest()
    http_req("/?_type=loginData&_tag=login_entry", {
        "action": "login", "Username": ZTE_USER, "Password": digest, "_sessionTOKEN": session,
    })
    http_req("/")

def get_lan_counters():
    ts = int(time.time())
    http_req(f"/?_type=menuView&_tag=localNetStatus&Menu3Location=0&_={ts}")
    xml = http_req(f"/?_type=menuData&_tag=status_lan_info_lua.lua&_={ts}")
    if "SessionTimeout" in xml:
        login()
        ts = int(time.time())
        http_req(f"/?_type=menuView&_tag=localNetStatus&Menu3Location=0&_={ts}")
        xml = http_req(f"/?_type=menuData&_tag=status_lan_info_lua.lua&_={ts}")
    result = {}
    for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL):
        names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
        raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
        vals = [(a or b).strip() for a, b in raw]
        row = dict(zip(names, vals))
        port = row.get("_InstID", "?")
        result[port] = {
            "InBytes": int(row.get("InBytes", "0") or "0"),
            "OutBytes": int(row.get("OutBytes", "0") or "0"),
            "InPkts": int(row.get("InPkts", "0") or "0"),
            "OutPkts": int(row.get("OutPkts", "0") or "0"),
            "Status": row.get("Status", "?"),
            "Speed": row.get("Speed", "?"),
        }
    return result

def get_wan_counters():
    ts = int(time.time())
    http_req(f"/?_type=menuView&_tag=ethWanConfig&Menu3Location=0&_={ts}")
    xml = http_req(f"/?_type=menuData&_tag=wan_internet_lua.lua&_={ts}&TypeUplink=2&pageType=0")
    if "SessionTimeout" in xml:
        login()
        ts = int(time.time())
        http_req(f"/?_type=menuView&_tag=ethWanConfig&Menu3Location=0&_={ts}")
        xml = http_req(f"/?_type=menuData&_tag=wan_internet_lua.lua&_={ts}&TypeUplink=2&pageType=0")
    for block in re.findall(r"<Instance>(.*?)</Instance>", xml, re.DOTALL):
        names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
        raw = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", block, re.DOTALL)
        vals = [(a or b).strip() for a, b in raw]
        row = dict(zip(names, vals))
        if row.get("WANCName") == "internet":
            return {
                "RxBytes": int(row.get("RxBytes", "0") or "0"),
                "TxBytes": int(row.get("TxBytes", "0") or "0"),
            }
    return {}

def mb(b): return b / 1_000_000

login()
print("Logged in\n")

# BEFORE snapshot
print("=== BEFORE iperf ===")
lan_before = get_lan_counters()
wan_before = get_wan_counters()
ts_before = time.time()

port1 = "DEV.ETH.IF1"
print(f"LAN {port1}: InBytes={lan_before[port1]['InBytes']:,}  OutBytes={lan_before[port1]['OutBytes']:,}")
print(f"WAN internet: RxBytes={wan_before.get('RxBytes',0):,}  TxBytes={wan_before.get('TxBytes',0):,}")

# Run short iperf3 download (10 MB)
print("\n=== Running iperf3: 10M download (-R) ===")
result = subprocess.run(
    ["iperf3", "-c", "speedtest.wtnet.de", "-p", "5205", "-n", "10M", "-R"],
    capture_output=True, text=True, timeout=120
)
# Parse iperf output for received bytes
lines = result.stdout.strip().split("\n")
for line in lines[-5:]:
    print(f"  {line}")

time.sleep(2)  # let counters settle

# AFTER snapshot
print("\n=== AFTER iperf ===")
lan_after = get_lan_counters()
wan_after = get_wan_counters()
ts_after = time.time()

print(f"LAN {port1}: InBytes={lan_after[port1]['InBytes']:,}  OutBytes={lan_after[port1]['OutBytes']:,}")
print(f"WAN internet: RxBytes={wan_after.get('RxBytes',0):,}  TxBytes={wan_after.get('TxBytes',0):,}")

# DELTAS
elapsed = ts_after - ts_before
lan_in_d = lan_after[port1]["InBytes"] - lan_before[port1]["InBytes"]
lan_out_d = lan_after[port1]["OutBytes"] - lan_before[port1]["OutBytes"]
wan_rx_d = wan_after.get("RxBytes", 0) - wan_before.get("RxBytes", 0)
wan_tx_d = wan_after.get("TxBytes", 0) - wan_before.get("TxBytes", 0)

print(f"\n=== DELTAS ({elapsed:.0f}s) ===")
print(f"iperf downloaded: ~10 MB")
print(f"LAN {port1} InBytes delta:  {lan_in_d:>12,} ({mb(lan_in_d):.2f} MB) [upload from client]")
print(f"LAN {port1} OutBytes delta: {lan_out_d:>12,} ({mb(lan_out_d):.2f} MB) [download to client] <<<")
print(f"WAN RxBytes delta:          {wan_rx_d:>12,} ({mb(wan_rx_d):.2f} MB) [download from internet]")
print(f"WAN TxBytes delta:          {wan_tx_d:>12,} ({mb(wan_tx_d):.2f} MB) [upload to internet]")

if lan_out_d > 0:
    accuracy = lan_out_d / 10_000_000 * 100
    print(f"\nLAN OutBytes accuracy: {accuracy:.0f}% of 10 MB")
if wan_rx_d > 0:
    accuracy = wan_rx_d / 10_000_000 * 100
    print(f"WAN RxBytes accuracy:  {accuracy:.0f}% of 10 MB")
