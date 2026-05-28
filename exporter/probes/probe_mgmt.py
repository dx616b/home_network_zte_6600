#!/usr/bin/env python3
"""Probe management pages for SNMP/telnet/SSH config."""
import requests
import re
import os

s = requests.Session()
r = s.get('http://192.168.1.1')
token = re.search(r'getObj\("Frm_Logintoken"\)\.value\s*=\s*"(\d+)"', r.text)
tok = token.group(1) if token else ''

username = os.environ.get('ZTE_USERNAME', 'root')
password = os.environ.get('ZTE_PASSWORD', 'ZTEEQL4Q5C03281')

# Hash password same way as login page
import hashlib
pwd_hash = password + "$$bbEdbbgj5656"

s.post('http://192.168.1.1', data={
    'action': 'login',
    'Username': username,
    'Password': pwd_hash,
    'Frm_Logintoken': tok,
})

# Try management pages
pages = [
    '/?_type=menuView&_tag=sysManageMgr',
    '/?_type=menuView&_tag=remoteAccess',
    '/?_type=menuView&_tag=telnetConfig',
    '/?_type=menuView&_tag=sshConfig',
    '/?_type=menuView&_tag=snmpConfig',
    '/?_type=menuView&_tag=tr069Config',
    '/?_type=menuView&_tag=diagMgr',
    '/?_type=menuView&_tag=netDiagMgr',
    '/?_type=menuData&_tag=admin_remotemgr_lua.lua',
    '/?_type=menuData&_tag=admin_snmp_lua.lua',
    '/?_type=menuData&_tag=admin_telnet_lua.lua',
    '/?_type=menuData&_tag=admin_ssh_lua.lua',
    '/?_type=menuData&_tag=admin_manage_lua.lua',
    '/?_type=menuData&_tag=admin_servicecontrol_lua.lua',
    '/?_type=menuData&_tag=diag_ping_lua.lua',
    '/?_type=menuData&_tag=diag_traceroute_lua.lua',
    '/?_type=menuData&_tag=admin_sysmanage_lua.lua',
]

for path in pages:
    try:
        r = s.get(f'http://192.168.1.1{path}', timeout=5)
        if r.status_code == 200 and len(r.text) > 50:
            content = r.text.strip()
            print(f"=== {path} ===")
            print(f"  Length: {len(r.text)}")
            print(f"  Content: {content[:300]}")
            print()
    except Exception as e:
        pass

# Also check if there's a diagnostic command injection page
# that might let us enable telnet from within
diag_pages = [
    '/?_type=menuData&_tag=diag_nslookup_lua.lua',
    '/?_type=menuData&_tag=diag_cmd_lua.lua',
]
for path in diag_pages:
    try:
        r = s.get(f'http://192.168.1.1{path}', timeout=5)
        if r.status_code == 200 and len(r.text) > 50:
            print(f"=== {path} ===")
            print(f"  Content: {r.text.strip()[:300]}")
            print()
    except:
        pass

s.get('http://192.168.1.1', params={'_type': 'loginOut', '_tag': 'logout_entry'})
