"""
Voiceprint API Router - RESTful endpoints for voiceprint management

Provides CRUD operations for trusted person voiceprints:
- List voiceprints (with filtering)
- Get specific voiceprint
- Create voiceprint
- Update voiceprint metadata
- Delete voiceprint
- Match speaker against voiceprints

Integrates with central/policy-server/server.py via FastAPI router.
"""

import os
import sys
import base64
import numpy as np
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from packages.data.voiceprint_service import VoiceprintService, Voiceprint, VoiceprintMatch


# ============================================================================
# Pydantic Models
# ============================================================================

class VoiceprintCreate(BaseModel):
    """Request model for creating a voiceprint."""
    trusted_id: int = Field(..., description="ID of trusted person")
    embedding_base64: str = Field(..., description="Base64-encoded float32 embedding")
    model_name: str = Field(..., description="Model used (e.g., 'speechbrain_ecapa')")
    quality_score: float = Field(1.0, ge=0.0, le=1.0, description="Audio quality score")
    camera_id: Optional[int] = Field(None, description="Camera/edge that captured this")
    audio_duration_sec: Optional[float] = Field(None, description="Audio sample duration")
    notes: Optional[str] = Field(None, description="Optional metadata")


class VoiceprintUpdate(BaseModel):
    """Request model for updating voiceprint metadata."""
    quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    notes: Optional[str] = None


class VoiceprintResponse(BaseModel):
    """Response model for voiceprint."""
    voiceprint_id: int
    trusted_id: int
    trusted_name: Optional[str] = None
    model_name: str
    embedding_dim: int
    camera_id: Optional[int]
    created_ts: int
    quality_score: float
    audio_duration_sec: Optional[float]
    notes: Optional[str]
    
    class Config:
        from_attributes = True


class VoiceprintListResponse(BaseModel):
    """Response model for list of voiceprints."""
    count: int
    voiceprints: List[VoiceprintResponse]


class VoiceprintMatchRequest(BaseModel):
    """Request model for matching a voiceprint."""
    embedding_base64: str = Field(..., description="Base64-encoded float32 embedding")
    model_name: str = Field(..., description="Model name (must match stored voiceprints)")
    threshold: float = Field(0.75, ge=0.0, le=1.0, description="Minimum similarity score")
    top_k: int = Field(5, ge=1, le=20, description="Maximum matches to return")
    camera_id: Optional[int] = Field(None, description="Camera ID for logging")
    session_id: Optional[str] = Field(None, description="Conversation session ID")


class VoiceprintMatchResponse(BaseModel):
    """Response model for voiceprint match."""
    matched: bool
    matches: List[dict]  # List of VoiceprintMatch dicts
    

# ============================================================================
# Database Dependency
# ============================================================================

def get_db_connection():
    """Get database connection (imported from server module)."""
    import sqlite3
    db_path = os.path.join(PROJECT_ROOT, "data", "doorbell.db")
    db_path = os.getenv("ECHOBELL_DB_PATH", db_path)
    
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ============================================================================
# Router
# ============================================================================

router = APIRouter(
    prefix="/voiceprints",
    tags=["voiceprints"],
    responses={404: {"description": "Not found"}},
)


@router.get("/", response_model=VoiceprintListResponse)
async def list_voiceprints(
    trusted_id: Optional[int] = None,
    model_name: Optional[str] = None,
    conn=Depends(get_db_connection)
):
    """
    List all voiceprints, with optional filtering.
    
    Query parameters:
    - trusted_id: Filter by trusted person ID
    - model_name: Filter by model name
    """
    if trusted_id:
        voiceprints = VoiceprintService.get_voiceprints_for_person(
            conn, trusted_id, model_name
        )
    else:
        voiceprints = VoiceprintService.list_voiceprints(conn, model_name)
    
    # Enrich with trusted person names
    enriched = []
    for vp in voiceprints:
        row = conn.execute(
            "SELECT name FROM trusted_person WHERE trusted_id = ?",
            (vp.trusted_id,)
        ).fetchone()
        
        enriched.append(VoiceprintResponse(
            voiceprint_id=vp.voiceprint_id,
            trusted_id=vp.trusted_id,
            trusted_name=row[0] if row else None,
            model_name=vp.model_name,
            embedding_dim=vp.embedding_dim,
            camera_id=vp.camera_id,
            created_ts=vp.created_ts,
            quality_score=vp.quality_score,
            audio_duration_sec=vp.audio_duration_sec,
            notes=vp.notes
        ))
    
    return VoiceprintListResponse(
        count=len(enriched),
        voiceprints=enriched
    )


@router.get("/{voiceprint_id}", response_model=VoiceprintResponse)
async def get_voiceprint(voiceprint_id: int, conn=Depends(get_db_connection)):
    """Get a specific voiceprint by ID."""
    vp = VoiceprintService.get_voiceprint(conn, voiceprint_id)
    
    if not vp:
        raise HTTPException(status_code=404, detail=f"Voiceprint {voiceprint_id} not found")
    
    # Get trusted person name
    row = conn.execute(
        "SELECT name FROM trusted_person WHERE trusted_id = ?",
        (vp.trusted_id,)
    ).fetchone()
    
    return VoiceprintResponse(
        voiceprint_id=vp.voiceprint_id,
        trusted_id=vp.trusted_id,
        trusted_name=row[0] if row else None,
        model_name=vp.model_name,
        embedding_dim=vp.embedding_dim,
        camera_id=vp.camera_id,
        created_ts=vp.created_ts,
        quality_score=vp.quality_score,
        audio_duration_sec=vp.audio_duration_sec,
        notes=vp.notes
    )


