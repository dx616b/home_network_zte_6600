"""Check what the modem reports as HostName for each client."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from zte_exporter import ZTEClient, ZTECollector

client = ZTEClient("http://192.168.1.1", "root", "ZTEEQL4Q5C03281")
client.login()

# Fetch home page first to establish session context
home_xml = client.fetch("homePage", "accessdev_homepage_lua.lua")
wlan_xml = client.fetch_hidden("accessdev_data", "DeveiceType=WLAN")
eth_xml = client.fetch_hidden("accessdev_data", "DeveiceType=ETH")

sources = {"HOME": home_xml, "WLAN": wlan_xml, "ETH": eth_xml}

for label, xml in sources.items():
    instances = client.parse_instances(xml, "OBJ_ACCESSDEV_ID")
    print(f"\n=== {label} ({len(instances)} instances) ===")
    for idx, inst in enumerate(instances):
        mac_raw = ZTECollector._pick(inst, "MACAddress", "MacAddr", "Mac", "PhysAddress", "MAC")
        ip_raw = ZTECollector._pick(inst, "IPAddress", "IpAddress", "IP", "ClientIP")
        hostname_raw = ZTECollector._pick(inst, "HostName", "Hostname", "DevName")
        mac = ZTECollector._norm_mac(mac_raw)
        if not mac and not ip_raw:
            continue
        print(f"  [{idx:2d}] MAC={mac or mac_raw!r:20s}  IP={ip_raw!r:18s}  HostName={hostname_raw!r}")
