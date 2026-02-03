"""
Voiceprint Service

Manages speaker voiceprints for trusted person identification using SpeechBrain embeddings.

Usage:
    from packages.data.voiceprint_service import VoiceprintService, Voiceprint
    
    # Store voiceprint
    service = VoiceprintService()
    voiceprint_id = service.create_voiceprint(
        conn,
        trusted_id=1,
        embedding=embedding_vector,
        model_name="speechbrain_ecapa",
        quality_score=0.95
    )
    
    # Match speaker
    matches = service.match_voiceprint(
        conn,
        embedding=test_embedding,
        model_name="speechbrain_ecapa",
        threshold=0.75
    )
"""

import sqlite3
import numpy as np
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Voiceprint:
    """Represents a stored voiceprint for a trusted person."""
    voiceprint_id: int
    trusted_id: int
    model_name: str
    embedding_dim: int
    embedding_blob: bytes
    camera_id: Optional[int]
    created_ts: int
    quality_score: float
    audio_duration_sec: Optional[float]
    notes: Optional[str]
    
    @property
    def embedding(self) -> np.ndarray:
        """Deserialize embedding from blob."""
        return np.frombuffer(self.embedding_blob, dtype=np.float32)
    
    @property
    def created_datetime(self) -> datetime:
        """Convert timestamp to datetime."""
        return datetime.fromtimestamp(self.created_ts)


@dataclass
class VoiceprintMatch:
    """Result of voiceprint matching."""
    trusted_id: int
    trusted_name: str
    confidence: float
    voiceprint_id: int
    quality_score: float


