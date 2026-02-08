# Watch System Examples

The **Watch System** enables time-based policy evaluation with escalation chains. Watches are created by policies and evaluated asynchronously when they become due.

## Key Concepts

### What is a Watch?
A **watch** is a deferred policy evaluation scheduled for a future time. Think of it as setting a timer that will check conditions later.

### Core Components
- **Watch Type**: Free-form string identifying the watch purpose (e.g., "loitering_2min", "delivery_expected")
- **Watch Key**: Unique identifier preventing duplicate watches (auto-generated: `cam{id}:track_{key}:{type}`)
- **Due Time**: When the watch should be evaluated
- **Expiration**: When the watch should be discarded if not evaluated
- **State**: ARMED → TRIGGERED/DISARMED/EXPIRED

### Escalation Chains
Watches can create new watches, enabling progressive escalation:
```
Detection → 2min watch → alert + 5min watch → alert + 10min watch → critical alert
```

## Example Files

### 1. **loitering_watch_policy.yaml** - Person Loitering Detection

**Scenario**: Progressive escalation for unknown persons lingering on property

**Flow**:
1. Unknown person enters → create 2-minute watch
2. At 2 minutes (if still present) → alert + create 5-minute watch  
3. At 5 minutes (if still present) → escalated alert + create 10-minute watch
4. At 10 minutes (if still present) → critical alert

**Key Pattern**:
```yaml
# Step 1: Initial detection
- id: unknown_person_initial_watch
  conditions:
    all:
      - evidence_exists: {source: "scene", feature: "person_entered"}
      - trust_check: {level: "unknown"}
  actions:
    - type: create_watch
      watch_type: "loitering_2min"
      due_in_seconds: 120

# Step 2: 2-minute evaluation
- id: unknown_person_2min_alert
  conditions:
    all:
      - evidence_exists: {source: "watch", feature: "triggered", value: "loitering_2min"}
      - evidence_exists: {source: "scene", feature: "person_present"}
  actions:
    - type: telegram
      message: "Person loitering 2+ min"
    - type: create_watch
      watch_type: "loitering_5min"
      due_in_seconds: 180  # Additional 3 minutes
```

