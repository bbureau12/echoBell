#!/usr/bin/env python3
"""
EchoBell MCP Server - Model Context Protocol Server for Policy API

Provides MCP tools for:
- Policy management (CRUD, evaluation)
- Scene tracking queries (active tracks, visit history)
- Scheduled events (create, query, active events)
- Evidence inspection (debugging, analysis)

All tools use the shared service layer (services.py) to ensure
consistency with the FastAPI HTTP server.

Usage:
    python mcp_server.py

MCP Client Configuration (Claude Desktop):
    Add to ~/.config/Claude/claude_desktop_config.json (macOS/Linux)
    or %APPDATA%\Claude\claude_desktop_config.json (Windows):
    
    {
        "mcpServers": {
            "echobell": {
                "command": "python",
                "args": ["D:\\Projects\\echoBell\\echoBell\\apps\\policy-server\\mcp_server.py"],
                "env": {
                    "ECHOBELL_DB_PATH": "D:\\Projects\\echoBell\\echoBell\\echoBell.db"
                }
            }
        }
    }
"""

import os
import sys
import json
import sqlite3
from typing import Any, Dict, List, Optional
from datetime import datetime
from contextlib import contextmanager

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

# Import service layer (DRY business logic shared with FastAPI)
import services

# MCP SDK imports
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: MCP SDK not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)


# ============================================================================
# Database Connection
# ============================================================================

def get_db_path() -> str:
    """Get database path from environment or default"""
    default_path = os.path.join(PROJECT_ROOT, "echoBell.db")
    return os.getenv("ECHOBELL_DB_PATH", default_path)


