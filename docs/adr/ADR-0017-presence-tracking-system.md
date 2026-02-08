# ADR-0017: Presence Tracking System

**Status**: Accepted  
**Date**: 2026-02-07  
**Deciders**: System Architect  
**Related**: ADR-0008 (Trusted Entity Allowlists), ADR-0010 (Cross-Camera Person Tracking), Scheduled Events

---

## Context

EchoBell currently tracks individual visitor events (person detected, vehicle arrived) but lacks a **holistic view of who is currently home**. This creates several limitations:

### Problems

1. **No "Home/Away" State**: System can't answer "Is Beau home?" without scanning recent events
2. **Fragmented Signals**: Phone heartbeats, vehicle presence, and face recognition are isolated
3. **No Confidence Aggregation**: Multiple weak signals (phone last seen 5min ago + car present) should combine into strong confidence
4. **Policy Limitations**: Can't write policies like "only notify if nobody is home"
5. **No Manual Overrides**: User can't tell system "I'm leaving for 2 hours"

### Use Cases

- **Quiet Hours Enhancement**: "Don't ring doorbell if anyone is home"
- **Security Policies**: "Alert immediately if stranger detected when nobody home"
- **Smart Notifications**: "Only send Telegram if owner is away"
- **LLM Context**: "Who's home right now?" → "Beau is home (phone seen 2min ago, car present)"
- **Automation Integration**: "Turn on lights when first person arrives home"

### Requirements

1. Track presence for multiple people (not just binary home/away)
2. Aggregate evidence from multiple sources (phones, vehicles, face recognition, manual input)
3. Maintain confidence scores that decay over time
4. Support manual overrides ("I'm leaving for 2 hours")
5. Efficient lookups (policy conditions need fast "is anyone home?" checks)
6. Audit trail of all presence evidence

---

## Decision

