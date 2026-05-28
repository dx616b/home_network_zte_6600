#!/usr/bin/env python3
"""Deep probe of system management and TR-069 management pages."""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(__file__))
from zte_exporter import ZTEClient

client = ZTEClient('http://192.168.1.1', 'root', 'ZTEEQL4Q5C03281')
client.login()
print("Logged in.\n")

# ============================================================
# 1. System management area — try all plausible lua tags
# ============================================================
sys_tags = [
    # Status / diagnostics
    'devmgr_statusmgr_lua.lua',
    'devmgr_sysinfo_lua.lua',
    'devmgr_log_lua.lua',
    'devmgr_logconfig_lua.lua',
    'devmgr_syslog_lua.lua',
    'devmgr_oplog_lua.lua',
    'devmgr_upgrade_lua.lua',
    'devmgr_backup_lua.lua',
    'devmgr_restore_lua.lua',
    'devmgr_reboot_lua.lua',
    'devmgr_reset_lua.lua',
    'devmgr_time_lua.lua',
    'devmgr_ntp_lua.lua',
    'devmgr_usb_lua.lua',
    # Admin / management
    'admin_remotemgr_lua.lua',
    'admin_servicecontrol_lua.lua',
    'admin_manage_lua.lua',
    'admin_sysmanage_lua.lua',
    'admin_account_lua.lua',
    'admin_password_lua.lua',
    'admin_snmp_lua.lua',
    'admin_telnet_lua.lua',
    'admin_ssh_lua.lua',
    'admin_acl_lua.lua',
    'admin_firewall_lua.lua',
    # TR-069 / CWMP
    'tr069_config_lua.lua',
    'tr069_status_lua.lua',
    'tr069_param_lua.lua',
    'tr069_lua.lua',
    'cwmp_config_lua.lua',
    'cwmp_lua.lua',
    'admin_tr069_lua.lua',
    'admin_cwmp_lua.lua',
    'manage_tr069_lua.lua',
    'manage_cwmp_lua.lua',
    'wan_tr069_lua.lua',
    # Network diag
    'diag_ping_lua.lua',
    'diag_traceroute_lua.lua',
    'diag_nslookup_lua.lua',
    'diag_cmd_lua.lua',
    'diag_speedtest_lua.lua',
    'diag_portmirror_lua.lua',
    # Other management
    'manage_upnp_lua.lua',
    'manage_ddns_lua.lua',
    'manage_ddns_status_lua.lua',
    'manage_nat_lua.lua',
    'manage_portforward_lua.lua',
    'manage_dmz_lua.lua',
    'manage_qos_lua.lua',
    'manage_igmp_lua.lua',
    'manage_alg_lua.lua',
    'manage_acl_lua.lua',
    'manage_route_lua.lua',
    'manage_dns_lua.lua',
    'manage_dhcp_lua.lua',
    # Security
    'sec_firewall_lua.lua',
    'sec_filter_lua.lua',
    'sec_macfilter_lua.lua',
    'sec_ipfilter_lua.lua',
    'sec_urlfilter_lua.lua',
    'sec_dos_lua.lua',
    # Status
    'status_wan_lua.lua',
    'status_lan_lua.lua',
    'status_wlan_lua.lua',
    'status_voip_lua.lua',
    'status_route_lua.lua',
    'status_arp_lua.lua',
    'status_dhcp_lua.lua',
    'status_nat_lua.lua',
    'status_iptables_lua.lua',
    'status_traffic_lua.lua',
    'status_statistics_lua.lua',
    'status_interface_lua.lua',
]

# Views to try for context
views = ['statusMgr', 'localNetStatus', 'ethWanConfig', 'homePage', 'ponopticalinfo', 'voipStatus']

print("=" * 60)
print("PROBING LUA TAGS through multiple view contexts")
print("=" * 60)

accessible = []
locked = []
notfound = []

