# EchoBell MCP Server

Model Context Protocol (MCP) server for the EchoBell Policy API. Provides programmatic access to policy management, scene tracking, scheduled events, and evidence inspection.

## Overview

The MCP server exposes 24 tools for interacting with the EchoBell policy engine:

### Policy Management (6 tools)
- `list_policies` - List all policy rules
- `get_policy` - Get detailed policy information
- `create_policy` - Create new policy rules
- `update_policy` - Update existing policies
- `delete_policy` - Delete policies
- `evaluate_policy` - Test policies against evidence

### Scene Tracking (3 tools)
- `get_active_tracks` - Query active scene tracks
- `query_scene_context` - Get scene state for policy evaluation
- `get_visit_history` - Retrieve visit history by plate/person

### Scheduled Events (3 tools)
- `list_events` - List scheduled events
- `create_event` - Create time-based events
- `active_events_now` - Query events active right now

### Alert History (1 tool)
- `get_alert_history` - Retrieve recent alert history

### Quiet Hours Management (6 tools)
- `list_quiet_hours` - List quiet hour schedules
- `create_quiet_hour` - Create new quiet hour period
- `update_quiet_hour` - Update existing quiet hour
- `delete_quiet_hour` - Delete quiet hour schedule
- `is_quiet_time` - Check if currently in quiet hours
- `get_active_quiet_hours` - Get currently active quiet hours

### Echonet Voice Interaction (3 tools)
- `activate_echonet_listening` - Enable continuous voice conversation
- `deactivate_echonet_listening` - Disable listening mode
- `get_echonet_status` - Get Echonet device status

### Visitor Reclassification (2 tools)
- `reclassify_visitor_intent` - Correct visitor intent classification
- `get_visitor_event` - Get visitor event details with audit trail

---

## Installation

### 1. Install MCP SDK

```powershell
# Activate your virtual environment
.\.venv-vision\Scripts\Activate.ps1

# Install MCP SDK
pip install mcp
```

### 2. Configure MCP Client

Add to your MCP client configuration (e.g., Claude Desktop):

**Windows (Claude Desktop):**
```json
{
  "mcpServers": {
    "echobell": {
      "command": "python",
      "args": ["D:\\Projects\\echoBell\\echoBell\\apps\\policy-server\\mcp_server.py"],
      "env": {
        "ECHOBELL_DB": "D:\\Projects\\echoBell\\echoBell\\echoBell.db"
      }
    }
  }
}
```

**macOS/Linux:**
```json
{
  "mcpServers": {
    "echobell": {
      "command": "python3",
      "args": ["/path/to/echoBell/apps/policy-server/mcp_server.py"],
      "env": {
        "ECHOBELL_DB": "/path/to/echoBell/echoBell.db"
      }
    }
  }
}
```

### 3. Restart MCP Client

Restart Claude Desktop or your MCP client to load the server.

---

## Usage Examples

### Policy Management

#### List All Policies
```
Please list all enabled policies
```

Response:
```json
{
  "count": 3,
  "policies": [
    {
      "id": "greet_halloween",
      "name": "Halloween Greeting",
      "priority": 90,
      "enabled": true,
      "conditions": {
        "all_of": [
          {"has_evidence": {"source": "vision", "feature": "class", "value": "person"}},
          {"active_event": {"policy_hint": "greet_visitors"}}
        ]
      },
      "actions": [
        {"speak": {"message": "Happy Halloween! {greeting}"}}
      ]
    }
  ]
}
```

#### Create a New Policy
```
Create a policy to alert when an unknown vehicle approaches at night
```

Example tool call:
```json
{
  "policy_id": "night_unknown_vehicle",
  "name": "Night Unknown Vehicle Alert",
  "priority": 70,
  "conditions": {
    "all_of": [
      {"has_evidence": {"source": "vision", "feature": "class", "value": "vehicle"}},
      {"time_of_day": {"start": "22:00", "end": "06:00"}},
      {"not": {"has_evidence": {"source": "plate", "feature": "trusted", "value": "true"}}}
    ]
  },
  "actions": [
    {"notify": {"channel": "telegram", "message": "Unknown vehicle detected at night"}},
    {"save_evidence": true}
  ]
}
```

#### Evaluate Policy Against Evidence
```
Test the Halloween greeting policy with this evidence:
- vision.class = person (confidence 0.95)
- Check if there's an active event with policy_hint = greet_visitors
```

