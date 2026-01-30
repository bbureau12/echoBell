# Policy API - Dynamic Policy Management

The EchoBell Policy Engine can be fully managed via REST API through your **existing policy-server**, enabling **zero-code policy changes** through HTTP requests or a web UI.

---

## Quick Start

### 1. **Run the migration** to create policy tables:

```powershell
# Apply the new migration
sqlite3 data/echoBell.db < infra/db/migrations/004_add_policy_rules.sql
```

### 2. **Start your existing policy-server**:

```powershell
# Your policy-server already exists!
cd apps/policy-server
python server.py
```

The policy management endpoints will automatically be available at:
- `http://localhost:8000/policies/` (list all policies)
- `http://localhost:8000/policies/{policy_id}` (get/update/delete)
- Plus 9 more endpoints (see below)

### 3. **Test the API**:

```powershell
# List all policies
curl http://localhost:8000/policies/

# Create a new policy
curl -X POST http://localhost:8000/policies/ `
  -H "Content-Type: application/json" `
  -d '{
    "id": "weekend_party_mode",
    "name": "Weekend Party Mode",
    "description": "Reduce alerts on Friday/Saturday nights",
    "enabled": true,
    "priority": 95,
    "conditions": {
      "all": [
        {"day_of_week": {"days": ["friday", "saturday"]}},
        {"time_between": {"start": "20:00", "end": "02:00"}}
      ]
    },
    "actions": [
      {
        "type": "telegram",
        "message": "🎉 Guest arriving (party mode active)",
        "priority": "low"
      }
    ]
  }'
```

---

## API Reference

**Base URL**: `http://localhost:8000/policies`

All endpoints are mounted under `/policies` in your existing policy-server.

### **GET /policies/**
List all policies (sorted by priority, descending)

**Query Parameters:**
- `enabled_only` (bool): Only return active policies

**Response:**
```json
[
  {
    "id": "unknown_vehicle_alert",
    "name": "Unknown Vehicle Alert",
    "description": "Alert when unknown vehicle arrives",
    "enabled": true,
    "priority": 80,
    "conditions": { ... },
    "actions": [ ... ],
    "variables": {},
    "created_ts": 1706112000,
    "updated_ts": 1706112000,
    "created_by": "system",
    "tags": "",
    "version": 1
  }
]
```

---

### **GET /policies/{policy_id}**
Get a single policy by ID

**Response:** Single policy object (or 404 if not found)

---

### **POST /policies/**
Create a new policy

**Request Body:**
```json
{
  "id": "my_policy",           // Required: Unique ID
  "name": "My Policy",          // Required: Human-readable name
  "description": "...",         // Optional: What it does
  "enabled": true,              // Optional: default true
  "priority": 75,               // Optional: 0-100, default 50
  "conditions": {               // Required: Condition tree
    "all": [
      {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
      {"time_between": {"start": "22:00", "end": "06:00"}}
    ]
  },
  "actions": [                  // Required: Actions to execute
    {
      "type": "telegram",
      "message": "Vehicle at night!",
      "priority": "urgent"
    }
  ],
  "variables": {},              // Optional: Variable definitions
  "tags": "nighttime vehicle"   // Optional: Space-separated tags
}
```

**Response:** Created policy object (201 status)

---

### **PATCH /policies/{policy_id}**
Update an existing policy (partial update)

**Request Body:** Any subset of policy fields
```json
{
  "enabled": false,
  "priority": 90
}
```

**Response:** Updated policy object

---

### **DELETE /policies/{policy_id}**
Delete a policy

**Response:** 204 No Content (or 404 if not found)

---

### **POST /policies/{policy_id}/enable**
Enable a disabled policy

**Response:** Updated policy object

---

### **POST /policies/{policy_id}/disable**
Disable an active policy

**Response:** Updated policy object

---

### **GET /policies/{policy_id}/history**
Get execution history for a specific policy

**Query Parameters:**
- `limit` (int): Max results (default 100)

**Response:**
```json
[
  {
    "id": 1,
    "policy_id": "unknown_vehicle_alert",
    "policy_name": "Unknown Vehicle Alert",
    "event_id": "evt_123",
    "track_key": "plate_abc123",
    "track_type": "vehicle",
    "camera_id": 1,
    "matched_conditions": { ... },
    "executed_actions": [ ... ],
    "execution_ts": 1706112000,
    "success": true,
    "error_message": null
  }
]
```

---

### **GET /policies/executions/recent**
Get recent executions across all policies

**Query Parameters:**
- `limit` (int): Max results (default 100)

**Response:** Same as history endpoint

