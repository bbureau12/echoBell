"""
Models for voice command handling

Pydantic models for:
- Echonet voice event payloads
- Voice command tracking
- Voice-to-person mapping
"""

from typing import Optional
from pydantic import BaseModel, Field


class EchonetVoiceEvent(BaseModel):
    """
    Voice event payload from Echonet edge device.
    
    See: UPSTREAM_API_PAYLOAD.md for full specification
    """
    event_id: str = Field(..., description="Unique event identifier from Echonet")
    ts: int = Field(..., description="Unix timestamp (seconds) when audio was captured")
    source_id: str = Field(..., description="Audio source identifier (e.g., 'microphone')")
    room: Optional[str] = Field(None, description="Physical room/location")
    session_id: Optional[str] = Field(None, description="Session ID for multi-turn conversations")
    mode: str = Field(..., description="Interaction mode: 'triggered' or 'open_listen'")
    text: str = Field(..., description="Transcribed text from speech recognition")
    confidence: Optional[float] = Field(None, description="Speech recognition confidence (0-1)")
    voiceprint_user_id: Optional[str] = Field(None, description="Identified user ID from voiceprint")
    voiceprint_confidence: Optional[float] = Field(None, description="Voiceprint match confidence (0-1)")


class VoiceCommandCreate(BaseModel):
    """Request to create a voice command record"""
    correlation_id: str
    echonet_event: EchonetVoiceEvent
    trusted_person_id: Optional[int] = None
    auth_result: str = "pending"
    auth_reason: Optional[str] = None


class VoiceCommandResponse(BaseModel):
    """Response after processing voice command"""
    correlation_id: str
    handled: bool
    response: str
    actions: Optional[list[str]] = None
    user_acknowledged: Optional[str] = None
    llm_used: bool = False
    processing_time_ms: Optional[int] = None


class VoiceprintPersonMapping(BaseModel):
    """Mapping between Echonet voiceprint ID and trusted person"""
    voiceprint_user_id: str
    trusted_person_id: int
    notes: Optional[str] = None


class VoiceprintPersonMappingResponse(BaseModel):
    """Response for voiceprint mapping operations"""
    id: int
    voiceprint_user_id: str
    trusted_person_id: int
    person_name: Optional[str] = None
    created_ts: int
    updated_ts: int
    notes: Optional[str] = None


class MCPToolPermission(BaseModel):
    """MCP tool permission configuration for voice commands"""
    tool_name: str
    voice_enabled: bool = False
    requires_confidence: float = 0.75
    requires_2fa: bool = False
    security_level: str = "normal"
    notes: Optional[str] = None


class MCPToolPermissionResponse(BaseModel):
    """Response for MCP tool permission queries"""
    tool_name: str
    voice_enabled: bool
    requires_confidence: float
    requires_2fa: bool
    security_level: str
    notes: Optional[str]
    created_ts: int
    updated_ts: int


class VoiceAuthorizationCheck(BaseModel):
    """Request to check if voice command is authorized"""
    text: str
    user_id: Optional[str] = None
    voiceprint_confidence: Optional[float] = None
    tool_name: Optional[str] = None


class VoiceAuthorizationResponse(BaseModel):
    """Response for voice authorization check"""
    allowed: bool
    reason: str
    action_required: Optional[str] = None  # e.g., "request_telegram_confirmation"
    confidence_threshold: Optional[float] = None
