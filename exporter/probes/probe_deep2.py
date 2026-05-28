#!/usr/bin/env python3
"""Deep dive into remoteMgr (TR-069), logMgr, ethWanStatus and their data."""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(__file__))
from zte_exporter import ZTEClient

client = ZTEClient('http://192.168.1.1', 'root', 'ZTEEQL4Q5C03281')
client.login()
print("Logged in.\n")

# ============================================================
# 1. remoteMgr view — get the full HTML to find lua tags
# ============================================================
print("=" * 60)
print("remoteMgr VIEW (TR-069 / CWMP)")
print("=" * 60)
ts = int(time.time())
html = client._http(f"/?_type=menuView&_tag=remoteMgr&Menu3Location=0&_={ts}")
# Extract all lua references and data tags
lua_refs = set(re.findall(r'["\']([a-z0-9_]+_lua\.lua)["\']', html, re.IGNORECASE))
data_tags = set(re.findall(r'_tag[=:]\s*["\']([^"\']+)["\']', html, re.IGNORECASE))
menu_tags = set(re.findall(r'menuData[^"]*_tag=([^&"\']+)', html, re.IGNORECASE))
all_tags = lua_refs | data_tags | menu_tags
print(f"Lua refs: {lua_refs}")
print(f"Data tags: {data_tags}")
print(f"Menu tags: {menu_tags}")