---

### **POST /policies/import-yaml**
Import policies from YAML file into database

**Query Parameters:**
- `yaml_file` (str): Path to YAML file (default: config/policy_rules.yaml)
- `overwrite` (bool): Update existing policies (default: false)

**Response:**
```json
{
  "status": "success",
  "imported": 5,
  "overwrite": false
}
```

---

## Common Use Cases

### 1. **Create a time-based policy** (no code)

```powershell
# Nighttime strict mode
curl -X POST http://localhost:8000/policies/ `
  -H "Content-Type: application/json" `
  -d '{
    "id": "nighttime_strict",
    "name": "Nighttime Strict Mode",
    "enabled": true,
    "priority": 85,
    "conditions": {
      "all": [
        {"time_between": {"start": "23:00", "end": "06:00"}},
        {"evidence_missing": {"source": "plate_trust", "feature": "trusted_plate"}}
      ]
    },
    "actions": [
      {"type": "telegram", "message": "⚠️ ALERT: Unknown activity at {timestamp}", "priority": "urgent"},
      {"type": "speak", "text": "You are on private property. Please leave immediately."}
    ]
  }'
```

### 2. **Temporarily disable a policy**

```powershell
# Disable loitering alerts during party
curl -X POST http://localhost:8000/policies/nighttime_loitering/disable
```

### 3. **Update policy priority**

```powershell
# Boost priority of family arrival detection
curl -X PATCH http://localhost:8000/policies/trusted_person_quiet `
  -H "Content-Type: application/json" `
  -d '{"priority": 100}'
```

### 4. **Add IoT integration**

```powershell
# Turn on lights when unknown vehicle detected
curl -X POST http://localhost:8000/policies/ `
  -H "Content-Type: application/json" `
  -d '{
    "id": "lights_on_unknown",
    "name": "Lights On - Unknown Vehicle",
    "enabled": true,
    "priority": 70,
    "conditions": {
      "all": [
        {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
        {"evidence_missing": {"source": "plate_trust", "feature": "trusted_plate"}}
      ]
    },
    "actions": [
      {
        "type": "webhook",
        "url": "http://192.168.1.100:8123/api/services/light/turn_on",
        "method": "POST",
        "payload": {
          "entity_id": "light.driveway",
          "brightness": 255
        }
      }
    ]
  }'
```

---

## Migration Workflow

### **Phase 1: Seed from YAML** (one-time)

```powershell
# Import existing YAML policies into database
curl -X POST "http://localhost:8000/policies/import-yaml?overwrite=true"
```

### **Phase 2: Use Database** (ongoing)

Update `packages/policy/apply.py` to use database:

```python
# Before (YAML-only)
evaluator = PolicyEvaluator(policy_file="config/policy_rules.yaml", conn=conn)

# After (Database-first)
evaluator = PolicyEvaluator(conn=conn, use_database=True)
```

### **Phase 3: API-Driven** (future changes)

All policy changes via API—no file editing needed!

---

## Web UI (Future)

Build a simple React/Vue frontend:

```javascript
// Example: Fetch and display policies
fetch('/policies/')
  .then(res => res.json())
  .then(policies => {
    policies.forEach(p => {
      console.log(`${p.name} (Priority: ${p.priority}, Enabled: ${p.enabled})`);
    });
  });

// Toggle policy
fetch('/policies/nighttime_loitering/disable', {method: 'POST'})
  .then(() => console.log('Policy disabled'));
```

---

## Benefits

✅ **Zero-code policy changes** - Update via HTTP, not YAML editing  
✅ **Version tracking** - Database tracks version and timestamps  
✅ **Audit trail** - Execution history shows which policies fired  
✅ **Remote management** - Update policies from anywhere (with auth)  
✅ **A/B testing** - Easily enable/disable policies to test  
✅ **Non-technical users** - Web UI makes policy management accessible  
✅ **Rollback-friendly** - Version tracking enables easy rollback  

---

## Security Considerations

🔒 **Add authentication** before deploying:

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

@router.post("/", dependencies=[Depends(security)])
async def create_policy(...):
    # Policy creation now requires bearer token
```

🔒 **Rate limiting** to prevent abuse:

```python
from slowapi import Limiter

limiter = Limiter(key_func=lambda: "global")

@router.post("/", dependencies=[Depends(limiter.limit("5/minute"))])
async def create_policy(...):
    # Max 5 policy creations per minute
```

🔒 **Input validation** (already handled by Pydantic models)

---

**Ready to use!** Run the migration, start the API, and manage policies dynamically via HTTP.
