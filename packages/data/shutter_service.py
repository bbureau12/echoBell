"""
Camera Shutter Service

Manages polygon-based ignore regions for cameras.
Shutters define areas where YOLO detections should be filtered out.

Common use cases:
- Ignore sky/trees (false person detections from leaves)
- Ignore neighbor's property (privacy + reduce false alerts)
- Ignore TV screens showing people/vehicles
- Ignore static background objects (statues, parked cars)
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import List, Tuple, Optional
import numpy as np


Point = Tuple[float, float]  # Normalized coordinates (0.0 - 1.0)


@dataclass
class Shutter:
    """
    A polygon-based ignore region for a camera.
    
    Attributes:
        id: Database ID
        camera_id: Camera this shutter belongs to
        name: Optional label (e.g., "neighbor's driveway")
        mode: 'ignore' (filter out detections) or 'allow' (inverse mask, future)
        polygon: List of normalized points [[x1,y1], [x2,y2], ...]
        enabled: Whether this shutter is active
    """
    id: int
    camera_id: int
    name: Optional[str]
    mode: str
    polygon: List[Point]
    enabled: bool


class ShutterService:
    """Service for managing camera shutters (ignore regions)"""
    
    @staticmethod
    def create_shutter(
        conn: sqlite3.Connection,
        camera_id: int,
        polygon: List[Point],
        name: Optional[str] = None,
        mode: str = "ignore",
        enabled: bool = True
    ) -> int:
        """
        Create a new shutter for a camera.
        
        Args:
            conn: Database connection
            camera_id: Camera ID
            polygon: List of normalized (x, y) points, e.g., [(0.1, 0.2), (0.3, 0.4), ...]
            name: Optional descriptive name
            mode: 'ignore' (default) or 'allow'
            enabled: Whether shutter is active
            
        Returns:
            ID of created shutter
        """
        polygon_json = json.dumps([[x, y] for x, y in polygon])
        
        cursor = conn.execute(
            """
            INSERT INTO camera_shutters (camera_id, name, mode, polygon_json, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (camera_id, name, mode, polygon_json, 1 if enabled else 0)
        )
        conn.commit()
        return cursor.lastrowid
    
    @staticmethod
    def get_shutters(
        conn: sqlite3.Connection,
        camera_id: int,
        enabled_only: bool = True
    ) -> List[Shutter]:
        """
        Get all shutters for a camera.
        
        Args:
            conn: Database connection
            camera_id: Camera ID
            enabled_only: Only return enabled shutters
            
        Returns:
            List of Shutter objects
        """
        query = """
            SELECT id, camera_id, name, mode, polygon_json, enabled
            FROM camera_shutters
            WHERE camera_id = ?
        """
        params: List = [camera_id]
        
        if enabled_only:
            query += " AND enabled = 1"
        
        rows = conn.execute(query, params).fetchall()
        
        shutters = []
        for row in rows:
            shutter_id, cam_id, name, mode, poly_json, enabled = row
            polygon = [tuple(pt) for pt in json.loads(poly_json)]
            shutters.append(Shutter(
                id=shutter_id,
                camera_id=cam_id,
                name=name,
                mode=mode,
                polygon=polygon,
                enabled=bool(enabled)
            ))
        
        return shutters
    
    @staticmethod
    def update_shutter(
        conn: sqlite3.Connection,
        shutter_id: int,
        polygon: Optional[List[Point]] = None,
        name: Optional[str] = None,
        enabled: Optional[bool] = None
    ) -> None:
        """Update shutter properties"""
        updates = []
        params = []
        
        if polygon is not None:
            updates.append("polygon_json = ?")
            params.append(json.dumps([[x, y] for x, y in polygon]))
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        
        if not updates:
            return
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(shutter_id)
        
        query = f"UPDATE camera_shutters SET {', '.join(updates)} WHERE id = ?"
        conn.execute(query, params)
        conn.commit()
    
    @staticmethod
    def delete_shutter(conn: sqlite3.Connection, shutter_id: int) -> None:
        """Delete a shutter"""
        conn.execute("DELETE FROM camera_shutters WHERE id = ?", (shutter_id,))
        conn.commit()
    
    @staticmethod
    def is_point_in_shutter_region(
        x: float,
        y: float,
        shutters: List[Shutter],
        image_width: int,
        image_height: int
    ) -> bool:
        """
        Check if a point (in pixel coordinates) is inside any shutter polygon.
        
        Args:
            x, y: Pixel coordinates
            shutters: List of shutters to check
            image_width, image_height: Image dimensions
            
        Returns:
            True if point is inside any ignore shutter
        """
        # Normalize to 0-1
        x_norm = x / image_width
        y_norm = y / image_height
        
        for shutter in shutters:
            if shutter.mode != "ignore":
                continue
            
            # Convert polygon to numpy array for cv2.pointPolygonTest
            poly_points = np.array([[px, py] for px, py in shutter.polygon], dtype=np.float32)
            
            # pointPolygonTest returns positive if inside, negative if outside, 0 if on edge
            import cv2
            result = cv2.pointPolygonTest(poly_points, (x_norm, y_norm), False)
            
            if result >= 0:  # Inside or on edge
                return True
        
        return False
    
    @staticmethod
    def is_bbox_in_shutter_region(
        bbox: Tuple[int, int, int, int],
        shutters: List[Shutter],
        image_width: int,
        image_height: int,
        threshold: float = 0.5
    ) -> bool:
        """
        Check if a bounding box overlaps with any shutter polygon.
        
        Args:
            bbox: (x1, y1, x2, y2) in pixel coordinates
            shutters: List of shutters to check
            image_width, image_height: Image dimensions
            threshold: Fraction of bbox area that must be in shutter to filter (0.0-1.0)
                      0.5 = filter if >50% of bbox is in shutter region
                      
        Returns:
            True if bbox should be filtered out
        """
        if not shutters:
            return False
        
        x1, y1, x2, y2 = bbox
        
        # Quick check: bbox center
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        
        if threshold <= 0.5:
            # For threshold <= 0.5, just check center point (faster)
            return ShutterService.is_point_in_shutter_region(
                cx, cy, shutters, image_width, image_height
            )
        
        # For higher thresholds, check multiple points
        # Sample 9 points across the bbox
        points = [
            (x1, y1), (cx, y1), (x2, y1),      # Top row
            (x1, cy), (cx, cy), (x2, cy),      # Middle row
            (x1, y2), (cx, y2), (x2, y2)       # Bottom row
        ]
        
        points_in_shutter = sum(
            1 for px, py in points
            if ShutterService.is_point_in_shutter_region(px, py, shutters, image_width, image_height)
        )
        
        fraction_in_shutter = points_in_shutter / len(points)
        return fraction_in_shutter >= threshold
    
    @staticmethod
    def filter_detections(
        detections: List,
        shutters: List[Shutter],
        image_width: int,
        image_height: int,
        threshold: float = 0.5
    ) -> List:
        """
        Filter out detections that overlap with shutter regions.
        
        Args:
            detections: List of Detection objects with .box attribute
            shutters: List of Shutter objects
            image_width, image_height: Image dimensions
            threshold: Overlap threshold for filtering
            
        Returns:
            Filtered list of detections
        """
        if not shutters:
            return detections
        
        filtered = []
        for det in detections:
            if hasattr(det, 'box'):
                bbox = det.box
                if not ShutterService.is_bbox_in_shutter_region(
                    bbox, shutters, image_width, image_height, threshold
                ):
                    filtered.append(det)
            else:
                # No box info, keep it
                filtered.append(det)
        
        return filtered
