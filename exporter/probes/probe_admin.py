#!/usr/bin/env python3
"""Probe admin/management lua scripts to find SNMP/telnet/SSH config."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from zte_exporter import ZTEClient

client = ZTEClient('http://192.168.1.1', 'root', 'ZTEEQL4Q5C03281')
client.login()

# These lua scripts exist (they return SessionTimeout, not 404)
# Try to fetch their data properly through the fetch mechanism
tags = [
    'admin_remotemgr_lua.lua',
    'admin_snmp_lua.lua',
    'admin_telnet_lua.lua',
    'admin_ssh_lua.lua',
    'admin_manage_lua.lua',
    'admin_servicecontrol_lua.lua',
    'admin_sysmanage_lua.lua',
    'diag_ping_lua.lua',
    'diag_traceroute_lua.lua',
    'diag_nslookup_lua.lua',
    'diag_cmd_lua.lua',
]

import time, re, urllib.request

for tag in tags:
    try:
        ts = int(time.time())
        xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
        if "SessionTimeout" in xml:
            client.login()
            ts = int(time.time())
            xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
        
        if "SessionTimeout" in xml:
            print(f"[TIMEOUT] {tag}")
        elif len(xml) < 50:
            print(f"[EMPTY]   {tag}: {xml!r}")
        else:
            print(f"[OK]      {tag}")
            print(f"          {xml[:500]}")
            # Parse instances
            instances = ZTEClient.parse_instances(xml)
            if instances:
                for i, inst in enumerate(instances):
                    print(f"          Instance {i}: {inst}")
            print()
    except Exception as e:
        print(f"[ERROR]   {tag}: {e}")
