# Policy Management Integration Summary

## What We Built

You asked: **"How would we drive new policies without adjusting the code?"**

Answer: **Use your existing Policy API server with new database-backed policy management!**

---

## Key Components

### ✅ Already Existed (Your Work):
- **`apps/policy-server/server.py`** - FastAPI server with scene tracking
- **Policy evaluation engine** - YAML-based policy rules
- **Scene tracking** - Cross-camera vehicle/person tracking

### ✅ Newly Added (This Session):
1. **Database Migration** (`infra/db/migrations/004_add_policy_rules.sql`)
   - `policy_rules` table - JSON-based policy storage
   - `policy_executions` table - Audit trail
   - 3 seed policies

2. **Policy Service** (`packages/policy/policy_service.py`)
   - CRUD operations for policies
   - Execution logging
   - YAML import functionality

3. **REST API Router** (`apps/doorbell-agent/api_policies.py`)
   - 12 endpoints for policy management
   - Auto-integrated into your existing policy-server

4. **Updated Evaluator** (`packages/policy/evaluator.py`)
   - Load from database OR YAML
   - `use_database=True` flag

5. **Tests** (`tests/test_policy_api.py`)
   - 14 tests, all passing ✅

---

## How To Use

### 1. **Setup** (one-time):

```powershell
# Run migration
sqlite3 data/echoBell.db < infra/db/migrations/004_add_policy_rules.sql

# Start your existing server
cd apps/policy-server
python server.py
```

### 2. **Manage Policies via API** (no code changes):

```powershell
# List policies
curl http://localhost:8000/policies/

# Create new policy
curl -X POST http://localhost:8000/policies/ `
  -H "Content-Type: application/json" `
  -d '{
    "id": "weekend_mode",
    "name": "Weekend Party Mode",
    "enabled": true,
    "priority": 95,
    "conditions": {
      "day_of_week": {"days": ["friday", "saturday"]}
    },
    "actions": [
      {"type": "telegram", "message": "Guest arriving!", "priority": "low"}
    ]
  }'

# Disable policy
curl -X POST http://localhost:8000/policies/weekend_mode/disable

# Delete policy
curl -X DELETE http://localhost:8000/policies/weekend_mode
```

### 3. **Import YAML policies to database**:

```powershell
# One-time import
curl -X POST "http://localhost:8000/policies/import-yaml?overwrite=true"
```

---

## API Endpoints

Your existing `policy-server` now has these additional endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/policies/` | List all policies |
| `GET` | `/policies/{id}` | Get specific policy |
| `POST` | `/policies/` | Create new policy |
| `PATCH` | `/policies/{id}` | Update policy |
| `DELETE` | `/policies/{id}` | Delete policy |
| `POST` | `/policies/{id}/enable` | Enable policy |
| `POST` | `/policies/{id}/disable` | Disable policy |
| `GET` | `/policies/{id}/history` | Get execution history |
| `GET` | `/policies/executions/recent` | Recent executions (all policies) |
| `POST` | `/policies/import-yaml` | Import from YAML file |

**Plus your existing endpoints:**
- `/health`
- `/scene/update`
- `/scene/tracks/{camera_id}`
- `/scene/vehicles/{camera_id}`
- `/scene/people/{camera_id}`
- `/scene/summary/{camera_id}`
- `/evidence`

---

## Benefits

✅ **No code changes** - Policies managed via HTTP  
✅ **Database-backed** - Persistent, versioned  
✅ **Audit trail** - Execution history tracked  
✅ **Remote management** - Update from anywhere  
✅ **A/B testing** - Enable/disable to test  
✅ **Web UI ready** - Easy frontend integration  
✅ **Works with existing server** - Integrated cleanly  

---

## Migration Path

### Phase 1: Seed Database (one-time)
```powershell
# Import existing YAML policies
curl -X POST "http://localhost:8000/policies/import-yaml?overwrite=true"
```

### Phase 2: Switch to Database Loading
Update `packages/policy/apply.py`:
```python
# Before (YAML-only)
evaluator = PolicyEvaluator(policy_file="config/policy_rules.yaml", conn=conn)

# After (Database-first)
evaluator = PolicyEvaluator(conn=conn, use_database=True)
```

### Phase 3: API-Driven (ongoing)
All future policy changes via API—no YAML editing!

---

## Next Steps

1. **Run migration**: `sqlite3 data/echoBell.db < infra/db/migrations/004_add_policy_rules.sql`
2. **Import YAML**: `curl -X POST http://localhost:8000/policies/import-yaml`
3. **Test API**: `curl http://localhost:8000/policies/`
4. **Update evaluator**: Change to `use_database=True`
5. **Create policies via API**: No more YAML editing!

---

## Files Changed/Created

**New Files:**
- `infra/db/migrations/004_add_policy_rules.sql` - Database schema
- `packages/policy/policy_service.py` - CRUD service
- `apps/doorbell-agent/api_policies.py` - FastAPI router
- `tests/test_policy_api.py` - 14 passing tests
- `docs/POLICY_API.md` - Complete API reference

**Modified Files:**
- `apps/policy-server/server.py` - Integrated policy router
- `packages/policy/evaluator.py` - Added database loading

---

**You're ready to manage policies via API!** 🎉
