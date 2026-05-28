#!/usr/bin/env python3
"""Full ZTE F6600P API endpoint scan — find all data tags in JS and probe them."""

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
        return resp.read().decode("utf-8", errors="replace")

def login():
    text = http_req("/?_type=loginData&_tag=login_entry")
    m = re.search(r'"sess_token"\s*:\s*"([^"]+)"', text)
    session = m.group(1)
    text2 = http_req("/?_type=loginData&_tag=login_token")
    try:
        root = ET.fromstring(text2)
        token = root.text.strip()
    except Exception:
        token = re.search(r">(\d+)<", text2).group(1)
    digest = hashlib.sha256((ZTE_PASS + token).encode()).hexdigest()
    http_req("/?_type=loginData&_tag=login_entry", {
        "action": "login", "Username": ZTE_USER, "Password": digest, "_sessionTOKEN": session,
    })
    http_req("/")
    print("Logged in")

login()

# Get main page HTML
main = http_req("/")

# Extract ALL JS file URLs
js_urls = re.findall(r'src="(/[^"]*\.js[^"]*)"', main)
print(f"Found {len(js_urls)} JS files in main page")

# Collect all lua tags, view tags, and hiddenData tags from ALL JS
all_lua_tags = set()
all_view_tags = set()
all_hidden_tags = set()
all_js_content = main  # include main page HTML too

for js_url in js_urls:
    try:
        js = http_req(js_url)
        all_js_content += js
    except Exception as e:
        print(f"  Error fetching {js_url}: {e}")

# Find all _tag= references
all_tag_refs = set(re.findall(r'_tag=([a-zA-Z0-9_]+(?:_lua)?\.lua)', all_js_content))
all_tag_refs |= set(re.findall(r'_tag=([a-zA-Z0-9_]+)', all_js_content))
# Find menuView tags
view_refs = set(re.findall(r'menuView[^"\']*_tag=([a-zA-Z0-9_]+)', all_js_content))
# Find menuData tags
data_refs = set(re.findall(r'menuData[^"\']*_tag=([a-zA-Z0-9_]+(?:_lua)?\.lua)', all_js_content))
# Find hiddenData tags  
hidden_refs = set(re.findall(r'hiddenData[^"\']*_tag=([a-zA-Z0-9_]+)', all_js_content))
# Find any _lua.lua references
lua_refs = set(re.findall(r'([a-zA-Z0-9_]+_lua\.lua)', all_js_content))

# Find view->data_tag mappings from JS patterns like menuView...tag=X followed by menuData...tag=Y
view_data_pairs = re.findall(r'menuView[^"\']*_tag=([a-zA-Z0-9_]+).*?menuData[^"\']*_tag=([a-zA-Z0-9_]+_lua\.lua)', all_js_content, re.DOTALL)

print(f"\nDiscovered tags:")
print(f"  All _tag references: {len(all_tag_refs)}")
print(f"  menuView tags: {len(view_refs)}")
print(f"  menuData tags: {len(data_refs)}")
print(f"  hiddenData tags: {len(hidden_refs)}")
print(f"  _lua.lua refs: {len(lua_refs)}")
print(f"  view->data pairs: {len(view_data_pairs)}")

print(f"\nmenuView tags: {sorted(view_refs)}")
print(f"\nmenuData tags (lua): {sorted(data_refs)}")
print(f"\nhiddenData tags: {sorted(hidden_refs)}")
print(f"\nAll lua refs: {sorted(lua_refs)}")
print(f"\nView->Data pairs: {sorted(set(view_data_pairs))}")

# Now probe each discovered lua data tag
print(f"\n{'='*70}")
print(f"PROBING ALL {len(lua_refs)} LUA DATA TAGS")
print(f"{'='*70}")

