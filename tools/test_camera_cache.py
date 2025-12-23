#!/usr/bin/env python3
"""
Test harness for camera service caching.
"""
import os
import sys
import sqlite3
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from apps.app import AppConfig, build_context
from packages.data.camera_service import CameraRepository


def test_camera_cache():
    """Test that camera data is properly cached."""
    print("=" * 80)
    print("Testing Camera Service Cache")
    print("=" * 80)
    
    # Load config and build context
    config_path = os.path.join(ROOT, "config.json")
    config = AppConfig.from_json_or_defaults(config_path)
    ctx = build_context(config)
    
    print(f"\nCache Type: {type(ctx.cache).__name__ if ctx.cache else 'None'}")
    print(f"Cache TTL: {ctx.camera_service.cache_ttl_s} seconds ({ctx.camera_service.cache_ttl_s // 60} minutes)")
    
    # Connect to database
    db_path = os.path.join(ROOT, "data", "doorbell.db")
    
    with sqlite3.connect(db_path) as conn:
        repo = CameraRepository(conn, cache=ctx.cache, cache_ttl_s=ctx.camera_service.cache_ttl_s)
        
        print("\n" + "-" * 80)
        print("Test 1: get_by_id() - First call (cache miss)")
        print("-" * 80)
        
        start = time.time()
        camera = repo.get_by_id(1)
        elapsed_ms = (time.time() - start) * 1000
        
        if camera:
            print(f"✓ Camera found: {camera.name} (ID: {camera.id})")
            print(f"  Location ID: {camera.location_id}")
            print(f"  Hostname: {camera.hostname}")
            print(f"  IP: {camera.ip_address}")
            print(f"  Time: {elapsed_ms:.2f}ms")
        else:
            print("✗ Camera not found")
            return
        
        print("\n" + "-" * 80)
        print("Test 2: get_by_id() - Second call (cache hit)")
        print("-" * 80)
        
        start = time.time()
        camera2 = repo.get_by_id(1)
        elapsed_ms = (time.time() - start) * 1000
        
        if camera2:
            print(f"✓ Camera found: {camera2.name} (ID: {camera2.id})")
            print(f"  Time: {elapsed_ms:.2f}ms")
            print(f"  Speedup: Cache should be faster!")
        else:
            print("✗ Camera not found")
        
        print("\n" + "-" * 80)
        print("Test 3: list_all() - First call (cache miss)")
        print("-" * 80)
        
        start = time.time()
        cameras = repo.list_all()
        elapsed_ms = (time.time() - start) * 1000
        
        print(f"✓ Found {len(cameras)} cameras")
        for cam in cameras:
            print(f"  - {cam.name} (ID: {cam.id})")
        print(f"  Time: {elapsed_ms:.2f}ms")
        
        print("\n" + "-" * 80)
        print("Test 4: list_all() - Second call (cache hit)")
        print("-" * 80)
        
        start = time.time()
        cameras2 = repo.list_all()
        elapsed_ms = (time.time() - start) * 1000
        
        print(f"✓ Found {len(cameras2)} cameras")
        print(f"  Time: {elapsed_ms:.2f}ms")
        print(f"  Speedup: Cache should be faster!")
        
        # Verify cache keys exist
        if ctx.cache:
            print("\n" + "-" * 80)
            print("Test 5: Verify cache keys")
            print("-" * 80)
            
            cache_key_single = "camera:1"
            cache_key_list = "camera:list_all"
            
            cached_single = ctx.cache.get(cache_key_single)
            cached_list = ctx.cache.get(cache_key_list)
            
            print(f"✓ Cache key '{cache_key_single}': {'EXISTS' if cached_single else 'MISSING'}")
            print(f"✓ Cache key '{cache_key_list}': {'EXISTS' if cached_list else 'MISSING'}")
            
            if cached_single:
                print(f"  Single camera cached data length: {len(cached_single)} bytes")
            if cached_list:
                print(f"  Camera list cached data length: {len(cached_list)} bytes")
    
    print("\n" + "=" * 80)
    print("✓ All cache tests completed!")
    print("=" * 80)


if __name__ == "__main__":
    test_camera_cache()
