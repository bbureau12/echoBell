# ADR-0016: Temporal Context-Based Intent Overrides

**Status**: Accepted  
**Date**: 2026-02-06  
**Deciders**: System Architect  
**Related**: ADR-0004 (Vehicle Role Inference), ADR-0009 (Scene Context), Policy Layer, Scheduled Events

---

## Context

EchoBell's visitor classification system uses ML models to infer intent (delivery, friend, stranger, etc.) with confidence scores. However, these classifications lack temporal context awareness. When users set expectations for upcoming arrivals (e.g., "expecting pizza in 2 hours"), the system should leverage this information to override low-confidence classifications.

### Problem

**Scenario**: User orders pizza and tells EchoBell: "Hey Echobell, expecting pizza delivery in 2 hours"

1. User voice command is processed by LLM
2. Delivery driver arrives in an unmarked vehicle
3. ML classifier detects vehicle, infers `intent=authority` with `confidence=0.42` (low confidence)
4. System treats visitor as potential authority figure instead of expected delivery
5. Wrong announcement: "Unidentified vehicle detected" instead of "Your delivery has arrived"

**Root Cause**: The classification system has no mechanism to incorporate temporal expectations set by users. The ML model operates on visual evidence alone, missing critical context.

### Requirements

1. Users must be able to set temporal expectations via voice commands
2. System must override low-confidence classifications when expectations match
3. Time windows must be enforced (expectations expire)
4. Solution must support multiple overlapping expectations (pizza + technician)
5. Full audit trail required for reclassifications
6. Must work across all cameras (centralized context)

---

## Decision

**We will implement temporal context-based intent overrides at the policy layer using the existing scheduled_event infrastructure and a new `reclassify` action handler.**

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User Voice Command                        │
│           "Hey Echobell, expecting pizza in 2 hours"         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     LLM (via MCP)                            │
│  Creates scheduled_event with policy_hint="expecting_delivery"│
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  scheduled_event Table                       │
│  name: "Pizza delivery from Dominos"                         │
│  start_ts: 1738856400                                        │
│  end_ts: 1738863600                                          │
│  policy_hint: "expecting_delivery"                           │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ (2 hours later)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Vehicle Arrives (Unknown Car)                   │
│  ML Classifier: intent=authority, confidence=0.42            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Policy Evaluator                           │
│  Conditions:                                                 │
│    ✓ vehicle_present = true                                 │
│    ✓ active_event(expecting_delivery) = true                │
│    ✓ trust_score < 0.6                                      │
│  Policy matches → Execute actions                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Reclassify Action Handler                       │
│  Calls: reclassify_visitor_intent()                          │
│  Changes: authority (0.42) → delivery_arriving (0.85)       │
│  Audit: reason="Active delivery expectation: Pizza delivery" │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Subsequent Actions                          │
│  speak: "Your delivery has arrived at front door!"          │
│  telegram: "📦 Delivery arrived - Expected: Pizza delivery"  │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Components

#### 1. Scheduled Event Storage (Already Exists)
```sql
CREATE TABLE scheduled_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL,
    policy_hint TEXT,  -- Key field: "expecting_delivery", "expecting_guest", etc.
    metadata_json TEXT
);
```

#### 2. Active Event Policy Condition (Already Exists)
```python
# In PolicyEvaluator._check_active_event()
cursor.execute("""
    SELECT name, policy_hint 
    FROM scheduled_event
    WHERE ? BETWEEN start_ts AND end_ts
      AND policy_hint = ?
""", (timestamp, condition['policy_hint']))
```

#### 3. Reclassify Action Handler (NEW)
```python
@register_action_handler("reclassify")
class ReclassifyActionHandler:
    async def execute(self, action, variables, context):
        event_id = action.get('event_id') or context.get('event_id')
        new_intent = action['intent']
        new_confidence = action.get('confidence', 0.85)
        reason = action.get('reason', 'Policy-driven reclassification')
        
        # Call existing service with audit trail
        result = services.reclassify_visitor_intent(
            event_id=event_id,
            new_intent=new_intent,
            new_confidence=new_confidence,
            reclassified_by='policy',
            reason=reason
        )
        return result
```

#### 4. Example Policy Definition
```yaml
name: expected_delivery_override
priority: 90  # High priority to override normal classification
conditions:
  all:
    - type: evidence_exists
      evidence_key: vehicle_present
      value: true
    - type: active_event
      policy_hint: expecting_delivery
    - type: trust_check
      operator: lt
      threshold: 0.6
actions:
  - type: reclassify
    event_id: "{event_id}"
    intent: delivery_arriving
    confidence: 0.85
    reason: "Active delivery expectation: {event_name}"
  - type: speak
    message: "Your delivery has arrived at {camera_name}!"
  - type: telegram
    message: "📦 Delivery arrived at {camera_name}"
```

### Why Policy Layer (Not Edge)

| Aspect | Edge Implementation | Policy Layer (Chosen) |
|--------|---------------------|----------------------|
| **Temporal Context** | ❌ No access to scheduled events | ✅ Full access to scheduled_event table |
| **Cross-Camera Awareness** | ❌ Per-camera only | ✅ System-wide expectations |
| **LLM Integration** | ❌ No LLM access | ✅ LLM creates scheduled events |
| **Flexibility** | ❌ Requires edge firmware updates | ✅ Policy updates without edge changes |
| **Audit Trail** | ⚠️ Limited logging | ✅ Full reclassification audit |
| **Complexity** | ⚠️ Edge code complexity | ✅ Centralized logic |

