#!/usr/bin/env python3
"""Prometheus exporter — full ZTE F6600P monitoring via web UI API."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar
from urllib import parse, request

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, InfoMetricFamily

LOG = logging.getLogger("zte_exporter")

ZTE_URL = os.environ.get("ZTE_URL", "http://192.168.1.1").rstrip("/")
ZTE_USERNAME = os.environ.get("ZTE_USERNAME", "root")
ZTE_PASSWORD = os.environ.get("ZTE_PASSWORD", "")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9105"))
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "5"))
WAN_NAME_FILTER = os.environ.get("WAN_NAME_FILTER", "internet")
EXPORT_CLIENTS = os.environ.get("EXPORT_CLIENTS", "false").lower() in ("1", "true", "yes")
CLIENT_REVERSE_DNS = os.environ.get("CLIENT_REVERSE_DNS", "false").lower() in ("1", "true", "yes")
CLIENT_DNS_TIMEOUT = float(os.environ.get("CLIENT_DNS_TIMEOUT", "0.8"))
CLIENT_DNS_CACHE_SECONDS = int(os.environ.get("CLIENT_DNS_CACHE_SECONDS", "300"))
STATE_FILE = os.environ.get("STATE_FILE", "/data/zte_wan_counters.json")


def _int(val: str | None, default: int = 0) -> int:
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _float(val: str | None, default: float = 0.0) -> float:
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


class _DnsCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = ttl_seconds
        self._entries: dict[str, tuple[float, str]] = {}

    def get(self, ip: str) -> str | None:
        row = self._entries.get(ip)
        if not row:
            return None
        ts, name = row
        if time.time() - ts > self.ttl:
            del self._entries[ip]
            return None
        return name

    def set(self, ip: str, name: str) -> None:
        self._entries[ip] = (time.time(), name)


_DNS_CACHE = _DnsCache(CLIENT_DNS_CACHE_SECONDS)


def _reverse_dns(ip: str, timeout: float) -> str:
    if not ip or ip in ("unknown", "0.0.0.0"):
        return ""
    cached = _DNS_CACHE.get(ip)
    if cached is not None:
        return cached
    name = ""
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(socket.gethostbyaddr, ip)
            host, _, _ = future.result(timeout=timeout)
            name = host.rstrip(".")
    except Exception:
        name = ""
    _DNS_CACHE.set(ip, name)
    return name


def _resolve_client_dns(ips: list[str]) -> dict[str, str]:
    unique = sorted({ip for ip in ips if ip})
    if not unique:
        return {}
    results: dict[str, str] = {}
    workers = min(8, len(unique))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_reverse_dns, ip, CLIENT_DNS_TIMEOUT): ip for ip in unique}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                results[ip] = future.result()
            except Exception:
                results[ip] = ""
    return results


class ZTEClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password
        self.opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))

    def _http(self, path: str, data: dict | None = None) -> str:
        url = f"{self.base_url}{path}"
        body = None
        headers: dict[str, str] = {}
        if data is not None:
            body = parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        req = request.Request(url, data=body, headers=headers, method="POST" if data else "GET")
        with self.opener.open(req, timeout=25) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def login(self) -> None:
        session = self._sess_token(self._http("/?_type=loginData&_tag=login_entry"))
        login_token = self._login_token(self._http("/?_type=loginData&_tag=login_token"))
        digest = hashlib.sha256((self.password + login_token).encode()).hexdigest()
        result = self._http(
            "/?_type=loginData&_tag=login_entry",
            {
                "action": "login",
                "Username": self.username,
                "Password": digest,
                "_sessionTOKEN": session,
            },
        )
        if '"login_need_refresh":true' not in result.replace(" ", "").lower():
            raise RuntimeError(f"login failed: {result[:300]}")
        self._http("/")

    @staticmethod
    def _sess_token(text: str) -> str:
        m = re.search(r'"sess_token"\s*:\s*"([^"]+)"', text)
        if not m:
            raise RuntimeError("no sess_token")
        return m.group(1)

    @staticmethod
    def _login_token(text: str) -> str:
        try:
            root = ET.fromstring(text)
            if root.text and root.text.strip():
                return root.text.strip()
        except ET.ParseError:
            pass
        m = re.search(r">(\d+)<", text)
        if not m:
            raise RuntimeError("no login token")
        return m.group(1)

    def fetch(self, view: str, data_tag: str, extra: str = "") -> str:
        ts = int(time.time())
        self._http(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
        q = f"&{extra}" if extra else ""
        xml = self._http(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")
        if "SessionTimeout" in xml:
            LOG.warning("SessionTimeout on %s — re-login", data_tag)
            self.login()
            ts = int(time.time())
            self._http(f"/?_type=menuView&_tag={view}&Menu3Location=0&_={ts}")
            xml = self._http(f"/?_type=menuData&_tag={data_tag}&_={ts}{q}")
        if "SessionTimeout" in xml:
            raise RuntimeError(f"SessionTimeout: {data_tag}")
        return xml

    def fetch_hidden(self, data_tag: str, extra: str = "") -> str:
        """GET hiddenData API (used for accessdev_data with DeveiceType=WLAN|ETH)."""
        ts = int(time.time())
        q = f"&{extra}" if extra else ""
        path = f"/?_type=hiddenData&_tag={data_tag}&_={ts}{q}"
        xml = self._http(path)
        if "SessionTimeout" in xml:
            LOG.warning("SessionTimeout on hidden %s — re-login", data_tag)
            self.login()
            ts = int(time.time())
            path = f"/?_type=hiddenData&_tag={data_tag}&_={ts}{q}"
            xml = self._http(path)
        if "SessionTimeout" in xml:
            raise RuntimeError(f"SessionTimeout: hidden {data_tag}")
        return xml

    @staticmethod
    def parse_instances(xml_text: str, obj_id: str | None = None) -> list[dict[str, str]]:
        rows = ZTEClient._parse_instances_et(xml_text, obj_id)
        if rows:
            return rows
        return ZTEClient._parse_instances_regex(xml_text, obj_id)

    @staticmethod
    def _parse_instances_et(xml_text: str, obj_id: str | None) -> list[dict[str, str]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        if obj_id:
            instances: list[ET.Element] = []
            for parent in root.iter(obj_id):
                instances.extend(parent.findall("Instance"))
            if not instances:
                instances = root.findall(".//Instance")
        else:
            instances = root.findall(".//Instance")
        rows: list[dict[str, str]] = []
        for inst in instances:
            row: dict[str, str] = {}
            children = list(inst)
            i = 0
            while i < len(children):
                child = children[i]
                if child.tag == "ParaName" and child.text:
                    name = child.text.strip()
                    val = ""
                    if i + 1 < len(children) and children[i + 1].tag == "ParaValue":
                        val = (children[i + 1].text or "").strip()
                        i += 2
                    else:
                        i += 1
                    row[name] = val
                else:
                    i += 1
            if row:
                rows.append(row)
        return rows

    @staticmethod
    def _parse_instances_regex(xml_text: str, obj_id: str | None) -> list[dict[str, str]]:
        if obj_id:
            m = re.search(
                rf"<{re.escape(obj_id)}>(.*?)</{re.escape(obj_id)}>",
                xml_text,
                re.DOTALL | re.IGNORECASE,
            )
            if m:
                xml_text = m.group(1)
        rows: list[dict[str, str]] = []
        for block in re.findall(r"<Instance>(.*?)</Instance>", xml_text, re.DOTALL):
            names = re.findall(r"<ParaName>([^<]+)</ParaName>", block)
            raw_values = re.findall(
                r"<ParaValue>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</ParaValue>",
                block,
                re.DOTALL,
            )
            values = [(a or b).strip() for a, b in raw_values]
            if names:
                rows.append(dict(zip(names, values)))
        return rows

    @staticmethod
    def parse_flat(xml_text: str) -> dict[str, str]:
        names = re.findall(r"<ParaName>([^<]+)</ParaName>", xml_text)
        values = re.findall(r"<ParaValue>([^<]*)</ParaValue>", xml_text)
        out: dict[str, str] = {}
        for n, v in zip(names, values):
            out[n] = v
        return out


class WanByteTracker:
    """Track modem WAN byte counters across device reboots (raw counters reset to 0)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._keys: dict[str, dict[str, int]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data.get("keys"), dict):
                self._keys = {k: dict(v) for k, v in data["keys"].items()}
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            LOG.warning("could not load counter state %s: %s", self.path, exc)

    def _save(self) -> None:
        if not self.path:
            return
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = json.dumps({"keys": self._keys}, indent=2)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, self.path)

    def observe(self, key: str, rx_raw: int, tx_raw: int) -> tuple[int, int, int, float, float]:
        """Return cumulative totals, reset count, and modem-derived rx/tx bit rates."""
        entry = self._keys.setdefault(
            key,
            {"rx_offset": 0, "tx_offset": 0, "rx_last": None, "tx_last": None,
             "last_ts": None, "resets_total": 0},
        )
        resets = 0
        now = time.time()
        prev_ts = entry.get("last_ts")
        rates_bps: dict[str, float] = {"rx": 0.0, "tx": 0.0}
        for field, raw in (("rx", rx_raw), ("tx", tx_raw)):
            last_key = f"{field}_last"
            offset_key = f"{field}_offset"
            last = entry.get(last_key)
            if last is not None and raw < int(last):
                # Counter reset (modem reboot) — add previous high-water mark
                # to offset and emit zero rate for this interval to avoid spike.
                entry[offset_key] = entry.get(offset_key, 0) + int(last)
                resets += 1
                rates_bps[field] = 0.0
                LOG.info(
                    "WAN %s %s counter reset (modem reboot?): %s -> %s, offset now %s",
                    key,
                    field,
                    last,
                    raw,
                    entry[offset_key],
                )
            elif last is not None and prev_ts is not None and now > float(prev_ts):
                delta = raw - int(last)
                rates_bps[field] = max(0.0, (float(delta) * 8.0) / (now - float(prev_ts)))
            entry[last_key] = raw
        entry["last_ts"] = now
        entry["resets_total"] = entry.get("resets_total", 0) + resets
        cumulative_rx = entry["rx_offset"] + rx_raw
        cumulative_tx = entry["tx_offset"] + tx_raw
        self._save()
        return cumulative_rx, cumulative_tx, entry["resets_total"], rates_bps["rx"], rates_bps["tx"]