Tool call:
```json
{
  "evidence": [
    {"source": "vision", "feature": "class", "value": "person", "conf": 0.95}
  ],
  "context": {
    "camera_id": 1,
    "track_key": "person_12345"
  }
}
```

### Scene Tracking

#### Get Active Tracks
```
Show me all active scene tracks for camera 1
```

Response:
```json
{
  "camera_id": 1,
  "count": 2,
  "tracks": [
    {
      "track_key": "vehicle_ABC123",
      "track_type": "vehicle",
      "first_seen_ts": 1737843600,
      "last_seen_ts": 1737843720,
      "duration_seconds": 120,
      "age_seconds": 15,
      "plate": "ABC123",
      "visitor_id": null
    },
    {
      "track_key": "person_45678",
      "track_type": "person",
      "first_seen_ts": 1737843650,
      "last_seen_ts": 1737843700,
      "duration_seconds": 50,
      "age_seconds": 35,
      "plate": null,
      "visitor_id": 42
    }
  ]
}
```

#### Query Scene Context
```
What's the current scene state for policy evaluation?
```

Response:
```json
{
  "camera_id": 1,
  "timestamp": 1737843735,
  "active_tracks": [
    {"track_key": "vehicle_ABC123", "track_type": "vehicle", "duration": 120}
  ],
  "active_intents": [
    {"intent": "delivery", "urgency": 40, "track_key": "vehicle_ABC123"}
  ],
  "num_vehicles": 1,
  "num_people": 0
}
```

#### Get Visit History
```
Show me the visit history for plate ABC123
```

Tool call:
```json
{
  "plate": "ABC123",
  "limit": 5
}
```

Response:
```json
{
  "plate": "ABC123",
  "count": 3,
  "visits": [
    {
      "event_ts": 1737843600,
      "camera_id": 1,
      "intent": "delivery",
      "urgency": 40,
      "track_key": "vehicle_ABC123",
      "duration_seconds": 120
    }
  ]
}
```

### Scheduled Events

#### List Active Events
```
What events are active right now?
```

Tool call:
```json
{
  "active_only": true
}
```

Response:
```json
{
  "count": 1,
  "events": [
    {
      "id": 1,
      "name": "Halloween",
      "description": "Halloween trick-or-treating hours",
      "start_ts": 1730415600,
      "end_ts": 1730422800,
      "policy_hint": "greet_visitors"
    }
  ]
}
```

#### Create a Scheduled Event
```
Create a scheduled event for New Year's Eve party on Dec 31 from 8 PM to 2 AM
```

Tool call:
```json
{
  "name": "New Year's Eve Party",
  "description": "Guests arriving for NYE party",
  "start_ts": 1735689600,
  "end_ts": 1735711200,
  "policy_hint": "party_mode"
}
```

### Alert History

#### Get Recent Alerts
```
Show me the last 20 alerts from camera 1
```

Response:
```json
{
  "count": 20,
  "alerts": [
    {
      "id": 1234,
      "camera_id": 1,
      "policy_id": "night_unknown_vehicle",
      "message": "Unknown vehicle detected at night",
      "timestamp": 1737843600,
      "track_key": "vehicle_XYZ789"
    }
  ]
}
```

### Quiet Hours Management

#### Create Quiet Hours
```
Create a quiet hour period for weekday nights from 10 PM to 7 AM
```

Example (Monday night):
```json
{
  "name": "Weeknight Sleep",
  "weekday": 0,
  "start_time": "22:00",
  "end_time": "07:00",
  "enabled": true
}
```

#### Check Quiet Time Status
```
Is it currently quiet time?
```

Response:
```json
{
  "is_quiet_time": true,
  "active_periods": [
    {
      "id": 5,
      "name": "Weeknight Sleep",
      "weekday": 0,
      "start_time": "22:00",
      "end_time": "07:00"
    }
  ]
}
```

### Echonet Voice Interaction

#### Activate Listening Mode
```
Activate listening mode to ask the user for clarification
```

This enables continuous conversation without requiring the wake word to be repeated.

#### Get Echonet Status
```
What's the status of all Echonet devices?
```

Response:
```json
{
  "devices": [
    {
      "url": "http://192.168.1.50:8123",
      "registered_targets": ["echobell"],
      "listening_mode": "trigger",
      "status": "ready"
    }
  ]
}
```

### Visitor Reclassification

#### Reclassify Visitor Intent
```
Reclassify visitor event evt_123456 - they said they have a package, add evidence that uniform is UPS
```

