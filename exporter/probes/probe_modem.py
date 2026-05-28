#!/usr/bin/env python3
"""Probe ZTE F6600P modem for all available API endpoints with traffic/byte data."""

import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from urllib import parse, request

ZTE_URL = os.environ.get("ZTE_URL", "http://192.168.1.1").rstrip("/")
ZTE_USERNAME = os.environ.get("ZTE_USERNAME", "root")
ZTE_PASSWORD = os.environ.get("ZTE_PASSWORD", "")

opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))

def http_get(path):
    url = f"{ZTE_URL}{path}"
    req = request.Request(url)
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

def http_post(path, data):
    url = f"{ZTE_URL}{path}"
    body = parse.urlencode(data).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}, method="POST")
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

def login():
    text = http_get("/?_type=loginData&_tag=login_entry")
    m = re.search(r'"sess_token"\s*:\s*"([^"]+)"', text)
    if not m:
        print(f"FATAL: no sess_token in: {text[:200]}")
        sys.exit(1)
    session = m.group(1)

    text2 = http_get("/?_type=loginData&_tag=login_token")
    try:
        root = ET.fromstring(text2)
        token = root.text.strip() if root.text else ""
    except:
        m2 = re.search(r">(\d+)<", text2)
        token = m2.group(1) if m2 else ""
    if not token:
        print(f"FATAL: no login_token in: {text2[:200]}")
        sys.exit(1)

    digest = hashlib.sha256((ZTE_PASSWORD + token).encode()).hexdigest()
    result = http_post("/?_type=loginData&_tag=login_entry", {
        "action": "login",
        "Username": ZTE_USERNAME,
        "Password": digest,
        "_sessionTOKEN": session,
    })
    if "login_need_refresh" not in result.lower().replace(" ", ""):
        print(f"Login failed: {result[:300]}")
        sys.exit(1)
    http_get("/")
    print("Login OK\n")