class ZTECollector:
    def __init__(self, client: ZTEClient, interval: int) -> None:
        self.client = client
        self.interval = interval
        self.wan_tracker = WanByteTracker(STATE_FILE)
        self.last_error: str | None = None
        self._last_scrape = 0.0
        self._cached: list = []

    def _scrape(self) -> list:
        metrics: list = []
        scrape_ok = GaugeMetricFamily(
            "zte_scrape_success",
            "1 if subsystem scrape succeeded",
            labels=["subsystem"],
        )
        wan_ok = False

        # --- WAN / Internet ---
        try:
            xml = self.client.fetch("ethWanConfig", "wan_internet_lua.lua", "TypeUplink=2&pageType=0")
            for inst in self.client.parse_instances(xml):
                name = inst.get("WANCName", "")
                if WAN_NAME_FILTER and name.lower() != WAN_NAME_FILTER.lower():
                    continue
                # Skip instances where byte counters are absent or zero-string;
                # but do NOT call _int() yet — we need to distinguish "missing"
                # from genuine "0" to avoid false counter-reset detection.
                rx_str = (inst.get("RxBytes") or "").strip()
                tx_str = (inst.get("TxBytes") or "").strip()
                if not rx_str and not tx_str:
                    continue
                labels = [name, inst.get("TransType") or inst.get("wantype", "unknown")]
                rx_raw = _int(rx_str)
                tx_raw = _int(tx_str)
                key = f"{labels[0]}|{labels[1]}"
                cumulative_rx, cumulative_tx, resets, rx_bps, tx_bps = self.wan_tracker.observe(key, rx_raw, tx_raw)

                metrics.append(self._gauge_labeled(
                    "zte_wan_modem_rx_bytes",
                    "Raw download bytes on modem (resets on reboot)",
                    labels,
                    float(rx_raw),
                ))
                metrics.append(self._gauge_labeled(
                    "zte_wan_modem_tx_bytes",
                    "Raw upload bytes on modem (resets on reboot)",
                    labels,
                    float(tx_raw),
                ))
                metrics.append(self._counter_value(
                    "zte_wan_rx_bytes_total",
                    "Monotonic WAN download bytes (survives modem reboot)",
                    labels,
                    cumulative_rx,
                ))
                metrics.append(self._counter_value(
                    "zte_wan_tx_bytes_total",
                    "Monotonic WAN upload bytes (survives modem reboot)",
                    labels,
                    cumulative_tx,
                ))
                metrics.append(self._gauge_labeled(
                    "zte_wan_rx_bps",
                    "Modem-derived WAN download rate in bits per second",
                    labels,
                    rx_bps,
                ))
                metrics.append(self._gauge_labeled(
                    "zte_wan_tx_bps",
                    "Modem-derived WAN upload rate in bits per second",
                    labels,
                    tx_bps,
                ))
                resets_metric = CounterMetricFamily(
                    "zte_wan_counter_resets_total",
                    "Modem WAN byte counter resets detected",
                    labels=["connection", "type"],
                )
                resets_metric.add_metric(labels, resets)
                metrics.append(resets_metric)
                for prom, field, help_ in (
                    ("zte_wan_rx_packets_total", "RxPackets", "WAN download packets"),
                    ("zte_wan_tx_packets_total", "TxPackets", "WAN upload packets"),
                    ("zte_wan_errors_received_total", "ErrorsReceived", "WAN receive errors"),
                    ("zte_wan_errors_sent_total", "ErrorsSent", "WAN send errors"),
                    ("zte_wan_multicast_rx_total", "MulticastPacketsReceived", "WAN multicast received"),
                    ("zte_wan_multicast_tx_total", "MulticastPacketsSent", "WAN multicast sent"),
                ):
                    if inst.get(field):
                        metrics.append(self._counter(prom, help_, labels, field, inst))
                wan_ok = True
                LOG.info("WAN %s rx=%s tx=%s", name, inst.get("RxBytes"), inst.get("TxBytes"))
                break
            if not wan_ok:
                raise RuntimeError("no WAN internet instance")
            scrape_ok.add_metric(["wan"], 1)
        except Exception as exc:
            LOG.warning("WAN scrape failed: %s", exc)
            scrape_ok.add_metric(["wan"], 0)
            self.last_error = str(exc)

        # --- Optical / PON ---
        try:
            xml = self.client.fetch("ponopticalinfo", "optical_info_lua.lua")
            p = self.client.parse_flat(xml)
            metrics.extend([
                self._gauge("zte_pon_rx_power_dbm", "PON receive power dBm", [], _float(p.get("RxPower"))),
                self._gauge("zte_pon_tx_power_dbm", "PON transmit power dBm", [], _float(p.get("TxPower"))),
                self._gauge("zte_pon_temperature_celsius", "PON module temperature", [], _float(p.get("Temp"))),
                self._gauge("zte_pon_voltage_mv", "PON module voltage mV", [], _float(p.get("Volt"))),
                self._gauge("zte_pon_bias_current_ma", "PON bias current mA", [], _float(p.get("Current"))),
                self._gauge("zte_pon_los", "PON loss of signal (1=LOS)", [], _float(p.get("LosInfo"))),
                self._gauge("zte_pon_gpon_reg_status", "GPON registration status code", [], _float(p.get("RegStatus"))),
                self._gauge("zte_pon_catv_enabled", "CATV enabled on PON", [], _float(p.get("CatvEnable"))),
            ])
            if p.get("PONOnTime"):
                metrics.append(self._gauge("zte_pon_uptime_seconds", "PON uptime seconds", [], _float(p.get("PONOnTime"))))
            if p.get("VideoRxPower"):
                metrics.append(self._gauge("zte_pon_video_rx_power", "CATV video RX power", [], _float(p.get("VideoRxPower"))))
            if p.get("RFTxPower"):
                metrics.append(self._gauge("zte_pon_rf_tx_power", "CATV RF TX power", [], _float(p.get("RFTxPower"))))
            scrape_ok.add_metric(["optical"], 1)
        except Exception as exc:
            LOG.warning("optical scrape failed: %s", exc)
            scrape_ok.add_metric(["optical"], 0)

        # --- System / device ---
        try:
            xml = self.client.fetch("statusMgr", "devmgr_statusmgr_lua.lua")
            p = self.client.parse_flat(xml)
            for i in range(1, 5):
                key = f"CpuUsage{i}"
                if key in p:
                    metrics.append(self._gauge(
                        "zte_cpu_usage_percent", "CPU usage percent",
                        [str(i)], _float(p[key]),
                    ))
            if "MemUsage" in p:
                metrics.append(self._gauge("zte_memory_usage_percent", "Memory usage percent", [], _float(p["MemUsage"])))
            if "PowerOnTime" in p:
                metrics.append(self._gauge("zte_modem_uptime_seconds", "Modem uptime seconds", [], _float(p["PowerOnTime"])))
            if "Temp" in p:
                metrics.append(self._gauge("zte_modem_temperature_celsius", "Modem SoC temperature", [], _float(p["Temp"])))
            if "Flash_Percent_Used" in p:
                metrics.append(self._gauge("zte_flash_usage_percent", "Flash storage usage percent", [], _float(p["Flash_Percent_Used"])))
            if "TotalFlash" in p:
                metrics.append(self._gauge("zte_flash_total_bytes", "Total flash storage bytes", [], _float(p["TotalFlash"])))
            info_labels = {
                k: p[v] for k, v in (
                    ("model", "ModelName"), ("serial", "SerialNumber"),
                    ("software", "SoftwareVer"), ("hardware", "HardwareVer"),
                    ("manufacturer", "ManuFacturer"),
                ) if p.get(v)
            }
            if info_labels:
                info = InfoMetricFamily("zte_modem_info", "Modem identity")
                info.add_metric([], info_labels)
                metrics.append(info)
            scrape_ok.add_metric(["system"], 1)
        except Exception as exc:
            LOG.warning("system scrape failed: %s", exc)
            scrape_ok.add_metric(["system"], 0)

        # --- LAN ports ---
        try:
            xml = self.client.fetch("localNetStatus", "status_lan_info_lua.lua")
            for inst in self.client.parse_instances(xml):
                port = inst.get("_InstID", "unknown")
                labels = [port]
                for prom, field, help_ in (
                    ("zte_lan_rx_bytes_total", "InBytes", "LAN port bytes received"),
                    ("zte_lan_tx_bytes_total", "OutBytes", "LAN port bytes sent"),
                    ("zte_lan_rx_packets_total", "InPkts", "LAN port packets received"),
                    ("zte_lan_tx_packets_total", "OutPkts", "LAN port packets sent"),
                    ("zte_lan_rx_errors_total", "InError", "LAN port receive errors"),
                    ("zte_lan_tx_errors_total", "OutError", "LAN port send errors"),
                    ("zte_lan_rx_discards_total", "InDiscard", "LAN port receive discards"),
                    ("zte_lan_tx_discards_total", "OutDiscard", "LAN port send discards"),
                ):
                    if inst.get(field):
                        metrics.append(self._counter(prom, help_, labels, field, inst))
                metrics.append(self._gauge("zte_lan_link_up", "LAN link up (1=up)", labels, 1.0 if inst.get("Status") == "0" else 0.0))
                metrics.append(self._gauge("zte_lan_speed_mbps", "LAN negotiated speed Mbps", labels, _float(inst.get("Speed"))))
            scrape_ok.add_metric(["lan"], 1)
        except Exception as exc:
            LOG.warning("LAN scrape failed: %s", exc)
            scrape_ok.add_metric(["lan"], 0)

        # --- WLAN interface traffic ---
        try:
            xml = self.client.fetch("localNetStatus", "wlan_wlanstatus_lua.lua")
            # Build SSID alias→name map from instances without traffic data
            ssid_names: dict[str, str] = {}
            for inst in self.client.parse_instances(xml):
                inst_id = inst.get("_InstID", "")
                essid = inst.get("ESSID", "")
                if essid and not inst.get("TotalBytesReceived"):
                    ssid_names[inst_id] = essid
            # Emit metrics for instances WITH traffic counters
            for inst in self.client.parse_instances(xml):
                if not inst.get("TotalBytesReceived") and not inst.get("TotalBytesSent"):
                    continue
                inst_id = inst.get("_InstID", "unknown")
                ssid = ssid_names.get(inst_id, inst.get("Alias", inst_id))
                band = inst.get("BandWidthInUsed", "")
                radio = inst.get("WLANViewName", "")
                labels = [inst_id, ssid, radio]
                label_names = ["interface", "ssid", "radio"]
                for prom, field, help_ in (
                    ("zte_wlan_rx_bytes_total", "TotalBytesReceived", "WLAN interface bytes received"),
                    ("zte_wlan_tx_bytes_total", "TotalBytesSent", "WLAN interface bytes sent"),
                    ("zte_wlan_rx_packets_total", "TotalPacketsReceived", "WLAN interface packets received"),
                    ("zte_wlan_tx_packets_total", "TotalPacketsSent", "WLAN interface packets sent"),
                ):
                    val = _int(inst.get(field))
                    c = CounterMetricFamily(prom, help_, labels=label_names)
                    c.add_metric(labels, val)
                    metrics.append(c)
                # Channel and bandwidth as info
                if inst.get("ChannelInUsed"):
                    g = GaugeMetricFamily("zte_wlan_channel", "WLAN channel in use", labels=label_names)
                    g.add_metric(labels, _float(inst.get("ChannelInUsed")))
                    metrics.append(g)
            scrape_ok.add_metric(["wlan"], 1)
        except Exception as exc:
            LOG.warning("WLAN interface scrape failed: %s", exc)
            scrape_ok.add_metric(["wlan"], 0)

        # --- WLAN client stats ---
        try:
            xml = self.client.fetch("localNetStatus", "wlan_client_stat_lua.lua")
            for inst in self.client.parse_instances(xml):
                if not inst.get("MACAddress"):
                    continue
                mac = ZTECollector._norm_mac(inst.get("MACAddress", ""))
                if not mac:
                    continue
                ip = inst.get("IPAddress", "")
                ap = inst.get("AliasName", inst.get("_InstID", "unknown"))
                labels = [mac, ip, ap]
                label_names = ["mac", "ip", "interface"]
                for prom, field, help_ in (
                    ("zte_wlan_client_rx_bytes_total", "RXBytes", "WLAN client bytes received"),
                    ("zte_wlan_client_tx_bytes_total", "TXBytes", "WLAN client bytes sent"),
                    ("zte_wlan_client_rx_packets_total", "RXPackets", "WLAN client packets received"),
                    ("zte_wlan_client_tx_packets_total", "TXPackets", "WLAN client packets sent"),
                ):
                    val = _int(inst.get(field))
                    c = CounterMetricFamily(prom, help_, labels=label_names)
                    c.add_metric(labels, val)
                    metrics.append(c)
                # Signal quality gauges
                for prom, field, help_ in (
                    ("zte_wlan_client_rssi_dbm", "RSSI", "WLAN client signal strength dBm"),
                    ("zte_wlan_client_snr_db", "SNR", "WLAN client signal-to-noise ratio dB"),
                    ("zte_wlan_client_noise_dbm", "NOISE", "WLAN client noise floor dBm"),
                    ("zte_wlan_client_tx_rate_kbps", "TxRate", "WLAN client TX rate kbps"),
                    ("zte_wlan_client_rx_rate_kbps", "RxRate", "WLAN client RX rate kbps"),
                    ("zte_wlan_client_link_time_seconds", "LinkTime", "WLAN client connected time seconds"),
                ):
                    val = inst.get(field)
                    if val:
                        g = GaugeMetricFamily(prom, help_, labels=label_names)
                        g.add_metric(labels, _float(val))
                        metrics.append(g)
            scrape_ok.add_metric(["wlan_clients"], 1)
        except Exception as exc:
            LOG.warning("WLAN client stats scrape failed: %s", exc)
            scrape_ok.add_metric(["wlan_clients"], 0)

        # --- VoIP ---
        try:
            xml = self.client.fetch("voipStatus", "voipRegStatus_lua.lua")
            for inst in self.client.parse_instances(xml):
                line = inst.get("DirectoryNumber") or inst.get("_InstID", "unknown")
                up = 1.0 if inst.get("IsOnline", "").lower() in ("1", "true", "yes", "online") else 0.0
                metrics.append(self._gauge("zte_voip_line_up", "VoIP line registered", [line], up))
            scrape_ok.add_metric(["voip"], 1)
        except Exception as exc:
            LOG.warning("VoIP scrape failed: %s", exc)
            scrape_ok.add_metric(["voip"], 0)

        # --- Connected clients (WLAN/ETH via hiddenData; homepage has IP/MAC details) ---
        try:
            wlan_xml = self.client.fetch_hidden("accessdev_data", "DeveiceType=WLAN")
            eth_xml = self.client.fetch_hidden("accessdev_data", "DeveiceType=ETH")
            home_xml = self.client.fetch("homePage", "accessdev_homepage_lua.lua")
            wlan_rows = self._client_rows(
                self.client.parse_instances(wlan_xml, "OBJ_ACCESSDEV_ID"), "wlan",
            )
            eth_rows = self._client_rows(
                self.client.parse_instances(eth_xml, "OBJ_ACCESSDEV_ID"), "eth",
            )
            home_rows = self._client_rows(
                self.client.parse_instances(home_xml, "OBJ_ACCESSDEV_ID"), "",
            )
            merged = self._merge_client_sources(home_rows, wlan_rows, eth_rows)
            metrics.append(self._gauge("zte_wlan_clients", "WiFi clients count", [], float(len(wlan_rows))))
            metrics.append(self._gauge("zte_eth_clients", "Ethernet clients count", [], float(len(eth_rows))))
            metrics.append(self._gauge("zte_lan_clients", "Connected devices count", [], float(len(merged))))
            if EXPORT_CLIENTS:
                metrics.extend(self._client_info_metrics(merged))
            scrape_ok.add_metric(["clients"], 1)
            LOG.info(
                "clients wlan=%s eth=%s home=%s exported=%s",
                len(wlan_rows), len(eth_rows), len(home_rows), len(merged),
            )
        except Exception as exc:
            LOG.warning("clients scrape failed: %s", exc)
            scrape_ok.add_metric(["clients"], 0)

        metrics.append(scrape_ok)
        up = GaugeMetricFamily("zte_exporter_up", "1 if primary WAN scrape succeeded")
        up.add_metric([], 1 if wan_ok else 0)
        metrics.append(up)
        if wan_ok:
            self.last_error = None
        return metrics

    @staticmethod
    def _pick(inst: dict[str, str], *keys: str) -> str:
        for key in keys:
            val = inst.get(key)
            if val and str(val).strip():
                return str(val).strip()
        lower = {k.lower(): v for k, v in inst.items()}
        for key in keys:
            val = lower.get(key.lower())
            if val and str(val).strip():
                return str(val).strip()
        return ""

    @staticmethod
    def _looks_like_mac(value: str) -> bool:
        return bool(re.match(r"^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$", value or ""))

    @staticmethod
    def _norm_mac(value: str) -> str:
        raw = (value or "").strip().lower().replace("-", ":")
        if not ZTECollector._looks_like_mac(raw):
            return ""
        parts = re.split(r"[:]", raw)
        # Uppercase to match SNMP bridge MIB (dot1dTpFdbAddress) for joins in Grafana/PromQL.
        return ":".join(p.zfill(2) for p in parts).upper()

    @staticmethod
    def _client_rows(instances: list[dict[str, str]], access: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for idx, inst in enumerate(instances):
            mac = ZTECollector._pick(inst, "MACAddress", "MacAddr", "Mac", "PhysAddress", "MAC")
            ip = ZTECollector._pick(inst, "IPAddress", "IpAddress", "IP", "ClientIP")
            if not mac or not ip:
                for key, val in inst.items():
                    if not val:
                        continue
                    kl = key.lower()
                    if not mac and "mac" in kl:
                        mac = val.strip()
                    if not ip and "ip" in kl and "type" not in kl:
                        ip = val.strip()
            mac = ZTECollector._norm_mac(mac)
            row = {
                "mac": mac or "unknown",
                "ip": ip,
                "modem_hostname": ZTECollector._pick(inst, "HostName", "Hostname", "DevName"),
                "interface": ZTECollector._pick(inst, "Interface", "InterfaceType", "IfName"),
                "access": access,
                "inst_id": inst.get("_InstID", ""),
                "_index": str(idx),
            }
            rows.append(row)
        if rows and not any(r["ip"] or r["mac"] != "unknown" for r in rows):
            LOG.warning("accessdev instances have no IP/MAC; sample keys=%s", sorted(instances[0]))
        return rows

    @staticmethod
    def _client_key(row: dict[str, str]) -> str:
        mac = row.get("mac", "")
        if mac and mac != "unknown":
            return f"mac:{mac}"
        ip = row.get("ip", "")
        if ip:
            return f"ip:{ip}"
        inst_id = row.get("inst_id", "")
        if inst_id:
            return f"inst:{inst_id}"
        idx = row.get("_index", "")
        if idx:
            return f"{row.get('access', 'dev')}:idx:{idx}"
        return ""

    @staticmethod
    def _merge_client_sources(
        home_rows: list[dict[str, str]],
        wlan_rows: list[dict[str, str]],
        eth_rows: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        by_key: dict[str, dict[str, str]] = {}

        def put(row: dict[str, str], *, access: str | None = None) -> None:
            key = ZTECollector._client_key(row)
            if not key:
                return
            existing = by_key.get(key)
            if existing is None:
                merged = dict(row)
                if access:
                    merged["access"] = access
                by_key[key] = merged
                return
            for field in ("ip", "modem_hostname", "interface", "mac", "inst_id"):
                if row.get(field) and (
                    field != "mac" or row[field] != "unknown" or existing.get("mac") in ("", "unknown")
                ):
                    existing[field] = row[field]
            if access:
                existing["access"] = access

        for row in home_rows:
            put(row)
        for row in eth_rows:
            put(row, access="eth")
        for row in wlan_rows:
            put(row, access="wlan")

        out = [r for r in by_key.values() if r.get("access") in ("wlan", "eth")]
        if not out:
            out = list(by_key.values())
        return out

    def _client_info_metrics(self, rows: list[dict[str, str]]) -> list:
        dns_names: dict[str, str] = {}
        if CLIENT_REVERSE_DNS:
            dns_names = _resolve_client_dns([r["ip"] for r in rows if r.get("ip")])
        info = InfoMetricFamily("zte_client_info", "Connected device")
        seen: set[tuple[str, ...]] = set()
        for row in rows:
            dns_name = dns_names.get(row["ip"], "")
            hostname = row["modem_hostname"] or dns_name
            labels = {
                "mac": row["mac"],
                "hostname": hostname,
                "dns_name": dns_name,
                "modem_hostname": row["modem_hostname"],
                "ip": row["ip"],
                "interface": row["interface"],
                "access": row.get("access", ""),
            }
            key = tuple(labels.items())
            if key in seen:
                continue
            seen.add(key)
            info.add_metric([], labels)
        return [info]

    @staticmethod
    def _counter_value(
        name: str, help_: str, labels: list[str], value: int,
    ) -> CounterMetricFamily:
        c = CounterMetricFamily(name, help_, labels=["connection", "type"])
        c.add_metric(labels, value)
        return c

    @staticmethod
    def _gauge_labeled(name: str, help_: str, labels: list[str], value: float) -> GaugeMetricFamily:
        g = GaugeMetricFamily(name, help_, labels=["connection", "type"])
        g.add_metric(labels, value)
        return g

    @staticmethod
    def _counter(name: str, help_: str, labels: list[str], field: str, inst: dict[str, str]) -> CounterMetricFamily:
        label_names = ["connection", "type"] if len(labels) == 2 else ["port"]
        if len(labels) == 2:
            c = CounterMetricFamily(name, help_, labels=label_names)
        elif name.startswith("zte_lan"):
            c = CounterMetricFamily(name, help_, labels=["port"])
        else:
            c = CounterMetricFamily(name, help_, labels=label_names)
        c.add_metric(labels, _int(inst.get(field)))
        return c

    @staticmethod
    def _gauge(name: str, help_: str, labels: list[str], value: float) -> GaugeMetricFamily:
        g = GaugeMetricFamily(name, help_, labels=["port"] if labels and name.startswith("zte_lan") else (
            ["core"] if labels and name.startswith("zte_cpu") else (
                ["line"] if labels and name.startswith("zte_voip") else []
            )
        ))
        if not labels:
            g.add_metric([], value)
        else:
            g.add_metric(labels, value)
        return g

    def collect(self):
        now = time.time()
        if now - self._last_scrape >= self.interval or not self._cached:
            self._cached = self._scrape()
            self._last_scrape = now
        yield from self._cached


class ScrapeState:
    def __init__(self, client: ZTEClient, interval: int) -> None:
        self.registry = CollectorRegistry()
        self.collector = ZTECollector(client, interval)
        self.registry.register(self.collector)


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    state: ScrapeState = environ["zte.state"]

    if path == "/health":
        body = b"ok" if state.collector.last_error is None else b"degraded"
        code = "200 OK" if state.collector.last_error is None else "503 Service Unavailable"
        start_response(code, [("Content-Type", "text/plain")])
        return [body]

    if path not in ("/", "/metrics"):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    body = generate_latest(state.registry)
    start_response("200 OK", [("Content-Type", CONTENT_TYPE_LATEST)])
    return [body]


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not ZTE_PASSWORD:
        raise SystemExit("ZTE_PASSWORD is required")

    client = ZTEClient(ZTE_URL, ZTE_USERNAME, ZTE_PASSWORD)
    client.login()
    LOG.info("logged in to %s as %s", ZTE_URL, ZTE_USERNAME)

    state = ScrapeState(client, SCRAPE_INTERVAL)

    def wrapper(environ, start_response):
        environ["zte.state"] = state
        return app(environ, start_response)

    from wsgiref.simple_server import make_server

    httpd = make_server(LISTEN_HOST, LISTEN_PORT, wrapper)
    LOG.info("listening on %s:%s (full monitoring)", LISTEN_HOST, LISTEN_PORT)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