**We will implement a dual-table presence tracking system: `presence_events` for evidence collection and `presence_state` for current aggregated state.**

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Evidence Sources                          │
├──────────────────┬──────────────────┬───────────────────────┤
│  Phone Heartbeat │  Vehicle Present │  Manual Override      │
│  (every 60s)     │  (camera detect) │  (voice/API)          │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│              presence_events (Evidence Log)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ timestamp: 1738891000                                  │ │
│  │ source: "phone"                                        │ │
│  │ signal: "heartbeat"                                    │ │
│  │ subject_id: "beau_phone"                               │ │
│  │ person_id: "beau" ←─────────────────────┐              │ │
│  │ confidence: 0.95                         │              │ │
│  │ metadata: {"ip": "192.168.1.50", ...}    │              │ │
│  └────────────────────────────────────────────────────────┘ │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│           Presence Aggregator (Service Layer)                │
│  - Aggregates evidence per person                            │
│  - Applies time decay to old signals                         │
│  - Combines confidence scores                                │
│  - Updates presence_state table                              │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│              presence_state (Current State)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ person_id: "beau"                                      │ │
│  │ status: "home"                                         │ │
│  │ confidence: 0.86                                       │ │
│  │ last_updated: 1738891000                               │ │
│  │ state_json: {                                          │ │
│  │   "reasons": [                                         │ │
│  │     "phone_seen_2m_ago",                               │ │
│  │     "both_cars_present"                                │ │
│  │   ],                                                   │ │
│  │   "evidence": {                                        │ │
│  │     "phone_last_seen": 1738890880,                     │ │
│  │     "vehicles_present": ["tesla", "truck"]             │ │
│  │   }                                                    │ │
│  │ }                                                      │ │
│  └────────────────────────────────────────────────────────┘ │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Policy Conditions                         │
│  - person_home("beau")                                       │
│  - anyone_home()                                             │
│  - everyone_away()                                           │
│  - presence_confidence_gt(person, threshold)                 │
└─────────────────────────────────────────────────────────────┘
```

### Schema Design

#### Table 1: `presence_events` (Evidence Log)

```sql
CREATE TABLE presence_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    source TEXT NOT NULL,           -- "phone", "plate", "face", "manual"
    signal TEXT NOT NULL,            -- "heartbeat", "vehicle_present", "vehicle_left", 
                                     -- "face_seen", "override_home", "override_away"
    subject_id TEXT NOT NULL,        -- "beau_phone", "beau_tesla", "beau_face"
    person_id TEXT,                  -- "beau" (links to trusted_people or similar)
    confidence REAL,                 -- 0.0-1.0 (NULL for definitive signals)
    metadata_json TEXT,              -- {"ip": "...", "rssi": -45, "camera_id": 1, ...}
    
    INDEX idx_presence_timestamp (timestamp),
    INDEX idx_presence_person_time (person_id, timestamp),
    INDEX idx_presence_subject (subject_id)
);
```

**Why Separate `subject_id` and `person_id`?**
- `subject_id`: The specific device/entity ("beau_phone", "beau_tesla")
- `person_id`: The person it belongs to ("beau")
- Allows one person to have multiple signal sources
- Enables aggregation: "beau's phone OR beau's car"

#### Table 2: `presence_state` (Current State)

```sql
CREATE TABLE presence_state (
    person_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,            -- "home", "away", "uncertain"
    confidence REAL NOT NULL,        -- 0.0-1.0
    last_updated INTEGER NOT NULL,
    state_json TEXT,                 -- Full state with reasons and evidence
    
    INDEX idx_presence_status (status)
);
```

**Why JSON State Instead of Columns?**
- Flexible evidence structure (phones, cars, faces vary per person)
- Reasons array can grow/shrink without schema changes
- Easy to serialize for API responses
- Still indexed on status for fast policy lookups

### Evidence Sources & Signals

| Source | Signal | Subject ID | Confidence | Metadata |
|--------|--------|------------|------------|----------|
| `phone` | `heartbeat` | `{person}_phone` | 0.95 | `{ip, rssi, last_seen}` |
| `plate` | `vehicle_present` | `{person}_{vehicle}` | 0.90 | `{plate, camera_id, event_id}` |
| `plate` | `vehicle_left` | `{person}_{vehicle}` | -0.90 | `{plate, camera_id}` |
| `face` | `face_seen` | `{person}_face` | 0.70-0.95 | `{camera_id, embedding_distance}` |
| `manual` | `override_home` | `{person}` | 1.0 | `{source: "voice", duration_hours}` |
| `manual` | `override_away` | `{person}` | 1.0 | `{source: "voice", duration_hours}` |

### Confidence Aggregation Algorithm

```python
def calculate_presence_confidence(person_id: str, current_time: int) -> dict:
    """
    Aggregate recent evidence into presence confidence.
    
    Returns:
        {
            "status": "home" | "away" | "uncertain",
            "confidence": 0.0-1.0,
            "reasons": ["phone_seen_2m_ago", ...],
            "evidence": {...}
        }
    """
    evidence = get_recent_evidence(person_id, lookback_seconds=3600)
    
    signals = []
    
    for event in evidence:
        # Time decay: confidence decreases over time
        age_seconds = current_time - event.timestamp
        time_factor = calculate_time_decay(age_seconds, event.source)
        
        # Signal confidence
        signal_conf = event.confidence or 1.0
        
        # Decayed confidence
        decayed_conf = signal_conf * time_factor
        
        # Add to signals with sign (+home, -away)
        if event.signal in ("heartbeat", "vehicle_present", "face_seen", "override_home"):
            signals.append(decayed_conf)
        elif event.signal in ("vehicle_left", "override_away"):
            signals.append(-decayed_conf)
    
    # Combine signals (weighted average or Bayesian)
    final_confidence = combine_signals(signals)
    
    # Determine status
    if final_confidence > 0.6:
        status = "home"
    elif final_confidence < -0.6:
        status = "away"
    else:
        status = "uncertain"
    
    return {
        "status": status,
        "confidence": abs(final_confidence),
        "reasons": generate_reasons(evidence, current_time),
        "evidence": extract_evidence_summary(evidence)
    }
