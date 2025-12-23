# packages/data/snapshot_service.py

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class SnapshotMetadata:
    """Metadata for saving a snapshot."""
    camera_id: int
    timestamp: int
    visitor_event_id: Optional[str] = None  # UUID string from visitor_events


class SnapshotService:
    """
    Service for saving and resizing snapshots to disk and logging them to the database.
    """

    def __init__(self, output_dir: str = "data/img_log", max_size: int = 1920):
        """
        Args:
            output_dir: Directory where snapshots will be saved
            max_size: Maximum dimension (width or height) for resized images
        """
        self.output_dir = output_dir
        self.max_size = max_size
        
        # Create output directory if it doesn't exist
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    def save_snapshot(
        self,
        conn: sqlite3.Connection,
        image: np.ndarray,
        metadata: SnapshotMetadata,
        original_extension: str = ".jpg",
    ) -> tuple[str, int]:
        """
        Save an image snapshot to disk and log it to the database.

        Args:
            conn: Database connection
            image: Image as numpy array (BGR format from OpenCV)
            metadata: Snapshot metadata (camera_id, timestamp, visitor_event_id)
            original_extension: File extension to use (default: .jpg)

        Returns:
            Tuple of (filename, snapshot_id)
        """
        # Generate unique filename with GUID
        guid = str(uuid.uuid4())
        filename = f"{guid}{original_extension}"
        filepath = os.path.join(self.output_dir, filename)

        # Resize image if needed
        resized_image = self._resize_image(image)

        # Save to disk
        cv2.imwrite(filepath, resized_image)

        # Insert into database
        cursor = conn.execute(
            """
            INSERT INTO snapshots (filename, timestamp, camera_id, visitor_event_id)
            VALUES (?, ?, ?, ?)
            """,
            (filename, metadata.timestamp, metadata.camera_id, metadata.visitor_event_id),
        )
        snapshot_id = cursor.lastrowid

        return filename, snapshot_id

    def _resize_image(self, image: np.ndarray) -> np.ndarray:
        """
        Resize image so that the maximum dimension (width or height) is max_size.

        Args:
            image: Input image as numpy array

        Returns:
            Resized image
        """
        height, width = image.shape[:2]
        
        # Check if resizing is needed
        if max(height, width) <= self.max_size:
            return image

        # Calculate new dimensions
        if height > width:
            new_height = self.max_size
            new_width = int(width * (self.max_size / height))
        else:
            new_width = self.max_size
            new_height = int(height * (self.max_size / width))

        # Resize using high-quality interpolation
        resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
        return resized

    def get_last_snapshot_timestamp(
        self,
        conn: sqlite3.Connection,
        camera_id: int,
        visitor_event_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Get the timestamp of the most recent snapshot for a camera/visitor.

        Args:
            conn: Database connection
            camera_id: Camera ID
            visitor_event_id: Optional visitor event ID to filter by

        Returns:
            Unix timestamp of last snapshot, or None if no snapshots exist
        """
        if visitor_event_id is not None:
            row = conn.execute(
                """
                SELECT MAX(timestamp) FROM snapshots
                WHERE camera_id = ? AND visitor_event_id = ?
                """,
                (camera_id, visitor_event_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT MAX(timestamp) FROM snapshots
                WHERE camera_id = ?
                """,
                (camera_id,),
            ).fetchone()

        return row[0] if row and row[0] is not None else None

    def should_save_snapshot(
        self,
        conn: sqlite3.Connection,
        visitor_id: str,
        camera_id: int,
        now_ts: int,
        is_new_visitor: bool,
        min_interval_seconds: int = 3600,  # 1 hour default
    ) -> bool:
        """
        Determine if a snapshot should be saved based on visitor status and time since last snapshot.

        Args:
            conn: Database connection
            visitor_id: Visitor ID
            camera_id: Camera ID
            now_ts: Current timestamp
            is_new_visitor: True if this is a new visitor
            min_interval_seconds: Minimum time between snapshots (default: 3600 = 1 hour)

        Returns:
            True if snapshot should be saved
        """
        # Always save for new visitors
        if is_new_visitor:
            return True

        # Check last snapshot time for this visitor
        # We need to find visitor_events for this visitor and check their snapshots
        row = conn.execute(
            """
            SELECT MAX(s.timestamp)
            FROM snapshots s
            INNER JOIN visitor_events ve ON s.visitor_event_id = ve.event_id
            WHERE ve.visitor_id = ? AND s.camera_id = ?
            """,
            (visitor_id, camera_id),
        ).fetchone()

        last_snapshot_ts = row[0] if row and row[0] is not None else None

        # If no previous snapshot or more than min_interval_seconds have passed
        if last_snapshot_ts is None:
            return True

        time_since_last = now_ts - last_snapshot_ts
        return time_since_last >= min_interval_seconds