for tag in sys_tags:
    found = False
    for view in views:
        try:
            ts = int(time.time())
            client._http(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
            ts = int(time.time())
            xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
            
            if "SessionTimeout" in xml:
                continue  # Try next view
            
            if len(xml.strip()) < 30:
                continue  # Empty/trivial
            
            # Check if it's a real 404-style response
            if "404 Not Found" in xml or "<title>404" in xml:
                notfound.append(tag)
                found = True
                break
            
            # Got actual data!
            accessible.append((tag, view, xml))
            found = True
            break
        except Exception as e:
            pass
    
    if not found:
        # All views returned SessionTimeout — it exists but is locked
        # Verify it exists by checking if we get SessionTimeout vs nothing
        try:
            ts = int(time.time())
            xml = client._http(f"/?_type=menuData&_tag={tag}&_={ts}")
            if "SessionTimeout" in xml:
                locked.append(tag)
            elif len(xml.strip()) < 30:
                notfound.append(tag)
            else:
                # Actually got data without view context!
                accessible.append((tag, "direct", xml))
        except:
            notfound.append(tag)

print(f"\n{'='*60}")
print(f"ACCESSIBLE ({len(accessible)} tags):")
print(f"{'='*60}")
for tag, view, xml in accessible:
    print(f"\n--- {tag} (via {view}) ---")
    print(f"Length: {len(xml)}")
    # Parse and show fields
    instances = client.parse_instances(xml)
    if instances:
        for i, inst in enumerate(instances):
            print(f"  Instance {i}:")
            for k, v in inst.items():
                print(f"    {k} = {v[:100] if len(v) > 100 else v}")
    else:
        flat = client.parse_flat(xml)
        if flat:
            for k, v in flat.items():
                print(f"  {k} = {v[:100] if len(v) > 100 else v}")
        else:
            print(f"  Raw: {xml[:500]}")

print(f"\n{'='*60}")
print(f"LOCKED / ISP-restricted ({len(locked)} tags):")
print(f"{'='*60}")
for tag in locked:
    print(f"  {tag}")

print(f"\n{'='*60}")
print(f"NOT FOUND ({len(notfound)} tags):")
print(f"{'='*60}")
for tag in notfound:
    print(f"  {tag}")

# ============================================================
# 2. Try menuView tags for management sections
# ============================================================
print(f"\n{'='*60}")
print("PROBING MENU VIEWS for management sections")
print(f"{'='*60}")

mgmt_views = [
    'sysMgr', 'sysManageMgr', 'systemMgr', 'manageMgr',
    'adminMgr', 'securityMgr', 'diagnosticMgr',
    'tr069Mgr', 'cwmpMgr', 'tr069Config', 'cwmpConfig',
    'remoteMgr', 'remoteAccess', 'serviceMgr',
    'logMgr', 'timeMgr', 'ntpMgr', 'upgradeMgr',
    'backupMgr', 'firewallMgr', 'natMgr', 'routeMgr',
    'qosMgr', 'upnpMgr', 'ddnsMgr', 'aclMgr',
    'snmpMgr', 'telnetMgr', 'sshMgr',
    'maintenanceMgr', 'maintMgr',
    'ethWanStatus',  # we know this works
]

for view in mgmt_views:
    try:
        ts = int(time.time())
        html = client._http(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
        if "404 Not Found" in html:
            continue
        if "SessionTimeout" in html:
            print(f"  [LOCKED] {view}")
            continue
        if len(html) > 200:
            # Extract any lua tags referenced in the page JS
            lua_refs = re.findall(r'["\']([a-z_]+_lua\.lua)["\']', html, re.IGNORECASE)
            js_tags = re.findall(r'_tag[=:]\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
            if lua_refs or js_tags:
                print(f"  [OK] {view} — lua refs: {lua_refs}, tags: {js_tags}")
            else:
                # Check for form elements or interesting content
                forms = re.findall(r'<form[^>]*>', html, re.IGNORECASE)
                inputs = re.findall(r'name=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if forms or inputs:
                    print(f"  [OK] {view} — forms: {len(forms)}, inputs: {inputs[:10]}")
                else:
                    print(f"  [OK] {view} — len={len(html)}, no lua refs found")
    except Exception as e:
        pass

# Logout
try:
    client._http("/?_type=loginOut&_tag=logout_entry")
except:
    pass
print("\nDone.")
