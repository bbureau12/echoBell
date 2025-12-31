import os
import sys
import sqlite3
import argparse
import glob
import uuid
import cv2
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from packages.classify.classify_and_log import classify_and_log, PlateRead
from packages.perception.vision import snapshot_and_detect
from packages.classify.intent import classify

# Import AppConfig and build_context for cache setup
from apps.app import AppConfig, build_context

# Import SnapshotService for saving visitor snapshots
from packages.data.snapshot_service import SnapshotService

# Import SceneTracker for vehicle/person enter/exit tracking
from packages.scene.scene_tracker import SceneTracker


VALID_EXT = (".jpg", ".jpeg", ".png")


def cleanup_annotated_files(data_root: str):
    """
    Delete all files with 'annotated' in the filename from data folder and subfolders.
    """
    deleted_count = 0
    pattern = os.path.join(data_root, "**", "*annotated*")
    
    for file_path in glob.glob(pattern, recursive=True):
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                print(f"[CLEANUP] Deleted: {file_path}")
                deleted_count += 1
            except Exception as e:
                print(f"[CLEANUP] Failed to delete {file_path}: {e}")
    
    if deleted_count > 0:
        print(f"[CLEANUP] Removed {deleted_count} annotated file(s)\n")
    else:
        print("[CLEANUP] No annotated files found\n")


def walk_dataset(root: str):
    """
    Yields tuples: (folder_name, file_path)
    Example: ('police', 'samples/police/1.png')
    """
    for dirpath, dirs, files in os.walk(root):
        # Skip the root itself (we want subfolders)
        if dirpath == root:
            continue

        folder = os.path.basename(dirpath)

        for f in files:
            if f.lower().endswith(VALID_EXT):
                yield folder, os.path.join(dirpath, f)


def format_detection(det):
    """Convert a Detection object into a simple readable dict."""
    x1, y1, x2, y2 = det.box
    return f"{det.cls}, color={det.color}, conf={det.conf:.2f}, box=({x1},{y1},{x2},{y2})"