class VoiceprintService:
    """Service for managing voiceprints and speaker identification."""
    
    @staticmethod
    def create_voiceprint(
        conn: sqlite3.Connection,
        trusted_id: int,
        embedding: np.ndarray,
        model_name: str,
        quality_score: float = 1.0,
        camera_id: Optional[int] = None,
        audio_duration_sec: Optional[float] = None,
        notes: Optional[str] = None
    ) -> int:
        """
        Store a voiceprint for a trusted person.
        
        Args:
            conn: Database connection
            trusted_id: ID of trusted person
            embedding: Voiceprint embedding vector (numpy array)
            model_name: Model used to generate embedding (e.g., "speechbrain_ecapa")
            quality_score: Quality of audio sample (0-1)
            camera_id: Optional camera/edge that captured this
            audio_duration_sec: Length of audio sample
            notes: Optional metadata
            
        Returns:
            voiceprint_id of created voiceprint
        """
        # Normalize embedding to float32
        if embedding.dtype != np.float32:
            embedding = embedding.astype(np.float32)
        
        # L2 normalize (common for speaker embeddings)
        embedding = embedding / (np.linalg.norm(embedding) + 1e-8)
        
        cursor = conn.execute(
            """
            INSERT INTO trusted_voiceprints 
            (trusted_id, model_name, embedding_dim, embedding_blob, camera_id,
             created_ts, quality_score, audio_duration_sec, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trusted_id,
                model_name,
                len(embedding),
                embedding.tobytes(),
                camera_id,
                int(datetime.now().timestamp()),
                quality_score,
                audio_duration_sec,
                notes
            )
        )
        conn.commit()
        return cursor.lastrowid
    
    @staticmethod
    def get_voiceprint(
        conn: sqlite3.Connection,
        voiceprint_id: int
    ) -> Optional[Voiceprint]:
        """Get a specific voiceprint by ID."""
        row = conn.execute(
            """
            SELECT voiceprint_id, trusted_id, model_name, embedding_dim,
                   embedding_blob, camera_id, created_ts, quality_score,
                   audio_duration_sec, notes
            FROM trusted_voiceprints
            WHERE voiceprint_id = ?
            """,
            (voiceprint_id,)
        ).fetchone()
        
        if not row:
            return None
        
        return Voiceprint(*row)
    
    @staticmethod
    def get_voiceprints_for_person(
        conn: sqlite3.Connection,
        trusted_id: int,
        model_name: Optional[str] = None
    ) -> List[Voiceprint]:
        """
        Get all voiceprints for a trusted person.
        
        Args:
            conn: Database connection
            trusted_id: ID of trusted person
            model_name: Optional filter by model name
            
        Returns:
            List of Voiceprint objects
        """
        if model_name:
            rows = conn.execute(
                """
                SELECT voiceprint_id, trusted_id, model_name, embedding_dim,
                       embedding_blob, camera_id, created_ts, quality_score,
                       audio_duration_sec, notes
                FROM trusted_voiceprints
                WHERE trusted_id = ? AND model_name = ?
                ORDER BY created_ts DESC
                """,
                (trusted_id, model_name)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT voiceprint_id, trusted_id, model_name, embedding_dim,
                       embedding_blob, camera_id, created_ts, quality_score,
                       audio_duration_sec, notes
                FROM trusted_voiceprints
                WHERE trusted_id = ?
                ORDER BY created_ts DESC
                """,
                (trusted_id,)
            ).fetchall()
        
        return [Voiceprint(*row) for row in rows]
    
    @staticmethod
    def list_voiceprints(
        conn: sqlite3.Connection,
        model_name: Optional[str] = None
    ) -> List[Voiceprint]:
        """
        List all voiceprints, optionally filtered by model.
        
        Args:
            conn: Database connection
            model_name: Optional filter by model name
            
        Returns:
            List of Voiceprint objects
        """
        if model_name:
            rows = conn.execute(
                """
                SELECT voiceprint_id, trusted_id, model_name, embedding_dim,
                       embedding_blob, camera_id, created_ts, quality_score,
                       audio_duration_sec, notes
                FROM trusted_voiceprints
                WHERE model_name = ?
                ORDER BY trusted_id, created_ts DESC
                """,
                (model_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT voiceprint_id, trusted_id, model_name, embedding_dim,
                       embedding_blob, camera_id, created_ts, quality_score,
                       audio_duration_sec, notes
                FROM trusted_voiceprints
                ORDER BY trusted_id, created_ts DESC
                """
            ).fetchall()
        
        return [Voiceprint(*row) for row in rows]
    
    @staticmethod
    def update_voiceprint(
        conn: sqlite3.Connection,
        voiceprint_id: int,
        quality_score: Optional[float] = None,
        notes: Optional[str] = None
    ) -> bool:
        """
        Update voiceprint metadata.
        
        Args:
            conn: Database connection
            voiceprint_id: ID of voiceprint to update
            quality_score: New quality score
            notes: New notes
            
        Returns:
            True if updated, False if not found
        """
        updates = []
        params = []
        
        if quality_score is not None:
            updates.append("quality_score = ?")
            params.append(quality_score)
        
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        
        if not updates:
            return True  # Nothing to update
        
        params.append(voiceprint_id)
        
        cursor = conn.execute(
            f"""
            UPDATE trusted_voiceprints
            SET {', '.join(updates)}
            WHERE voiceprint_id = ?
            """,
            params
        )
        conn.commit()
        
        return cursor.rowcount > 0
    
    @staticmethod
    def delete_voiceprint(
        conn: sqlite3.Connection,
        voiceprint_id: int
    ) -> bool:
        """
        Delete a voiceprint.
        
        Args:
            conn: Database connection
            voiceprint_id: ID of voiceprint to delete
            
        Returns:
            True if deleted, False if not found
        """
        cursor = conn.execute(
            "DELETE FROM trusted_voiceprints WHERE voiceprint_id = ?",
            (voiceprint_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    
    @staticmethod
    def delete_voiceprints_for_person(
        conn: sqlite3.Connection,
        trusted_id: int,
        model_name: Optional[str] = None
    ) -> int:
        """
        Delete all voiceprints for a trusted person.
        
        Args:
            conn: Database connection
            trusted_id: ID of trusted person
            model_name: Optional filter by model name
            
        Returns:
            Number of voiceprints deleted
        """
        if model_name:
            cursor = conn.execute(
                """
                DELETE FROM trusted_voiceprints 
                WHERE trusted_id = ? AND model_name = ?
                """,
                (trusted_id, model_name)
            )
        else:
            cursor = conn.execute(
                "DELETE FROM trusted_voiceprints WHERE trusted_id = ?",
                (trusted_id,)
            )
        
        conn.commit()
        return cursor.rowcount
    
    @staticmethod
    def match_voiceprint(
        conn: sqlite3.Connection,
        embedding: np.ndarray,
        model_name: str,
        threshold: float = 0.75,
        top_k: int = 5
    ) -> List[VoiceprintMatch]:
        """
        Match a voiceprint embedding against stored voiceprints.
        
        Uses cosine similarity for matching.
        
        Args:
            conn: Database connection
            embedding: Query voiceprint embedding
            model_name: Model name to match against
            threshold: Minimum similarity score (0-1)
            top_k: Maximum number of matches to return
            
        Returns:
            List of VoiceprintMatch objects, sorted by confidence (highest first)
        """
        # Normalize query embedding
        if embedding.dtype != np.float32:
            embedding = embedding.astype(np.float32)
        embedding = embedding / (np.linalg.norm(embedding) + 1e-8)
        
        # Get all voiceprints for this model
        rows = conn.execute(
            """
            SELECT v.voiceprint_id, v.trusted_id, v.embedding_blob, 
                   v.quality_score, tp.name
            FROM trusted_voiceprints v
            JOIN trusted_person tp ON tp.trusted_id = v.trusted_id
            WHERE v.model_name = ? AND tp.active = 1
            """,
            (model_name,)
        ).fetchall()
        
        if not rows:
            return []
        
        # Compute similarities
        matches = []
        for voiceprint_id, trusted_id, blob, quality_score, name in rows:
            stored_emb = np.frombuffer(blob, dtype=np.float32)
            
            # Cosine similarity
            similarity = float(np.dot(embedding, stored_emb))
            
            if similarity >= threshold:
                matches.append(VoiceprintMatch(
                    trusted_id=trusted_id,
                    trusted_name=name,
                    confidence=similarity,
                    voiceprint_id=voiceprint_id,
                    quality_score=quality_score
                ))
        
        # Sort by confidence (highest first)
        matches.sort(key=lambda m: m.confidence, reverse=True)
        
        return matches[:top_k]
    
    @staticmethod
    def log_match_attempt(
        conn: sqlite3.Connection,
        confidence_score: float,
        threshold_used: float,
        model_name: str,
        matched_trusted_id: Optional[int] = None,
        session_id: Optional[str] = None,
        camera_id: Optional[int] = None,
        audio_duration_sec: Optional[float] = None,
        notes: Optional[str] = None
    ) -> int:
        """
        Log a voiceprint matching attempt for analytics.
        
        Args:
            conn: Database connection
            confidence_score: Similarity score achieved
            threshold_used: Threshold used for matching
            model_name: Model used
            matched_trusted_id: ID if match found, None otherwise
            session_id: Optional conversation session ID
            camera_id: Optional camera ID
            audio_duration_sec: Length of audio sample
            notes: Optional notes
            
        Returns:
            match_id of created log entry
        """
        cursor = conn.execute(
            """
            INSERT INTO voiceprint_matches
            (session_id, camera_id, matched_trusted_id, confidence_score,
             threshold_used, model_name, matched_ts, audio_duration_sec, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                camera_id,
                matched_trusted_id,
                confidence_score,
                threshold_used,
                model_name,
                int(datetime.now().timestamp()),
                audio_duration_sec,
                notes
            )
        )
        conn.commit()
        return cursor.lastrowid
    
    @staticmethod
    def get_match_history(
        conn: sqlite3.Connection,
        trusted_id: Optional[int] = None,
        session_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get voiceprint match history.
        
        Args:
            conn: Database connection
            trusted_id: Optional filter by trusted person
            session_id: Optional filter by session
            limit: Maximum results
            
        Returns:
            List of match records
        """
        if trusted_id:
            rows = conn.execute(
                """
                SELECT m.*, tp.name as trusted_name
                FROM voiceprint_matches m
                LEFT JOIN trusted_person tp ON tp.trusted_id = m.matched_trusted_id
                WHERE m.matched_trusted_id = ?
                ORDER BY m.matched_ts DESC
                LIMIT ?
                """,
                (trusted_id, limit)
            ).fetchall()
        elif session_id:
            rows = conn.execute(
                """
                SELECT m.*, tp.name as trusted_name
                FROM voiceprint_matches m
                LEFT JOIN trusted_person tp ON tp.trusted_id = m.matched_trusted_id
                WHERE m.session_id = ?
                ORDER BY m.matched_ts DESC
                LIMIT ?
                """,
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT m.*, tp.name as trusted_name
                FROM voiceprint_matches m
                LEFT JOIN trusted_person tp ON tp.trusted_id = m.matched_trusted_id
                ORDER BY m.matched_ts DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
        
        # Convert to dicts
        columns = ['match_id', 'session_id', 'camera_id', 'matched_trusted_id',
                   'confidence_score', 'threshold_used', 'model_name', 'matched_ts',
                   'audio_duration_sec', 'notes', 'trusted_name']
        
        return [dict(zip(columns, row)) for row in rows]