def fetch_menu(view, data_tag, extra=""):
    ts = int(time.time())
    http_get(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
    q = f"&{extra}" if extra else ""
    return http_get(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")

def fetch_data_only(data_tag, extra=""):
    ts = int(time.time())
    q = f"&{extra}" if extra else ""
    return http_get(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")

def extract_fields(xml_text):
    """Extract all ParaName/ParaValue pairs."""
    names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml_text)
    raw_values = re.findall(
        r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>",
        xml_text, re.DOTALL,
    )
    values = [(a or b).strip() for a, b in raw_values]
    return dict(zip(names, values))

def has_traffic_data(fields):
    """Check if any field looks like a traffic/byte counter."""
    traffic_keys = []
    for k, v in fields.items():
        kl = k.lower()
        if any(word in kl for word in ["byte", "packet", "octet", "traffic", "counter",
                                        "rxbyte", "txbyte", "inbyte", "outbyte",
                                        "inpkt", "outpkt", "rxpkt", "txpkt",
                                        "upload", "download", "throughput", "rate",
                                        "rx_bytes", "tx_bytes"]):
            traffic_keys.append((k, v))
    return traffic_keys

def probe_endpoint(view, data_tag, extra="", label=""):
    """Try fetching an endpoint, look for traffic-related fields."""
    try:
        xml = fetch_menu(view, data_tag, extra)
        if "SessionTimeout" in xml:
            login()
            xml = fetch_menu(view, data_tag, extra)
        if "ERROR:" in xml or not xml.strip():
            return
        fields = extract_fields(xml)
        traffic = has_traffic_data(fields)
        if traffic:
            print(f"\n{'='*70}")
            print(f"TRAFFIC DATA FOUND: view={view} tag={data_tag} extra={extra}")
            print(f"{'='*70}")
            for k, v in traffic:
                print(f"  {k} = {v}")
            # Print ALL fields for context
            print(f"\n  All fields ({len(fields)}):")
            for k, v in sorted(fields.items()):
                print(f"    {k} = {v}")
        elif fields:
            # Has data but no traffic fields — just note it
            pass
        return fields
    except Exception as e:
        return None

def probe_data_only(data_tag, extra="", label=""):
    """Try fetching data endpoint directly without menuView."""
    try:
        xml = fetch_data_only(data_tag, extra)
        if "SessionTimeout" in xml:
            login()
            xml = fetch_data_only(data_tag, extra)
        if "ERROR:" in xml or not xml.strip():
            return
        fields = extract_fields(xml)
        traffic = has_traffic_data(fields)
        if traffic:
            print(f"\n{'='*70}")
            print(f"TRAFFIC DATA FOUND (data-only): tag={data_tag} extra={extra}")
            print(f"{'='*70}")
            for k, v in traffic:
                print(f"  {k} = {v}")
            print(f"\n  All fields ({len(fields)}):")
            for k, v in sorted(fields.items()):
                print(f"    {k} = {v}")
        return fields
    except Exception as e:
        return None


# Known ZTE F6600P menu views and data tags to probe
# Based on common ZTE ONT firmware endpoints
ENDPOINTS = [
    # WAN — already used, but try other variants
    ("ethWanConfig", "wan_internet_lua.lua", "TypeUplink=2&pageType=0", "WAN PPPoE"),
    ("ethWanConfig", "wan_internet_lua.lua", "TypeUplink=1&pageType=0", "WAN Bridge"),
    ("ethWanConfig", "wan_internet_lua.lua", "TypeUplink=0&pageType=0", "WAN Route"),
    ("ethWanConfig", "wan_internet_lua.lua", "", "WAN all"),

    # WAN status / statistics
    ("wanStatus", "wan_status_lua.lua", "", "WAN status"),
    ("wanStatistic", "wan_statistic_lua.lua", "", "WAN statistics"),
    ("wanStats", "wan_stats_lua.lua", "", "WAN stats"),
    ("wanTraffic", "wan_traffic_lua.lua", "", "WAN traffic"),
    ("statusWan", "status_wan_lua.lua", "", "Status WAN"),
    ("statusWan", "status_wan_info_lua.lua", "", "Status WAN info"),
    ("waninfo", "wan_info_lua.lua", "", "WAN info"),

    # Internet connection status
    ("internetStatus", "internet_status_lua.lua", "", "Internet status"),
    ("internetstatus", "internetstatus_lua.lua", "", "Internet status2"),

    # Network status
    ("networkStatus", "network_status_lua.lua", "", "Network status"),
    ("netStatus", "net_status_lua.lua", "", "Net status"),
    ("statusNet", "status_net_lua.lua", "", "Status net"),

    # DSL/PON traffic
    ("ponStatistic", "pon_statistic_lua.lua", "", "PON statistics"),
    ("ponStats", "pon_stats_lua.lua", "", "PON stats"),
    ("ponTraffic", "pon_traffic_lua.lua", "", "PON traffic"),
    ("ponStatus", "pon_status_lua.lua", "", "PON status"),
    ("ponopticalinfo", "optical_info_lua.lua", "", "PON optical"),
    ("gemPortStats", "gem_port_stats_lua.lua", "", "GEM port stats"),
    ("gemport", "gemport_lua.lua", "", "GEM port"),

    # Interface statistics
    ("ifStats", "if_stats_lua.lua", "", "Interface stats"),
    ("ifStatistic", "if_statistic_lua.lua", "", "Interface statistics"),
    ("interfaceStats", "interface_stats_lua.lua", "", "Interface stats2"),
    ("ethStats", "eth_stats_lua.lua", "", "Ethernet stats"),
    ("ethStatistic", "eth_statistic_lua.lua", "", "Ethernet statistics"),

    # LAN — already used
    ("localNetStatus", "status_lan_info_lua.lua", "", "LAN status"),

    # Traffic monitor
    ("trafficMonitor", "traffic_monitor_lua.lua", "", "Traffic monitor"),
    ("trafficStats", "traffic_stats_lua.lua", "", "Traffic stats"),
    ("trafficStatistic", "traffic_statistic_lua.lua", "", "Traffic statistic"),
    ("trafficInfo", "traffic_info_lua.lua", "", "Traffic info"),

    # Device status / homepage
    ("homePage", "homePage_lua.lua", "", "Home page"),
    ("statusMgr", "devmgr_statusmgr_lua.lua", "", "Device status"),

    # GPON
    ("gponStatus", "gpon_status_lua.lua", "", "GPON status"),
    ("gponStats", "gpon_stats_lua.lua", "", "GPON stats"),
    ("gponStatistic", "gpon_statistic_lua.lua", "", "GPON statistic"),

    # IP diagnostics
    ("diagWanInfo", "diag_wan_info_lua.lua", "", "Diag WAN info"),
    ("diagNetInfo", "diag_net_info_lua.lua", "", "Diag net info"),

    # NAT / routing
    ("routeStatus", "route_status_lua.lua", "", "Route status"),
    ("natStatus", "nat_status_lua.lua", "", "NAT status"),

    # IP statistics
    ("ipStats", "ip_stats_lua.lua", "", "IP stats"),
    ("ipStatistic", "ip_statistic_lua.lua", "", "IP statistics"),
]

# Data-only tags to try (no menuView needed)
DATA_ONLY_TAGS = [
    ("wan_statistic_lua.lua", "", "WAN statistic data"),
    ("wan_stats_lua.lua", "", "WAN stats data"),
    ("status_wan_info_lua.lua", "", "WAN status info data"),
    ("wan_traffic_lua.lua", "", "WAN traffic data"),
    ("pon_statistic_lua.lua", "", "PON statistic data"),
    ("pon_stats_lua.lua", "", "PON stats data"),
    ("traffic_stats_lua.lua", "", "Traffic stats data"),
    ("traffic_monitor_lua.lua", "", "Traffic monitor data"),
    ("if_stats_lua.lua", "", "Interface stats data"),
    ("eth_stats_lua.lua", "", "Eth stats data"),
    ("gem_port_stats_lua.lua", "", "GEM stats data"),
    ("homePage_lua.lua", "", "HomePage data"),
    ("gpon_stats_lua.lua", "", "GPON stats data"),
]


if __name__ == "__main__":
    if not ZTE_PASSWORD:
        print("Set ZTE_PASSWORD environment variable")
        sys.exit(1)

    login()

    print("="*70)
    print("PROBING MENU ENDPOINTS FOR TRAFFIC DATA")
    print("="*70)

    found_count = 0
    for view, tag, extra, label in ENDPOINTS:
        sys.stdout.write(f"  Probing {label:30s} ({tag})... ")
        sys.stdout.flush()
        fields = probe_endpoint(view, tag, extra, label)
        if fields is None:
            print("error/empty")
        elif has_traffic_data(fields):
            found_count += 1
            print(f"TRAFFIC DATA ({len(fields)} fields)")
        elif fields:
            print(f"ok ({len(fields)} fields, no traffic)")
        else:
            print("empty response")

    print(f"\n{'='*70}")
    print("PROBING DATA-ONLY ENDPOINTS")
    print("="*70)

    for tag, extra, label in DATA_ONLY_TAGS:
        sys.stdout.write(f"  Probing {label:30s} ({tag})... ")
        sys.stdout.flush()
        fields = probe_data_only(tag, extra, label)
        if fields is None:
            print("error/empty")
        elif has_traffic_data(fields):
            found_count += 1
            print(f"TRAFFIC DATA ({len(fields)} fields)")
        elif fields:
            print(f"ok ({len(fields)} fields, no traffic)")
        else:
            print("empty response")

    print(f"\n{'='*70}")
    print(f"Done. Found {found_count} endpoints with traffic data.")
    print("="*70)
