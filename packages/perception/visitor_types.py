# packages/perception/visitor_types.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class VisitorQuality:
    ok: bool
    tier: str               # "skip" | "known" | "trusted"
    blur_score: float
    reason: str | None = None


@dataclass(slots=True)
class VisitorMatch:
    kind: str                 # "trusted" | "known" | "new" | "skipped"
    visitor_id: Optional[str] = None
    profile_id: Optional[str] = None
    profile_label: Optional[str] = None
    similarity: float = 0.0
    visit_count_7d: int = 0
    visit_count_30d: int = 0
    visit_count_total: int = 0
    trusted_pending: bool = False
    trusted_verified: bool = False
    
    # Fields for trusted face matches
    trusted_id: Optional[int] = None
    trusted_label: Optional[str] = None

    # Optional historical hints
    intent_last: Optional[str] = None
    intent_last_ts: Optional[int] = None  # unix seconds