**Features**:
- ✅ Auto-disarms if person leaves (track becomes inactive)
- ✅ Progressive severity (medium → high → critical)
- ✅ Deduplication (same person won't create multiple watches)
- ✅ Camera-specific (only front/side doors)

### 2. **vehicle_dwell_watch_policy.yaml** - Vehicle Parking Monitoring

**Scenario**: Monitor parked vehicles with trust-based alert thresholds

**Trust-Based Timing**:
- **Unknown vehicle**: 5 min → 15 min escalation
- **Distrusted vehicle**: Immediate alert → 2 min escalation (faster response)

**Key Features**:
```yaml
# Unknown vehicle - longer threshold
- id: unknown_vehicle_initial
  conditions:
    - vehicle_stopped + trust_level:unknown
  actions:
    - create_watch:
        watch_type: "vehicle_dwell_5min"
        due_in_seconds: 300  # 5 minutes

# Distrusted vehicle - immediate alert + short watch
- id: distrusted_vehicle_alert
  conditions:
    - vehicle_entered + trust_level:distrust
  actions:
    - telegram: "⚠️ DISTRUSTED vehicle detected"
    - create_watch:
        watch_type: "distrusted_vehicle_dwell_2min"
        due_in_seconds: 120  # Only 2 minutes
```

**Features**:
- ✅ License plate tracking in alerts
- ✅ Different thresholds per trust level
- ✅ Progressive severity escalation
- ✅ Driveway/street camera filtering

### 3. **delivery_timeout_watch_policy.yaml** - Delivery Expectation Tracking

**Scenario**: User expects package delivery in a time window, get reminder if it doesn't arrive

**One-Shot Watch Pattern** (no scene track):
```yaml
# Watch fires if no delivery detected in time window
- id: delivery_timeout_reminder
  conditions:
    all:
      - evidence_exists: {source: "watch", value: "delivery_expected"}
      - not:
          evidence_exists: {source: "scene", classification: "delivery", within_minutes: 60}
  actions:
    - telegram: "Reminder: Expected delivery hasn't arrived"
    - create_watch:
        watch_type: "delivery_final_reminder"
        due_in_seconds: 3600  # Check again in 1 hour

# Cancel watches when delivery arrives
- id: delivery_person_arrived
  conditions:
    - person_entered + classification:delivery
  actions:
    - telegram: "Delivery person detected"
    # Note: Would need cancel_watches action in real implementation
```

**Features**:
- ✅ One-shot watches (independent of scene tracks)
- ✅ Time-window based checks
- ✅ Auto-cancellation when delivery detected
- ✅ Progressive reminders

## Watch System Architecture

```
┌─────────────┐
│   Policy    │ 1. Evaluates detection event
│  Evaluator  │    Condition: person_entered + unknown
└──────┬──────┘
       │ 2. Executes create_watch action
       ▼
┌─────────────┐
│CreateWatch  │ 3. Generates watch_key
│   Handler   │    cam1:track_abc:loitering_2min
└──────┬──────┘
       │ 4. Stores watch in database
       ▼
┌─────────────┐
│   Watch     │ 5. INSERT INTO watches
│   Service   │    (due_ts = now + 120 seconds)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Watch     │ 6. Background worker polls every N seconds
│   Worker    │    SELECT * WHERE due_ts <= now AND state = ARMED
└──────┬──────┘
       │ 7. Watch becomes due
       ▼
┌─────────────┐
│   Watch     │ 8. Re-evaluate policies with watch evidence
│  Evaluator  │    Evidence: {source:"watch", value:"loitering_2min"}
└──────┬──────┘
       │ 9. Policy matches and executes actions
       ▼
┌─────────────┐
│   Telegram  │ 10. Send alert
│   Action    │     Mark watch as TRIGGERED
└─────────────┘
```

## Testing Watch Policies

### Method 1: Manual Watch Creation (Admin API)

Create a watch directly to test evaluation:
```bash
curl -X POST http://localhost:8000/admin/watches \
  -H "Content-Type: application/json" \
  -d '{
    "watch_type": "test_watch",
    "camera_id": 1,
    "due_in_seconds": 10,
    "context": {"test": true}
  }'
```

### Method 2: View Due Watches
```bash
curl http://localhost:8000/admin/watches/due
```

### Method 3: Monitor Worker Health
```bash
curl http://localhost:8000/health

# Expected output:
{
  "status": "healthy",
  "watch_worker": "running",
  "last_poll": "2024-01-15T10:30:00"
}
```

### Method 4: Check Watch by Track ID
```bash
curl http://localhost:8000/admin/watches/track/123
```

### Method 5: Trigger Cleanup
```bash
curl -X POST http://localhost:8000/admin/watches/cleanup
```

## Best Practices

### ⏱️ Watch Timing
```yaml
# ✅ Good: Progressive escalation
actions:
  - create_watch:
      watch_type: "level1"
      due_in_seconds: 120      # 2 minutes
      expires_in_seconds: 600  # 10 minutes (5x buffer)

# ❌ Bad: Too short expiration
actions:
  - create_watch:
      due_in_seconds: 120
      expires_in_seconds: 130  # Only 10 seconds after due!
```

**Guideline**: Set `expires_in_seconds` to 2-5x `due_in_seconds` to handle:
- Worker poll delays
- Policy evaluation time
- System restarts

### 🔑 Watch Keys

```yaml
# ✅ Good: Let system auto-generate for track-based watches
actions:
  - create_watch:
      watch_type: "loitering_2min"
      # No watch_key needed - system generates: cam1:track_abc:loitering_2min

# ✅ Good: Explicit key for one-shot watches
actions:
  - create_watch:
      watch_type: "delivery_expected"
      watch_key: "delivery_2024-01-15_morning"  # Prevents duplicates

# ❌ Bad: Manual key for track-based watch
actions:
  - create_watch:
      watch_key: "custom_key_123"  # Won't deduplicate properly!
```

### 📊 Escalation Chains

```yaml
# ✅ Good: Each level creates next watch
- id: level_1
  conditions: [person_entered]
  actions:
    - create_watch: {type: "alert_2min", due: 120}

- id: level_2
  conditions: [watch_triggered: "alert_2min", person_present]
  actions:
    - telegram: "2 min alert"
    - create_watch: {type: "alert_5min", due: 180}  # Creates next level

- id: level_3
  conditions: [watch_triggered: "alert_5min", person_present]
  actions:
    - telegram: "5 min ESCALATED"
    - create_watch: {type: "alert_10min", due: 300}

# ❌ Bad: Creating all watches at once
- id: bad_pattern
  actions:
    - create_watch: {type: "alert_2min", due: 120}
    - create_watch: {type: "alert_5min", due: 300}   # Don't do this!
    - create_watch: {type: "alert_10min", due: 600}  # All fire regardless
```

### ✅ Duration Verification

```yaml
# ✅ Good: Verify actual duration
- id: watch_evaluation
  conditions:
    all:
      - evidence_exists: {source: "watch", value: "loitering_2min"}
      - track_duration_gt: 120  # Verify person actually stayed 2+ min
  actions:
    - telegram: "Confirmed loitering"

# ❌ Bad: No duration check
- id: bad_pattern
  conditions:
    - evidence_exists: {source: "watch", value: "loitering_2min"}
    # Missing duration check - could alert if person left and returned
  actions:
    - telegram: "Alert"  # Might be false positive!
```

### 🎯 One-Shot Watches

```yaml
# ✅ Good: Schedule-based watch (no scene_track_id)
actions:
  - create_watch:
      watch_type: "delivery_expected"
      watch_key: "delivery_morning_slot"  # Explicit key
      # No scene_track_id - not linked to detection
      due_in_seconds: 3600

# ✅ Good: Track-linked watch (auto-disarms)
actions:
  - create_watch:
      watch_type: "loitering_2min"
      scene_track_id: ${context.track_id}  # Linked to person
      # Auto-disarms when track becomes inactive
```

### 🧹 Cleanup & Lifecycle

```yaml
# Watch states:
ARMED      → Initial state, waiting for due_ts
TRIGGERED  → Evaluated and fired action
DISARMED   → Track became inactive before due_ts
EXPIRED    → Reached expires_ts without evaluation

# Automatic cleanup:
- Watches auto-disarm when scene_track becomes inactive
- Watches auto-expire when expires_ts reached
- Soft-deleted watches purged after 30 days
```

## Common Patterns

### Pattern 1: Loitering Detection
```yaml
person_entered → 2min watch → alert + 5min watch → escalate + 10min watch → critical
```

### Pattern 2: Vehicle Dwell Time
```yaml
vehicle_stopped → 5min watch → alert + 15min watch → escalate
```

### Pattern 3: Expected Delivery
```yaml
user_sets_expectation → 60min watch → reminder + 120min watch → final reminder
```

### Pattern 4: Trust-Based Escalation
```yaml
unknown: 5min → 15min
distrust: immediate → 2min → 5min (faster escalation)
```

### Pattern 5: Multi-Camera Coverage
```yaml
person_exits_cam1 → 30sec watch → check_cam2_entry → track_continuation
```

## Performance Considerations

### Worker Poll Interval
```python
# In central/policy-server/server.py
worker = WatchWorker(
    db_path=DB_PATH,
    poll_interval_seconds=5  # Check every 5 seconds
)
```

**Guidelines**:
- **5-10 seconds**: Good balance for most use cases
- **1-2 seconds**: High-frequency alerts (increases CPU usage)
- **30-60 seconds**: Low-priority background checks

### Database Impact
- Each poll: `SELECT * FROM watches WHERE due_ts <= ? AND state = 'ARMED'`
- Index on `(state, due_ts)` for performance
- Auto-cleanup prevents table bloat

### Watch Volume
- **Low** (<100 watches/hour): No impact
- **Medium** (100-1000/hour): Monitor poll interval
- **High** (>1000/hour): Consider batching, increase poll interval

## Troubleshooting

### Watch Not Firing

**Check 1**: Is watch in database?
```bash
sqlite3 data/echoBell.db "SELECT * FROM watches WHERE watch_type = 'loitering_2min'"
```

**Check 2**: Is worker running?
```bash
curl http://localhost:8000/health
# Should show: "watch_worker": "running"
```

**Check 3**: Is watch due?
```bash
SELECT id, watch_type, due_ts, datetime(due_ts, 'unixepoch') as due_time
FROM watches
WHERE state = 'ARMED'
```

**Check 4**: Check worker logs
```bash
# Look for: "Evaluating N due watches"
tail -f logs/policy_server.log | grep -i watch
```

### Watch Fires but No Action

**Check 1**: Does policy match watch evidence?
```yaml
# Policy must match watch evidence
conditions:
  - evidence_exists:
      source: "watch"
      feature: "triggered"
      value: "loitering_2min"  # Must match watch_type exactly
```

**Check 2**: Are other conditions met?
```yaml
# All conditions must be true
conditions:
  all:
    - evidence_exists: {source: "watch", value: "loitering_2min"}  # ✅
    - track_duration_gt: 120  # ⚠️ Is track actually 2+ min old?
    - person_present: true     # ⚠️ Is person still in scene?
```

### Duplicate Watches

**Solution**: Watch keys prevent duplicates
```python
# Auto-generated key format:
# cam{camera_id}:track_{track_key}:{watch_type}

# Example: cam1:track_person_abc:loitering_2min
# If same person triggers same watch type twice:
# → INSERT will succeed but watch_key will be identical
# → Service deduplicates before creation
```

## See Also

- **docs/TWO_LAYER_ARCHITECTURE.md** - Edge vs Policy layer design
- **docs/ARCHITECTURE.md** - Overall system architecture
- **packages/policy/watch_service.py** - Watch service implementation
- **packages/policy/watch_worker.py** - Background worker code
- **tests/test_watch_system.py** - Comprehensive test examples
- **infra/db/migrations/020_add_watches.sql** - Database schema
