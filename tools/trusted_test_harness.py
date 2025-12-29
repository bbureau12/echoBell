#!/usr/bin/env python3
"""
Test harness for trusted face matching.
Scans test images and attempts to match them against enrolled trusted persons.
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict, Counter

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from apps.app import AppConfig, build_context
from packages.perception.trusted_embeddings.trusted_face_matching import try_match_trusted
from tools.torch_utils import allowlist_checkpoint_globals

VALID_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def walk_test_dataset(root: str):
    """
    Yields tuples: (folder_name, file_path)
    Example: ('amanda_bureau', 'data/test/amanda_bureau/1.png')
    """
    root_path = Path(root)
    for dirpath, dirs, files in os.walk(root):
        # Skip the root itself (we want subfolders)
        if dirpath == root:
            continue

        folder = os.path.basename(dirpath)

        for f in files:
            if f.lower().endswith(VALID_EXT):
                yield folder, os.path.join(dirpath, f)


def extract_person_bbox(frame_bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    Simple person detection using YOLO.
    Returns the largest person bbox or None.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] ultralytics not installed. Run: pip install ultralytics")
        return None
    
    # Allowlist all globals in the checkpoint for PyTorch 2.6+ compatibility
    allowlist_checkpoint_globals("yolov8n.pt")
    
    # Load YOLO model
    model = YOLO("yolov8n.pt")
    
    # Run detection
    results = model(frame_bgr, verbose=False)
    
    if not results or len(results) == 0:
        return None
    
    # Find largest person (class 0)
    best_box = None
    best_area = 0
    
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls == 0:  # person class
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                area = (x2 - x1) * (y2 - y1)
                if area > best_area:
                    best_area = area
                    best_box = (int(x1), int(y1), int(x2), int(y2))
    
    return best_box


def run_test_harness(db_path: str, test_root: str, camera_id: int = 1, debug: bool = False):
    """
    Test trusted face matching on all images in test_root.
    """
    print(f"\n[TEST HARNESS] Trusted Face Matching")
    print(f"[DATABASE] {db_path}")
    print(f"[TEST ROOT] {test_root}")
    print(f"[CAMERA ID] {camera_id}\n")
    
    # Set up context
    config_path = os.path.join(ROOT, "config.json")
    config = AppConfig.from_json_or_defaults(config_path)
    ctx = build_context(config)
    
    if ctx.cache:
        print(f"[CACHE] Using: {type(ctx.cache).__name__}")
    else:
        print("[CACHE] No cache available")
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    
    # Load trusted persons for reference
    trusted_people = conn.execute(
        "SELECT trusted_id, name, label FROM trusted_person ORDER BY trusted_id"
    ).fetchall()
    
    if not trusted_people:
        print("[WARNING] No trusted persons enrolled in database!")
        print("Run: python packages/perception/trusted_embeddings/trusted_cli.py scan-folders")
        conn.close()
        return
    
    print(f"[TRUSTED PERSONS] {len(trusted_people)} enrolled:")
    for tid, name, label in trusted_people:
        print(f"  ID {tid}: {name} ({label})")
    print()
    
    # Track results
    results = []
    stats = Counter()
    matches_by_folder = defaultdict(list)
    
    # Process each test image
    for folder, file_path in walk_test_dataset(test_root):
        print(f"[TEST] {folder}/{os.path.basename(file_path)}")
        
        # Read image
        frame_bgr = cv2.imread(file_path)
        if frame_bgr is None:
            print(f"  ❌ Could not read image")
            stats["unreadable"] += 1
            continue
        
        # Detect person
        person_box = extract_person_bbox(frame_bgr)
        if person_box is None:
            print(f"  ⚠️  No person detected")
            stats["no_person"] += 1
            results.append({
                "folder": folder,
                "file": file_path,
                "status": "no_person",
                "match": None
            })
            continue
        
        x1, y1, x2, y2 = person_box
        print(f"  ✓ Person detected: bbox=({x1},{y1},{x2},{y2})")
        
        # Try trusted matching
        match = try_match_trusted(
            conn,
            ctx.camera_service,
            camera_id=camera_id,
            cache=ctx.cache,
            frame_bgr=frame_bgr,
            person_box=person_box,
            model_pack="buffalo_l",
            threshold=0.60,
            margin=0.05,
        )
        
        if match:
            print(f"  ✅ MATCHED: {match.trusted_label} (ID {match.trusted_id}) - similarity: {match.similarity:.3f}")
            stats["matched"] += 1
            matches_by_folder[folder].append({
                "trusted_id": match.trusted_id,
                "trusted_label": match.trusted_label,
                "similarity": match.similarity
            })
            results.append({
                "folder": folder,
                "file": file_path,
                "status": "matched",
                "match": match
            })
        else:
            print(f"  ❌ No trusted match found")
            if debug:
                print(f"     Debug: Check camera capability, face detection, and similarity threshold")
            stats["no_match"] += 1
            results.append({
                "folder": folder,
                "file": file_path,
                "status": "no_match",
                "match": None
            })
        
        if debug:
            # Draw bbox and result on image
            cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label_text = f"{match.trusted_label} ({match.similarity:.2f})" if match else "Unknown"
            cv2.putText(frame_bgr, label_text, (x1, y1 - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Save annotated image
            output_path = file_path.replace(os.path.basename(file_path), 
                                           f"annotated_{os.path.basename(file_path)}")
            cv2.imwrite(output_path, frame_bgr)
            print(f"  💾 Saved annotated: {output_path}")
        
        print()
    
    conn.close()
    
    # Print summary
    print("=" * 80)
    print("[SUMMARY]")
    print(f"Total images: {sum(stats.values())}")
    print(f"  ✅ Matched: {stats['matched']}")
    print(f"  ❌ No match: {stats['no_match']}")
    print(f"  ⚠️  No person detected: {stats['no_person']}")
    print(f"  ❌ Unreadable: {stats['unreadable']}")
    print()
    
    # Accuracy by folder
    print("[ACCURACY BY FOLDER]")
    for folder in sorted(matches_by_folder.keys()):
        matches = matches_by_folder[folder]
        total_in_folder = sum(1 for r in results if r["folder"] == folder)
        correct = sum(1 for m in matches if m["trusted_label"] == folder)
        accuracy = (correct / len(matches) * 100) if matches else 0
        print(f"  {folder}:")
        print(f"    Total: {total_in_folder}, Matched: {len(matches)}, Correct: {correct}")
        print(f"    Accuracy: {accuracy:.1f}%")
        
        if matches:
            avg_sim = sum(m["similarity"] for m in matches) / len(matches)
            print(f"    Avg similarity: {avg_sim:.3f}")
    print()


def main():
    ap = argparse.ArgumentParser(
        prog="trusted_test_harness",
        description="Test trusted face matching against test dataset"
    )
    ap.add_argument(
        "--test-root",
        default="data/test",
        help="Root directory containing test image folders (default: data/test)"
    )
    ap.add_argument(
        "--db",
        default="data/doorbell.db",
        help="Path to database (default: data/doorbell.db)"
    )
    ap.add_argument(
        "--camera-id",
        type=int,
        default=1,
        help="Camera ID to use for capability checking (default: 1)"
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Save annotated images with match results"
    )
    
    args = ap.parse_args()
    
    run_test_harness(
        db_path=args.db,
        test_root=args.test_root,
        camera_id=args.camera_id,
        debug=args.debug
    )


if __name__ == "__main__":
    main()