results = []
for tag in sorted(lua_refs):
    ts = int(time.time())
    try:
        xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
    except Exception:
        print(f"  {tag}: ERROR")
        continue
    if "SessionTimeout" in xml:
        print(f"  {tag}: SessionTimeout, re-login...")
        login()
        try:
            xml = http_req(f"/?_type=menuData&_tag={tag}&_={ts}")
        except Exception:
            continue

    names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
    raw_vals = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", xml, re.DOTALL)
    vals = [(a or b).strip() for a, b in raw_vals]
    fields = dict(zip(names, vals))

    if not fields:
        sys.stdout.write("x")
        sys.stdout.flush()
        continue

    # Check for traffic-relevant fields
    traffic = {}
    large_nums = {}
    for k, v in fields.items():
        kl = k.lower()
        if any(w in kl for w in ["byte", "octet", "packet", "traffic",
                                  "rxbyte", "txbyte", "upload", "download",
                                  "throughput", "bitrate", "bandwidth", "rate",
                                  "inbyte", "outbyte", "counter"]):
            traffic[k] = v
        elif v.isdigit() and int(v) > 100000:
            large_nums[k] = v

    if traffic:
        print(f"\n*** TRAFFIC: {tag} ***")
        for k, v in sorted(traffic.items()):
            print(f"    {k} = {v}")
        results.append(("TRAFFIC", tag, fields))
    elif large_nums:
        print(f"\n  ? LARGE NUMS: {tag}: {large_nums}")
        results.append(("LARGE", tag, fields))
    else:
        sys.stdout.write(".")
        sys.stdout.flush()

# Also probe hiddenData endpoints
print(f"\n\n{'='*70}")
print(f"PROBING {len(hidden_refs)} HIDDEN DATA TAGS")
print(f"{'='*70}")

for tag in sorted(hidden_refs):
    ts = int(time.time())
    try:
        xml = http_req(f"/?_type=hiddenData&_tag={tag}&_={ts}")
    except Exception:
        continue
    if "SessionTimeout" in xml:
        login()
        try:
            xml = http_req(f"/?_type=hiddenData&_tag={tag}&_={ts}")
        except Exception:
            continue

    names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
    raw_vals = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", xml, re.DOTALL)
    vals = [(a or b).strip() for a, b in raw_vals]
    fields = dict(zip(names, vals))

    if not fields:
        sys.stdout.write("x")
        sys.stdout.flush()
        continue

    traffic = {}
    for k, v in fields.items():
        kl = k.lower()
        if any(w in kl for w in ["byte", "octet", "packet", "traffic",
                                  "rxbyte", "txbyte", "upload", "download"]):
            traffic[k] = v

    if traffic:
        print(f"\n*** HIDDEN TRAFFIC: {tag} ***")
        for k, v in sorted(traffic.items()):
            print(f"    {k} = {v}")
        results.append(("HIDDEN_TRAFFIC", tag, fields))
    elif fields:
        sys.stdout.write(".")
        sys.stdout.flush()
    else:
        sys.stdout.write("x")
        sys.stdout.flush()

# Also try view+data pairs
print(f"\n\n{'='*70}")
print(f"PROBING {len(view_data_pairs)} VIEW+DATA PAIRS")
print(f"{'='*70}")

already_probed = {r[1] for r in results}
for view, data_tag in sorted(set(view_data_pairs)):
    if data_tag in already_probed:
        continue
    ts = int(time.time())
    try:
        http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
        xml = http_req(f"/?_type=menuData&_tag={data_tag}&_={ts}")
    except Exception:
        continue
    if "SessionTimeout" in xml:
        login()
        try:
            http_req(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
            xml = http_req(f"/?_type=menuData&_tag={data_tag}&_={ts}")
        except Exception:
            continue

    names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml)
    raw_vals = re.findall(r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>", xml, re.DOTALL)
    vals = [(a or b).strip() for a, b in raw_vals]
    fields = dict(zip(names, vals))

    traffic = {}
    for k, v in fields.items():
        kl = k.lower()
        if any(w in kl for w in ["byte", "octet", "packet", "traffic"]):
            traffic[k] = v

    if traffic:
        print(f"\n*** VIEW+DATA TRAFFIC: {view} -> {data_tag} ***")
        for k, v in sorted(traffic.items()):
            print(f"    {k} = {v}")
        print(f"    All fields: {sorted(fields.keys())}")
        results.append(("VIEW_DATA", data_tag, fields))
    elif fields:
        sys.stdout.write(".")
        sys.stdout.flush()

print(f"\n\n{'='*70}")
print(f"SUMMARY: {len(results)} endpoints with traffic/large-number data")
print(f"{'='*70}")
for kind, tag, fields in results:
    print(f"\n[{kind}] {tag}:")
    for k, v in sorted(fields.items()):
        print(f"  {k} = {v}")
