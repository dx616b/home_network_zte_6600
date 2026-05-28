#!/usr/bin/env python3
"""Tests for WanByteTracker data correctness fixes."""
import json
import os
import shutil
import tempfile
import time

# Monkey-patch time.time before importing the module
_fake_time = [1000.0]
_orig_time = time.time
time.time = lambda: _fake_time[0]

import zte_exporter

def run_tests():
    tmpdir = tempfile.mkdtemp()
    state_file = os.path.join(tmpdir, "test_state.json")
    tracker = zte_exporter.WanByteTracker(state_file)
    passed = 0

    # Test 1: First observation — no previous state
    rx, tx, resets, rx_bps, tx_bps = tracker.observe("wan", 1000, 500)
    assert rx == 1000 and tx == 500, f"totals: {rx},{tx}"
    assert resets == 0, f"resets: {resets}"
    assert rx_bps == 0.0 and tx_bps == 0.0, f"rates: {rx_bps},{tx_bps}"
    print("PASS 1: First observation")
    passed += 1

    # Test 2: Normal increment — rates computed correctly
    _fake_time[0] = 1005.0
    rx, tx, resets, rx_bps, tx_bps = tracker.observe("wan", 2000, 1000)
    assert rx == 2000 and tx == 1000, f"totals: {rx},{tx}"
    assert resets == 0
    assert abs(rx_bps - (1000 * 8 / 5.0)) < 0.01, f"rx_bps={rx_bps}"
    assert abs(tx_bps - (500 * 8 / 5.0)) < 0.01, f"tx_bps={tx_bps}"
    print("PASS 2: Normal increment, correct rates")
    passed += 1

    # Test 3: Counter reset — NO rate spike
    _fake_time[0] = 1010.0
    rx, tx, resets, rx_bps, tx_bps = tracker.observe("wan", 100, 50)
    assert rx == 2100, f"rx={rx}"  # offset(2000)+100
    assert tx == 1050, f"tx={tx}"  # offset(1000)+50
    assert resets == 2, f"resets={resets}"  # rx+tx each reset
    assert rx_bps == 0.0, f"SPIKE! rx_bps={rx_bps}"
    assert tx_bps == 0.0, f"SPIKE! tx_bps={tx_bps}"
    print("PASS 3: Counter reset — zero rate (no spike), correct cumulative")
    passed += 1

    # Test 4: Normal after reset
    _fake_time[0] = 1015.0
    rx, tx, resets, rx_bps, tx_bps = tracker.observe("wan", 600, 300)
    assert rx == 2600, f"rx={rx}"
    assert tx == 1300, f"tx={tx}"
    assert resets == 2, f"resets={resets}"
    assert abs(rx_bps - (500 * 8 / 5.0)) < 0.01, f"rx_bps={rx_bps}"
    assert abs(tx_bps - (250 * 8 / 5.0)) < 0.01, f"tx_bps={tx_bps}"
    print("PASS 4: Normal after reset, rates correct")
    passed += 1

    # Test 5: State persistence across restarts
    tracker2 = zte_exporter.WanByteTracker(state_file)
    _fake_time[0] = 1020.0
    rx, tx, resets, rx_bps, tx_bps = tracker2.observe("wan", 900, 450)
    assert rx == 2900, f"rx={rx}"
    assert tx == 1450, f"tx={tx}"
    assert resets == 2, f"resets={resets}"
    print("PASS 5: State file persistence")
    passed += 1

    # Test 6: Second reboot — resets cumulative
    _fake_time[0] = 1025.0
    rx, tx, resets, rx_bps, tx_bps = tracker2.observe("wan", 10, 5)
    assert resets == 4, f"resets={resets}"  # 2 more
    assert rx == 2910, f"rx={rx}"  # offset(2000+900)+10
    assert tx == 1455, f"tx={tx}"  # offset(1000+450)+5
    assert rx_bps == 0.0 and tx_bps == 0.0, f"SPIKE on 2nd reboot!"
    print("PASS 6: Second reboot — resets cumulative, no spike")
    passed += 1

    # Test 7: Verify state file contents
    with open(state_file, encoding="utf-8") as f:
        data = json.load(f)
    entry = data["keys"]["wan"]
    assert entry["resets_total"] == 4, f"persisted resets={entry['resets_total']}"
    assert entry["rx_offset"] == 2900, f"rx_offset={entry['rx_offset']}"
    assert entry["tx_offset"] == 1450, f"tx_offset={entry['tx_offset']}"
    print("PASS 7: State file has correct offsets and resets_total")
    passed += 1

    # Cleanup
    shutil.rmtree(tmpdir)
    print(f"\n{passed}/{passed} tests passed")

if __name__ == "__main__":
    try:
        run_tests()
    finally:
        time.time = _orig_time