**Decision**: Policy layer provides temporal context, cross-camera awareness, and centralized intelligence without requiring edge device modifications.

---

## Consequences

### Positive

1. **Better UX**: "Your delivery has arrived!" instead of "Unidentified vehicle detected"
2. **Leverages Existing Infrastructure**: 90% of components already existed (scheduled_event, active_event condition, reclassify service)
3. **Extensible**: New policy_hint values easily added (expecting_guest, service_appointment, etc.)
4. **Full Audit Trail**: Every reclassification tracked with reason, timestamp, count
5. **No Edge Changes**: Works with existing edge devices
6. **Cross-Camera**: Expectations apply system-wide
7. **Time-Bounded**: Expectations automatically expire after end_ts

### Negative

1. **Latency**: Policy evaluation adds ~50-100ms vs edge-only classification
2. **Central Dependency**: Requires policy server availability (already required for notifications)
3. **Potential Over-Reclassification**: Poorly written policies could misclassify (mitigated by testing)
4. **Complexity**: Adds another layer to intent determination (acceptable tradeoff)

### Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| **False positives** (wrong reclassification) | High priority (90) but still below safety policies; trust_check prevents reclassifying trusted entities |
| **Time window too broad** | User can specify exact windows via voice; default 2-hour windows configurable |
| **Conflicting expectations** | Each policy_hint is independent; multiple can be active simultaneously |
| **Audit trail abuse** | reclassification_count limits; alerts on excessive reclassifications |

---

## Alternatives Considered

### 1. Edge-Based Temporal Context
**Approach**: Send scheduled events to edge devices, perform reclassification locally

**Pros**:
- Lower latency (~20ms vs ~100ms)
- Works during central server outage

**Cons**:
- ❌ No LLM access on edge (can't create scheduled events from voice)
- ❌ No cross-camera awareness (each camera isolated)
- ❌ Requires edge firmware updates for every policy change
- ❌ Limited storage on edge devices
- ❌ Complex synchronization logic

**Rejection Reason**: Edge devices lack LLM integration and cross-camera context

### 2. Post-Classification Override (Event Handler)
**Approach**: Let ML classify normally, override in event handler after storage

**Pros**:
- Simple implementation
- Original classification preserved

**Cons**:
- ❌ Too late - notifications already sent
- ❌ Can't prevent wrong TTS announcement
- ❌ Requires complex event replay logic

**Rejection Reason**: User experience suffers (wrong announcement already played)

### 3. ML Model Retraining with Temporal Features
**Approach**: Add temporal expectations as ML model inputs

**Pros**:
- "True" AI solution
- No separate reclassification step

**Cons**:
- ❌ Months of development
- ❌ Requires training data with temporal labels
- ❌ Model retraining for every new expectation type
- ❌ Less transparent than policy rules

**Rejection Reason**: Overengineered; policy layer provides same outcome with existing infrastructure

---

## Implementation Checklist

- [x] Create `ReclassifyActionHandler` with `@register_action_handler("reclassify")`
- [x] Add action handler registration to `executor.py`
- [x] Create example policy YAML (`examples/delivery_expectation_policy.yaml`)
- [x] Create workflow demo (`examples/delivery_expectation_workflow.py`)
- [x] Create integration tests (`tests/test_delivery_expectation.py`)
- [x] Create unit tests (`tests/test_reclassify_action_handler.py`)
- [x] Create migration with default policies (`018_add_delivery_expectation_policy.sql`)
- [x] Add indexes on `scheduled_event(policy_hint)` and `scheduled_event(start_ts, end_ts)`
- [ ] Update documentation (`docs/policies/POLICY_REFERENCE.md`)
- [ ] Update `docs/SCHEDULED_EVENTS.md` with reclassification examples
- [ ] Run end-to-end test: voice command → scheduled event → reclassification
- [ ] Monitor production metrics for reclassification rates

---

## References

- **Related ADRs**:
  - ADR-0004: Vehicle Role Inference (original classification system)
  - ADR-0009: Scene Context - Concurrent Intents (multi-intent handling)
  
- **Implementation Files**:
  - `packages/policy/actions/reclassify_handler.py` (215 lines)
  - `examples/delivery_expectation_policy.yaml` (140 lines)
  - `tests/test_delivery_expectation.py` (399 lines)
  - `tests/test_reclassify_action_handler.py` (10 unit tests)
  - `infra/db/migrations/018_add_delivery_expectation_policy.sql`

- **Database Schema**:
  - `scheduled_event` table (already exists)
  - `visitor_events.reclassified_by`, `reclassification_reason`, `reclassified_ts`, `reclassification_count` columns

- **Policy Hints Defined**:
  - `expecting_delivery` - Package/food delivery
  - `expecting_guest` - Friend/family visit
  - `service_appointment` - Technician/contractor visit

---

## Notes

This ADR represents a shift from purely ML-driven classification to **hybrid ML + temporal context** classification. The ML model provides the initial assessment, and the policy layer overrides when temporal expectations provide stronger signals.

**Key Insight**: Sometimes the user knows more than the ML model. When they tell us "expecting pizza in 2 hours," that's higher-confidence information than a 0.42 visual classification.

**Future Enhancements**:
- Learning from reclassifications to improve ML model
- Confidence boost (0.42 → 0.70) instead of full override for borderline cases
- User feedback: "Was this your delivery?" to validate reclassifications
- Analytics dashboard showing reclassification accuracy
