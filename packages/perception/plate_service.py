from __future__ import annotations

import hmac
import hashlib
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from time import time
from typing import Optional

_PLATE_RE = re.compile(r"[A-Z0-9]+")


def normalize_plate_text(raw: str) -> str:
    s = raw.upper()
    parts = _PLATE_RE.findall(s)
    return "".join(parts)


def plate_hmac_hex(secret_key: bytes, normalized_plate: str, *, truncate_bytes: int = 16) -> str:
    """
    Keyed hash for plates. truncate_bytes=16 -> 128-bit hex (32 chars), plenty for uniqueness.
    """
    mac = hmac.new(secret_key, normalized_plate.encode("utf-8"), hashlib.sha256).digest()
    return mac[:truncate_bytes].hex()


@dataclass(frozen=True)
class PlateRepeatResult:
    plate_hmac: str
    is_repeat: bool
    visit_count: int
    first_seen_ts: int
    last_seen_ts: int


class PlateService:
    def __init__(self, *, secret_key: bytes):
        if not secret_key or len(secret_key) < 16:
            raise ValueError("PlateService secret_key must be >= 16 bytes.")
        self.secret_key = secret_key

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plate_visitors (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              plate_hmac      TEXT NOT NULL UNIQUE,
              first_seen_ts   INTEGER NOT NULL,
              last_seen_ts    INTEGER NOT NULL,
              visit_count     INTEGER NOT NULL DEFAULT 1,
              last_camera_id  INTEGER,
              notes           TEXT
            );
            """
        )
        conn.execute(
    """
    CREATE TABLE IF NOT EXISTS trusted_plates (
      plate_hmac   TEXT PRIMARY KEY,
      label        TEXT NOT NULL,
      created_ts   INTEGER NOT NULL,
      enabled      INTEGER NOT NULL DEFAULT 1,
      notes        TEXT
    );
    """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trusted_plates_enabled
            ON trusted_plates(enabled);
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_plate_visitors_last_seen
              ON plate_visitors(last_seen_ts);
            """
        )
        # Optional; UNIQUE already creates an index, but explicit is fine:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_plate_visitors_plate_hmac
              ON plate_visitors(plate_hmac);
            """
        )
        conn.commit()
    
    def add_trusted_plate(
        self,
        conn: sqlite3.Connection,
        *,
        raw_plate_text: str,
        label: str,
        enabled: bool = True,
        notes: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> Optional[str]:
        """
        Add/update a trusted plate by raw text. Stores only plate_hmac + label.
        Returns plate_hmac or None if plate text invalid.
        """
        plate_hmac = self._hmac_from_raw(raw_plate_text)
        if not plate_hmac:
            return None

        ts = int(now_ts or time())
        conn.execute(
            """
            INSERT INTO trusted_plates (plate_hmac, label, created_ts, enabled, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(plate_hmac) DO UPDATE SET
              label   = excluded.label,
              enabled = excluded.enabled,
              notes   = excluded.notes;
            """,
            (plate_hmac, label.strip(), ts, 1 if enabled else 0, notes),
        )
        conn.commit()
        return plate_hmac
    
    def upsert_plate_visit(
        self,
        conn: sqlite3.Connection,
        *,
        raw_plate_text: str,
        camera_id: Optional[int],
        seen_ts: Optional[int] = None,
    ) -> Optional[PlateRepeatResult]:
        """
        Returns repeat stats. Returns None if plate text can't be normalized.
        Does NOT store raw plate text.
        """
        normalized = normalize_plate_text(raw_plate_text)
        if not normalized:
            return None

        ph = plate_hmac_hex(self.secret_key, normalized)
        ts = int(seen_ts or time())

        # Atomic upsert + returning lets us determine repeat without a pre-select.
        # Requires SQLite 3.35+ (pretty common now).
        row = conn.execute(
            """
            INSERT INTO plate_visitors (plate_hmac, first_seen_ts, last_seen_ts, visit_count, last_camera_id)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(plate_hmac) DO UPDATE SET
              last_seen_ts   = excluded.last_seen_ts,
              visit_count    = plate_visitors.visit_count + 1,
              last_camera_id = excluded.last_camera_id
            RETURNING
              visit_count,
              first_seen_ts,
              last_seen_ts;
            """,
            (ph, ts, ts, camera_id),
        ).fetchone()

        if row is None:
            # Extremely unlikely, but keep it safe.
            conn.commit()
            return None

        visit_count, first_seen_ts, last_seen_ts = row
        conn.commit()

        # If visit_count == 1, it was newly inserted; otherwise it was a repeat.
        is_repeat = int(visit_count) > 1

        return PlateRepeatResult(
            plate_hmac=ph,
            is_repeat=is_repeat,
            visit_count=int(visit_count),
            first_seen_ts=int(first_seen_ts),
            last_seen_ts=int(last_seen_ts),
        )

    def get_plate_intent_history(
        self,
        conn: sqlite3.Connection,
        raw_plate_text: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Given a raw plate text, find its plate_hmac and return 
        the most common intents from past visitor_events.
        
        Args:
            conn: Database connection
            raw_plate_text: Raw plate text from OCR
            limit: Maximum number of past events to consider
        
        Returns: 
            List of dicts: [{"intent": "delivery", "count": 5, "avg_conf": 0.87}, ...]
            Sorted by count (descending)
        """
        normalized = normalize_plate_text(raw_plate_text)
        if not normalized:
            return []
        
        plate_hmac = plate_hmac_hex(self.secret_key, normalized)
        
        rows = conn.execute(
            """
            SELECT ve.intent_inferred, ve.intent_confidence
            FROM visitor_events ve
            JOIN visitor_event_plate_sightings veps 
              ON ve.event_id = veps.event_id
            WHERE veps.plate_hmac = ?
              AND ve.intent_inferred IS NOT NULL
            ORDER BY ve.detected_ts DESC
            LIMIT ?
            """,
            (plate_hmac, limit),
        ).fetchall()
        
        if not rows:
            return []
        
        # Aggregate by intent
        intent_stats = defaultdict(lambda: {"count": 0, "total_conf": 0.0})
        for intent, conf in rows:
            intent_stats[intent]["count"] += 1
            intent_stats[intent]["total_conf"] += (conf or 0.0)
        
        # Convert to sorted list
        result = []
        for intent, stats in intent_stats.items():
            result.append({
                "intent": intent,
                "count": stats["count"],
                "avg_conf": stats["total_conf"] / stats["count"]
            })
        
        return sorted(result, key=lambda x: x["count"], reverse=True)