@contextmanager
def get_db():
    """Get database connection with proper cleanup"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================================
# MCP Server Setup
# ============================================================================

app = Server("echobell-mcp-server")


# ============================================================================
# Tool Definitions
# ============================================================================

TOOLS = [
    # Policy Management Tools
    Tool(
        name="list_policies",
        description="List all policy rules, optionally filtered by status (active/disabled)",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "disabled"],
                    "description": "Filter by policy status (optional)"
                }
            }
        }
    ),
    
    Tool(
        name="get_policy",
        description="Get detailed information about a specific policy by ID",
        inputSchema={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "integer",
                    "description": "The policy ID to retrieve"
                }
            },
            "required": ["policy_id"]
        }
    ),
    
    Tool(
        name="create_policy",
        description="Create a new policy rule with conditions and actions",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Policy name"
                },
                "conditions": {
                    "type": "object",
                    "description": "Policy conditions (e.g., {\"label\": {\"equals\": \"person\"}})"
                },
                "actions": {
                    "type": "object",
                    "description": "Policy actions (e.g., {\"send_alert\": {\"message\": \"Person detected\"}})"
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority (higher = more important, default 50)",
                    "default": 50
                },
                "description": {
                    "type": "string",
                    "description": "Policy description (optional)",
                    "default": ""
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "disabled"],
                    "description": "Policy status (default: active)",
                    "default": "active"
                }
            },
            "required": ["name", "conditions", "actions"]
        }
    ),
    
    Tool(
        name="update_policy",
        description="Update an existing policy (partial update supported)",
        inputSchema={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "integer",
                    "description": "The policy ID to update"
                },
                "name": {
                    "type": "string",
                    "description": "New policy name (optional)"
                },
                "conditions": {
                    "type": "object",
                    "description": "New conditions (optional)"
                },
                "actions": {
                    "type": "object",
                    "description": "New actions (optional)"
                },
                "priority": {
                    "type": "integer",
                    "description": "New priority (optional)"
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "disabled"],
                    "description": "New status (optional)"
                }
            },
            "required": ["policy_id"]
        }
    ),
    
    Tool(
        name="delete_policy",
        description="Delete a policy by ID",
        inputSchema={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "integer",
                    "description": "The policy ID to delete"
                }
            },
            "required": ["policy_id"]
        }
    ),
    
    Tool(
        name="evaluate_policy",
        description="Evaluate a policy's conditions against given evidence",
        inputSchema={
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "integer",
                    "description": "The policy ID to evaluate"
                },
                "evidence": {
                    "type": "array",
                    "description": "List of evidence objects with source, feature, value, conf",
                    "items": {
                        "type": "object"
                    }
                },
                "timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp for evaluation (optional, defaults to now)"
                }
            },
            "required": ["policy_id", "evidence"]
        }
    ),
    
    # Scene Tracking Tools
    Tool(
        name="get_active_tracks",
        description="Get currently active scene tracks for a camera",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_id": {
                    "type": "integer",
                    "description": "Camera ID to query (optional, returns all if omitted)"
                }
            }
        }
    ),
    
    Tool(
        name="query_scene_context",
        description="Query recent scene context including active tracks, alerts, and visit history",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_id": {
                    "type": "integer",
                    "description": "Camera ID to query"
                },
                "time_range_seconds": {
                    "type": "integer",
                    "description": "Time range in seconds (default 300 = 5 minutes)",
                    "default": 300
                }
            },
            "required": ["camera_id"]
        }
    ),
    
    Tool(
        name="get_visit_history",
        description="Get visit history for a camera within a time range",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_id": {
                    "type": "integer",
                    "description": "Camera ID to query"
                },
                "time_range_seconds": {
                    "type": "integer",
                    "description": "Time range in seconds (default 86400 = 24 hours)",
                    "default": 86400
                }
            },
            "required": ["camera_id"]
        }
    ),
    
    # Scheduled Events Tools
    Tool(
        name="list_events",
        description="List all scheduled events, optionally filter to active events only",
        inputSchema={
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "description": "Only return currently active events (default false)",
                    "default": False
                }
            }
        }
    ),
    
    Tool(
        name="create_event",
        description="Create a new scheduled event for time-based policy behavior",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Event name (e.g., 'Halloween', 'Pizza Delivery Window')"
                },
                "start_ts": {
                    "type": "integer",
                    "description": "Start time as Unix timestamp"
                },
                "end_ts": {
                    "type": "integer",
                    "description": "End time as Unix timestamp"
                },
                "description": {
                    "type": "string",
                    "description": "Event description (optional)",
                    "default": ""
                },
                "policy_hint": {
                    "type": "string",
                    "description": "Policy hint for matching (e.g., 'greet_visitors', 'expect_delivery')",
                    "default": ""
                }
            },
            "required": ["name", "start_ts", "end_ts"]
        }
    ),
    
    Tool(
        name="active_events_now",
        description="Get all events that are currently active (or active at a specific timestamp)",
        inputSchema={
            "type": "object",
            "properties": {
                "timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp to check (optional, defaults to now)"
                }
            }
        }
    ),
    
    # Alert History Tool
    Tool(
        name="get_alert_history",
        description="Get recent alert history, optionally filtered by camera",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_id": {
                    "type": "integer",
                    "description": "Camera ID to filter by (optional)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of alerts to return (default 100)",
                    "default": 100
                }
            }
        }
    ),
    
    # Quiet Hours Tools
    Tool(
        name="list_quiet_hours",
        description="List all quiet hour schedules, optionally filtered by weekday or status",
        inputSchema={
            "type": "object",
            "properties": {
                "weekday": {
                    "type": "integer",
                    "description": "Filter by weekday (0=Monday, 6=Sunday) (optional)"
                },
                "enabled_only": {
                    "type": "boolean",
                    "description": "Only return enabled schedules (default true)",
                    "default": True
                }
            }
        }
    ),
    
    Tool(
        name="create_quiet_hour",
        description="Create a new quiet hour schedule for a specific day and time range",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for this quiet hour period (e.g., 'Sleep', 'Lunch', 'Work Hours')"
                },
                "weekday": {
                    "type": "integer",
                    "description": "Day of week (0=Monday, 1=Tuesday, ..., 6=Sunday)"
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in HH:MM format (24-hour, e.g., '22:00')"
                },
                "end_time": {
                    "type": "string",
                    "description": "End time in HH:MM format (24-hour, e.g., '07:00'). Can span overnight."
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether this schedule is active (default true)",
                    "default": True
                }
            },
            "required": ["name", "weekday", "start_time", "end_time"]
        }
    ),
    
    Tool(
        name="update_quiet_hour",
        description="Update an existing quiet hour schedule",
        inputSchema={
            "type": "object",
            "properties": {
                "quiet_hour_id": {
                    "type": "integer",
                    "description": "The quiet hour ID to update"
                },
                "name": {
                    "type": "string",
                    "description": "New name (optional)"
                },
                "weekday": {
                    "type": "integer",
                    "description": "New weekday (optional)"
                },
                "start_time": {
                    "type": "string",
                    "description": "New start time in HH:MM format (optional)"
                },
                "end_time": {
                    "type": "string",
                    "description": "New end time in HH:MM format (optional)"
                },
                "enabled": {
                    "type": "boolean",
                    "description": "New enabled status (optional)"
                }
            },
            "required": ["quiet_hour_id"]
        }
    ),
    
    Tool(
        name="delete_quiet_hour",
        description="Delete a quiet hour schedule by ID",
        inputSchema={
            "type": "object",
            "properties": {
                "quiet_hour_id": {
                    "type": "integer",
                    "description": "The quiet hour ID to delete"
                }
            },
            "required": ["quiet_hour_id"]
        }
    ),
    
    Tool(
        name="is_quiet_time",
        description="Check if current time (or a specific timestamp) is within quiet hours",
        inputSchema={
            "type": "object",
            "properties": {
                "timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp to check (optional, defaults to now)"
                }
            }
        }
    ),
    
    Tool(
        name="get_active_quiet_hours",
        description="Get all quiet hour schedules that are currently active (or active at a specific timestamp)",
        inputSchema={
            "type": "object",
            "properties": {
                "timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp to check (optional, defaults to now)"
                }
            }
        }
    ),
    
    # Echonet Voice Interaction Tools
    Tool(
        name="activate_echonet_listening",
        description="""Activate open listening mode on an Echonet device to enable continuous voice conversation.
        
        Use this when you need additional information from the user that wasn't provided in their initial voice command.
        The Echonet device will stay in listening mode for 30 seconds (configurable) or until the user stops speaking,
        allowing natural conversation without requiring the wake word to be repeated.
        
        Examples:
        - User says "What's the status?" - You can ask "Status of what?" by activating listening
        - User says "Unlock the door" - You can ask "Which door?" if ambiguous
        - User provides partial information - You can request clarification
        
        The device will automatically return to trigger mode after the conversation or timeout.""",
        inputSchema={
            "type": "object",
            "properties": {
                "echonet_url": {
                    "type": "string",
                    "description": "Base URL of the Echonet instance (e.g., http://192.168.1.50:8123). If not provided, uses the first discovered Echonet."
                },
                "target_name": {
                    "type": "string",
                    "description": "Target name registered with Echonet (default: 'echobell')",
                    "default": "echobell"
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason for requesting voice input (optional, e.g., 'Need clarification on which door to unlock')"
                }
            }
        }
    ),
    
    Tool(
        name="deactivate_echonet_listening",
        description="Deactivate open listening mode and return Echonet to trigger mode (wake word required). Use this to end the conversation when you have sufficient information.",
        inputSchema={
            "type": "object",
            "properties": {
                "echonet_url": {
                    "type": "string",
                    "description": "Base URL of the Echonet instance. If not provided, uses the first discovered Echonet."
                },
                "target_name": {
                    "type": "string",
                    "description": "Target name (default: 'echobell')",
                    "default": "echobell"
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason for ending listening (optional, e.g., 'Conversation complete')"
                }
            }
        }
    ),
    
    Tool(
        name="get_echonet_status",
        description="Get status of all discovered Echonet instances including their current listening mode and registration state",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    ),
    
    # Visitor Intent Reclassification Tools
    Tool(
        name="reclassify_visitor_intent",
        description="""Reclassify a visitor's intent by adding evidence or directly overriding the classification.
        
        Use this when the initial classification was incorrect or insufficient. You can either:
        
        1. Add evidence (recommended): Inject additional evidence that the system should have detected.
           The classification engine will re-run with this evidence included, respecting existing rules.
           Example: Add evidence that uniform was "ups" if OCR missed it.
        
        2. Direct override: Force a specific intent regardless of evidence.
           Use sparingly - only when classification rules are fundamentally wrong.
        
        Common scenarios:
        - Visitor was classified as "unknown" but you recognize them from context
        - Uniform/vehicle details were missed by vision but clear from conversation
        - Historical pattern suggests different intent than visual evidence
        - User provides verbal correction via voice command
        
        All reclassifications are logged with full audit trail including reason and source.""",
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The visitor event ID to reclassify (from visitor_events table)"
                },
                "additional_evidence": {
                    "type": "array",
                    "description": "Evidence to add before re-classification (e.g., [{\"source\": \"llm\", \"key\": \"uniform_type\", \"value\": \"ups\", \"conf\": 0.95}])",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "Evidence source (e.g., 'llm', 'user_correction')"},
                            "key": {"type": "string", "description": "Evidence feature key"},
                            "value": {"type": "string", "description": "Evidence value"},
                            "conf": {"type": "number", "description": "Confidence (0-1, default 0.95)"},
                            "object_id": {"type": "integer", "description": "Object ID if evidence is object-specific"}
                        },
                        "required": ["key", "value"]
                    }
                },
                "override_intent": {
                    "type": "string",
                    "description": "Direct intent override (bypasses classification - use only when evidence approach fails)"
                },
                "override_confidence": {
                    "type": "number",
                    "description": "Confidence for override (required if override_intent provided, 0-1)"
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable explanation for why reclassification was needed (for audit trail)"
                }
            },
            "required": ["event_id"]
        }
    ),
    
    Tool(
        name="get_visitor_event",
        description="Get detailed information about a specific visitor event including intent, evidence, and reclassification history",
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The visitor event ID to retrieve"
                }
            },
            "required": ["event_id"]
        }
    ),
]


# ============================================================================
# Tool Handlers (all use service layer)
# ============================================================================

async def handle_list_policies(args: dict) -> dict:
    """List all policies - uses services layer"""
    status = args.get("status")
    
    with get_db() as conn:
        policies = services.list_policies(conn, status=status)
    
    return {
        "count": len(policies),
        "policies": policies
    }


async def handle_get_policy(args: dict) -> dict:
    """Get a specific policy - uses services layer"""
    policy_id = args["policy_id"]
    
    with get_db() as conn:
        policy = services.get_policy(conn, policy_id)
    
    if not policy:
        return {"error": f"Policy not found: {policy_id}"}
    
    return policy


async def handle_create_policy(args: dict) -> dict:
    """Create a new policy - uses services layer"""
    with get_db() as conn:
        policy = services.create_policy(
            conn=conn,
            name=args["name"],
            conditions=args["conditions"],
            actions=args["actions"],
            priority=args.get("priority", 50),
            description=args.get("description", ""),
            status=args.get("status", "active")
        )
    
    return {
        "status": "created",
        "policy": policy
    }


async def handle_update_policy(args: dict) -> dict:
    """Update a policy - uses services layer"""
    policy_id = args.pop("policy_id")
    
    with get_db() as conn:
        updated = services.update_policy(
            conn=conn,
            policy_id=policy_id,
            name=args.get("name"),
            description=args.get("description"),
            conditions=args.get("conditions"),
            actions=args.get("actions"),
            priority=args.get("priority"),
            status=args.get("status")
        )
    
    if not updated:
        return {"error": f"Policy not found: {policy_id}"}
    
    return {
        "status": "updated",
        "policy": updated
    }


async def handle_delete_policy(args: dict) -> dict:
    """Delete a policy - uses services layer"""
    policy_id = args["policy_id"]
    
    with get_db() as conn:
        deleted = services.delete_policy(conn, policy_id)
    
    if not deleted:
        return {"error": f"Policy not found: {policy_id}"}
    
    return {
        "status": "deleted",
        "policy_id": policy_id
    }


async def handle_evaluate_policy(args: dict) -> dict:
    """Evaluate a policy - uses services layer"""
    policy_id = args["policy_id"]
    evidence = args["evidence"]
    timestamp = args.get("timestamp")
    
    with get_db() as conn:
        result = services.evaluate_policy_conditions(
            conn=conn,
            policy_id=policy_id,
            evidence=evidence,
            timestamp=timestamp
        )
    
    return result


async def handle_get_active_tracks(args: dict) -> dict:
    """Get active scene tracks - uses services layer"""
    camera_id = args.get("camera_id")
    
    with get_db() as conn:
        tracks = services.get_active_tracks(conn, camera_id=camera_id)
    
    return {
        "camera_id": camera_id or "all",
        "count": len(tracks),
        "tracks": tracks
    }


async def handle_query_scene_context(args: dict) -> dict:
    """Query scene context - uses services layer"""
    camera_id = args["camera_id"]
    time_range_s = args.get("time_range_seconds", 300)
    
    with get_db() as conn:
        context = services.query_scene_context(conn, camera_id, time_range_s)
    
    return context


async def handle_get_visit_history(args: dict) -> dict:
    """Get visit history - uses services layer"""
    camera_id = args["camera_id"]
    time_range_s = args.get("time_range_seconds", 86400)
    
    with get_db() as conn:
        visits = services.get_visit_history(conn, camera_id, time_range_s)
    
    return {
        "camera_id": camera_id,
        "time_range_seconds": time_range_s,
        "count": len(visits),
        "visits": visits
    }


async def handle_list_events(args: dict) -> dict:
    """List scheduled events - uses services layer"""
    active_only = args.get("active_only", False)
    
    with get_db() as conn:
        if active_only:
            now = int(datetime.now().timestamp())
            events = services.get_active_events(conn, timestamp=now)
        else:
            events = services.list_scheduled_events(conn)
    
    return {
        "count": len(events),
        "events": events
    }


async def handle_create_event(args: dict) -> dict:
    """Create a scheduled event - uses services layer"""
    with get_db() as conn:
        event = services.create_scheduled_event(
            conn=conn,
            name=args["name"],
            start_ts=args["start_ts"],
            end_ts=args["end_ts"],
            description=args.get("description", ""),
            policy_hint=args.get("policy_hint", "")
        )
    
    return {
        "status": "created",
        "event": event
    }


async def handle_active_events_now(args: dict) -> dict:
    """Get events active now - uses services layer"""
    timestamp = args.get("timestamp", int(datetime.now().timestamp()))
    
    with get_db() as conn:
        events = services.get_active_events(conn, timestamp=timestamp)
    
    return {
        "timestamp": timestamp,
        "count": len(events),
        "events": events
    }


async def handle_get_alert_history(args: dict) -> dict:
    """Get alert history - uses services layer"""
    camera_id = args.get("camera_id")
    limit = args.get("limit", 100)
    
    with get_db() as conn:
        alerts = services.get_alert_history(conn, camera_id=camera_id, limit=limit)
    
    return {
        "camera_id": camera_id or "all",
        "count": len(alerts),
        "alerts": alerts
    }


async def handle_list_quiet_hours(args: dict) -> dict:
    """List quiet hour schedules"""
    from packages.data.quiet_hours_service import QuietHoursService
    
    weekday = args.get("weekday")
    enabled_only = args.get("enabled_only", True)
    
    with get_db() as conn:
        if weekday is not None:
            quiet_hours = QuietHoursService.get_quiet_hours_for_day(
                conn, 
                weekday=weekday,
                enabled_only=enabled_only
            )
        else:
            quiet_hours = QuietHoursService.get_quiet_hours(
                conn,
                enabled_only=enabled_only
            )
    
    # Convert QuietHour dataclass instances to dicts
    quiet_hours_dicts = [
        {
            "id": qh.id,
            "name": qh.name,
            "weekday": qh.weekday,
            "start_time": qh.start_time,
            "end_time": qh.end_time,
            "enabled": qh.enabled,
            "is_overnight": qh.is_overnight()
        }
        for qh in quiet_hours
    ]
    
    return {
        "count": len(quiet_hours_dicts),
        "quiet_hours": quiet_hours_dicts
    }


async def handle_create_quiet_hour(args: dict) -> dict:
    """Create a new quiet hour schedule"""
    from packages.data.quiet_hours_service import QuietHoursService
    
    with get_db() as conn:
        quiet_hour_id = QuietHoursService.create_quiet_hour(
            conn=conn,
            name=args["name"],
            weekday=args["weekday"],
            start_time=args["start_time"],
            end_time=args["end_time"],
            enabled=args.get("enabled", True)
        )
        
        # Fetch the created quiet hour
        quiet_hours = QuietHoursService.get_quiet_hours(conn, enabled_only=False)
        quiet_hour = next((qh for qh in quiet_hours if qh.id == quiet_hour_id), None)
    
    if not quiet_hour:
        return {"error": "Failed to retrieve created quiet hour"}
    
    return {
        "status": "created",
        "quiet_hour": {
            "id": quiet_hour.id,
            "name": quiet_hour.name,
            "weekday": quiet_hour.weekday,
            "start_time": quiet_hour.start_time,
            "end_time": quiet_hour.end_time,
            "enabled": quiet_hour.enabled,
            "is_overnight": quiet_hour.is_overnight()
        }
    }


async def handle_update_quiet_hour(args: dict) -> dict:
    """Update an existing quiet hour schedule"""
    from packages.data.quiet_hours_service import QuietHoursService
    
    quiet_hour_id = args["quiet_hour_id"]
    updates = {
        k: v for k, v in args.items() 
        if k != "quiet_hour_id" and v is not None
    }
    
    with get_db() as conn:
        # Update (doesn't return anything)
        QuietHoursService.update_quiet_hour(
            conn=conn,
            quiet_hour_id=quiet_hour_id,
            **updates
        )
        
        # Fetch the updated quiet hour
        quiet_hours = QuietHoursService.get_quiet_hours(conn, enabled_only=False)
        quiet_hour = next((qh for qh in quiet_hours if qh.id == quiet_hour_id), None)
    
    if not quiet_hour:
        return {"error": f"Quiet hour not found: {quiet_hour_id}"}
    
    return {
        "status": "updated",
        "quiet_hour": {
            "id": quiet_hour.id,
            "name": quiet_hour.name,
            "weekday": quiet_hour.weekday,
            "start_time": quiet_hour.start_time,
            "end_time": quiet_hour.end_time,
            "enabled": quiet_hour.enabled,
            "is_overnight": quiet_hour.is_overnight()
        }
    }


async def handle_delete_quiet_hour(args: dict) -> dict:
    """Delete a quiet hour schedule"""
    from packages.data.quiet_hours_service import QuietHoursService
    
    quiet_hour_id = args["quiet_hour_id"]
    
    with get_db() as conn:
        # Delete doesn't return anything, just execute it
        QuietHoursService.delete_quiet_hour(conn, quiet_hour_id)
    
    return {
        "status": "deleted",
        "quiet_hour_id": quiet_hour_id
    }
    
    return {
        "status": "deleted",
        "quiet_hour_id": quiet_hour_id
    }


async def handle_is_quiet_time(args: dict) -> dict:
    """Check if it's currently quiet time"""
    from packages.data.quiet_hours_service import QuietHoursService
    
    timestamp = args.get("timestamp")
    dt = datetime.fromtimestamp(timestamp) if timestamp else None
    
    with get_db() as conn:
        is_quiet = QuietHoursService.is_quiet_time(conn, dt)
    
    return {
        "is_quiet_time": is_quiet,
        "checked_at": timestamp or int(datetime.now().timestamp())
    }


