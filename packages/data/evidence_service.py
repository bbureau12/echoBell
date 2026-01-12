"""
Evidence Service

Manages persistent storage and querying of evidence data for people and vehicles.
Supports temporal queries, analytics, and configurable retention policies.

Design Philosophy:
- Evidence is ephemeral by nature (observations are time-bound)
- Retention policy prevents unbounded growth
- Queryable for debugging, analytics, and pattern detection
- Separates concerns: Evidence dataclass (in-memory) vs evidence_log (persistent)

Usage:
    from packages.data.evidence_service import EvidenceService, EvidenceRetentionConfig
    
    config = EvidenceRetentionConfig(retention_days=30)
    service = EvidenceService(config=config)
    
    # Store evidence
    service.log_evidence(conn, event_id="evt_123", camera_id=1, evidence_list=[...])
    
    # Query evidence
    evidence = service.get_evidence_for_event(conn, event_id="evt_123")
    
    # Cleanup old evidence (call from maintenance script)
    deleted = service.cleanup_old_evidence(conn)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, asdict
from time import time
from typing import List, Optional, Dict, Any

# Import Evidence from common types
# Note: This creates a circular dependency risk, so we'll use TYPE_CHECKING
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from packages.common.types import Evidence


@dataclass
class EvidenceRetentionConfig:
    """
    Configuration for evidence retention policy.
    
    Attributes:
        retention_days: How many days to keep evidence (default: 30)
        cleanup_batch_size: Max records to delete in one cleanup run (default: 1000)
        enabled: Whether retention cleanup is enabled (default: True)
    """
    retention_days: int = 30
    cleanup_batch_size: int = 1000
    enabled: bool = True
    
    @property
    def retention_seconds(self) -> int:
        """Convert retention_days to seconds for timestamp comparisons."""
        return self.retention_days * 24 * 60 * 60


class EvidenceService:
    """
    Service for managing evidence persistence and querying.
    
    Responsibilities:
    - Store Evidence objects to database
    - Query evidence by event, track, camera, or time range
    - Clean up old evidence based on retention policy
    - Generate analytics summaries
    """
    
    def __init__(self, config: Optional[EvidenceRetentionConfig] = None):
        """
        Initialize evidence service with retention configuration.
        
        Args:
            config: Retention policy config (uses defaults if None)
        """
        self.config = config or EvidenceRetentionConfig()
    
    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        """
        Ensure evidence_log table exists.
        
        This is idempotent and safe to call multiple times.
        Migration 009 creates the table, but this ensures it exists.
        """
        # Schema is created by migration 009_add_evidence_tracking.sql
        # This method is a safety check for standalone usage
        cur = conn.cursor()
        cur.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='evidence_log';
        """)
        if not cur.fetchone():
            raise RuntimeError(
                "evidence_log table does not exist. "
                "Run migrations: python storage/dao.py"
            )
    
    def log_evidence(
        self,
        conn: sqlite3.Connection,
        event_id: Optional[str],
        camera_id: Optional[int],
        evidence_list: List[Evidence],
        track_type: Optional[str] = None,
        track_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Store a list of Evidence objects to the database.
        
        Args:
            conn: Database connection
            event_id: Associated visitor event ID (can be None)
            camera_id: Camera that produced this evidence
            evidence_list: List of Evidence objects to store
            track_type: Optional track type ('person' or 'vehicle')
            track_key: Optional track key (plate_hmac, visitor_id, temp UUID)
            metadata: Optional additional context as JSON
            
        Returns:
            Number of evidence records inserted
        """
        if not evidence_list:
            return 0
        
        created_ts = int(time())
        metadata_json = json.dumps(metadata) if metadata else None
        
        cur = conn.cursor()
        inserted = 0
        
        for ev in evidence_list:
            # Extract object_id from Evidence if present
            obj_id = getattr(ev, 'object_id', None)
            
            cur.execute("""
                INSERT INTO evidence_log (
                    created_ts, event_id, camera_id,
                    source, feature, value, conf,
                    object_id, track_type, track_key,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                created_ts, event_id, camera_id,
                ev.source, ev.feature, ev.value, ev.conf,
                obj_id, track_type, track_key,
                metadata_json
            ))
            inserted += 1
        
        conn.commit()
        return inserted
    
    def get_evidence_for_event(
        self,
        conn: sqlite3.Connection,
        event_id: str
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all evidence for a specific event.
        
        Args:
            conn: Database connection
            event_id: Event ID to query
            
        Returns:
            List of evidence dictionaries with all fields
        """
        cur = conn.cursor()
        cur.execute("""
            SELECT id, created_ts, event_id, camera_id,
                   source, feature, value, conf,
                   object_id, track_type, track_key,
                   metadata_json
            FROM evidence_log
            WHERE event_id = ?
            ORDER BY created_ts ASC, id ASC
        """, (event_id,))
        
        return [self._row_to_dict(row) for row in cur.fetchall()]
    
    def get_evidence_for_track(
        self,
        conn: sqlite3.Connection,
        track_type: str,
        track_key: str,
        since_ts: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all evidence for a specific person or vehicle track.
        
        Args:
            conn: Database connection
            track_type: 'person' or 'vehicle'
            track_key: plate_hmac, visitor_id, or temp UUID
            since_ts: Optional timestamp filter (only evidence after this time)
            limit: Optional max number of records to return
            
        Returns:
            List of evidence dictionaries ordered by time (newest first)
        """
        cur = conn.cursor()
        
        query = """
            SELECT id, created_ts, event_id, camera_id,
                   source, feature, value, conf,
                   object_id, track_type, track_key,
                   metadata_json
            FROM evidence_log
            WHERE track_type = ? AND track_key = ?
        """
        params = [track_type, track_key]
        
        if since_ts is not None:
            query += " AND created_ts >= ?"
            params.append(since_ts)
        
        query += " ORDER BY created_ts DESC, id DESC"
        
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        
        cur.execute(query, params)
        return [self._row_to_dict(row) for row in cur.fetchall()]
    
    def get_evidence_by_source_feature(
        self,
        conn: sqlite3.Connection,
        source: str,
        feature: str,
        value: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: Optional[int] = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query evidence by source and feature (e.g., all "vision.vehicle_type" evidence).
        
        Args:
            conn: Database connection
            source: Evidence source ('vision', 'ocr', 'scene', etc.)
            feature: Evidence feature ('vehicle_type', 'color', etc.)
            value: Optional value filter (e.g., 'bicycle')
            since_ts: Optional timestamp filter
            limit: Max records to return (default: 100)
            
        Returns:
            List of evidence dictionaries ordered by time (newest first)
        """
        cur = conn.cursor()
        
        query = """
            SELECT id, created_ts, event_id, camera_id,
                   source, feature, value, conf,
                   object_id, track_type, track_key,
                   metadata_json
            FROM evidence_log
            WHERE source = ? AND feature = ?
        """
        params = [source, feature]
        
        if value is not None:
            query += " AND value = ?"
            params.append(value)
        
        if since_ts is not None:
            query += " AND created_ts >= ?"
            params.append(since_ts)
        
        query += " ORDER BY created_ts DESC, id DESC LIMIT ?"
        params.append(limit)
        
        cur.execute(query, params)
        return [self._row_to_dict(row) for row in cur.fetchall()]
    
    def get_evidence_summary_by_track(
        self,
        conn: sqlite3.Connection,
        track_type: str,
        track_key: str,
    ) -> Dict[str, Any]:
        """
        Get aggregated evidence summary for a track (useful for analytics).
        
        Args:
            conn: Database connection
            track_type: 'person' or 'vehicle'
            track_key: plate_hmac, visitor_id, or temp UUID
            
        Returns:
            Dictionary with summary stats:
            - total_evidence_count
            - unique_sources
            - unique_features
            - avg_confidence
            - first_seen_ts
            - last_seen_ts
            - most_common_values (top 5)
        """
        cur = conn.cursor()
        
        # Basic stats
        cur.execute("""
            SELECT 
                COUNT(*) as total_count,
                COUNT(DISTINCT source) as unique_sources,
                COUNT(DISTINCT feature) as unique_features,
                AVG(conf) as avg_conf,
                MIN(created_ts) as first_seen,
                MAX(created_ts) as last_seen
            FROM evidence_log
            WHERE track_type = ? AND track_key = ?
        """, (track_type, track_key))
        
        row = cur.fetchone()
        summary = {
            'total_evidence_count': row[0] or 0,
            'unique_sources': row[1] or 0,
            'unique_features': row[2] or 0,
            'avg_confidence': round(row[3], 3) if row[3] else 0.0,
            'first_seen_ts': row[4],
            'last_seen_ts': row[5],
        }
        
        # Most common values
        cur.execute("""
            SELECT value, COUNT(*) as count
            FROM evidence_log
            WHERE track_type = ? AND track_key = ?
            GROUP BY value
            ORDER BY count DESC
            LIMIT 5
        """, (track_type, track_key))
        
        summary['most_common_values'] = [
            {'value': row[0], 'count': row[1]}
            for row in cur.fetchall()
        ]
        
        return summary
    
    def cleanup_old_evidence(
        self,
        conn: sqlite3.Connection,
        dry_run: bool = False,
    ) -> int:
        """
        Delete evidence older than retention_days.
        
        This should be called periodically by a maintenance script.
        NOT called automatically to give explicit control over cleanup.
        
        Args:
            conn: Database connection
            dry_run: If True, count records but don't delete (default: False)
            
        Returns:
            Number of records deleted (or would be deleted if dry_run=True)
        """
        if not self.config.enabled:
            return 0
        
        cutoff_ts = int(time()) - self.config.retention_seconds
        
        cur = conn.cursor()
        
        # Count records to delete
        cur.execute("""
            SELECT COUNT(*) FROM evidence_log
            WHERE created_ts < ?
        """, (cutoff_ts,))
        total_to_delete = cur.fetchone()[0]
        
        if dry_run:
            return total_to_delete
        
        # Delete in batches to avoid locking
        deleted = 0
        batch_size = self.config.cleanup_batch_size
        
        while deleted < total_to_delete:
            cur.execute("""
                DELETE FROM evidence_log
                WHERE id IN (
                    SELECT id FROM evidence_log
                    WHERE created_ts < ?
                    ORDER BY created_ts ASC
                    LIMIT ?
                )
            """, (cutoff_ts, batch_size))
            
            batch_deleted = cur.rowcount
            if batch_deleted == 0:
                break
            
            deleted += batch_deleted
            conn.commit()
        
        return deleted
    
    def get_retention_stats(
        self,
        conn: sqlite3.Connection
    ) -> Dict[str, Any]:
        """
        Get statistics about evidence retention and storage.
        
        Returns:
            Dictionary with:
            - total_records
            - oldest_record_ts
            - newest_record_ts
            - retention_cutoff_ts
            - records_due_for_cleanup
            - estimated_cleanup_date (next cleanup if run now)
        """
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                MIN(created_ts) as oldest,
                MAX(created_ts) as newest
            FROM evidence_log
        """)
        
        row = cur.fetchone()
        total = row[0] or 0
        oldest_ts = row[1]
        newest_ts = row[2]
        
        cutoff_ts = int(time()) - self.config.retention_seconds
        
        cur.execute("""
            SELECT COUNT(*) FROM evidence_log
            WHERE created_ts < ?
        """, (cutoff_ts,))
        
        due_for_cleanup = cur.fetchone()[0]
        
        return {
            'total_records': total,
            'oldest_record_ts': oldest_ts,
            'newest_record_ts': newest_ts,
            'retention_cutoff_ts': cutoff_ts,
            'records_due_for_cleanup': due_for_cleanup,
            'retention_days_configured': self.config.retention_days,
            'cleanup_enabled': self.config.enabled,
        }
    
    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        """Convert SQLite row tuple to dictionary."""
        return {
            'id': row[0],
            'created_ts': row[1],
            'event_id': row[2],
            'camera_id': row[3],
            'source': row[4],
            'feature': row[5],
            'value': row[6],
            'conf': row[7],
            'object_id': row[8],
            'track_type': row[9],
            'track_key': row[10],
            'metadata_json': row[11],
        }


# Convenience functions for standalone usage

def create_evidence_service(
    retention_days: int = 30,
    cleanup_batch_size: int = 1000,
    enabled: bool = True,
) -> EvidenceService:
    """
    Factory function to create EvidenceService with custom config.
    
    Args:
        retention_days: How many days to keep evidence
        cleanup_batch_size: Max records to delete per cleanup batch
        enabled: Whether cleanup is enabled
        
    Returns:
        Configured EvidenceService instance
    """
    config = EvidenceRetentionConfig(
        retention_days=retention_days,
        cleanup_batch_size=cleanup_batch_size,
        enabled=enabled,
    )
    return EvidenceService(config=config)
