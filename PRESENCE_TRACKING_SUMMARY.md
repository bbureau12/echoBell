# Presence Tracking Implementation Summary

**Status**: ✅ Complete - Ready for Integration  
**Date**: 2026-02-07  
**Related**: ADR-0017, Vehicle Detection, Phone Integration, Policy Layer

---

## Overview

Implemented a comprehensive presence tracking system that answers **"Who is currently home?"** by aggregating evidence from multiple sources with time-decay confidence scoring.

## Architecture

### Dual-Table Design

1. **`presence_events`** - Immutable evidence log (append-only audit trail)
2. **`presence_state`** - Current aggregated state (computed from events)

### Evidence Flow

```
Phone Heartbeat ──┐
Vehicle Present ──┼──> presence_events ──> Aggregator ──> presence_state
Face Detection ───┤                         (time decay)    (home/away)
Manual Override ──┘
```

## What Was Created

### 1. Database Schema
**File**: `infra/db/migrations/019_add_presence_tracking.sql` (338 lines)

- **Tables**:
  - `presence_events`: Evidence log with source, signal, subject_id, person_id, confidence
  - `presence_state`: Current state with status, confidence, last_updated, state_json
  
- **Indexes**:
  - `idx_presence_events_timestamp` - Time-based queries
  - `idx_presence_events_person_time` - Person-based lookups
  - `idx_presence_state_status` - Fast "who is home?" queries
  
- **Views**:
  - `recent_presence_events` - Last 24 hours of events
  - `presence_summary` - Denormalized current state with signal counts
  
- **Auto-cleanup**: Trigger deletes events older than 30 days

### 2. Core Service
**File**: `packages/presence/services.py` (421 lines)

**Classes**:
- `PresenceService` - Main service API
- `PresenceEvent` - Single evidence dataclass
- `PresenceState` - Current state dataclass

**Key Methods**:
- `insert_event()` - Add evidence (phone heartbeat, vehicle detection, etc.)
- `get_recent_events()` - Fetch events for aggregation
- `update_presence_state()` - Calculate and persist new state
- `get_presence()` - Get current state for person
- `get_all_presence()` - Get all tracked people
- `is_anyone_home()` - Fast boolean check
- `is_everyone_away()` - Fast boolean check
- `set_manual_override()` - User voice commands ("I'm leaving for 2 hours")

**Enums**:
- `PresenceStatus`: HOME, AWAY, UNCERTAIN
- `PresenceSource`: PHONE, PLATE, FACE, MANUAL, BLUETOOTH, OTHER
- `PresenceSignal`: HEARTBEAT, VEHICLE_PRESENT, VEHICLE_LEFT, FACE_SEEN, OVERRIDE_HOME, OVERRIDE_AWAY

### 3. Aggregation Logic
**File**: `packages/presence/aggregator.py` (362 lines)

**Algorithm**:
1. Collect recent evidence (last hour)
2. Apply **exponential time decay** per source type
3. Combine signals with weighted average
4. Generate human-readable reasons
5. Return status (home/away/uncertain) with confidence

**Time Decay Configurations**:
| Source | Half-Life | Max Age | Rationale |
|--------|-----------|---------|-----------|
| Phone | 5 min | 15 min | High decay - phones are mobile |
| Vehicle | 1 hour | 2 hours | Low decay - cars stay parked |
| Face | 30 min | 1 hour | Medium decay |
| Manual | None | Check expiration | No decay until user-specified time |
| Bluetooth | 3 min | 10 min | Very high decay - short range |

**Key Functions**:
- `calculate_time_decay()` - Exponential decay formula
- `combine_signals()` - Weighted average with sign (+home, -away)
- `generate_reasons()` - Human-readable explanations
- `extract_evidence_summary()` - Structured evidence dict
- `calculate_presence_state()` - Main aggregation entry point

### 4. Comprehensive Tests
**File**: `tests/test_presence_tracking.py` (478 lines)

**Test Coverage** (18 tests):
- ✅ Insert phone heartbeat
- ✅ Insert vehicle present/left
- ✅ Manual overrides
- ✅ Single-source presence (phone only, vehicle only)
- ✅ Multi-source presence (phone + vehicle + face)
- ✅ Conflicting signals (car present, phone old)
- ✅ Time decay validation (phone vs vehicle)
- ✅ anyone_home() / everyone_away() queries
- ✅ Manual override expiration
- ✅ Get all presence
- ✅ Serialization (to_dict)
- ✅ No evidence = uncertain

### 5. Example Demos
**File**: `examples/presence_demos.py` (399 lines)