async def handle_get_active_quiet_hours(args: dict) -> dict:
    """Get active quiet hour schedules"""
    from packages.data.quiet_hours_service import QuietHoursService
    
    timestamp = args.get("timestamp")
    dt = datetime.fromtimestamp(timestamp) if timestamp else None
    
    with get_db() as conn:
        active_quiet_hours = QuietHoursService.get_active_quiet_hours(conn, dt)
    
    # Convert to dicts
    active_dicts = [
        {
            "id": qh.id,
            "name": qh.name,
            "weekday": qh.weekday,
            "start_time": qh.start_time,
            "end_time": qh.end_time,
            "is_overnight": qh.is_overnight()
        }
        for qh in active_quiet_hours
    ]
    
    return {
        "is_quiet_time": len(active_dicts) > 0,
        "count": len(active_dicts),
        "active_quiet_hours": active_dicts,
        "checked_at": timestamp or int(datetime.now().timestamp())
    }


async def handle_activate_echonet_listening(args: dict) -> dict:
    """Activate open listening mode on Echonet device"""
    echonet_url = args.get("echonet_url")
    target_name = args.get("target_name", "echobell")
    reason = args.get("reason", "LLM requesting additional information")
    
    # If no URL provided, get first discovered Echonet
    if not echonet_url:
        with get_db() as conn:
            instances = await services.get_echonet_instances_status(conn)
        
        if not instances:
            return {
                "success": False,
                "error": "No Echonet instances discovered",
                "message": "Please provide echonet_url or ensure Echonet discovery is running"
            }
        
        echonet_url = instances[0]["url"]
    
    result = await services.activate_echonet_listening(
        echonet_url=echonet_url,
        target_name=target_name,
        source="mcp_llm",
        reason=reason
    )
    
    return result


