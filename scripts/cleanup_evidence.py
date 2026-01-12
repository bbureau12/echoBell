#!/usr/bin/env python3
"""
Evidence Cleanup Maintenance Script

Deletes evidence records older than the configured retention period.
This script is designed to be run periodically (e.g., via cron, Task Scheduler).

Usage:
    # Dry run (show what would be deleted)
    python scripts/cleanup_evidence.py --dry-run
    
    # Actually delete old evidence
    python scripts/cleanup_evidence.py
    
    # Use custom retention period (overrides config)
    python scripts/cleanup_evidence.py --retention-days 60
    
    # Use custom database path
    python scripts/cleanup_evidence.py --db-path /custom/path/doorbell.db
    
    # Verbose output
    python scripts/cleanup_evidence.py --verbose

Design:
- NOT called automatically by the system
- Meant to be scheduled externally (cron, systemd timer, Windows Task Scheduler)
- Respects config.json retention settings by default
- Provides dry-run mode for safety
- Returns exit code 0 on success, 1 on error

Example Cron Entry (daily at 2 AM):
    0 2 * * * cd /path/to/echoBell && python scripts/cleanup_evidence.py >> logs/cleanup.log 2>&1

Example Windows Task Scheduler:
    Program: python
    Arguments: scripts/cleanup_evidence.py
    Start in: D:\Projects\echoBell\echoBell
    Schedule: Daily at 2:00 AM
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.data.evidence_service import EvidenceService, EvidenceRetentionConfig


def load_config(config_path: Path) -> dict:
    """Load configuration from JSON file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in config file: {e}", file=sys.stderr)
        sys.exit(1)


def format_timestamp(ts: int) -> str:
    """Format Unix timestamp as readable string."""
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def format_bytes(size: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def main():
    parser = argparse.ArgumentParser(
        description='Clean up old evidence records from the database.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--db-path',
        type=Path,
        default=None,
        help='Path to database file (default: from config.json)'
    )
    
    parser.add_argument(
        '--config',
        type=Path,
        default=Path(__file__).parent.parent / 'config.json',
        help='Path to config file (default: config.json)'
    )
    
    parser.add_argument(
        '--retention-days',
        type=int,
        default=None,
        help='Override retention period in days (default: from config)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=None,
        help='Override cleanup batch size (default: from config)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output with detailed statistics'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompt (use with caution!)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Get database path
    if args.db_path:
        db_path = args.db_path
    else:
        db_path = Path(config.get('db_path', 'data/doorbell.db'))
    
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    
    # Get retention settings
    retention_config = config.get('retention', {})
    retention_days = args.retention_days or retention_config.get('evidence_retention_days', 30)
    batch_size = args.batch_size or retention_config.get('evidence_cleanup_batch_size', 1000)
    cleanup_enabled = retention_config.get('evidence_cleanup_enabled', True)
    
    if not cleanup_enabled and not args.force:
        print("ERROR: Evidence cleanup is disabled in config.json", file=sys.stderr)
        print("Use --force to override, or enable in config", file=sys.stderr)
        sys.exit(1)
    
    # Create service
    service_config = EvidenceRetentionConfig(
        retention_days=retention_days,
        cleanup_batch_size=batch_size,
        enabled=cleanup_enabled,
    )
    service = EvidenceService(config=service_config)
    
    # Connect to database
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as e:
        print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Get statistics before cleanup
        stats = service.get_retention_stats(conn)
        
        if args.verbose:
            print("=" * 60)
            print("EVIDENCE RETENTION STATISTICS")
            print("=" * 60)
            print(f"Database: {db_path}")
            print(f"Total evidence records: {stats['total_records']:,}")
            print(f"Oldest record: {format_timestamp(stats['oldest_record_ts'])}")
            print(f"Newest record: {format_timestamp(stats['newest_record_ts'])}")
            print(f"Retention period: {retention_days} days")
            print(f"Cutoff timestamp: {format_timestamp(stats['retention_cutoff_ts'])}")
            print(f"Records due for cleanup: {stats['records_due_for_cleanup']:,}")
            print(f"Cleanup enabled: {cleanup_enabled}")
            print("=" * 60)
            print()
        
        if stats['records_due_for_cleanup'] == 0:
            print("✓ No evidence records need cleanup.")
            print(f"  All {stats['total_records']:,} records are within retention period.")
            return 0
        
        # Show what will be deleted
        cutoff_date = datetime.fromtimestamp(stats['retention_cutoff_ts'])
        print(f"Found {stats['records_due_for_cleanup']:,} evidence records older than {retention_days} days")
        print(f"  (created before {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')})")
        
        if args.dry_run:
            print()
            print("DRY RUN: No records will be deleted.")
            print(f"  Would delete {stats['records_due_for_cleanup']:,} records")
            print(f"  Would retain {stats['total_records'] - stats['records_due_for_cleanup']:,} records")
            return 0
        
        # Confirmation prompt (unless --force)
        if not args.force:
            print()
            response = input("Proceed with deletion? [y/N]: ").strip().lower()
            if response not in ('y', 'yes'):
                print("Cancelled.")
                return 0
        
        # Perform cleanup
        print()
        print("Deleting old evidence records...")
        deleted = service.cleanup_old_evidence(conn, dry_run=False)
        
        print(f"✓ Successfully deleted {deleted:,} evidence records")
        
        # Show after statistics
        if args.verbose:
            stats_after = service.get_retention_stats(conn)
            print()
            print("=" * 60)
            print("AFTER CLEANUP")
            print("=" * 60)
            print(f"Remaining records: {stats_after['total_records']:,}")
            print(f"Oldest record: {format_timestamp(stats_after['oldest_record_ts'])}")
            print(f"Space potentially freed: (run VACUUM to reclaim)")
            print("=" * 60)
        
        # Suggest running VACUUM
        if deleted > 1000:
            print()
            print("TIP: Run 'VACUUM' to reclaim disk space:")
            print(f"  sqlite3 {db_path} 'VACUUM;'")
        
        return 0
        
    except Exception as e:
        print(f"ERROR: Cleanup failed: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1
        
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
