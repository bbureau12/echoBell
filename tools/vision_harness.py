import os
import sys
import sqlite3
import argparse
import glob

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from packages.perception.vision import snapshot_and_detect
from packages.classify.intent import classify


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
    
    # Clean up any annotated files before running tests
    cleanup_annotated_files(dataset_root)

    results = []

    for folder, file_path in walk_dataset(dataset_root):
        print("=" * 80)
        print(f"[TEST CASE] folder={folder} file={file_path}")

        # 1) Run vision
        vr = snapshot_and_detect(db_path, file_path, debug=debug)

        # 2) Run intent classification (just vision; text="")
        classified = classify("", vr, db_path=db_path)

        # 3) Print detections summary
        print("Detections:")
        if not vr.detections:
            print("  (none)")
        else:
            for det in vr.detections:
                print("  -", format_detection(det))

        # 4) Print rule results
        print("\nVision rule result:")
        print(f"  vision_intent  = {vr.vision_intent}")
        print(f"  vision_conf    = {vr.vision_conf}")
        print(f"  vision_urgency = {vr.vision_urgency}")

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
        default=os.path.join(ROOT, "data"),
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
