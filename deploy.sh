#!/usr/bin/env bash
# Run on mon.router.al (same LAN as the ZTE modem)
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Edit .env (ZTE_PASSWORD) then re-run."
  exit 1
fi

docker compose build
docker compose up -d

echo "ZTE exporter:  http://mon.router.al:9105/metrics"
echo "SNMP exporter: http://mon.router.al:9116/snmp?target=192.168.1.254&module=if_mib"
echo "Prometheus: add prometheus/zte-f6600p-scrape.yml and prometheus/switch-snmp-scrape.yml, then reload."
echo "SNMP bridge module: prometheus/snmp-bridge-mib.yml is mounted into snmp-exporter (restart after pull)."
echo "Grafana: import grafana/home-network.json, grafana/switch-main.json"
