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
    """Handle tool execution"""
    try:
        # Get the handler for this tool
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"})
            )]
        
        # Execute the handler
        result = await handler(arguments)
        
        # Return result as JSON
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]
        
    except Exception as e:
        # Return error
        import traceback
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc()
            }, indent=2)
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
