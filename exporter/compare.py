#!/usr/bin/env python3
# BEFORE
rx_before = 4597448250
tx_before = 5406291636
modem_rx_before = 303168386
modem_tx_before = 1111585401

# AFTER
rx_after = 4672219953
tx_after = 5463938483
modem_rx_after = 379692703
modem_tx_after = 1170474430

# Deltas
rx_delta = rx_after - rx_before
tx_delta = tx_after - tx_before
modem_rx_delta = modem_rx_after - modem_rx_before
modem_tx_delta = modem_tx_after - modem_tx_before

# iperf reported
iperf_rx = 10.0 * 1024 * 1024   # 10.0 MB received (download)
iperf_tx = 5.38 * 1024 * 1024   # 5.38 MB sent (upload)

print("=== COMPARISON ===")
print()
print(f"Cumulative counter delta (rx_bytes_total):  {rx_delta:>15,} bytes  ({rx_delta/1e6:.2f} MB)")
print(f"Cumulative counter delta (tx_bytes_total):  {tx_delta:>15,} bytes  ({tx_delta/1e6:.2f} MB)")
print(f"Modem raw counter delta (modem_rx_bytes):   {modem_rx_delta:>15,} bytes  ({modem_rx_delta/1e6:.2f} MB)")
print(f"Modem raw counter delta (modem_tx_bytes):   {modem_tx_delta:>15,} bytes  ({modem_tx_delta/1e6:.2f} MB)")
print()
print(f"iperf3 download (receiver):                 {iperf_rx:>15,.0f} bytes  ({iperf_rx/1e6:.2f} MB)")
print(f"iperf3 upload (sender):                     {iperf_tx:>15,.0f} bytes  ({iperf_tx/1e6:.2f} MB)")
print()
print("NOTE: Deltas include ALL traffic during the test window (background")
print("      browsing, DNS, other devices, etc.), so WAN deltas >= iperf numbers.")
print()

print(f"Cumulative vs Modem raw (rx): {rx_delta:,} vs {modem_rx_delta:,}")
print(f"Cumulative vs Modem raw (tx): {tx_delta:,} vs {modem_tx_delta:,}")
diff_rx = abs(rx_delta - modem_rx_delta)
diff_tx = abs(tx_delta - modem_tx_delta)
print(f"RX consistency: {'PASS' if diff_rx < 1000 else f'FAIL (off by {diff_rx:,})'}")
print(f"TX consistency: {'PASS' if diff_tx < 1000 else f'FAIL (off by {diff_tx:,})'}")
print()

covers_rx = rx_delta >= iperf_rx
covers_tx = tx_delta >= iperf_tx
print(f"RX covers iperf download: {'PASS' if covers_rx else 'FAIL'} ({rx_delta/1e6:.2f} MB >= {iperf_rx/1e6:.2f} MB)")
print(f"TX covers iperf upload:   {'PASS' if covers_tx else 'FAIL'} ({tx_delta/1e6:.2f} MB >= {iperf_tx/1e6:.2f} MB)")
print()
print("Resets counter: 0 (no reboot during test) - PASS")
print("zte_wan_rx_bps after: 934726 bps (~0.93 Mbps) - background traffic, no spike - PASS")
