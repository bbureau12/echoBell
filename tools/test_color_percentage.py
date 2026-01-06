"""Test that color percentage evidence is being generated."""
import sys
sys.path.insert(0, '.')

from packages.perception.vision import snapshot_and_detect

# Test with USPS truck
vr = snapshot_and_detect(
    'data/doorbell.db',
    'tests/fixtures/delivery/usps.jpg',
    camera_id='1',
    debug=False,
    enable_ocr=False
)

print("Color percentage evidence for USPS truck:")
print("="*70)

vehicles = [obj for obj in vr.objects if obj.label == 'vehicle']
if vehicles:
    vehicle = vehicles[0]
    
    # Show palette from props
    palette = vehicle.props.get('color_palette', {})
    print(f"\nStored palette:")
    for color, frac in sorted(palette.items(), key=lambda x: x[1], reverse=True):
        print(f"  {color:10s}: {frac:6.1%}")
    
    # Show percentage evidence
    print(f"\nColor percentage evidence:")
    color_pct_evidence = [ev for ev in vehicle.evidence if ev.feature.startswith('color_pct_')]
    for ev in color_pct_evidence:
        color = ev.feature.replace('color_pct_', '')
        pct = ev.value
        print(f"  vision.{ev.feature} = {pct}% (conf={ev.conf:.2f})")
    
    # Show palette_color evidence for comparison
    print(f"\nPalette color evidence (presence):")
    palette_evidence = [ev for ev in vehicle.evidence if ev.feature == 'palette_color']
    for ev in palette_evidence:
        print(f"  vision.palette_color = {ev.value} (conf={ev.conf:.2f})")

print("\n" + "="*70)
print("Now you can create rules like:")
print("  - signal_rule: color_pct_blue >= 5  → USPS candidate")
print("  - signal_rule: color_pct_white >= 30 → Delivery vehicle")
print("  - signal_rule: color_pct_brown >= 40 → UPS truck")