def run_dataset(db_path: str, dataset_root: str, debug: bool = False):
    print(f"\n[DATASET] scanning: {dataset_root}")
    print(f"[DATASET] using DB: {db_path}\n")
    
    # Set up cache using the same config as app.py
    config_path = os.path.join(ROOT, "config.json")
    config = AppConfig.from_json_or_defaults(config_path)
    ctx = build_context(config)
    cache = ctx.cache
    
    if cache:
        print(f"[CACHE] Using cache: {type(cache).__name__}")
    else:
        print("[CACHE] No cache available")
    
    # Create snapshot service for saving visitor snapshots
    snapshot_service = SnapshotService(
        output_dir=os.path.join(ROOT, "data", "img_log"),
        max_size=1920
    )
    print(f"[SNAPSHOT] Service initialized: {snapshot_service.output_dir}")
    
    # Create scene tracker for vehicle/person enter/exit detection
    scene_tracker = SceneTracker(
        iou_match_threshold=0.30,  # 30% bounding box overlap to match tracks
        grace_period_s=6,          # 6 seconds before marking object as exited
    )
    print(f"[SCENE] Tracker initialized: IoU={scene_tracker.iou_match_threshold}, grace={scene_tracker.grace_period_s}s")
    
    # Clean up any annotated files before running tests
    cleanup_annotated_files(dataset_root)

    results = []

    for folder, file_path in walk_dataset(dataset_root):
        print("=" * 80)
        print(f"[TEST CASE] folder={folder} file={file_path}")

        # Load the frame for snapshot service
        frame_bgr = cv2.imread(file_path)
        camera_id = 1  # Test camera
        now_ts = int(time.time())

        # 1) Run vision with cache and camera_service
        vr = snapshot_and_detect(
            db_path, 
            file_path, 
            camera_id=str(camera_id), 
            debug=debug, 
            cache=cache,
            camera_service=ctx.camera_service,
            plate_service=ctx.plate_service,
            plate_modifiers=config.plate_modifiers,
        )

        # 1.5) Extract plate reads from vision evidence
        print(f"\n=== EVIDENCE DEBUG ===")
        print(f"Total VisionResult evidence items: {len(vr.evidence)}")
        print(f"Total objects: {len(vr.objects)}")
        
        for i, obj in enumerate(vr.objects):
            print(f"\nObject[{i}] ({obj.label}): {len(obj.evidence)} evidence items")
            for j, ev in enumerate(obj.evidence):
                print(f"  [{j}] source={ev.source}, feature={ev.feature}, value={str(ev.value)[:30]}")
        
        print(f"\nVisionResult-level evidence:")
        for i, ev in enumerate(vr.evidence):
            val_str = str(ev.value)[:30]
            if ev.source == "ocr":
                print(f"  [{i}] source={ev.source}, feature={ev.feature}, value={val_str}, conf={ev.conf:.3f}, obj_id={ev.object_id}")
            else:
                print(f"  [{i}] source={ev.source}, feature={ev.feature}, value={val_str}, obj_id={ev.object_id}")
        
        plate_reads = []
        for ev in vr.evidence:
            if ev.source == "ocr" and ev.feature == "plate_text":
                print(f"  ✓ Found plate_text evidence: {ev.value}")
                plate_reads.append(PlateRead(
                    raw_text=ev.value,
                    conf=ev.conf,
                    object_id=ev.object_id
                ))
        
        if plate_reads:
            print(f"\n✓ Extracted {len(plate_reads)} plate reads:")
            for pr in plate_reads:
                print(f"  - {pr.raw_text} (conf={pr.conf:.2f}, obj={pr.object_id})")
        else:
            print("\n✗ No plate reads extracted from evidence")
        print(f"=== END EVIDENCE DEBUG ===\n")

        # 2) Run intent classification with snapshot service and scene tracker
        classified, event_id = classify_and_log(
            db_path=db_path,
            vision=vr,
            text="",
            event_id=None,
            lock_conf_threshold=0.85,
            snapshot_service=snapshot_service,
            frame_bgr=frame_bgr,
            camera_id=camera_id,
            retention=config.retention,
            plate_service=ctx.plate_service,
            plate_reads=plate_reads,
            scene_tracker=scene_tracker,  # Track vehicles/people entering and exiting
            # plate_conf_threshold default is 0.65, which should work with pattern-boosted confidence
        )
        print("intent:", classified.intent, classified.conf, "event:", event_id)

        # 3) Print detections summary
        print("Detections:")
        if not vr.detections:
            print("  (none)")
        else:
            for det in vr.detections:
                print("  -", format_detection(det))

        # 4) Evidence summary (new world)
        print("\nEvidence (first 15):")
        for ev in (vr.evidence[:15] if vr.evidence else []):
            print(f"  - {ev.source}.{ev.feature}={ev.value} conf={ev.conf:.2f} obj={ev.object_id}")


        # 5) Final classified intent
        print("\nClassified intent:")
        print(f"  intent  = {classified.intent}")
        print(f"  conf    = {classified.conf:.2f}")
        print(f"  urgency = {classified.urgency}")
        if (vr.ocr_raw):
            print("\nOCR tokens:")
            print(f"  raw: {vr.ocr_raw}")
        else:
            print("\nOCR tokens: (none)")

        print("\n--- TRACE ---")
        if classified.trace:
            for line in classified.trace:
                print(line)

                print()

        results.append((folder, file_path, vr, classified))

    return results


def main():
    parser = argparse.ArgumentParser(description="EchoBell dataset test harness.")
    parser.add_argument(
        "--db",
        default=os.path.join(ROOT, "data", "doorbell.db"),
        help="Path to doorbell.db"
    )
    parser.add_argument(
        "--dataset",
        default=os.path.join(ROOT, "data", "test"),
        help="Dataset root directory containing subfolders of images"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=True,
        help="Enable YOLO debug output"
    )
    args = parser.parse_args()

    run_dataset(args.db, args.dataset, debug=args.debug)


if __name__ == "__main__":
    main()