Tool call:
```json
{
  "event_id": "evt_123456",
  "additional_evidence": [
    {
      "source": "llm",
      "key": "uniform_type",
      "value": "ups",
      "conf": 0.95
    }
  ],
  "reason": "Visitor stated they have a package during conversation, visual analysis missed UPS uniform"
}
```

Response:
```json
{
  "status": "reclassified",
  "event_id": "evt_123456",
  "old_intent": "unknown",
  "new_intent": "delivery_arriving",
  "confidence": 0.92,
  "reason": "Added uniform evidence from voice conversation"
}
```

#### Get Visitor Event Details
```
Show me the full details and reclassification history for visitor event evt_123456
```

Response:
```json
{
  "event_id": "evt_123456",
  "camera_id": 1,
  "timestamp": 1737843600,
  "track_key": "person_98765",
  "current_intent": "delivery_arriving",
  "confidence": 0.92,
  "evidence": [
    {"source": "vision", "key": "class", "value": "person", "conf": 0.98},
    {"source": "llm", "key": "uniform_type", "value": "ups", "conf": 0.95}
  ],
  "reclassification_history": [
    {
      "timestamp": 1737843650,
      "old_intent": "unknown",
      "new_intent": "delivery_arriving",
      "reason": "Visitor stated they have a package during conversation",
      "source": "llm_conversation"
    }
  ]
}
```

---

## Deprecated Usage Examples

### Evidence & Debugging (OLD)

#### Get Scene Evidence
```
Show me all evidence for track vehicle_ABC123 on camera 1
```

Tool call:
```json
{
  "camera_id": 1,
  "track_key": "vehicle_ABC123"
}
```

Response:
```json
{
  "camera_id": 1,
  "track_key": "vehicle_ABC123",
  "track_info": {
    "track_type": "vehicle",
    "first_seen_ts": 1737843600,
    "last_seen_ts": 1737843720,
    "plate": "ABC123"
  },
  "evidence_count": 15,
  "evidence": [
    {"source": "vision", "feature": "class", "value": "vehicle", "conf": 0.98},
    {"source": "vision", "feature": "color", "value": "white", "conf": 0.85},
    {"source": "plate", "feature": "text", "value": "ABC123", "conf": 0.92},
    {"source": "scene", "feature": "vehicle_entered", "value": "true", "conf": 1.0}
  ]
}
```

#### Explain Policy Match
```
Explain why the Halloween greeting policy matched (or didn't match) for this evidence
```

Tool call:
```json
{
  "policy_id": "greet_halloween",
  "evidence": [
    {"source": "vision", "feature": "class", "value": "person", "conf": 0.95}
  ],
  "context": {
    "camera_id": 1
  }
}
```

---

## Tool Reference

### `list_policies`

List all policy rules with optional filtering.

**Parameters:**
- `enabled_only` (boolean, optional): If true, only return enabled policies. Default: `false`

**Returns:**
```json
{
  "count": 5,
  "policies": [ /* array of policy objects */ ]
}
```

---

### `get_policy`

Get detailed information about a specific policy.

**Parameters:**
- `policy_id` (string, required): Policy ID (e.g., `"alert_unknown_vehicle"`)

**Returns:**
```json
{
  "id": "alert_unknown_vehicle",
  "name": "Alert on Unknown Vehicle",
  "description": "Send notification when unknown vehicle detected",
  "priority": 50,
  "enabled": true,
  "conditions": { /* condition object */ },
  "actions": [ /* array of action objects */ ]
}
```

---

### `create_policy`

Create a new policy rule.

**Parameters:**
- `policy_id` (string, required): Unique policy ID
- `name` (string, required): Human-readable name
- `description` (string, optional): Policy description
- `priority` (integer, optional): Priority (higher = evaluated first). Default: `50`
- `conditions` (object, required): Condition rules
- `actions` (array, required): Actions to execute
- `enabled` (boolean, optional): Whether enabled. Default: `true`

**Returns:**
```json
{
  "status": "created",
  "policy_id": "my_new_policy"
}
```

---

### `update_policy`

Update an existing policy (partial updates supported).

**Parameters:**
- `policy_id` (string, required): Policy ID to update
- All other fields from `create_policy` are optional

**Returns:**
```json
{
  "status": "updated",
  "policy_id": "my_policy"
}
```

---

### `delete_policy`

Delete a policy by ID.