async def handle_deactivate_echonet_listening(args: dict) -> dict:
    """Deactivate open listening mode (return to trigger mode)"""
    echonet_url = args.get("echonet_url")
    target_name = args.get("target_name", "echobell")
    reason = args.get("reason", "Conversation complete")
    
    # If no URL provided, get first discovered Echonet
    if not echonet_url:
        with get_db() as conn:
            instances = await services.get_echonet_instances_status(conn)
        
        if not instances:
            return {
                "success": False,
                "error": "No Echonet instances discovered"
            }
        
        echonet_url = instances[0]["url"]
    
    result = await services.deactivate_echonet_listening(
        echonet_url=echonet_url,
        target_name=target_name,
        source="mcp_llm",
        reason=reason
    )
    
    return result


async def handle_get_echonet_status(args: dict) -> dict:
    """Get status of all Echonet instances"""
    with get_db() as conn:
        instances = await services.get_echonet_instances_status(conn)
    
    return {
        "count": len(instances),
        "instances": instances
    }


async def handle_reclassify_visitor_intent(args: dict) -> dict:
    """Reclassify a visitor event's intent with additional evidence or override"""
    event_id = args["event_id"]
    additional_evidence = args.get("additional_evidence")
    override_intent = args.get("override_intent")
    override_confidence = args.get("override_confidence")
    reason = args.get("reason")
    
    with get_db() as conn:
        result = services.reclassify_visitor_intent(
            conn=conn,
            event_id=event_id,
            additional_evidence=additional_evidence,
            override_intent=override_intent,
            override_confidence=override_confidence,
            reason=reason,
            reclassified_by="mcp_llm"
        )
    
    return result