**Demos**:
1. `demo_vehicle_presence_hook()` - Vehicle detection integration
2. `demo_phone_heartbeat()` - Phone WiFi heartbeats
3. `demo_manual_override_voice()` - "I'm leaving for 2 hours"
4. `demo_policy_condition()` - Policy decisions based on presence
5. `demo_multi_person_presence()` - Family tracking
6. `demo_complete_workflow()` - Full day simulation

### 6. Architecture Decision Record
**File**: `docs/adr/ADR-0017-presence-tracking-system.md` (495 lines)

**Sections**:
- Context (problems with event-centric approach)
- Decision (dual-table with aggregation)
- Architecture diagrams
- Schema design rationale
- Confidence aggregation algorithm
- Policy integration examples
- API endpoints (planned)
- MCP tools (planned)
- Consequences (positive/negative)
- Alternatives considered (single table, Redis, per-source tables)
- Implementation plan (6 phases)

### 7. Package Structure
**File**: `packages/presence/__init__.py`

Exports:
- `PresenceService`, `create_presence_service`
- `PresenceEvent`, `PresenceState`
- `PresenceStatus`, `PresenceSource`, `PresenceSignal`
- `calculate_presence_state`, `calculate_time_decay`

---

## Example Usage

### Insert Evidence
```python
from packages.presence import create_presence_service

service = create_presence_service("path/to/db.sqlite")

# Phone heartbeat
service.insert_event(
    source="phone",
    signal="heartbeat",
    subject_id="beau_phone",
    person_id="beau",
    confidence=0.95,
    metadata={"ip": "192.168.1.50", "rssi": -42}
)

# Vehicle detected
service.insert_event(
    source="plate",
    signal="vehicle_present",
    subject_id="beau_tesla",
    person_id="beau",
    confidence=0.90,
    metadata={"plate": "ABC123", "camera_id": 1}
)

# Manual override (voice command)
service.set_manual_override(
    person_id="beau",
    status="away",
    duration_hours=2,
    reason="Going to store"
)
```

### Query Presence
```python
# Get specific person
state = service.get_presence("beau")
print(f"{state.person_id} is {state.status} (confidence: {state.confidence})")
print(f"Reasons: {', '.join(state.reasons)}")

# Get all people
all_states = service.get_all_presence()
for state in all_states:
    print(f"{state.person_id}: {state.status}")

# Quick checks
if service.is_anyone_home():
    print("Someone is home")

if service.is_everyone_away():
    print("House is empty - enable security mode")
```

### State Output Example
```json
{
  "person_id": "beau",
  "status": "home",
  "confidence": 0.86,
  "last_updated": 1738891000,
  "reasons": [
    "phone_seen_2m_ago",
    "tesla_present"
  ],
  "evidence": {
    "phone_last_seen": 1738890880,
    "vehicles_present": ["tesla"],
    "face_last_seen": null
  },
  "raw_signals": [
    {"source": "phone", "confidence": 0.95, "time_factor": 0.741, "decayed_confidence": 0.704, "age_seconds": 120},
    {"source": "plate", "confidence": 0.90, "time_factor": 0.951, "decayed_confidence": 0.856, "age_seconds": 300}
  ]
}
```

---

## Integration Points

### 1. Vehicle Detection Hook (Immediate)
```python
# In vehicle detection handler
def on_trusted_vehicle_detected(plate, person_id, camera_id):
    presence_service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id=f"{person_id}_{plate}",
        person_id=person_id,
        confidence=0.90,
        metadata={"plate": plate, "camera_id": camera_id}
    )
    presence_service.update_presence_state(person_id)

def on_trusted_vehicle_left(plate, person_id, camera_id):
    presence_service.insert_event(
        source="plate",
        signal="vehicle_left",
        subject_id=f"{person_id}_{plate}",
        person_id=person_id,
        confidence=0.90,
        metadata={"plate": plate, "camera_id": camera_id}
    )
    presence_service.update_presence_state(person_id)
```

### 2. Policy Conditions (Immediate)
```yaml
# New policy conditions
conditions:
  all:
    - type: person_home
      person_id: "beau"
      confidence_min: 0.7
      inverse: false  # Is home
    
    - type: anyone_home
      confidence_min: 0.6
      inverse: true  # Nobody home
```

### 3. Background Worker (Next Step)
```python
# Run every 60 seconds to refresh all presence states
def update_all_presence_states():
    for person_id in get_all_tracked_people():
        presence_service.update_presence_state(person_id)
```

### 4. Phone Integration (Future)
- Webhook endpoint: `POST /api/presence/heartbeat`
- Phone app sends heartbeat every 60s when on home WiFi
- Include IP, RSSI, connection type in metadata

