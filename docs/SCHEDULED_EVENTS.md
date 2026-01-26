# Scheduled Event API Examples

## Halloween Greeting Example

### Scenario
During Halloween (Oct 31, 10 PM - midnight), greet trick-or-treaters instead of sending security alerts.

### 1. Create the Halloween scheduled event

```powershell
# Halloween 2026: Oct 31, 10 PM - midnight
# Unix timestamps for Oct 31, 2026 22:00 - Oct 31, 2026 23:59
$halloween_start = 1793667600  # Oct 31, 2026 10:00 PM
$halloween_end = 1793674800    # Nov 1, 2026 12:00 AM

curl -X POST http://localhost:8000/scheduled_events `
  -H "Content-Type: application/json" `
  -d "{
    \"name\": \"Halloween\",
    \"description\": \"Halloween trick-or-treating hours\",
    \"start_ts\": $halloween_start,
    \"end_ts\": $halloween_end,
    \"policy_hint\": \"greet_visitors\"
  }"
```

**Response:**
```json
{
  "id": 1,
  "name": "Halloween",
  "description": "Halloween trick-or-treating hours",
  "start_ts": 1793667600,
  "end_ts": 1793674800,
  "policy_hint": "greet_visitors",
  "created_ts": 1737820800,
  "updated_ts": 1737820800
}
```

### 2. Create the Halloween greeting policy

```powershell
curl -X POST http://localhost:8000/policies/ `
  -H "Content-Type: application/json" `
  -d '{
    "id": "halloween_greeting",
    "name": "Halloween Greeting",
    "description": "During Halloween, greet trick-or-treaters",
    "enabled": true,
    "priority": 90,
    "conditions": {
      "all": [
        {"evidence_exists": {"source": "vision", "feature": "person_present"}},
        {"active_event": {"policy_hint": "greet_visitors"}}
      ]
    },
    "actions": [
      {
        "type": "speak",
        "text": "Happy Halloween! Enjoy your treats!"
      }
    ]
  }'
```

### 3. Create the normal security alert policy

```powershell
curl -X POST http://localhost:8000/policies/ `
  -H "Content-Type: application/json" `
  -d '{
    "id": "unknown_person_alert",
    "name": "Unknown Person Alert",
    "description": "Alert on unknown person (except during greeting events)",
    "enabled": true,
    "priority": 50,
    "conditions": {
      "all": [
        {"evidence_exists": {"source": "vision", "feature": "person_present"}},
        {"evidence_missing": {"source": "face_trust", "feature": "trusted_face"}},
        {"no_active_event": {"policy_hint": "greet_visitors"}}
      ]
    },
    "actions": [
      {
        "type": "telegram",
        "message": "⚠️ Unknown person at door",
        "priority": "normal"
      }
    ]
  }'
```

### How It Works

**During Halloween (10 PM - midnight):**
1. Visitor approaches door
2. Vision detects person
3. `halloween_greeting` policy (priority 90) matches:
   - `person_present` ✓
   - `active_event: greet_visitors` ✓
4. Speaker says: "Happy Halloween! Enjoy your treats!"
5. `unknown_person_alert` policy does NOT match:
   - `person_present` ✓
   - `trusted_face` missing ✓
   - `no_active_event: greet_visitors` ✗ (blocked!)
6. **Result:** Friendly greeting, no security alert

**Outside Halloween hours:**
1. Visitor approaches door
2. Vision detects person
3. `halloween_greeting` policy does NOT match:
   - `person_present` ✓
   - `active_event: greet_visitors` ✗ (no active event)
4. `unknown_person_alert` policy matches:
   - `person_present` ✓
   - `trusted_face` missing ✓
   - `no_active_event: greet_visitors` ✓
5. **Result:** Telegram alert sent

---

## Pizza Delivery Example

### Scenario
Expecting pizza delivery in the next hour. Don't alert on unknown vehicle.

### 1. Create the pizza delivery event

```powershell
# Now + 1 hour window
$now = [int][double]::Parse((Get-Date -UFormat %s))
$delivery_start = $now
$delivery_end = $now + 3600

curl -X POST http://localhost:8000/scheduled_events `
  -H "Content-Type: application/json" `
  -d "{
    \"name\": \"Pizza Delivery\",
    \"description\": \"Expecting pizza delivery\",
    \"start_ts\": $delivery_start,
    \"end_ts\": $delivery_end,
    \"policy_hint\": \"expecting_delivery\"
  }"
```

### 2. Create delivery-aware policy

```powershell
curl -X POST http://localhost:8000/policies/ `
  -H "Content-Type: application/json" `
  -d '{
    "id": "delivery_arrival",
    "name": "Delivery Arrival",
    "description": "Announce delivery arrival instead of alerting",
    "enabled": true,
    "priority": 85,
    "conditions": {
      "all": [
        {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
        {"active_event": {"policy_hint": "expecting_delivery"}}
      ]
    },
    "actions": [
      {
        "type": "speak",
        "text": "Your delivery has arrived!"
      }
    ]
  }'
```

### 3. Update normal vehicle alert policy

Add condition to NOT alert during expected deliveries:

```powershell
curl -X PATCH http://localhost:8000/policies/unknown_vehicle_alert `
  -H "Content-Type: application/json" `
  -d '{
    "conditions": {
      "all": [
        {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
        {"evidence_missing": {"source": "plate_trust", "feature": "trusted_plate"}},
        {"no_active_event": {"policy_hint": "expecting_delivery"}}
      ]
    }
  }'
```

---

## Manage Scheduled Events

### List all scheduled events
```powershell
curl http://localhost:8000/scheduled_events
```

### Get specific event
```powershell
curl http://localhost:8000/scheduled_events/1
```

### Update event time
```powershell
# Extend Halloween by 1 hour
$new_end = 1793678400

curl -X PATCH http://localhost:8000/scheduled_events/1 `
  -H "Content-Type: application/json" `
  -d "{\"end_ts\": $new_end}"
```

### Delete event
```powershell
curl -X DELETE http://localhost:8000/scheduled_events/1
```

---

## Condition Reference

### `active_event`
Matches when a scheduled event is currently active.

```json
{"active_event": {"policy_hint": "greet_visitors"}}
```

**Parameters:**
- `policy_hint` (optional): Match specific event type

### `no_active_event`
Matches when NO scheduled event with the given hint is active.

```json
{"no_active_event": {"policy_hint": "expecting_delivery"}}
```

**Use case:** Block normal alerts during special events.

---

## Best Practices

1. **Use priority wisely**
   - Event-specific policies: Higher priority (80-95)
   - Normal policies: Medium priority (40-60)
   - Fallback policies: Low priority (10-30)

2. **Policy hints are flexible**
   - `greet_visitors` - Halloween, open house, party
   - `expecting_delivery` - Package, food, service calls
   - `maintenance_mode` - System maintenance, testing
   - `vacation_mode` - Away from home
   - `guest_visit` - Expected guests

3. **Time-based events**
   - Use Unix timestamps for precise scheduling
   - Create events via API or directly in database
   - Events auto-activate based on timestamp range

4. **Cleanup**
   - Delete past events to keep database clean
   - Or keep for historical reference
