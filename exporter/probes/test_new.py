#!/usr/bin/env python3
"""Quick test of the exporter with new metrics."""
import os, sys
os.environ['ZTE_PASSWORD'] = 'ZTEEQL4Q5C03281'
os.environ['STATE_FILE'] = 'test_state.json'
sys.path.insert(0, os.path.dirname(__file__))
from zte_exporter import ZTEClient, ZTECollector

client = ZTEClient('http://192.168.1.1', 'root', 'ZTEEQL4Q5C03281')
client.login()
print('Login OK')
collector = ZTECollector(client, 5)
metrics = collector._scrape()

print(f'\nTotal metric families: {len(metrics)}')

# Show new metrics
print('\n--- New system metrics ---')
for m in metrics:
    name = getattr(m, 'name', '')
    if any(kw in name for kw in ['temperature', 'flash', 'temp']):
        for sample in m.samples:
            print(f'  {sample.name} = {sample.value}')

# Scrape success
print('\n--- Scrape success ---')
for m in metrics:
    if getattr(m, 'name', '') == 'zte_scrape_success':
        for s in m.samples:
            sub = s.labels.get('subsystem', '?')
            print(f'  {sub}: {s.value}')

# Count samples
total_samples = sum(len(m.samples) for m in metrics)
print(f'\nTotal samples: {total_samples}')