### 5. MCP Tools (Future)
```python
@mcp_tool
def get_presence_status(person_id: Optional[str] = None):
    """Check who is currently home."""
    if person_id:
        state = presence_service.get_presence(person_id)
        return f"{person_id} is {state.status} (confidence: {state.confidence})"
    else:
        states = presence_service.get_all_presence()
        return [s.to_dict() for s in states]

@mcp_tool
def set_presence_override(person_id: str, status: str, duration_hours: int):
    """Manually set presence (e.g., 'I'm leaving for 2 hours')."""
    presence_service.set_manual_override(person_id, status, duration_hours)
    return f"Set {person_id} to {status} for {duration_hours} hours"
```

---

## Next Steps

### Phase 1: Vehicle Integration (Immediate)
- [ ] Hook vehicle detection events into `presence_events`
- [ ] Test with actual vehicle detections
- [ ] Verify state updates correctly

### Phase 2: Policy Integration (Immediate)
- [ ] Add `person_home` policy condition
- [ ] Add `anyone_home` policy condition
- [ ] Add `everyone_away` policy condition
- [ ] Test policies: "Don't notify if owner is home"

### Phase 3: Background Worker
- [ ] Create worker to update all presence states every 60s
- [ ] Add monitoring/alerting if worker stops
- [ ] Optimize query performance

### Phase 4: API Endpoints
- [ ] `POST /api/presence/event` - Insert evidence
- [ ] `GET /api/presence/status/{person_id}` - Get state
- [ ] `GET /api/presence/status` - Get all states
- [ ] `POST /api/presence/override` - Manual override

### Phase 5: Phone Integration
- [ ] Design phone app webhook API
- [ ] Implement authentication for phone requests
- [ ] Test WiFi heartbeat detection
- [ ] Consider Bluetooth beacon support

### Phase 6: MCP Integration
- [ ] Add MCP tools for presence queries
- [ ] Add MCP tool for manual overrides
- [ ] Test voice commands: "Am I home?", "I'm leaving for 2 hours"

---

## Testing

### Run Tests
```bash
pytest tests/test_presence_tracking.py -v
```

### Run Example Demos
```bash
python examples/presence_demos.py
```

### Apply Migration
```bash
sqlite3 your_database.db < infra/db/migrations/019_add_presence_tracking.sql
```

---

## Performance Considerations

### Indexes
All critical queries are indexed:
- `presence_events(timestamp)` - Recent event queries
- `presence_events(person_id, timestamp)` - Person-specific lookups
- `presence_state(status)` - "Who is home?" queries
- `presence_state(status, confidence)` - High-confidence checks

### Auto-Cleanup
Trigger deletes events older than 30 days automatically, preventing unbounded growth.

### Caching Strategy
- `presence_state` acts as materialized view (cached aggregation)
- Background worker refreshes every 60s
- Policies can read directly from `presence_state` (no aggregation needed)

---

## Key Design Decisions

1. **Dual-table design** - Events immutable, state computed (enables audit trail + fast queries)
2. **Time decay** - Old signals automatically weaken (realistic confidence degradation)
3. **Multi-source** - Phone + car + face > any single signal (robust against false negatives)
4. **Manual overrides trump sensors** - User knows best (definitive confidence 1.0)
5. **Confidence-based status** - Not binary home/away (handles uncertainty gracefully)
6. **Person-centric** - Tracks individuals, not just "house occupied" (multi-person support)

---

## Files Created

1. ✅ `docs/adr/ADR-0017-presence-tracking-system.md` (495 lines)
2. ✅ `infra/db/migrations/019_add_presence_tracking.sql` (338 lines)
3. ✅ `packages/presence/__init__.py` (38 lines)
4. ✅ `packages/presence/services.py` (421 lines)
5. ✅ `packages/presence/aggregator.py` (362 lines)
6. ✅ `tests/test_presence_tracking.py` (478 lines)
7. ✅ `examples/presence_demos.py` (399 lines)

**Total**: 2,531 lines of production-ready code + tests + documentation

---

## Success Criteria

- [x] Track presence from multiple sources (phone, vehicle, face, manual)
- [x] Aggregate signals with time decay
- [x] Support manual overrides with expiration
- [x] Fast queries for policy conditions
- [x] Full audit trail in events table
- [x] Comprehensive test coverage (18 tests)
- [x] Example workflows for all integration points
- [x] Complete documentation (ADR + code comments)

**Status**: ✅ **Ready for integration with vehicle detection and policy layer!**
