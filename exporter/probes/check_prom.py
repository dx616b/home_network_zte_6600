import urllib.request, json

def prom_query(expr):
    url = f'http://mon.router.al:9090/api/v1/query?query={urllib.request.quote(expr)}'
    r = urllib.request.urlopen(url, timeout=10)
    return json.loads(r.read())['data']['result']

print("=== zte_exporter_up ===")
for r in prom_query('zte_exporter_up'):
    print(f"  value={r['value'][1]}  labels={r['metric']}")

print("\n=== zte_scrape_success ===")
for r in prom_query('zte_scrape_success'):
    sub = r['metric'].get('subsystem', '?')
    print(f"  {sub}: {r['value'][1]}")

print("\n=== WLAN metrics ===")
for metric in ['zte_wlan_tx_bytes_total', 'zte_wlan_rx_bytes_total', 'zte_wlan_clients']:
    res = prom_query(metric)
    if res:
        print(f"  {metric}: {len(res)} series, sample={res[0]['value'][1]}")
    else:
        print(f"  {metric}: NO DATA")

print("\n=== LAN metrics ===")
for metric in ['zte_lan_tx_bytes_total', 'zte_lan_rx_bytes_total']:
    res = prom_query(metric)
    if res:
        for r in res:
            port = r['metric'].get('port', '?')
            print(f"  {metric} port={port}: {r['value'][1]}")
    else:
        print(f"  {metric}: NO DATA")

print("\n=== New system metrics ===")
for metric in ['zte_modem_temperature_celsius', 'zte_flash_usage_percent']:
    res = prom_query(metric)
    if res:
        print(f"  {metric}: {res[0]['value'][1]}")
    else:
        print(f"  {metric}: NO DATA")