@router.post("/", response_model=VoiceprintResponse, status_code=201)
async def create_voiceprint(request: VoiceprintCreate, conn=Depends(get_db_connection)):
    """
    Create a new voiceprint for a trusted person.
    
    The embedding should be base64-encoded float32 array.
    """
    # Verify trusted person exists
    row = conn.execute(
        "SELECT name FROM trusted_person WHERE trusted_id = ?",
        (request.trusted_id,)
    ).fetchone()
    
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Trusted person {request.trusted_id} not found"
        )
    
    # Decode embedding
    try:
        embedding_bytes = base64.b64decode(request.embedding_base64)
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid embedding format: {str(e)}"
        )
    
    # Create voiceprint
    try:
        voiceprint_id = VoiceprintService.create_voiceprint(
            conn,
            trusted_id=request.trusted_id,
            embedding=embedding,
            model_name=request.model_name,
            quality_score=request.quality_score,
            camera_id=request.camera_id,
            audio_duration_sec=request.audio_duration_sec,
            notes=request.notes
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create voiceprint: {str(e)}"
        )
    
    # Return created voiceprint
    vp = VoiceprintService.get_voiceprint(conn, voiceprint_id)
    
    return VoiceprintResponse(
        voiceprint_id=vp.voiceprint_id,
        trusted_id=vp.trusted_id,
        trusted_name=row[0],
        model_name=vp.model_name,
        embedding_dim=vp.embedding_dim,
        camera_id=vp.camera_id,
        created_ts=vp.created_ts,
        quality_score=vp.quality_score,
        audio_duration_sec=vp.audio_duration_sec,
        notes=vp.notes
    )


@router.patch("/{voiceprint_id}", response_model=VoiceprintResponse)
async def update_voiceprint(
    voiceprint_id: int,
    request: VoiceprintUpdate,
    conn=Depends(get_db_connection)
):
    """Update voiceprint metadata (quality score, notes)."""
    # Check if voiceprint exists
    vp = VoiceprintService.get_voiceprint(conn, voiceprint_id)
    if not vp:
        raise HTTPException(status_code=404, detail=f"Voiceprint {voiceprint_id} not found")
    
    # Update
    success = VoiceprintService.update_voiceprint(
        conn,
        voiceprint_id,
        quality_score=request.quality_score,
        notes=request.notes
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update voiceprint")
    
    # Return updated voiceprint
    vp = VoiceprintService.get_voiceprint(conn, voiceprint_id)
    
    row = conn.execute(
        "SELECT name FROM trusted_person WHERE trusted_id = ?",
        (vp.trusted_id,)
    ).fetchone()
    
    return VoiceprintResponse(
        voiceprint_id=vp.voiceprint_id,
        trusted_id=vp.trusted_id,
        trusted_name=row[0] if row else None,
        model_name=vp.model_name,
        embedding_dim=vp.embedding_dim,
        camera_id=vp.camera_id,
        created_ts=vp.created_ts,
        quality_score=vp.quality_score,
        audio_duration_sec=vp.audio_duration_sec,
        notes=vp.notes
    )


@router.delete("/{voiceprint_id}", status_code=204)
async def delete_voiceprint(voiceprint_id: int, conn=Depends(get_db_connection)):
    """Delete a voiceprint."""
    success = VoiceprintService.delete_voiceprint(conn, voiceprint_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Voiceprint {voiceprint_id} not found")
    
    return None  # 204 No Content


@router.post("/match", response_model=VoiceprintMatchResponse)
async def match_voiceprint(request: VoiceprintMatchRequest, conn=Depends(get_db_connection)):
    """
    Match a voiceprint embedding against stored voiceprints.
    
    Returns list of matches sorted by confidence (highest first).
    """
    # Decode embedding
    try:
        embedding_bytes = base64.b64decode(request.embedding_base64)
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid embedding format: {str(e)}"
        )
    
    # Match against database
    matches = VoiceprintService.match_voiceprint(
        conn,
        embedding=embedding,
        model_name=request.model_name,
        threshold=request.threshold,
        top_k=request.top_k
    )
    
    # Log the match attempt
    if matches:
        best_match = matches[0]
        VoiceprintService.log_match_attempt(
            conn,
            confidence_score=best_match.confidence,
            threshold_used=request.threshold,
            model_name=request.model_name,
            matched_trusted_id=best_match.trusted_id,
            session_id=request.session_id,
            camera_id=request.camera_id
        )
    else:
        VoiceprintService.log_match_attempt(
            conn,
            confidence_score=0.0,
            threshold_used=request.threshold,
            model_name=request.model_name,
            session_id=request.session_id,
            camera_id=request.camera_id
        )
    
    # Convert to response format
    match_dicts = [
        {
            "trusted_id": m.trusted_id,
            "trusted_name": m.trusted_name,
            "confidence": m.confidence,
            "confidence_percent": round(m.confidence * 100, 1),
            "voiceprint_id": m.voiceprint_id,
            "quality_score": m.quality_score
        }
        for m in matches
    ]
    
    return VoiceprintMatchResponse(
        matched=len(matches) > 0,
        matches=match_dicts
    )


@router.get("/history/matches", response_model=dict)
async def get_match_history(
    trusted_id: Optional[int] = None,
    session_id: Optional[str] = None,
    limit: int = 100,
    conn=Depends(get_db_connection)
):
    """
    Get voiceprint matching history.
    
    Query parameters:
    - trusted_id: Filter by trusted person
    - session_id: Filter by conversation session
    - limit: Maximum results (default 100)
    """
    history = VoiceprintService.get_match_history(
        conn,
        trusted_id=trusted_id,
        session_id=session_id,
        limit=limit
    )
    
    return {
        "count": len(history),
        "matches": history
    }