# Also look for form action URLs and input names
inputs = re.findall(r'(?:name|id)\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
print(f"Form inputs/ids: {inputs}")

# Print relevant JS sections
for m in re.finditer(r'function\s+(\w+)\s*\([^)]*\)\s*\{([^}]{0,500})', html):
    fname, body = m.groups()
    if any(kw in body.lower() for kw in ['lua', 'menudata', 'transfer', 'getobj', 'rxbyte', 'txbyte', 'traffic', 'stat']):
        print(f"\nFunction {fname}:")
        print(f"  {body[:300]}")

# Now fetch data through the valid view context
print(f"\n--- Fetching data through remoteMgr context ---")
for tag in sorted(all_tags):
    if not tag.endswith('.lua'):
        continue
    ts = int(time.time())
    xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        # re-login and re-enter view
        client.login()
        ts = int(time.time())
        client._http(f"/?_type=menuView&_tag=remoteMgr&Menu3Location=0&_={ts}")
        ts = int(time.time())
        xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
    
    if "SessionTimeout" in xml:
        print(f"  [LOCKED] {tag}")
    elif len(xml.strip()) > 50:
        print(f"\n  [OK] {tag} (len={len(xml)})")
        instances = client.parse_instances(xml)
        if instances:
            for i, inst in enumerate(instances):
                print(f"    Instance {i}:")
                for k, v in inst.items():
                    print(f"      {k} = {v}")
        else:
            flat = client.parse_flat(xml)
            if flat:
                for k, v in flat.items():
                    print(f"    {k} = {v}")
            else:
                print(f"    Raw: {xml[:400]}")

# ============================================================
# 2. logMgr view
# ============================================================
print(f"\n{'='*60}")
print("logMgr VIEW")
print("=" * 60)
ts = int(time.time())
html = client._http(f"/?_type=menuView&_tag=logMgr&Menu3Location=0&_={ts}")
lua_refs = set(re.findall(r'["\']([a-z0-9_]+_lua\.lua)["\']', html, re.IGNORECASE))
data_tags = set(re.findall(r'_tag[=:]\s*["\']([^"\']+)["\']', html, re.IGNORECASE))
menu_tags = set(re.findall(r'menuData[^"]*_tag=([^&"\']+)', html, re.IGNORECASE))
all_tags = lua_refs | data_tags | menu_tags
print(f"Lua refs: {lua_refs}")
print(f"Data tags: {data_tags}")
print(f"Menu tags: {menu_tags}")

for tag in sorted(all_tags):
    if not tag.endswith('.lua'):
        continue
    ts = int(time.time())
    client._http(f"/?_type=menuView&_tag=logMgr&Menu3Location=0&_={ts}")
    ts = int(time.time())
    xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        print(f"  [LOCKED] {tag}")
    elif len(xml.strip()) > 50:
        print(f"\n  [OK] {tag} (len={len(xml)})")
        instances = client.parse_instances(xml)
        if instances:
            for i, inst in enumerate(instances[:3]):  # First 3 only
                print(f"    Instance {i}:")
                for k, v in inst.items():
                    print(f"      {k} = {v[:80] if len(v) > 80 else v}")
            if len(instances) > 3:
                print(f"    ... and {len(instances)-3} more instances")
        else:
            flat = client.parse_flat(xml)
            if flat:
                for k, v in flat.items():
                    print(f"    {k} = {v[:80] if len(v) > 80 else v}")

# ============================================================
# 3. ethWanStatus view — may have different data than ethWanConfig
# ============================================================
print(f"\n{'='*60}")
print("ethWanStatus VIEW")
print("=" * 60)
ts = int(time.time())
html = client._http(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
lua_refs = set(re.findall(r'["\']([a-z0-9_]+_lua\.lua)["\']', html, re.IGNORECASE))
data_tags = set(re.findall(r'_tag[=:]\s*["\']([^"\']+)["\']', html, re.IGNORECASE))
menu_tags = set(re.findall(r'menuData[^"]*_tag=([^&"\']+)', html, re.IGNORECASE))
all_tags = lua_refs | data_tags | menu_tags
print(f"Lua refs: {lua_refs}")
print(f"Data tags: {data_tags}")
print(f"Menu tags: {menu_tags}")

# Extract form inputs
inputs = re.findall(r'(?:name|id)\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
print(f"Inputs/ids: {[x for x in inputs if 'byte' in x.lower() or 'traffic' in x.lower() or 'stat' in x.lower() or 'rx' in x.lower() or 'tx' in x.lower()]}")

# Look for JS that references bytes/traffic
for m in re.finditer(r'((?:rx|tx|byte|traffic|counter|stat)\w*)', html, re.IGNORECASE):
    pass  # Just scan
byte_related = set(re.findall(r'\b\w*(?:byte|traffic|counter|packet|stat)\w*\b', html, re.IGNORECASE))
print(f"Byte/traffic related identifiers: {byte_related}")

for tag in sorted(all_tags):
    if not tag.endswith('.lua'):
        continue
    ts = int(time.time())
    client._http(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
    ts = int(time.time())
    xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
    if "SessionTimeout" in xml:
        print(f"  [LOCKED] {tag}")
    elif len(xml.strip()) > 50:
        print(f"\n  [OK] {tag} (len={len(xml)})")
        instances = client.parse_instances(xml)
        if instances:
            for i, inst in enumerate(instances):
                print(f"    Instance {i}:")
                for k, v in inst.items():
                    print(f"      {k} = {v}")
        else:
            flat = client.parse_flat(xml)
            if flat:
                for k, v in flat.items():
                    print(f"    {k} = {v}")

# ============================================================
# 4. Also try fetching with extra parameters through ethWanStatus context
# ============================================================
print(f"\n{'='*60}")
print("ethWanStatus — wan_internetstatus with various params")
print("=" * 60)
for extra in [
    'TypeUplink=2&pageType=1',
    'TypeUplink=2&pageType=0',
    'TypeUplink=1&pageType=1',
    'TypeUplink=1&pageType=0',
    'TypeUplink=0&pageType=1',
    'TypeUplink=0&pageType=0',
]:
    try:
        ts = int(time.time())
        client._http(f"/?_type=menuView&_tag=ethWanStatus&Menu3Location=0&_={ts}")
        ts = int(time.time())
        xml = client._http(f"/?_type=menuData&_tag=wan_internetstatus_lua.lua&_={ts}&{extra}")
        if "SessionTimeout" in xml:
            client.login()
            continue
        instances = client.parse_instances(xml)
        if instances:
            print(f"\n  [{extra}] — {len(instances)} instances")
            for i, inst in enumerate(instances):
                # Only show byte/traffic related fields
                traffic_fields = {k: v for k, v in inst.items() 
                                  if any(kw in k.lower() for kw in ['byte', 'packet', 'rx', 'tx', 'traffic', 'error', 'speed', 'rate', 'name', 'type', 'status', 'ip'])}
                if traffic_fields:
                    print(f"    Instance {i}: {traffic_fields}")
    except Exception as e:
        print(f"  [{extra}] ERROR: {e}")

# ============================================================
# 5. Probe the system management extra — flash, temp, SN details
# ============================================================
print(f"\n{'='*60}")
print("SYSTEM STATUS — full details from devmgr_statusmgr_lua.lua")
print("=" * 60)
# We already know this works; check if there are additional instances
# with different parameters
for extra in ['', 'pageType=0', 'pageType=1', 'type=all', 'type=detail']:
    try:
        ts = int(time.time())
        client._http(f"/?_type=menuView&_tag=statusMgr&Menu3Location=0&_={ts}")
        ts = int(time.time())
        q = f"&{extra}" if extra else ""
        xml = client._http(f"/?_type=menuData&_tag=devmgr_statusmgr_lua.lua&_={ts}{q}")
        if "SessionTimeout" not in xml:
            instances = client.parse_instances(xml)
            fields_count = sum(len(inst) for inst in instances)
            print(f"  [{extra or 'default'}] — {len(instances)} instances, {fields_count} total fields")
    except:
        pass

# Logout
try:
    client._http("/?_type=loginOut&_tag=logout_entry")
except:
    pass
print("\nDone.")