```

**Time Decay Functions**:
- **Phone heartbeat**: High decay (5min window → 0.5 confidence, 15min → 0.1)
- **Vehicle present**: Low decay (2hr window → 0.9 confidence)
- **Face seen**: Medium decay (30min window → 0.6 confidence)
- **Manual override**: No decay until expiration time

### Policy Integration

New policy conditions:

```yaml
# Don't notify if owner is home
conditions:
  all:
    - type: person_home
      person_id: "beau"
      confidence_min: 0.7
      inverse: true  # NOT home

# Only alert if nobody home
conditions:
  all:
    - type: anyone_home
      confidence_min: 0.6
      inverse: true  # Nobody home

# Alert if specific person away
conditions:
  all:
    - type: person_presence
      person_id: "beau"
      status: "away"
      confidence_min: 0.8
```

### API Endpoints

```python
# Insert evidence
POST /api/presence/event
{
    "source": "phone",
    "signal": "heartbeat",
    "subject_id": "beau_phone",
    "person_id": "beau",
    "confidence": 0.95,
    "metadata": {"ip": "192.168.1.50", "rssi": -42}
}

# Get current presence
GET /api/presence/status/{person_id}
→ {"status": "home", "confidence": 0.86, "reasons": [...]}

# Get all presence
GET /api/presence/status
→ [{"person_id": "beau", "status": "home", ...}, ...]

# Manual override
POST /api/presence/override
{
    "person_id": "beau",
    "status": "away",
    "duration_hours": 2,
    "reason": "Going to store"
}
```

### MCP Tools

```python
# LLM can check presence
@mcp_tool
def get_presence_status(person_id: Optional[str] = None):
    """Get who is currently home."""
    if person_id:
        return get_person_presence(person_id)
    else:
        return get_all_presence()

@mcp_tool
def set_presence_override(person_id: str, status: str, duration_hours: int):
    """Manually set presence (e.g., 'I'm leaving for 2 hours')."""
    insert_presence_event(
        source="manual",
        signal=f"override_{status}",
        subject_id=person_id,
        person_id=person_id,
        confidence=1.0,
        metadata={"source": "llm", "duration_hours": duration_hours}
    )
