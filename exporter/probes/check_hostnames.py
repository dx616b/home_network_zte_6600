"""Query Prometheus to see what hostnames are in zte_client_info_info."""
import urllib.request, json

PROM = "http://mon.router.al:9090"

# Get all client info metrics
url = f"{PROM}/api/v1/query?query=zte_client_info_info"
resp = json.loads(urllib.request.urlopen(url, timeout=10).read())

results = resp["data"]["result"]
print(f"Total client_info series: {len(results)}\n")
print(f"{'IP':<18} {'MAC':<20} {'Hostname':<25} {'DNS name':<25} {'Modem hostname':<20} {'Access'}")
print("-" * 135)
for r in sorted(results, key=lambda x: x["metric"].get("ip", "")):
    m = r["metric"]
    ip = m.get("ip", "")
    # Sort by IP numerically
    print(f"{ip:<18} {m.get('mac', ''):<20} {m.get('hostname', ''):<25} {m.get('dns_name', ''):<25} {m.get('modem_hostname', ''):<20} {m.get('access', '')}")