async def handle_get_visitor_event(args: dict) -> dict:
    """Get details of a specific visitor event"""
    event_id = args["event_id"]
    
    with get_db() as conn:
        event = services.get_visitor_event(conn, event_id)
    
    if not event:
        return {
            "error": f"Visitor event not found: {event_id}"
        }
    
    return event


# Map tool names to handlers
TOOL_HANDLERS = {
    "list_policies": handle_list_policies,
    "get_policy": handle_get_policy,
    "create_policy": handle_create_policy,
    "update_policy": handle_update_policy,
    "delete_policy": handle_delete_policy,
    "evaluate_policy": handle_evaluate_policy,
    "get_active_tracks": handle_get_active_tracks,
    "query_scene_context": handle_query_scene_context,
    "get_visit_history": handle_get_visit_history,
    "list_events": handle_list_events,
    "create_event": handle_create_event,
    "active_events_now": handle_active_events_now,
    "get_alert_history": handle_get_alert_history,
    "list_quiet_hours": handle_list_quiet_hours,
    "create_quiet_hour": handle_create_quiet_hour,
    "update_quiet_hour": handle_update_quiet_hour,
    "delete_quiet_hour": handle_delete_quiet_hour,
    "is_quiet_time": handle_is_quiet_time,
    "get_active_quiet_hours": handle_get_active_quiet_hours,
    "activate_echonet_listening": handle_activate_echonet_listening,
    "deactivate_echonet_listening": handle_deactivate_echonet_listening,
    "get_echonet_status": handle_get_echonet_status,
    "reclassify_visitor_intent": handle_reclassify_visitor_intent,
    "get_visitor_event": handle_get_visitor_event,
}


