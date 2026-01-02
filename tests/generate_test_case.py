#!/usr/bin/env python3
"""
Helper script to generate test case template from vision_harness output.

Usage:
    python tests/generate_test_case.py <image_path> <test_name>

This script:
1. Runs vision_harness on the image
2. Captures the evidence output
3. Generates a VisionTestCase template
4. Prints Python code to add to test_vision_regression.py
"""

import sys
import sqlite3
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.perception.vision import snapshot_and_detect
from packages.data.camera_service import CameraService
from packages.common.types import Camera, CameraCapabilities


def generate_test_case(image_path: str, test_name: str, db_path: str = "data/doorbell.db"):
    """Generate a test case template from actual vision output."""
    
    image_path = Path(image_path)
    if not image_path.exists():
        print(f"Error: Image not found: {image_path}")
        sys.exit(1)
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    camera_service = CameraService()
    
    # Create dummy camera
    camera = Camera(
        id=1,
        name="test_camera",
        rtsp_url="",
        capabilities=CameraCapabilities(
            has_ptz=False,
            has_audio=False,
            max_resolution=(1920, 1080)
        )
    )
    
    # Run vision detection
    print(f"Running vision detection on {image_path.name}...")
    vision_result = snapshot_and_detect(
        conn=conn,
        frame_path=str(image_path),
        camera=camera,
        now_ts=None,
        camera_service=camera_service,
    )
    
    conn.close()
    
    # Print evidence
    print(f"\nEvidence from {image_path.name}:")
    print("=" * 60)
    for ev in vision_result.evidence:
        print(f"  - {ev.source}.{ev.feature}={ev.value} conf={ev.conf:.2f} obj={ev.object_id}")
    print("=" * 60)
    
    # Generate test case code
    print(f"\n\nGenerated test case code:")
    print("=" * 60)
    
    # Determine relative path for fixtures
    relative_path = image_path.relative_to(Path.cwd()) if image_path.is_relative_to(Path.cwd()) else image_path
    
    # Extract directory name for fixtures path
    if "fixtures" in str(relative_path):
        # Already in fixtures, extract subdirectory
        parts = relative_path.parts
        if "fixtures" in parts:
            idx = parts.index("fixtures")
            fixture_subdir = "/".join(parts[idx+1:-1]) if len(parts) > idx + 2 else parts[idx+1]
            fixture_path = f'TEST_CASES_DIR / "{fixture_subdir}" / "{image_path.name}"'
        else:
            fixture_path = f'TEST_CASES_DIR / "{image_path.name}"'
    else:
        # Suggest moving to fixtures
        print(f"# NOTE: Move {image_path.name} to tests/fixtures/<category>/")
        fixture_path = f'TEST_CASES_DIR / "<category>" / "{image_path.name}"'
    
    print(f"""
VisionTestCase(
    name="{test_name}",
    image_path={fixture_path},
    expected_evidence=[""")
    
    # Generate evidence entries
    for ev in vision_result.evidence:
        obj_str = f'"{ev.object_id}"' if ev.object_id is not None else "None"
        print(f'        {{"source": "{ev.source}", "feature": "{ev.feature}", "value": "{ev.value}", "min_conf": {ev.conf:.2f}, "object_id": {obj_str}}},')
    
    print(f"""    ]
),""")
    
    print("=" * 60)
    print("\nInstructions:")
    print(f"1. Move {image_path.name} to tests/fixtures/<category>/")
    print(f"2. Copy the VisionTestCase code above")
    print(f"3. Paste into VISION_TEST_CASES list in test_vision_regression.py")
    print(f"4. Adjust confidence thresholds and values as needed")
    print(f"5. Remove any non-deterministic evidence items")
    print(f"\nRun test with:")
    print(f"  pytest tests/test_vision_regression.py::test_vision_regression[{test_name}] -v")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python tests/generate_test_case.py <image_path> <test_name>")
        print("\nExample:")
        print("  python tests/generate_test_case.py tests/fixtures/police/officer.jpg police_officer_trusted")
        sys.exit(1)
    
    image_path = sys.argv[1]
    test_name = sys.argv[2]
    
    generate_test_case(image_path, test_name)
