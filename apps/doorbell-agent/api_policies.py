"""
Policy Management API Router
RESTful API for creating, reading, updating, and deleting policy rules dynamically.

To integrate with existing policy-server:
    from apps.doorbell-agent.api_policies import router as policy_router
    app.include_router(policy_router)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from packages.policy.policy_service import PolicyRulesService
import sqlite3
import os


router = APIRouter(prefix="/policies", tags=["policy-management"])


# Pydantic models for request/response validation
class PolicyCondition(BaseModel):
    """Policy condition schema (flexible dict)"""
    pass  # Accept any dict structure


class PolicyAction(BaseModel):
    """Policy action schema"""
    type: str = Field(..., description="Action type: telegram, speak, webhook")
    message: Optional[str] = Field(None, description="Message template")
    text: Optional[str] = Field(None, description="TTS text")
    url: Optional[str] = Field(None, description="Webhook URL")
    method: Optional[str] = Field("POST", description="HTTP method")
    payload: Optional[Dict[str, Any]] = Field(None, description="Webhook payload")
    priority: Optional[str] = Field("normal", description="low, normal, urgent")


class PolicyCreate(BaseModel):
    """Request model for creating a policy"""
    id: str = Field(..., description="Unique policy ID", example="loitering_alert")
    name: str = Field(..., description="Human-readable name", example="Loitering Alert")
    description: Optional[str] = Field("", description="What this policy does")
    enabled: bool = Field(True, description="Whether policy is active")
    priority: int = Field(50, description="Evaluation priority (higher = first)", ge=0, le=100)
    conditions: Dict[str, Any] = Field(..., description="Condition tree")
    actions: List[Dict[str, Any]] = Field(..., description="Actions to execute")
    variables: Optional[Dict[str, Any]] = Field(None, description="Variable definitions")
    tags: Optional[str] = Field("", description="Space-separated tags")


class PolicyUpdate(BaseModel):
    """Request model for updating a policy (all fields optional)"""
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=100)
    conditions: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    variables: Optional[Dict[str, Any]] = None
    tags: Optional[str] = None


class PolicyResponse(BaseModel):
    """Response model for policy data"""
    id: str
    name: str
    description: str
    enabled: bool
    priority: int
    conditions: Dict[str, Any]
    actions: List[Dict[str, Any]]
    variables: Dict[str, Any]
    created_ts: int
    updated_ts: int
    created_by: str
    tags: str
    version: int


class ExecutionHistoryResponse(BaseModel):
    """Response model for execution history"""
    id: int
    policy_id: str
    policy_name: Optional[str]
    event_id: Optional[str]
    track_key: Optional[str]
    track_type: Optional[str]
    camera_id: Optional[int]
    matched_conditions: Optional[Dict[str, Any]]
    executed_actions: Optional[List[Dict[str, Any]]]
    execution_ts: int
    success: bool
    error_message: Optional[str]


# Dependency injection for database path
def get_db_path() -> str:
    """Get database path from environment or use default"""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.getenv("ECHOBELL_DB_PATH", os.path.join(project_root, "data", "echoBell.db"))


def get_policy_service(db_path: str = Depends(get_db_path)) -> PolicyRulesService:
    """Dependency injection for PolicyRulesService"""
    return PolicyRulesService(db_path)


# =========================
# API Endpoints
# =========================

@router.get("/", response_model=List[PolicyResponse])
async def list_policies(
    enabled_only: bool = False,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """
    List all policies, sorted by priority.
    
    Query Parameters:
    - enabled_only: If true, only return active policies
    """
    policies = service.get_all_policies(enabled_only=enabled_only)
    return policies


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: str,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """Get a single policy by ID"""
    policy = service.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
    return policy


@router.post("/", response_model=PolicyResponse, status_code=201)
async def create_policy(
    policy: PolicyCreate,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """
    Create a new policy.
    
    Example Request:
    ```json
    {
      "id": "custom_alert",
      "name": "Custom Alert",
      "description": "My custom policy",
      "enabled": true,
      "priority": 75,
      "conditions": {
        "all": [
          {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
          {"time_between": {"start": "22:00", "end": "06:00"}}
        ]
      },
      "actions": [
        {
          "type": "telegram",
          "message": "Vehicle detected at night!",
          "priority": "urgent"
        }
      ]
    }
    ```
    """
    try:
        created = service.create_policy(
            policy_id=policy.id,
            name=policy.name,
            description=policy.description,
            enabled=policy.enabled,
            priority=policy.priority,
            conditions=policy.conditions,
            actions=policy.actions,
            variables=policy.variables,
            created_by="api",
            tags=policy.tags or ""
        )
        return created
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: str,
    updates: PolicyUpdate,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """
    Update an existing policy (partial update).
    Only fields provided in request will be updated.
    
    Example Request:
    ```json
    {
      "enabled": false,
      "priority": 90
    }
    ```
    """
    try:
        updated = service.update_policy(
            policy_id=policy_id,
            name=updates.name,
            description=updates.description,
            enabled=updates.enabled,
            priority=updates.priority,
            conditions=updates.conditions,
            actions=updates.actions,
            variables=updates.variables,
            tags=updates.tags
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: str,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """Delete a policy by ID"""
    success = service.delete_policy(policy_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
    return None


@router.post("/{policy_id}/enable", response_model=PolicyResponse)
async def enable_policy(
    policy_id: str,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """Enable a disabled policy"""
    try:
        return service.toggle_policy(policy_id, enabled=True)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{policy_id}/disable", response_model=PolicyResponse)
async def disable_policy(
    policy_id: str,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """Disable an active policy"""
    try:
        return service.toggle_policy(policy_id, enabled=False)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{policy_id}/history", response_model=List[ExecutionHistoryResponse])
async def get_policy_history(
    policy_id: str,
    limit: int = 100,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """Get execution history for a specific policy"""
    history = service.get_execution_history(policy_id=policy_id, limit=limit)
    return history


@router.get("/executions/recent", response_model=List[ExecutionHistoryResponse])
async def get_recent_executions(
    limit: int = 100,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """Get recent policy executions across all policies"""
    history = service.get_execution_history(policy_id=None, limit=limit)
    return history


@router.post("/import-yaml")
async def import_from_yaml(
    yaml_file: str = "config/policy_rules.yaml",
    overwrite: bool = False,
    service: PolicyRulesService = Depends(get_policy_service)
):
    """
    Import policies from YAML file into database.
    
    Query Parameters:
    - yaml_file: Path to YAML file (default: config/policy_rules.yaml)
    - overwrite: If true, update existing policies; if false, skip existing
    """
    import yaml
    
    try:
        with open(yaml_file, 'r') as f:
            config = yaml.safe_load(f)
        
        policies = config.get('policies', [])
        service.import_from_yaml(policies, overwrite=overwrite)
        
        return {
            "status": "success",
            "imported": len(policies),
            "overwrite": overwrite
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"YAML file '{yaml_file}' not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")


# =========================
# Example cURL commands for testing
# =========================
"""
# List all policies
curl http://localhost:8000/api/policies/

# Get specific policy
curl http://localhost:8000/api/policies/unknown_vehicle_alert

# Create new policy
curl -X POST http://localhost:8000/api/policies/ \\
  -H "Content-Type: application/json" \\
  -d '{
    "id": "my_custom_policy",
    "name": "My Custom Policy",
    "description": "Test policy",
    "enabled": true,
    "priority": 60,
    "conditions": {
      "evidence_exists": {"source": "vision", "feature": "person_present"}
    },
    "actions": [
      {"type": "telegram", "message": "Person detected!", "priority": "normal"}
    ]
  }'

# Update policy (disable it)
curl -X PATCH http://localhost:8000/api/policies/my_custom_policy \\
  -H "Content-Type: application/json" \\
  -d '{"enabled": false}'

# Delete policy
curl -X DELETE http://localhost:8000/api/policies/my_custom_policy

# Get execution history
curl http://localhost:8000/api/policies/unknown_vehicle_alert/history

# Import YAML policies
curl -X POST "http://localhost:8000/api/policies/import-yaml?overwrite=false"
"""
