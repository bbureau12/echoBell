#!/usr/bin/env python3
"""
Cleanup Downloaded Images

Removes old images downloaded from edge devices by the policy server.
These are temporary files created when policies download snapshot_url images.

Usage:
    # Dry run (show what would be deleted)
    python tools/cleanup_downloaded_images.py --dry-run
    
    # Delete images older than 24 hours (default)
    python tools/cleanup_downloaded_images.py
    
    # Delete images older than 6 hours
    python tools/cleanup_downloaded_images.py --max-age 6
    
    # Force delete without confirmation
    python tools/cleanup_downloaded_images.py --force
"""

import argparse
import os
import sys
import time
from pathlib import Path


def cleanup_downloaded_images(
    directory: str = "data/downloaded_images",
    max_age_hours: int = 24,
    dry_run: bool = False,
    verbose: bool = False
) -> int:
    """
    Remove downloaded images older than max_age_hours.
    
    Args:
        directory: Directory containing downloaded images
        max_age_hours: Delete files older than this many hours
        dry_run: If True, show what would be deleted but don't delete
        verbose: If True, show detailed information
        
    Returns:
        Number of files deleted (or would be deleted if dry_run=True)
    """
    download_dir = Path(directory)
    
    if not download_dir.exists():
        if verbose:
            print(f"Directory does not exist: {download_dir}")
        return 0
    
    cutoff_time = time.time() - (max_age_hours * 3600)
    deleted = 0
    total_size = 0
    
    # Supported image extensions
    extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
    
    for filepath in download_dir.iterdir():
        if not filepath.is_file():
            continue
            
        # Only process image files
        if filepath.suffix.lower() not in extensions:
            continue
        
        # Check age
        file_mtime = filepath.stat().st_mtime
        if file_mtime < cutoff_time:
            file_size = filepath.stat().st_size
            total_size += file_size
            
            if verbose:
                age_hours = (time.time() - file_mtime) / 3600
                size_kb = file_size / 1024
                print(f"  {filepath.name}: {age_hours:.1f}h old, {size_kb:.1f} KB")
            
            if not dry_run:
                filepath.unlink()
            
            deleted += 1
    
    return deleted, total_size


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup old downloaded images from edge devices"
    )
    parser.add_argument(
        '--directory',
        type=str,
        default='data/downloaded_images',
        help='Directory containing downloaded images (default: data/downloaded_images)'
    )
    parser.add_argument(
        '--max-age',
        type=int,
        default=24,
        help='Delete images older than N hours (default: 24)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompt'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed information about each file'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Downloaded Images Cleanup")
    print("=" * 60)
    print(f"Directory: {args.directory}")
    print(f"Max age: {args.max_age} hours")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'DELETE'}")
    print("=" * 60)
    print()
    
    # Check if directory exists
    if not Path(args.directory).exists():
        print(f"✓ Directory does not exist yet: {args.directory}")
        print("  (No cleanup needed)")
        return 0
    
    # Count files
    download_dir = Path(args.directory)
    extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
    total_files = sum(1 for f in download_dir.iterdir() 
                     if f.is_file() and f.suffix.lower() in extensions)
    
    print(f"Total image files: {total_files}")
    
    # Do cleanup
    deleted, total_size = cleanup_downloaded_images(
        directory=args.directory,
        max_age_hours=args.max_age,
        dry_run=args.dry_run,
        verbose=args.verbose
    )
    
    print()
    
    if deleted == 0:
        print("✓ No old images to clean up")
        return 0
    
    size_mb = total_size / (1024 * 1024)
    
    if args.dry_run:
        print(f"DRY RUN: Would delete {deleted} images ({size_mb:.2f} MB)")
        print(f"Run without --dry-run to actually delete files")
        return 0
    
    # Confirmation prompt (unless --force)
    if not args.force:
        response = input(f"\nDelete {deleted} images ({size_mb:.2f} MB)? [y/N]: ").strip().lower()
        if response not in ('y', 'yes'):
            print("Cancelled.")
            return 0
    
    # Actually delete
    deleted, total_size = cleanup_downloaded_images(
        directory=args.directory,
        max_age_hours=args.max_age,
        dry_run=False,
        verbose=args.verbose
    )
    
    print(f"✓ Deleted {deleted} images ({size_mb:.2f} MB)")
    print()
    print("TIP: Schedule this script to run daily:")
    print("  cron: 0 2 * * * /path/to/cleanup_downloaded_images.py")
    print("  Windows Task Scheduler: python cleanup_downloaded_images.py")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
