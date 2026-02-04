"""
Visitor Event Management API Router

Provides endpoints for querying and reclassifying visitor events.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import sqlite3
import os

# Add project root to path for imports
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import services

router = APIRouter(prefix="/visitors", tags=["visitors"])


# ============================================================================
# Request/Response Models
# ============================================================================

class EvidenceItem(BaseModel):
    """Evidence to add during reclassification"""
    source: str = Field(default="llm", description="Evidence source")
    key: str = Field(..., description="Evidence feature key (e.g., 'uniform_type', 'vehicle_color')")
    value: str = Field(..., description="Evidence value")
    conf: float = Field(default=0.95, ge=0.0, le=1.0, description="Confidence level")
    object_id: Optional[int] = Field(default=None, description="Object ID if evidence is object-specific")


class ReclassifyRequest(BaseModel):
    """Request to reclassify a visitor event's intent"""
    additional_evidence: Optional[List[EvidenceItem]] = Field(
        default=None,
        description="Evidence to inject before re-classification (recommended approach)"
    )
    override_intent: Optional[str] = Field(
        default=None,
        description="Direct intent override (use sparingly, bypasses classification rules)"
    )
    override_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence for override (required if override_intent provided)"
    )
    reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason for reclassification (for audit trail)"
    )


class ReclassifyResponse(BaseModel):
    """Response from reclassification operation"""
    success: bool
    event_id: str
    visitor_id: Optional[str]
    original_intent: Optional[str]
    new_intent: str
    original_confidence: float
    new_confidence: float
    original_urgency: Optional[int]
    new_urgency: int
    method: str  # "evidence_injection" or "direct_override"
    reclassified_by: str
    reason: Optional[str]
    trace: List[str]
    changed: bool


class VisitorEventResponse(BaseModel):
    """Visitor event details"""
    event_id: str
    visitor_id: Optional[str]
    camera_id: Optional[int]
    detected_ts: str
    intent: Optional[str]
    intent_confidence: Optional[float]
    urgency: Optional[int]
    intent_locked: Optional[int]
    snapshot_path: Optional[str]
    duration_s: Optional[float]
    reclassification_count: Optional[int]
    reclassified_by: Optional[str]
    reclassification_reason: Optional[str]
    reclassified_ts: Optional[int]


# ============================================================================
# Database Connection
# ============================================================================

def get_db_path() -> str:
    """Get database path from environment or default"""
    default_path = os.path.join(PROJECT_ROOT, "echoBell.db")
    return os.getenv("ECHOBELL_DB_PATH", default_path)


def get_db_connection():
    """Get database connection"""
    db_path = get_db_path()
    return sqlite3.connect(db_path)


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/events/{event_id}", response_model=VisitorEventResponse)
async def get_visitor_event(event_id: str):
    """
    Get details of a specific visitor event.
    
    Returns event information including intent classification, confidence,
    and reclassification history if applicable.
    """
    with get_db_connection() as conn:
        event = services.get_visitor_event(conn, event_id)
    
    if not event:
        raise HTTPException(status_code=404, detail=f"Visitor event not found: {event_id}")
    
    return event


@router.post("/events/{event_id}/reclassify", response_model=ReclassifyResponse)
async def reclassify_visitor_intent(event_id: str, request: ReclassifyRequest):
    """
    Reclassify a visitor event's intent.
    
    Two approaches:
    
    1. **Evidence Injection** (recommended):
       Provide additional_evidence to add context that was missed.
       The classification engine re-runs with enriched evidence.
       
       Example:
       ```json
       {
         "additional_evidence": [
           {"key": "uniform_type", "value": "ups", "conf": 0.95},
           {"key": "vehicle_brand", "value": "ups_truck", "conf": 0.90}
         ],
         "reason": "OCR missed UPS logo on uniform"
       }
       ```
    
    2. **Direct Override** (use sparingly):
       Provide override_intent and override_confidence to force a specific classification.
       Bypasses all classification rules - use only when rules are fundamentally wrong.
       
       Example:
       ```json
       {
         "override_intent": "delivery_arriving",
         "override_confidence": 0.95,
         "reason": "User confirmed via voice command this was UPS delivery"
       }
       ```
    
    All reclassifications are logged with full audit trail.
    """
    # Convert Pydantic models to dicts
    additional_evidence_dicts = None
    if request.additional_evidence:
        additional_evidence_dicts = [item.dict() for item in request.additional_evidence]
    
    with get_db_connection() as conn:
        result = services.reclassify_visitor_intent(
            conn=conn,
            event_id=event_id,
            additional_evidence=additional_evidence_dicts,
            override_intent=request.override_intent,
            override_confidence=request.override_confidence,
            reason=request.reason,
            reclassified_by="api"
        )
    
    if not result.get("success"):
        error = result.get("error", "Reclassification failed")
        raise HTTPException(status_code=400, detail=error)
    
    return result


@router.get("/events")
async def list_visitor_events(
    camera_id: Optional[int] = None,
    visitor_id: Optional[str] = None,
    intent: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    List visitor events with optional filters.
    
    Filters:
    - camera_id: Filter by specific camera
    - visitor_id: Filter by specific visitor
    - intent: Filter by intent classification
    - limit: Maximum number of results (default 50)
    - offset: Pagination offset (default 0)
    
    Results are sorted by detected_ts DESC (most recent first).
    """
    query_parts = ["SELECT * FROM visitor_events WHERE 1=1"]
    params = []
    
    if camera_id is not None:
        query_parts.append("AND camera_id = ?")
        params.append(camera_id)
    
    if visitor_id:
        query_parts.append("AND visitor_id = ?")
        params.append(visitor_id)
    
    if intent:
        query_parts.append("AND intent_inferred = ?")
        params.append(intent)
    
    query_parts.append("ORDER BY detected_ts DESC")
    query_parts.append("LIMIT ? OFFSET ?")
    params.extend([limit, offset])
    
    query = " ".join(query_parts)
    
    with get_db_connection() as conn:
        cursor = conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        
        events = []
        for row in cursor.fetchall():
            event = dict(zip(columns, row))
            events.append(event)
    
    return {
        "count": len(events),
        "limit": limit,
        "offset": offset,
        "events": events
    }


@router.get("/events/{event_id}/reclassification_history")
async def get_reclassification_history(event_id: str):
    """
    Get reclassification history for a visitor event.
    
    Returns information about when and why the event was reclassified,
    including original and current intents.
    
    Note: Full reclassification history (all past values) requires
    separate visitor_event_reclassifications table (future enhancement).
    Current implementation shows current state and count.
    """
    with get_db_connection() as conn:
        event = services.get_visitor_event(conn, event_id)
    
    if not event:
        raise HTTPException(status_code=404, detail=f"Visitor event not found: {event_id}")
    
    reclass_count = event.get("reclassification_count", 0)
    
    if reclass_count == 0:
        return {
            "event_id": event_id,
            "reclassified": False,
            "message": "Event has not been reclassified"
        }
    
    return {
        "event_id": event_id,
        "reclassified": True,
        "reclassification_count": reclass_count,
        "reclassified_by": event.get("reclassified_by"),
        "reclassification_reason": event.get("reclassification_reason"),
        "reclassified_ts": event.get("reclassified_ts"),
        "current_intent": event.get("intent"),
        "current_confidence": event.get("intent_confidence"),
        "note": "Full history tracking requires separate reclassifications table (future enhancement)"
    }
