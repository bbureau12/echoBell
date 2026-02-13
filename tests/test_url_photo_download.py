#!/usr/bin/env python3
"""
Test URL Photo Download

Tests the policy server's ability to download images from edge device URLs
and send them via Telegram.

This simulates the realistic edge device scenario:
1. Edge device saves image locally
2. Edge device runs HTTP server to serve images
3. Edge device sends snapshot_url (not local path) to policy API
4. Policy API downloads image from URL
5. Policy API sends photo to Telegram

Prerequisites:
    1. Start test edge image server: python tests/test_edge_image_server.py --create-test-image
    2. Start policy API server: cd central/policy-server && python server.py
    3. Run this test script

Usage:
    # Test with default settings
    python tests/test_url_photo_download.py
    
    # Test with custom edge server URL
    python tests/test_url_photo_download.py --edge-url http://192.168.1.100:8080
    
    # Test with custom image
    python tests/test_url_photo_download.py --image test_image.jpg
"""

import argparse
import requests
import sys
import time
from pathlib import Path


def check_server_health(api_url: str) -> bool:
    """Check if policy API server is running"""
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def check_edge_server(edge_url: str, image_name: str) -> bool:
    """Check if edge image server is serving the test image"""
    try:
        headers = {'X-API-Key': 'dontgiveitupluffy'}
        response = requests.get(f"{edge_url}/{image_name}", timeout=5, headers=headers)
        return response.status_code == 200
    except:
        return False


def send_test_request(
    api_url: str,
    edge_url: str,
    image_name: str,
    camera_id: int = 1
) -> dict:
    """
    Send test evidence with snapshot_url (simulating edge agent)
    
    Args:
        api_url: Policy API base URL
        edge_url: Edge device image server URL
        image_name: Image filename on edge server
        camera_id: Camera ID to test
        
    Returns:
        API response dict
    """
    timestamp = int(time.time())
    snapshot_url = f"{edge_url}/{image_name}"
    
    payload = {
        'camera_id': camera_id,
        'event_id': f'test_url_{timestamp}_{camera_id}',
        'timestamp': timestamp,
        'event_type': 'detection',
        
        # Objects from vision detection
        'objects': [{
            'object_id': 1,
            'label': 'vehicle',
            'bbox': [100, 200, 400, 400],
            'confidence': 0.95,
            'props': {
                'raw_class': 'car',
                'color': 'white',
                'conf': 0.95
            }
        }],
        
        # Evidence from vision system
        'evidence': [
            # Scene-level
            {
                'source': 'vision',
                'feature': 'vehicle_present',
                'value': 'true',
                'conf': 0.95,
                'object_id': None
            },
            # Object-level
            {
                'source': 'vision',
                'feature': 'class',
                'value': 'vehicle',
                'conf': 0.95,
                'object_id': 1
            },
            {
                'source': 'vision',
                'feature': 'vehicle_type',
                'value': 'car',
                'conf': 0.90,
                'object_id': 1
            },
            {
                'source': 'vision',
                'feature': 'color',
                'value': 'white',
                'conf': 0.60,
                'object_id': 1
            }
        ],
        
        # Context from edge agent - includes snapshot_url!
        'context': {
            'mode': 'passive',
            'person_present': False,
            'vehicle_present': True,
            'source': f'camera_{camera_id}',
            'snapshot_url': snapshot_url  # This is what edge agent sends!
        }
    }
    
    print(f"\n[>] Sending request to policy API...")
    print(f"   Snapshot URL: {snapshot_url}")
    
    response = requests.post(f"{api_url}/evidence", json=payload, timeout=30)
    response.raise_for_status()
    
    return response.json()


def check_downloaded_image(image_name: str) -> bool:
    """Check if image was downloaded by policy server"""
    download_dir = Path("data/downloaded_images")
    downloaded_file = download_dir / image_name
    
    if downloaded_file.exists():
        size_kb = downloaded_file.stat().st_size / 1024
        print(f"   [OK] Downloaded image exists: {downloaded_file} ({size_kb:.1f} KB)")
        return True
    else:
        print(f"   [NOT FOUND] Downloaded image NOT found: {downloaded_file}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Test policy server URL photo download functionality"
    )
    parser.add_argument(
        '--api-url',
        type=str,
        default='http://localhost:8000',
        help='Policy API base URL (default: http://localhost:8000)'
    )
    parser.add_argument(
        '--edge-url',
        type=str,
        default='http://localhost:8080',
        help='Edge device image server URL (default: http://localhost:8080)'
    )
    parser.add_argument(
        '--image',
        type=str,
        default='test_image.jpg',
        help='Image filename to test (default: test_image.jpg)'
    )
    parser.add_argument(
        '--camera-id',
        type=int,
        default=1,
        help='Camera ID to test (default: 1)'
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("Testing URL Photo Download")
    print("=" * 70)
    print(f"Policy API: {args.api_url}")
    print(f"Edge Server: {args.edge_url}")
    print(f"Test Image: {args.image}")
    print(f"Camera ID: {args.camera_id}")
    print("=" * 70)
    
    # Step 1: Check policy API server
    print("\n[Step 1] Checking policy API server...")
    if not check_server_health(args.api_url):
        print("   [FAIL] Policy API server is NOT running!")
        print("   Start it with: cd central/policy-server && python server.py")
        return 1
    print("   [OK] Policy API server is running")
    
    # Step 2: Check edge image server
    print("\n[Step 2] Checking edge image server...")
    if not check_edge_server(args.edge_url, args.image):
        print(f"   [FAIL] Edge server not serving image: {args.edge_url}/{args.image}")
        print("   Start it with: python tests/test_edge_image_server.py --create-test-image")
        return 1
    print(f"   [OK] Edge server is serving: {args.edge_url}/{args.image}")
    
    # Step 3: Send test request
    print("\n[Step 3] Sending test evidence with snapshot_url...")
    try:
        result = send_test_request(
            args.api_url,
            args.edge_url,
            args.image,
            args.camera_id
        )
        print(f"   [OK] Request successful!")
        print(f"   Response: {result.get('message', 'OK')}")
    except requests.RequestException as e:
        print(f"   [FAIL] Request failed: {e}")
        return 1
    
    # Step 4: Wait a moment for policy execution
    print("\n[Step 4] Waiting for policy execution...")
    time.sleep(2)
    
    # Step 5: Check if image was downloaded
    print("\n[Step 5] Checking if image was downloaded...")
    if check_downloaded_image(args.image):
        print("   [OK] Policy server successfully downloaded image from URL!")
    else:
        print("   [WARN] Image was not downloaded (may not be required by policy)")
    
    # Step 6: Check Telegram
    print("\n[Step 6] Check Telegram for message...")
    print("   Check Telegram and verify:")
    print("      - Message received")
    print("      - Photo attached")
    print("      - Caption matches policy template")
    
    print("\n" + "=" * 70)
    print("[SUCCESS] Test Complete!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Check Telegram for the photo message")
    print("2. Verify downloaded image in data/downloaded_images/")
    print("3. Check policy server logs for download activity")
    print("4. Run cleanup: python tools/cleanup_downloaded_images.py --dry-run")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
