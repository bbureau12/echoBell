"""
Voice Command API - /listen endpoint for Echonet events

Handles voice commands from Echonet edge devices:
- Maps voiceprint IDs to trusted persons
- Checks authorization and confidence thresholds
- Routes to policies or LLM for decision-making
- Tracks correlation IDs for audit trail
"""

import os
import sys
import time
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from voice_models import (
    EchonetVoiceEvent,
    VoiceCommandResponse,
    VoiceprintPersonMapping,
    VoiceprintPersonMappingResponse,
    MCPToolPermission,
    MCPToolPermissionResponse,
    VoiceAuthorizationCheck,
    VoiceAuthorizationResponse
)
import services
from middleware import get_correlation_id, generate_correlation_id
from server import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


# ============================================================================
# Voice Command Endpoint
# ============================================================================

@router.post("/listen", response_model=VoiceCommandResponse)
async def handle_voice_event(event: EchonetVoiceEvent, request: Request):
    """
    Handle incoming voice event from Echonet edge device.
    
    This endpoint:
    1. Maps voiceprint_user_id to trusted_person_id
    2. Checks authorization based on confidence and command type
    3. Routes to explicit policies or LLM fallback
    4. Returns response for TTS
    
    The correlation ID is extracted from X-Correlation-ID header or generated.
    Client IP is logged for audit trail and security monitoring.
    """
    start_time = time.time()
    
    # Get or generate correlation ID
    correlation_id = get_correlation_id()
    if not correlation_id:
        correlation_id = generate_correlation_id()
    
    # Extract client IP address (handle proxies/load balancers)
    client_ip = request.client.host if request.client else None
    # Check for X-Forwarded-For header (if behind proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    logger.info(f"[{correlation_id}] Received voice event from {client_ip}: {event.text} from {event.voiceprint_user_id}")
    
    with get_db() as conn:
        # Map voiceprint to trusted person
        trusted_person_id = None
        person_name = "Unknown"
        
        if event.voiceprint_user_id:
            trusted_person_id = services.get_voiceprint_person_mapping(conn, event.voiceprint_user_id)
            if trusted_person_id:
                # Get person name
                cursor = conn.execute(
                    "SELECT name FROM trusted_person WHERE trusted_id = ?",
                    (trusted_person_id,)
                )
                row = cursor.fetchone()
                if row:
                    person_name = row[0]
                logger.info(f"[{correlation_id}] Mapped voiceprint '{event.voiceprint_user_id}' to person: {person_name}")
            else:
                logger.warning(f"[{correlation_id}] No mapping found for voiceprint: {event.voiceprint_user_id}")
        
        # Check authorization
        allowed, reason, action_required = services.check_voice_authorization(
            conn,
            event.text,
            event.voiceprint_confidence,
            tool_name=None  # TODO: Extract from command text or LLM intent
        )
        
        # Create voice command record (with client IP for audit)
        voice_cmd_id = services.create_voice_command(
            conn,
            correlation_id=correlation_id,
            echonet_event=event.dict(),
            trusted_person_id=trusted_person_id,
            auth_result="allowed" if allowed else "denied",
            auth_reason=reason,
            client_ip=client_ip
        )
        
        # If not authorized, request confirmation
        if not allowed:
            response_text = f"I need confirmation for this action. Reason: {reason}"
            if action_required == "request_telegram_confirmation":
                response_text = "I've sent a confirmation request to your Telegram. Please approve to continue."
                # TODO: Integrate with Telegram notifier
            
            services.update_voice_command_result(
                conn,
                voice_cmd_id,
                response_text=response_text,
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
            
            return VoiceCommandResponse(
                correlation_id=correlation_id,
                handled=False,
                response=response_text,
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        
        # TODO: Check for explicit policy matches
        # For now, route everything to LLM fallback
        
        # Route to LLM (placeholder - will integrate with actual LLM later)
        response_text = await _route_to_llm(
            conn,
            correlation_id,
            event,
            trusted_person_id,
            person_name
        )
        
        # Update voice command with results
        processing_time_ms = int((time.time() - start_time) * 1000)
        services.update_voice_command_result(
            conn,
            voice_cmd_id,
            llm_used=True,
            response_text=response_text,
            actions_taken=["llm_response"],  # TODO: Track actual actions
            processing_time_ms=processing_time_ms
        )
        
        return VoiceCommandResponse(
            correlation_id=correlation_id,
            handled=True,
            response=response_text,
            user_acknowledged=person_name if trusted_person_id else None,
            llm_used=True,
            processing_time_ms=processing_time_ms
        )


async def _route_to_llm(
    conn,
    correlation_id: str,
    event: EchonetVoiceEvent,
    trusted_person_id: Optional[int],
    person_name: str
) -> str:
    """
    Route voice command to LLM for processing.
    
    TODO: Integrate with actual LLM and MCP server
    For now, returns a placeholder response.
    """
    logger.info(f"[{correlation_id}] Routing to LLM: {event.text}")
    
    # Placeholder logic
    text_lower = event.text.lower()
    
    if "who" in text_lower or "what" in text_lower:
        return f"I can help with that, {person_name}. Let me check the scene information."
    elif "unlock" in text_lower or "open" in text_lower:
        return "I cannot perform security actions via voice command without additional confirmation."
    else:
        return f"I heard you say: {event.text}. I'm still learning how to help with this."


# ============================================================================
# Voiceprint Mapping Endpoints
# ============================================================================

@router.post("/mappings", response_model=VoiceprintPersonMappingResponse)
async def create_voiceprint_mapping(mapping: VoiceprintPersonMapping):
    """
    Create a mapping between Echonet voiceprint ID and trusted person.
    """
    with get_db() as conn:
        # Verify person exists
        cursor = conn.execute(
            "SELECT name FROM trusted_person WHERE trusted_id = ?",
            (mapping.trusted_person_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Trusted person {mapping.trusted_person_id} not found")
        
        person_name = row[0]
        
        # Create mapping
        mapping_id = services.create_voiceprint_person_mapping(
            conn,
            mapping.voiceprint_user_id,
            mapping.trusted_person_id,
            mapping.notes
        )
        
        # Get created mapping
        cursor = conn.execute(
            """
            SELECT id, voiceprint_user_id, trusted_person_id, created_ts, updated_ts, notes
            FROM voiceprint_person_mapping
            WHERE id = ?
            """,
            (mapping_id,)
        )
        row = cursor.fetchone()
        
        return VoiceprintPersonMappingResponse(
            id=row[0],
            voiceprint_user_id=row[1],
            trusted_person_id=row[2],
            person_name=person_name,
            created_ts=row[3],
            updated_ts=row[4],
            notes=row[5]
        )


@router.get("/mappings", response_model=list[VoiceprintPersonMappingResponse])
async def list_voiceprint_mappings():
    """
    List all voiceprint to person mappings.
    """
    with get_db() as conn:
        mappings = services.list_voiceprint_mappings(conn)
        return [VoiceprintPersonMappingResponse(**m) for m in mappings]


@router.get("/mappings/{voiceprint_user_id}", response_model=VoiceprintPersonMappingResponse)
async def get_voiceprint_mapping(voiceprint_user_id: str):
    """
    Get mapping for a specific voiceprint user ID.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT 
                vpm.id,
                vpm.voiceprint_user_id,
                vpm.trusted_person_id,
                tp.name as person_name,
                vpm.created_ts,
                vpm.updated_ts,
                vpm.notes
            FROM voiceprint_person_mapping vpm
            LEFT JOIN trusted_person tp ON vpm.trusted_person_id = tp.trusted_id
            WHERE vpm.voiceprint_user_id = ?
            """,
            (voiceprint_user_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Mapping not found for voiceprint: {voiceprint_user_id}")
        
        return VoiceprintPersonMappingResponse(
            id=row[0],
            voiceprint_user_id=row[1],
            trusted_person_id=row[2],
            person_name=row[3],
            created_ts=row[4],
            updated_ts=row[5],
            notes=row[6]
        )


# ============================================================================
# MCP Tool Permission Endpoints
# ============================================================================

@router.get("/tools/permissions", response_model=list[MCPToolPermissionResponse])
async def list_tool_permissions(voice_enabled_only: bool = False):
    """
    List MCP tool permissions for voice commands.
    """
    with get_db() as conn:
        permissions = services.list_mcp_tool_permissions(conn, voice_enabled_only)
        return [MCPToolPermissionResponse(**p) for p in permissions]


@router.get("/tools/permissions/{tool_name}", response_model=MCPToolPermissionResponse)
async def get_tool_permission(tool_name: str):
    """
    Get permission settings for a specific MCP tool.
    """
    with get_db() as conn:
        permission = services.get_mcp_tool_permission(conn, tool_name)
        if not permission:
            raise HTTPException(status_code=404, detail=f"Tool permission not found: {tool_name}")
        return MCPToolPermissionResponse(**permission)


@router.post("/authorize", response_model=VoiceAuthorizationResponse)
async def check_authorization(check: VoiceAuthorizationCheck):
    """
    Check if a voice command or tool call is authorized.
    """
    with get_db() as conn:
        allowed, reason, action_required = services.check_voice_authorization(
            conn,
            check.text,
            check.voiceprint_confidence,
            check.tool_name
        )
        
        # Extract confidence threshold if applicable
        confidence_threshold = None
        if check.tool_name:
            permission = services.get_mcp_tool_permission(conn, check.tool_name)
            if permission:
                confidence_threshold = permission["requires_confidence"]
        
        return VoiceAuthorizationResponse(
            allowed=allowed,
            reason=reason,
            action_required=action_required,
            confidence_threshold=confidence_threshold
        )