**Parameters:**
- `policy_id` (string, required): Policy ID to delete

**Returns:**
```json
{
  "status": "deleted",
  "policy_id": "my_policy"
}
```

---

### `evaluate_policy`

Test policies against evidence (doesn't execute actions).

**Parameters:**
- `evidence` (array, required): List of evidence objects
  - `source` (string): Evidence source (`"vision"`, `"plate"`, `"scene"`, etc.)
  - `feature` (string): Feature name (`"class"`, `"color"`, `"text"`, etc.)
  - `value` (string): Feature value
  - `conf` (number, optional): Confidence score. Default: `1.0`
- `context` (object, optional): Context variables (`camera_id`, `track_key`, etc.)

**Returns:**
```json
{
  "matched_count": 2,
  "matches": [
    {
      "policy_id": "greet_halloween",
      "policy_name": "Halloween Greeting",
      "priority": 90,
      "actions": [ /* actions */ ],
      "variables": { /* resolved variables */ }
    }
  ]
}
```

---

### `get_active_tracks`

Get all currently active scene tracks.

**Parameters:**
- `camera_id` (integer, optional): Camera ID. Default: `1`
- `max_age_seconds` (integer, optional): Maximum age of tracks. Default: `300`

**Returns:**
```json
{
  "camera_id": 1,
  "count": 2,
  "tracks": [ /* array of track objects */ ]
}
```

---

### `query_scene_context`

Query scene state and active intents for policy evaluation.

**Parameters:**
- `camera_id` (integer, optional): Camera ID. Default: `1`
- `timestamp` (integer, optional): Unix timestamp. Default: now

**Returns:**
```json
{
  "camera_id": 1,
  "timestamp": 1737843735,
  "active_tracks": [ /* tracks */ ],
  "active_intents": [ /* intents */ ],
  "num_vehicles": 1,
  "num_people": 0
}
```

---

### `get_visit_history`

Get visit history for a vehicle plate or person.

**Parameters:**
- `plate` (string, optional): License plate number
- `visitor_id` (integer, optional): Visitor ID
- `limit` (integer, optional): Maximum visits to return. Default: `10`

**Note:** Must provide either `plate` or `visitor_id`.

**Returns:**
```json
{
  "plate": "ABC123",
  "count": 3,
  "visits": [ /* array of visit objects */ ]
}
```

---

### `list_scheduled_events`

List scheduled events.

**Parameters:**
- `active_only` (boolean, optional): Only return events active now. Default: `false`

**Returns:**
```json
{
  "count": 2,
  "events": [ /* array of event objects */ ]
}
```

---

### `create_scheduled_event`

Create a new scheduled event.

**Parameters:**
- `name` (string, required): Event name
- `description` (string, optional): Event description
- `start_ts` (integer, required): Start timestamp (Unix epoch)
- `end_ts` (integer, required): End timestamp (Unix epoch)
- `policy_hint` (string, optional): Policy hint for rule matching

**Returns:**
```json
{
  "status": "created",
  "event_id": 5,
  "name": "New Year's Eve Party"
}
```

---

### `get_active_events`

Get all events active at a specific time.

**Parameters:**
- `timestamp` (integer, optional): Unix timestamp. Default: now

**Returns:**
```json
{
  "timestamp": 1737843735,
  "count": 1,
  "events": [ /* array of event objects */ ]
}
```

---

### `get_alert_history`

Retrieve recent alert history, optionally filtered by camera.

**Parameters:**
- `camera_id` (integer, optional): Filter by camera ID
- `limit` (integer, optional): Maximum alerts to return (default 100)

**Returns:**
```json
{
  "count": 50,
  "alerts": [
    {
      "id": 1234,
      "camera_id": 1,
      "policy_id": "night_alert",
      "message": "Motion detected",
      "timestamp": 1737843600
    }
  ]
}
```

---

### `list_quiet_hours`

List all quiet hour schedules.

**Parameters:**
- `weekday` (integer, optional): Filter by weekday (0=Monday, 6=Sunday)
- `enabled_only` (boolean, optional): Only return enabled schedules (default true)

**Returns:**
```json
{
  "count": 7,
  "quiet_hours": [
    {
      "id": 1,
      "name": "Weeknight Sleep",
      "weekday": 0,
      "start_time": "22:00",
      "end_time": "07:00",
      "enabled": true
    }
  ]
}
```

---

### `create_quiet_hour`

Create a new quiet hour schedule.

**Parameters:**
- `name` (string, required): Name for this period (e.g., "Sleep", "Work Hours")
- `weekday` (integer, required): Day of week (0=Monday, 6=Sunday)
- `start_time` (string, required): Start time in HH:MM format (24-hour)
- `end_time` (string, required): End time in HH:MM format (can span overnight)
- `enabled` (boolean, optional): Whether active (default true)

**Returns:**
```json
{
  "status": "created",
  "quiet_hour_id": 8,
  "name": "Weekend Sleep",
  "weekday": 5,
  "start_time": "23:00",
  "end_time": "09:00"
}
```

---

### `update_quiet_hour`

Update an existing quiet hour schedule.

**Parameters:**
- `quiet_hour_id` (integer, required): ID to update
- `name` (string, optional): New name
- `weekday` (integer, optional): New weekday
- `start_time` (string, optional): New start time
- `end_time` (string, optional): New end time
- `enabled` (boolean, optional): New enabled status

**Returns:**
```json
{
  "status": "updated",
  "quiet_hour_id": 8
}
```

---

### `delete_quiet_hour`

Delete a quiet hour schedule.

**Parameters:**
- `quiet_hour_id` (integer, required): ID to delete

**Returns:**
```json
{
  "status": "deleted",
  "quiet_hour_id": 8
}
```

---

### `is_quiet_time`

Check if currently in quiet hours.

**Parameters:**
- `timestamp` (integer, optional): Unix timestamp to check (defaults to now)

**Returns:**
```json
{
  "is_quiet_time": true,
  "timestamp": 1737843600
}
```

---

### `get_active_quiet_hours`

Get all currently active quiet hour schedules.

**Parameters:**
- `timestamp` (integer, optional): Unix timestamp to check (defaults to now)

**Returns:**
```json
{
  "count": 1,
  "active_periods": [
    {
      "id": 1,
      "name": "Weeknight Sleep",
      "weekday": 0,
      "start_time": "22:00",
      "end_time": "07:00"
    }
  ]
}
```

---

### `activate_echonet_listening`

Activate continuous listening mode on Echonet device for multi-turn conversation.

**Parameters:**
- `echonet_url` (string, optional): Echonet base URL (auto-discovers if omitted)
- `target_name` (string, optional): Target name (default "echobell")
- `reason` (string, optional): Human-readable reason for activation

**Returns:**
```json
{
  "status": "activated",
  "listening_mode": "open",
  "timeout_seconds": 30
}
```

---

### `deactivate_echonet_listening`

Deactivate listening mode and return to trigger mode.

**Parameters:**
- `echonet_url` (string, optional): Echonet base URL
- `target_name` (string, optional): Target name (default "echobell")
- `reason` (string, optional): Reason for deactivation

**Returns:**
```json
{
  "status": "deactivated",
  "listening_mode": "trigger"
}
```

---

### `get_echonet_status`

Get status of all discovered Echonet instances.

**Parameters:** None

**Returns:**
```json
{
  "devices": [
    {
      "url": "http://192.168.1.50:8123",
      "registered_targets": ["echobell"],
      "listening_mode": "trigger",
      "status": "ready"
    }
  ]
}
```

---

### `reclassify_visitor_intent`

Reclassify a visitor's intent by adding evidence or directly overriding.

**Parameters:**
- `event_id` (string, required): Visitor event ID to reclassify
- `additional_evidence` (array, optional): Evidence to inject before re-classification
  - Each evidence object should have: `source`, `key`, `value`, `conf` (0-1), optional `object_id`
- `override_intent` (string, optional): Direct intent override (bypasses classification)
- `override_confidence` (float, optional): Confidence for override (0-1)
- `reason` (string, optional): Explanation for audit trail

**Returns:**
```json
{
  "status": "reclassified",
  "event_id": "evt_123456",
  "old_intent": "unknown",
  "new_intent": "delivery_arriving",
  "confidence": 0.92,
  "method": "evidence_injection"
}
```

---

### `get_visitor_event`

Get detailed visitor event information including reclassification history.

**Parameters:**
- `event_id` (string, required): Visitor event ID

**Returns:**
```json
{
  "event_id": "evt_123456",
  "camera_id": 1,
  "timestamp": 1737843600,
  "track_key": "person_98765",
  "current_intent": "delivery_arriving",
  "confidence": 0.92,
  "evidence": [...],
  "reclassification_history": [...]
}
```

---

### `get_scene_evidence` (DEPRECATED)

Get all evidence for a specific scene track.

**Note:** This tool is deprecated. Use `query_scene_context` instead for comprehensive scene information.

**Parameters:**
- `camera_id` (integer, required): Camera ID
- `track_key` (string, required): Track key (e.g., `"vehicle_ABC123"`)

**Returns:**
```json
{
  "camera_id": 1,
  "track_key": "vehicle_ABC123",
  "track_info": { /* track metadata */ },
  "evidence_count": 15,
  "evidence": [ /* array of evidence objects */ ]
}
```

---

### `explain_policy_match` (DEPRECATED)

Explain why a policy matched or didn't match.

**Note:** This tool is deprecated. Use `evaluate_policy` instead for policy testing.

**Parameters:**
- `policy_id` (string, required): Policy ID to explain
- `evidence` (array, required): Evidence to test against
- `context` (object, optional): Context variables

**Returns:**
```json
{
  "policy_id": "greet_halloween",
  "policy_name": "Halloween Greeting",
  "matched": true,
  "priority": 90,
  "conditions": { /* condition object */ },
  "explanation": "Policy matched - all conditions satisfied"
}
```

---

## Common Workflows

### Creating a Time-Based Policy

1. **Create a scheduled event:**
   ```
   Create a scheduled event for "Summer BBQ" on July 4th from 2 PM to 8 PM
   ```

2. **Create a policy that references the event:**
   ```
   Create a policy to greet guests during the BBQ event with policy_hint "bbq_guests"
   ```

3. **Test the policy:**
   ```
   Evaluate the BBQ greeting policy at timestamp [July 4th, 3 PM]
   ```

### Debugging a Policy

1. **Get the policy details:**
   ```
   Show me the details of policy "alert_unknown_vehicle"
   ```

2. **Get evidence from a recent track:**
   ```
   Get all evidence for track "vehicle_XYZ789" on camera 1
   ```

3. **Test the policy with that evidence:**
   ```
   Evaluate policy "alert_unknown_vehicle" with the evidence from vehicle_XYZ789
   ```

4. **Explain the result:**
   ```
   Explain why policy "alert_unknown_vehicle" matched/didn't match for that evidence
   ```

### Monitoring Scene State

1. **Check active tracks:**
   ```
   What tracks are currently active on camera 1?
   ```

2. **Get scene context:**
   ```
   What's the current scene state for policy evaluation on camera 1?
   ```

3. **Review visit history:**
   ```
   Show me the last 10 visits for plate ABC123
   ```

### Correcting Visitor Classification

1. **Get visitor event details:**
   ```
   Show me visitor event evt_123456
   ```

2. **Review the classification:**
   Check the current intent, confidence, and evidence.

3. **Reclassify with additional evidence:**
   ```
   Reclassify evt_123456 - add evidence that uniform is UPS because visitor said they have a package
   ```

4. **Verify the reclassification:**
   ```
   Show me the reclassification history for evt_123456
   ```

---

## Architecture

### Database Schema

The MCP server queries these tables:
- `policy_rules` - Policy definitions
- `scene_tracks` - Active scene tracks
- `visitor_event` - Event history with evidence
- `scheduled_event` - Time-based events
- `plate_visit` - Visit history (privacy-safe)

### Security

- **Database Access**: Read-only for most queries, write access for policy/event management
- **Evidence Privacy**: Plate data is HMAC-hashed for privacy
- **Context Isolation**: Each tool operates independently

### Performance

- **Connection Pooling**: Uses SQLite connection per request
- **Query Optimization**: Indexed queries for active tracks and events
- **Result Limiting**: Default limits prevent excessive data transfer

---

## Troubleshooting

### Server Won't Start

**Error:** `FileNotFoundError: Database not found`

**Solution:** Set `ECHOBELL_DB` environment variable to absolute database path:
```json
{
  "env": {
    "ECHOBELL_DB": "D:\\Projects\\echoBell\\echoBell\\echoBell.db"
  }
}
```

---

### Import Errors

**Error:** `Import "mcp.server" could not be resolved`

**Solution:** Install MCP SDK:
```powershell
pip install mcp
```

---

### No Policies Returned

**Issue:** `list_policies` returns empty array

**Solution:** Check database has policies:
```python
sqlite3 echoBell.db "SELECT COUNT(*) FROM policy_rules;"
```

If empty, seed policies via API or YAML import.

---

## Development

### Adding New Tools

1. **Define tool schema** in `list_tools()`:
   ```python
   Tool(
       name="my_new_tool",
       description="What this tool does",
       inputSchema={
           "type": "object",
           "properties": { /* parameters */ },
           "required": [ /* required params */ ]
       }
   )
   ```

2. **Add handler** in `call_tool()`:
   ```python
   elif name == "my_new_tool":
       result = await handle_my_new_tool(arguments)
   ```

3. **Implement handler function**:
   ```python
   async def handle_my_new_tool(args: dict) -> dict:
       # Implementation
       return {"result": "data"}
   ```

### Testing

Run the server directly for testing:
```powershell
$env:ECHOBELL_DB="D:\Projects\echoBell\echoBell\echoBell.db"
python apps/policy-server/mcp_server.py
```

---

## Architecture: DRY Service Layer

Both the FastAPI HTTP server and the MCP server share the same business logic through a centralized **service layer** (`apps/policy-server/services.py`). This ensures:

- **DRY (Don't Repeat Yourself)**: Core logic is written once and used everywhere
- **Consistency**: Both HTTP and MCP interfaces behave identically
- **Maintainability**: Bug fixes and features update both servers automatically
- **Testability**: Service functions can be tested independently

### Architecture Diagram

```
┌─────────────────┐         ┌──────────────────┐
│  FastAPI HTTP   │         │   MCP Server     │
│     Server      │         │   (stdio/SSE)    │
│  (server.py)    │         │  (mcp_server.py) │
└────────┬────────┘         └────────┬─────────┘
         │                           │
         │    Both use same layer    │
         │                           │
         └──────────┬────────────────┘
                    │
         ┌──────────▼──────────┐
         │   Service Layer     │
         │   (services.py)     │
         │                     │
         │  - Policy CRUD      │
         │  - Scene Tracking   │
         │  - Scheduled Events │
         │  - Alert History    │
         │  - Evidence Query   │
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────┐
         │   SQLite Database   │
         │   (echoBell.db)     │
         └─────────────────────┘
```

### Service Layer Benefits

1. **DRY Code**: Business logic written once, used by both HTTP and MCP
2. **Type Safety**: Service functions are type-hinted and tested
3. **Easy Testing**: Service layer can be tested without server overhead
4. **Flexibility**: Can add new interfaces (GraphQL, gRPC, etc.) using same services
5. **Maintainability**: Bug fixes and features automatically available in both servers
6. **Documentation**: Service layer serves as single source of truth for business logic

### Example: How Both Servers Use Services

**Service function** (apps/policy-server/services.py):
```python
def create_scheduled_event(
    conn: sqlite3.Connection,
    name: str,
    start_ts: int,
    end_ts: int,
    description: str = "",
    policy_hint: str = ""
) -> Dict[str, Any]:
    """Create a new scheduled event."""
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO scheduled_event (...) VALUES (...)",
        (name, description, start_ts, end_ts, policy_hint, now, now)
    )
    conn.commit()
    return {"id": cursor.lastrowid, "name": name, ...}
```

**FastAPI endpoint** (apps/policy-server/server.py):
```python
@app.post("/scheduled_events")
async def create_scheduled_event(event: ScheduledEventCreate):
    try:
        with get_db() as conn:
            created = services.create_scheduled_event(
                conn=conn,
                name=event.name,
                start_ts=event.start_ts,
                end_ts=event.end_ts,
                description=event.description,
                policy_hint=event.policy_hint
            )
        return ScheduledEventResponse(**created)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**MCP tool handler** (apps/policy-server/mcp_server.py):
```python
async def handle_create_scheduled_event(args: dict) -> dict:
    with get_db() as conn:
        event = services.create_scheduled_event(
            conn=conn,
            name=args["name"],
            start_ts=args["start_ts"],
            end_ts=args["end_ts"],
            description=args.get("description", ""),
            policy_hint=args.get("policy_hint", "")
        )
    return {"status": "created", "event": event}
```

Both endpoints call the **exact same** service function, ensuring identical behavior.

---

## Related Documentation

- [Policy API Documentation](POLICY_API.md)
- [Scheduled Events Guide](SCHEDULED_EVENTS.md)
- [Policy Evaluator Reference](POLICY_ENGINE.md)
- [Scene Tracking Architecture](ARCHITECTURE.md)

---

## License

Part of the EchoBell project. See main repository for license details.
