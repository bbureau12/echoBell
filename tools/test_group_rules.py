"""
Test group-only rules with positive and negative test cases.

Positive case: Should have blue+white palette → group activates → package_drop
Negative case: Should NOT have blue+white palette → group doesn't activate → no package_drop (unless other rules match)
"""
import sys
sys.path.insert(0, '.')

from packages.perception.vision import snapshot_and_detect
from packages.classify.intent import classify
import sqlite3

def test_case(name, image_path, expected_has_blue_white_group):
    print(f"\n{'='*70}")
    print(f"TEST: {name}")
    print(f"{'='*70}")
    print(f"Image: {image_path}")
    print(f"Expected: {'Blue+White group should activate' if expected_has_blue_white_group else 'Blue+White group should NOT activate'}")
    
    # Run vision
    vr = snapshot_and_detect(
        'data/doorbell.db',
        image_path,
        camera_id='1',
        debug=False,
        enable_ocr=False
    )
    
    # Show palette
    vehicles = [obj for obj in vr.objects if obj.label == 'vehicle']
    if vehicles:
        palette = vehicles[0].props.get('color_palette', {})
        print(f"\nVehicle color palette:")
        for color, frac in sorted(palette.items(), key=lambda x: x[1], reverse=True):
            marker = " ✓" if color in ['blue', 'white'] else ""
            print(f"  {color:10s}: {frac:6.1%}{marker}")
        
        has_blue = 'blue' in palette
        has_white = 'white' in palette
        print(f"\nBlue present: {has_blue}")
        print(f"White present: {has_white}")
        print(f"Both present: {has_blue and has_white}")
    else:
        print("\nNo vehicles detected!")
    
    # Classify
    result = classify("", vr, 'data/doorbell.db')
    
    print(f"\nClassified intent: {result.intent} (conf={result.conf:.2f})")
    
    # Check trace for group activation
    print(f"\nTrace analysis:")
    group_activated = False
    group_only_rules = []
    standalone_rules = []
    
    for line in result.trace:
        if 'usps_delivery_truck' in line:
            group_activated = True
            print(f"  ✓ {line}")
        elif 'group-only' in line:
            group_only_rules.append(line)
        elif 'signal_rule' in line and 'package_drop' in line:
            standalone_rules.append(line)
    
    if group_only_rules:
        print(f"\n  Group-only rules (don't contribute standalone):")
        for line in group_only_rules:
            print(f"    - {line}")
    
    if standalone_rules:
        print(f"\n  Standalone rules that contributed:")
        for line in standalone_rules:
            print(f"    - {line}")
    
    # Verdict
    print(f"\n{'='*70}")
    if expected_has_blue_white_group:
        if group_activated:
            print(f"✓ PASS: Group activated as expected")
        else:
            print(f"✗ FAIL: Group should have activated but didn't!")
    else:
        if not group_activated:
            print(f"✓ PASS: Group did not activate as expected")
        else:
            print(f"✗ FAIL: Group should NOT have activated!")
    print(f"{'='*70}")


if __name__ == "__main__":
    # Test positive case (USPS truck with blue+white)
    test_case(
        "POSITIVE - USPS truck with blue stripe",
        "tests/fixtures/group_rules/positive.jpg",
        expected_has_blue_white_group=True
    )
    
    # Test negative case (vehicle without blue+white combination)
    test_case(
        "NEGATIVE - Vehicle without blue+white pattern",
        "tests/fixtures/group_rules/negative.jpg",
        expected_has_blue_white_group=False
    )
