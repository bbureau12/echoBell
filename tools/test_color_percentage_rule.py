"""Test color percentage rules with gte operator."""
import sqlite3
import sys
sys.path.insert(0, '.')

from packages.perception.vision import snapshot_and_detect
from packages.classify.intent import classify

# Add a test rule: blue >= 5% on vehicle → package_drop
conn = sqlite3.connect('data/doorbell.db')

print("Adding test rule: color_pct_blue >= 5 → package_drop")
conn.execute("""
    INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, min_conf, urgency, scope_any_of, contributes_standalone, enabled)
    VALUES ('vision', 'color_pct_blue', 'gte', '5', 'package_drop', 2.0, 0.0, 5, 'vehicle', 1, 1)
""")
conn.commit()

rule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
print(f"Created rule ID: {rule_id}")

# Test with USPS truck (has 6% blue)
print("\n" + "="*70)
print("Testing with USPS truck (has 6% blue - should match)")
print("="*70)

vr = snapshot_and_detect(
    'data/doorbell.db',
    'tests/fixtures/delivery/usps.jpg',
    camera_id='1',
    debug=False,
    enable_ocr=False
)

# Show color percentages
vehicles = [obj for obj in vr.objects if obj.label == 'vehicle']
if vehicles:
    palette = vehicles[0].props.get('color_palette', {})
    print(f"\nColor palette:")
    for color, frac in sorted(palette.items(), key=lambda x: x[1], reverse=True):
        print(f"  {color:10s}: {frac:6.1%}")

# Classify
result = classify("", vr, 'data/doorbell.db')

print(f"\nClassified intent: {result.intent} (conf={result.conf:.2f})")

print(f"\nLooking for our test rule (ID {rule_id}) in trace:")
for line in result.trace:
    if f'rule {rule_id}' in line or ('color_pct_blue' in line and 'gte' in line):
        print(f"  ✓ {line}")

# Cleanup
print(f"\n" + "="*70)
print(f"Cleaning up: Deleting test rule {rule_id}")
conn.execute("DELETE FROM signal_rule WHERE id = ?", (rule_id,))
conn.commit()
conn.close()
print("Done!")
