"""Test that contributes_standalone flag works correctly."""
import sys
sys.path.insert(0, '.')

from packages.perception.vision import snapshot_and_detect
from packages.classify.intent import classify
from packages.common.types import VisionResult
import sqlite3

# Test with USPS image
print("="*60)
print("Testing contributes_standalone flag with USPS truck")
print("="*60)

conn = sqlite3.connect('data/doorbell.db')

# Check rule 36 configuration
rule = conn.execute('SELECT id, intent_name, weight, contributes_standalone FROM signal_rule WHERE id=36').fetchone()
print(f"\nRule 36: {rule[1]}, weight={rule[2]}, contributes_standalone={rule[3]}")

# Run vision
vr = snapshot_and_detect(
    'data/doorbell.db',
    'tests/fixtures/delivery/usps.jpg',
    camera_id='1',
    debug=False,
    enable_ocr=False
)

# Classify intent
result = classify("", vr, 'data/doorbell.db')

print(f"\n{len(result.trace)} trace lines")
print("\nAll trace lines:")
for i, line in enumerate(result.trace, 1):
    print(f"  {i}. {line}")

print("\n" + "="*60)
print("Rule 36 analysis:")
for line in result.trace:
    if 'rule 36' in line.lower():
        print(f"  {line}")
        if '(group-only)' in line:
            print("  ✓ Correctly marked as group-only")
        else:
            print("  ✗ Missing '(group-only)' marker!")

print(f"\nClassified intent: {result.intent} (conf={result.conf:.2f}, urgency={result.urgency})")

print(f"\nExpected behavior:")
print(f"  - Rule 36 (blue palette) should show '(group-only)' in trace")
print(f"  - Rule 36 should NOT add standalone score to 'package_drop'")
print(f"  - Rule 36 SHOULD contribute via 'usps_delivery_truck' group")
print(f"  - Look for group trace line showing the combined contribution")

conn.close()