# ============================================================================
# MCP Protocol Handlers
# ============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available MCP tools"""
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool execution with permission checking for voice commands"""
    try:
        # Extract context if provided (for voice commands)
        context = arguments.get("_context", {})
        correlation_id = context.get("correlation_id")
        source = context.get("source")  # 'voice_command', 'http', etc.
        user_id = context.get("user_id")
        voiceprint_confidence = context.get("voiceprint_confidence")
        
        # Log the call with correlation ID if available
        if correlation_id:
            print(f"[{correlation_id}] MCP tool call: {name} (source: {source}, user: {user_id})", file=sys.stderr)
        
        # Check permissions for voice commands
        if source == "voice_command":
            with get_db() as conn:
                permission = services.get_mcp_tool_permission(conn, name)
                
                if not permission:
                    # Tool exists but no permission record - deny by default
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"Tool '{name}' has no voice permission configuration",
                            "correlation_id": correlation_id
                        })
                    )]
                
                if not permission["voice_enabled"]:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"Tool '{name}' is not enabled for voice commands",
                            "correlation_id": correlation_id
                        })
                    )]
                
                if voiceprint_confidence and voiceprint_confidence < permission["requires_confidence"]:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"Voiceprint confidence ({voiceprint_confidence:.2f}) below required threshold ({permission['requires_confidence']:.2f})",
                            "requires_2fa": True,
                            "correlation_id": correlation_id
                        })
                    )]
                
                if permission["requires_2fa"]:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"Tool '{name}' requires 2FA confirmation",
                            "requires_2fa": True,
                            "correlation_id": correlation_id
                        })
                    )]
        
        # Get the handler for this tool
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Unknown tool: {name}",
                    "correlation_id": correlation_id
                })
            )]
        
        # Remove _context from arguments before passing to handler
        handler_args = {k: v for k, v in arguments.items() if k != "_context"}
        
        # Execute the handler
        result = await handler(handler_args)
        
        # Add correlation ID to result if present
        if correlation_id and isinstance(result, dict):
            result["_correlation_id"] = correlation_id
        
        # Return result as JSON
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]
        
    except Exception as e:
        # Return error with correlation ID
        import traceback
        error_response = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        if correlation_id:
            error_response["correlation_id"] = correlation_id
        
        return [TextContent(
            type="text",
            text=json.dumps(error_response, indent=2)
        )]


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    
    print(f"Starting EchoBell MCP Server", file=sys.stderr)
    print(f"Database: {get_db_path()}", file=sys.stderr)
    print(f"Available tools: {len(TOOLS)}", file=sys.stderr)
    
    asyncio.run(main())