```

---

## Consequences

### Positive

1. **Holistic Presence View**: Answers "Who's home?" in one query
2. **Multi-Signal Fusion**: Phone + car + face = high confidence
3. **Time Awareness**: Old signals decay naturally
4. **Policy Enhancement**: Rich conditions for smart automation
5. **Manual Control**: Users can override ("I'm leaving for 2 hours")
6. **Audit Trail**: Full history in `presence_events`
7. **LLM Integration**: "Is Beau home?" → Natural language response
8. **Extensible**: Easy to add new sources (Bluetooth beacons, door locks, etc.)

### Negative

1. **Complexity**: Two tables + aggregation logic vs simple event lookup
2. **Phone Dependency**: Requires phone app integration (new component)
3. **Privacy**: Tracking presence could be sensitive
4. **Staleness**: State could be stale if aggregator doesn't run frequently
5. **Storage**: `presence_events` grows unbounded (needs cleanup job)

### Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| **Phone heartbeat stops** | Time decay handles gracefully (confidence drops, status → uncertain) |
| **False away (car left, person still home)** | Multiple signals prevent (face_seen or phone overrides car_left) |
| **Privacy concerns** | Optional feature; users control which signals to enable |
| **Stale state** | Background job every 60s updates presence_state; policies can force refresh |
| **Unbounded growth** | Cleanup job deletes presence_events older than 30 days |

---

## Alternatives Considered

### 1. Single Table (Events Only, No State)

**Approach**: Store only `presence_events`, calculate state on every query

**Pros**:
- Simpler schema
- No state synchronization issues

**Cons**:
- ❌ Slow policy evaluation (scan last hour of events on every visitor)
- ❌ No efficient "anyone_home()" check
- ❌ Repeated aggregation calculations

**Rejection Reason**: Policies need fast lookups; can't afford per-event aggregation

### 2. Redis/In-Memory State Only

**Approach**: Keep current state in Redis, no persistent `presence_state` table

**Pros**:
- Faster reads (~1ms vs ~10ms)
- Natural TTL for time decay

**Cons**:
- ❌ State lost on restart
- ❌ No historical "when did Beau leave?" queries
- ❌ Harder to audit/debug

**Rejection Reason**: Need persistent state for debugging and historical queries

### 3. Per-Source Tables

**Approach**: Separate tables for phone_heartbeats, vehicle_presence, etc.

**Pros**:
- Optimized schema per source
- No metadata JSON

**Cons**:
- ❌ Complex aggregation (join 5+ tables)
- ❌ Adding new source requires migration
- ❌ Harder to get unified timeline

**Rejection Reason**: Flexibility matters more than schema optimization

---

## Implementation Plan

### Phase 1: Schema & Core Service
- [ ] Create migration `019_add_presence_tracking.sql`
- [ ] Create `packages/presence/service.py` with:
  - `insert_presence_event()`
  - `calculate_presence_state(person_id)`
  - `get_presence_status(person_id)`
  - `update_all_presence_states()` (background job)
- [ ] Create `packages/presence/aggregator.py` with confidence math
- [ ] Unit tests for aggregation algorithm

### Phase 2: Integration Points
- [ ] Vehicle presence hook (when trusted plate detected/leaves)
- [ ] Face recognition hook (when trusted face seen)
- [ ] Manual override API endpoint (`POST /api/presence/override`)
- [ ] Background worker to update presence_state every 60s

### Phase 3: Policy Conditions
- [ ] `person_home` condition
- [ ] `anyone_home` condition
- [ ] `everyone_away` condition
- [ ] Integration tests for policy evaluation

### Phase 4: Phone Heartbeat (Future)
- [ ] Phone app integration (separate project)
- [ ] Webhook endpoint for phone heartbeats
- [ ] Authentication for phone requests

### Phase 5: MCP & LLM Integration
- [ ] MCP tool: `get_presence_status`
- [ ] MCP tool: `set_presence_override`
- [ ] Voice command examples: "I'm leaving for 2 hours"

### Phase 6: Cleanup & Monitoring
- [ ] Cleanup job: delete presence_events > 30 days
- [ ] Monitoring: alert if presence_state not updated in 5min
- [ ] Dashboard: presence timeline visualization

---

## Open Questions

1. **Phone Integration**: Build custom app or use existing home automation platform (Home Assistant)?
   - **Decision**: Start with webhook API, let users choose integration method

2. **Multiple Residences**: How to handle vacation homes?
   - **Decision**: Defer until needed; assume single location for MVP

3. **Guest Presence**: Track temporary visitors?
   - **Decision**: No, only trusted people with person_id

4. **Granular Location**: Track which room person is in?
   - **Decision**: No, binary home/away for MVP; room tracking is future enhancement

---

## References

- **Related ADRs**:
  - ADR-0008: Trusted Entity Allowlists (trusted people/vehicles)
  - ADR-0010: Cross-Camera Person Tracking (face recognition)
  
- **Implementation Files** (to be created):
  - `packages/presence/service.py`
  - `packages/presence/aggregator.py`
  - `infra/db/migrations/019_add_presence_tracking.sql`
  - `tests/test_presence_tracking.py`

- **Database Schema**:
  - `presence_events` - Evidence log
  - `presence_state` - Current aggregated state

- **Example Use Cases**:
  - "Don't notify me when I'm home"
  - "Alert immediately if stranger detected when nobody home"
  - "Turn on lights when first person arrives home"

---

## Notes

This represents a shift from **event-centric** to **state-centric** presence tracking. Instead of asking "was there a recent event?", we ask "what is the current state?".

**Key Insight**: Presence is not a single signal but an aggregation of multiple time-decayed signals. A person might be "probably home" (confidence 0.7) based on weak phone signal and recent car presence, even without definitive proof.

**Design Philosophy**: 
- **Evidence is immutable** (presence_events append-only)
- **State is computed** (presence_state derived from evidence)
- **Confidence degrades** (old evidence becomes less certain)
- **Manual overrides trump sensors** (user knows best)
