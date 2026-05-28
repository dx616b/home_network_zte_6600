#!/usr/bin/env python3
"""Try accessing admin scripts through valid menu views."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from zte_exporter import ZTEClient

client = ZTEClient('http://192.168.1.1', 'root', 'ZTEEQL4Q5C03281')
client.login()

# First establish a valid menu context
ts = int(time.time())
client._http(f"/?_type=menuView&_tag=statusMgr&Menu3Location=0&_={ts}")

# Now try admin scripts within this session context
admin_tags = [
    'admin_telnet_lua.lua',
    'admin_snmp_lua.lua', 
    'admin_ssh_lua.lua',
    'admin_remotemgr_lua.lua',
    'admin_servicecontrol_lua.lua',
]

for tag in admin_tags:
    ts = int(time.time())
    xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        # Maybe need specific menu location
        for view in ['localNetStatus', 'ethWanConfig', 'ponopticalinfo', 'homePage']:
            ts = int(time.time())
            client._http(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
            ts = int(time.time())
            xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
            if "SessionTimeout" not in xml:
                print(f"[OK via {view}] {tag}: {xml[:300]}")
                break
        else:
            print(f"[LOCKED] {tag}")
    else:
        print(f"[OK] {tag}: {xml[:300]}")

# Also try some PON-specific traffic tags we haven't tested
print("\n--- PON/GPON traffic data ---")
pon_tags = [
    'pon_traffic_lua.lua',
    'pon_statistics_lua.lua', 
    'pon_gemport_lua.lua',
    'gpon_statistics_lua.lua',
    'wan_traffic_lua.lua',
    'traffic_statistics_lua.lua',
    'status_traffic_lua.lua',
    'wan_statistics_lua.lua',
    'interface_statistics_lua.lua',
]

for tag in pon_tags:
    try:
        xml = client.fetch('statusMgr', tag)
        if xml and len(xml) > 100:
            print(f"[OK] {tag}: {xml[:400]}")
    except Exception as e:
        err = str(e)
        if "SessionTimeout" in err:
            print(f"[LOCKED] {tag}")
        else:
            # Try direct
            ts = int(time.time())
            xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
            if len(xml) > 50 and "SessionTimeout" not in xml:
                print(f"[OK-direct] {tag}: {xml[:300]}")
            else:
                print(f"[NONE] {tag}")
