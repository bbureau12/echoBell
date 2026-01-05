"""
Debug tool for testing color palette extraction on sample images.
Helps identify HSV range issues.
"""
import cv2
import numpy as np
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from packages.perception.vision import COLORS, extract_color_palette

def create_test_swatch(color_name: str, size: int = 100) -> np.ndarray:
    """Create a solid color test swatch in BGR format."""
    if color_name not in COLORS or not COLORS[color_name]["rgb"]:
        print(f"Color '{color_name}' not found in COLORS")
        return None
    
    r, g, b = COLORS[color_name]["rgb"]
    # Create BGR image (OpenCV format)
    swatch = np.zeros((size, size, 3), dtype=np.uint8)
    swatch[:, :] = [b, g, r]  # BGR order
    return swatch

def analyze_color_swatch(color_name: str):
    """Analyze a color swatch to see if it's detected correctly."""
    print(f"\n{'='*60}")
    print(f"Analyzing: {color_name.upper()}")
    print(f"{'='*60}")
    
    swatch_bgr = create_test_swatch(color_name)
    if swatch_bgr is None:
        return
    
    # Show RGB value
    rgb = COLORS[color_name]["rgb"]
    print(f"RGB: {rgb}")
    
    # Convert to HSV and show actual HSV value
    hsv_sample = cv2.cvtColor(swatch_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv_sample[0, 0]
    print(f"Actual HSV: H={h}, S={s}, V={v}")
    
    # Show expected HSV range
    hsv_range = COLORS[color_name]["hsv"]
    if hsv_range:
        lower, upper = hsv_range
        print(f"Expected HSV range: {lower} to {upper}")
        
        # Check if actual HSV falls within range
        h_match = lower[0] <= h <= upper[0] or (lower[0] > upper[0] and (h >= lower[0] or h <= upper[0]))
        s_match = lower[1] <= s <= upper[1]
        v_match = lower[2] <= v <= upper[2]
        
        print(f"Hue match: {h_match} ({h} in [{lower[0]}, {upper[0]}])")
        print(f"Sat match: {s_match} ({s} in [{lower[1]}, {upper[1]}])")
        print(f"Val match: {v_match} ({v} in [{lower[2]}, {upper[2]}])")
        
        if h_match and s_match and v_match:
            print("✓ Color should be detected!")
        else:
            print("✗ Color will NOT be detected - HSV range issue!")
    else:
        print("No HSV range defined")
    
    # Test palette extraction
    palette = extract_color_palette(swatch_bgr, min_fraction=0.05)
    print(f"\nExtracted palette: {palette}")
    
    if color_name in palette:
        print(f"✓ {color_name} detected with {palette[color_name]:.1%} coverage")
    else:
        print(f"✗ {color_name} NOT detected in palette")
        if palette:
            print(f"  Instead detected: {list(palette.keys())}")

def test_all_colors():
    """Test all defined colors."""
    for color_name in COLORS.keys():
        if COLORS[color_name]["hsv"] is not None:
            analyze_color_swatch(color_name)

def test_real_image(image_path: str):
    """Test palette extraction on a real image."""
    print(f"\n{'='*60}")
    print(f"Testing real image: {image_path}")
    print(f"{'='*60}")
    
    img = cv2.imread(image_path)
    if img is None:
        print(f"Failed to load image: {image_path}")
        return
    
    print(f"Image size: {img.shape[1]}x{img.shape[0]}")
    
    # Extract palette
    palette = extract_color_palette(img, min_fraction=0.05)
    print(f"\nExtracted palette:")
    for color, frac in sorted(palette.items(), key=lambda x: x[1], reverse=True):
        print(f"  {color:10s}: {frac:6.1%}")
    
    # Show HSV histogram
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_vals = hsv[:, :, 0].flatten()
    print(f"\nHue distribution (0-180):")
    print(f"  Min: {h_vals.min()}, Max: {h_vals.max()}, Mean: {h_vals.mean():.1f}")
    
    # Count pixels in blue hue range (85-130)
    blue_hue_mask = (h_vals >= 85) & (h_vals <= 130)
    blue_pct = blue_hue_mask.sum() / len(h_vals) * 100
    print(f"  Pixels in blue hue range (85-130): {blue_pct:.1f}%")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Debug color palette extraction")
    parser.add_argument("--color", help="Test a specific color (e.g., 'blue')")
    parser.add_argument("--all", action="store_true", help="Test all colors")
    parser.add_argument("--image", help="Test on a real image file")
    
    args = parser.parse_args()
    
    if args.all:
        test_all_colors()
    elif args.color:
        analyze_color_swatch(args.color)
    elif args.image:
        test_real_image(args.image)
    else:
        # Default: test blue
        print("Testing BLUE color detection")
        print("(Use --all to test all colors, --image <path> for real images)")
        analyze_color_swatch("blue")
