#!/usr/bin/env python3
"""Quick test: import and run one scrape to verify new WLAN metrics."""
import os, sys
os.environ.setdefault("ZTE_URL", "http://192.168.1.1")
os.environ.setdefault("ZTE_USERNAME", "root")
os.environ.setdefault("ZTE_PASSWORD", os.environ.get("ZTE_PASSWORD", ""))
os.environ.setdefault("STATE_FILE", "")  # disable state file
os.environ.setdefault("WAN_NAME_FILTER", "internet")

from zte_exporter import ZTEClient, ZTECollector, SCRAPE_INTERVAL
import logging
logging.basicConfig(level="DEBUG")

client = ZTEClient("http://192.168.1.1", "root", os.environ["ZTE_PASSWORD"])
client.login()
print("Logged in\n")

collector = ZTECollector(client, SCRAPE_INTERVAL)
metrics = list(collector.collect())

print(f"\n{'='*70}")
print(f"Total metrics: {len(metrics)}")
print(f"{'='*70}")

# Filter and display WLAN metrics
for m in metrics:
    name = m.name if hasattr(m, 'name') else str(m)
    if 'wlan' in name.lower() and name != 'zte_scrape_success':
        for sample in m.samples:
            print(f"  {sample.name}{sample.labels} = {sample.value}")

# Also show scrape_success
for m in metrics:
    if hasattr(m, 'name') and m.name == 'zte_scrape_success':
        for sample in m.samples:
            print(f"  {sample.name}{sample.labels} = {sample.value}")
