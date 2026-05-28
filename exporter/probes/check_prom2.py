import urllib.request, json

def prom_query(expr):
    url = f'http://mon.router.al:9090/api/v1/query?query={urllib.request.quote(expr)}'
    r = urllib.request.urlopen(url, timeout=10)
    return json.loads(r.read())['data']['result']

# Test the exact expressions used in panels
print("=== Panel queries (instant) ===")

queries = {
    "Exporter": "zte_exporter_up",
    "WLAN Downloaded": "sum(increase(zte_wlan_tx_bytes_total[24h]))",
    "WLAN Uploaded": "sum(increase(zte_wlan_rx_bytes_total[24h]))",
    "LAN Downloaded": "sum(increase(zte_lan_tx_bytes_total[24h]))",
    "LAN Uploaded": "sum(increase(zte_lan_rx_bytes_total[24h]))",
    "WLAN rate": "sum(8 * rate(zte_wlan_rx_bytes_total[1m])) + sum(8 * rate(zte_wlan_tx_bytes_total[1m]))",
    "LAN rate": "sum(8 * rate(zte_lan_rx_bytes_total[1m])) + sum(8 * rate(zte_lan_tx_bytes_total[1m]))",
}

for name, expr in queries.items():
    res = prom_query(expr)
    if res:
        print(f"  {name}: {res[0]['value'][1]}")
    else:
        print(f"  {name}: NO DATA")

# Check how long WLAN data has existed
print("\n=== WLAN data age ===")
# Get oldest WLAN sample
url = 'http://mon.router.al:9090/api/v1/query?query=' + urllib.request.quote('min(timestamp(zte_wlan_tx_bytes_total))')
r = urllib.request.urlopen(url, timeout=10)
d = json.loads(r.read())
if d['data']['result']:
    import time
    ts = float(d['data']['result'][0]['value'][1])
    age = time.time() - ts
    print(f"  Latest sample timestamp: {ts}")
    print(f"  Age: {age:.0f}s ({age/3600:.1f}h ago)")
    
# Check how many WLAN samples exist over 24h
url2 = 'http://mon.router.al:9090/api/v1/query?query=' + urllib.request.quote('count_over_time(zte_wlan_tx_bytes_total[24h])')
r2 = urllib.request.urlopen(url2, timeout=10)
d2 = json.loads(r2.read())
if d2['data']['result']:
    for item in d2['data']['result']:
        ssid = item['metric'].get('ssid', '?')
        print(f"  {ssid}: {item['value'][1]} samples over 24h")
