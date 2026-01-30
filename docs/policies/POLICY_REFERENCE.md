# Policy Engine Quick Reference

Comprehensive reference for EchoBell policy conditions, actions, and variables.

---

## Policy Structure

```yaml
policies:
  - id: policy_unique_id          # Required: Unique identifier
    name: "Human Readable Name"   # Required: Display name
    description: "What it does"   # Optional: Description
    enabled: true                 # Optional: Default true
    priority: 80                  # Optional: 0-100, default 50
    
    conditions:                   # Required: Condition tree
      all:  # AND logic
        - condition_1
        - condition_2
    
    actions:                      # Required: Actions to execute
      - type: telegram
        message: "Alert text"
    
    variables:                    # Optional: Custom variables
      my_var: "value"
```

---

## Condition Operators

### Evidence Matching

#### `evidence_exists`
Check if evidence with source/feature exists.

```yaml
evidence_exists:
  source: vision           # Required
  feature: vehicle_present # Required
```

**Example**:
```yaml
- evidence_exists:
    source: vision
    feature: vehicle_present
```

---

#### `evidence_missing`
Inverse of `evidence_exists` - condition matches if evidence NOT found.

```yaml
evidence_missing:
  source: plate_trust
  feature: trusted_plate
```

**Use Case**: Alert for unknown vehicles

---

#### `evidence_value_eq`
Evidence value equals expected value (exact match).

```yaml
evidence_value_eq:
  source: classify        # Required
  feature: intent         # Required
  expected: delivery      # Required
```

---

#### `evidence_value_gt` / `evidence_value_lt`
Numeric comparison (greater than / less than).

```yaml
evidence_value_gt:
  source: classify
  feature: intent_confidence
  threshold: 0.75          # Required: Numeric threshold
```

**Use Case**: High-confidence classification routing

---

#### `evidence_value_contains`
String substring match.

```yaml
evidence_value_contains:
  source: ocr
  feature: text
  substring: "POLICE"      # Required: Substring to find
```

---

### Trust Checks

#### `trust_check`
Check if person or vehicle is in trusted registry.

```yaml
trust_check:
  check_type: trusted_person    # or "trusted_plates"
```

**Evidence Required**:
- For `trusted_person`: Evidence with `source: face, feature: visitor_id`
- For `trusted_plates`: Evidence with `source: plate_trust, feature: trusted_plate`

**Example**:
```yaml
# Trusted person detected
conditions:
  all:
    - evidence_exists:
        source: face
        feature: visitor_id
    - trust_check:
        check_type: trusted_person
```

---

### Temporal Conditions

#### `track_duration_gt` / `track_duration_lt`
How long object has been present (in seconds).

```yaml
track_duration_gt:
  track_type: person      # Required: 'person' or 'vehicle'
  duration_s: 300         # Required: Duration in seconds
```

**Context Required**: `track_duration_seconds` in context dict

**Use Case**: Loitering detection

---

#### `camera_id_eq`
Match exactly one specific camera.

```yaml
camera_id_eq: main_door
```

**Context Required**: `camera_id` in context dict

**Use Case**: Camera-specific greetings or alerts

**Example**:
```yaml
conditions:
  all:
    - evidence_exists:
        source: vision
        feature: person_present
    - camera_id_eq: main_door
actions:
  - type: speak
    text: "Welcome to the main entrance!"
```

---

#### `camera_id_in`
Match any camera from a list.

```yaml
camera_id_in:
  - front_door
  - main_door
  - driveway
```

**Context Required**: `camera_id` in context dict

**Use Case**: Group multiple cameras for same behavior

**Example**:
```yaml
conditions:
  all:
    - evidence_exists:
        source: vision
        feature: person_present
    - camera_id_in:
        - front_door
        - main_door
        - porch
actions:
  - type: speak
    text: "Welcome to the front entrance!"
```

---

#### `time_between`
Current time within specified window.

```yaml
time_between:
  start: "22:00"          # Required: HH:MM format
  end: "06:00"            # Required: HH:MM format
```

**Handles overnight**: `22:00` to `06:00` crosses midnight correctly

---

#### `day_of_week`
Specific days of the week.

```yaml
day_of_week:
  days:                   # Required: Array of day names
    - friday
    - saturday
    - sunday
```

**Valid days**: monday, tuesday, wednesday, thursday, friday, saturday, sunday

---

### Alert Management

#### `no_recent_alert`
No alert sent recently (spam prevention).

```yaml
no_recent_alert:
  track_type: person      # Required: 'person' or 'vehicle'
  within_seconds: 600     # Required: Time window in seconds
```

**Context Required**: `track_key` in context dict

**Use Case**: Prevent alert spam for same person/vehicle

---

#### `alert_sent_within`
Alert was sent within timeframe (for escalation).

```yaml
alert_sent_within:
  track_type: person
  within_seconds: 300     # Required: Time window in seconds
```

**Use Case**: Escalation patterns (initial alert → followup alert)

---

## Boolean Logic

### `all` (AND)
All conditions must match.

```yaml
conditions:
  all:
    - condition_1
    - condition_2
    - condition_3
```

---

### `any` (OR)
At least one condition must match.

```yaml
conditions:
  any:
    - condition_1
    - condition_2
```

---

### `not` (NOT)
Condition must NOT match.

```yaml
conditions:
  not:
    trust_check:
      check_type: trusted_person
```

---

### Nested Logic

```yaml
conditions:
  all:
    - time_between: {start: "22:00", end: "06:00"}
    - any:
        - evidence_exists: {source: vision, feature: vehicle_present}
        - evidence_exists: {source: vision, feature: person_present}
    - not:
        trust_check:
          check_type: trusted_person
```

---

## Actions

### `telegram`
Send message via Telegram Bot API.

```yaml
- type: telegram
  message: "Alert text with {variables}"  # Required
  priority: urgent                        # Optional: low, normal, urgent
```

**Environment Variables**:
- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `TELEGRAM_CHAT_ID` - Your chat ID

**Features**:
- Variable substitution in message
- Records to `alert_history` table
- Prevents spam via alert tracking

---

### `speak`
Text-to-speech announcement.

```yaml
- type: speak
  text: "Hello! One moment please."      # Required
  voice: default                         # Optional: Voice model
```

**Integration**: Calls `packages/tts/piper.py`

---

### `webhook`
HTTP request to external service.

```yaml
- type: webhook
  url: "http://home-assistant:8123/api/trigger"  # Required
  method: POST                                   # Optional: POST, GET, PUT
  payload:                                       # Optional: JSON payload
    entity_id: "alert.driveway"
    value: "{confidence}"
```

**Use Cases**:
- Trigger Home Assistant automations
- Turn on smart lights
- Send to custom notification service
- Log to external database

---

## Variables

Variables enable dynamic message content and payload substitution.

### Evidence Variables

Automatically available from evidence:

- `{vehicle_color}` - From `vision.color` evidence
- `{vehicle_type}` - From `vision.vehicle_type` evidence
- `{plate_text}` - From `ocr.plate_text` evidence
- `{confidence}` - From classification confidence
- `{intent}` - From classification intent
- `{trusted_label}` - From `plate_trust.trusted_plate` evidence

### Context Variables

From runtime context:

- `{camera_id}` - Camera that detected event
- `{timestamp}` - Unix timestamp
- `{track_key}` - Scene track identifier (plate_hmac or visitor_id)

### Calculated Variables

From track duration:

- `{duration_seconds}` - How long object has been present
- `{duration_minutes}` - Duration in minutes (rounded)

### Database Queries

Execute SQL queries:

```yaml
variables:
  active_count: "{db.SELECT COUNT(*) FROM scene_tracks WHERE active=1}"
  vehicle_visits: "{db.SELECT visit_count FROM plate_visitors WHERE plate_hmac=?}"
```

**Parameterized queries**: Use `?` placeholders, bind from context

### Environment Variables

Access environment variables:

```yaml
variables:
  home_mode: "{env.HOME_MODE}"
  location: "{env.LOCATION}"
```

---

## Complete Examples

### Example 1: Nighttime Unknown Vehicle

```yaml
- id: nighttime_unknown_vehicle
  name: "Nighttime Unknown Vehicle Alert"
  enabled: true
  priority: 85
  
  conditions:
    all:
      - time_between:
          start: "22:00"
          end: "06:00"
      - evidence_exists:
          source: vision
          feature: vehicle_present
      - evidence_missing:
          source: plate_trust
          feature: trusted_plate
      - no_recent_alert:
          track_type: vehicle
          within_seconds: 900
  
  actions:
    - type: telegram
      message: "⚠️ Unknown {vehicle_color} {vehicle_type} at night"
      priority: urgent
    - type: webhook
      url: "http://192.168.1.100:8123/api/services/light/turn_on"
      method: POST
      payload:
        entity_id: "light.driveway_flood"
        brightness: 255
```

---

### Example 2: Loitering Escalation

```yaml
# Initial alert
- id: loitering_initial
  name: "Loitering - Initial Alert"
  enabled: true
  priority: 70
  
  conditions:
    all:
      - track_duration_gt:
          track_type: person
          duration_s: 300  # 5 minutes
      - not:
          trust_check:
            check_type: trusted_person
      - no_recent_alert:
          track_type: person
          within_seconds: 1200
  
  actions:
    - type: telegram
      message: "Person loitering for {duration_minutes} minutes"
      priority: normal

# Escalation alert
- id: loitering_escalation
  name: "Loitering - Escalation"
  enabled: true
  priority: 90
  
  conditions:
    all:
      - track_duration_gt:
          track_type: person
          duration_s: 600  # 10 minutes
      - alert_sent_within:
          track_type: person
          within_seconds: 600
  
  actions:
    - type: telegram
      message: "⚠️ URGENT: Person still present after {duration_minutes} min"
      priority: urgent
    - type: speak
      text: "You are being recorded. Please leave the premises."
```

---

### Example 3: High-Confidence Authority

```yaml
- id: authority_detected
  name: "Authority Detection - High Confidence"
  enabled: true
  priority: 100
  
  conditions:
    all:
      - evidence_value_eq:
          source: classify
          feature: intent
          expected: authority
      - evidence_value_gt:
          source: classify
          feature: intent_confidence
          threshold: 0.80
  
  actions:
    - type: telegram
      message: "🚔 Authority detected ({confidence}% confidence)"
      priority: urgent
    - type: webhook
      url: "http://localhost:3000/api/record/start"
      method: POST
      payload:
        reason: "authority_detected"
        confidence: "{confidence}"
```

---

### Example 4: Weekend Party Mode

```yaml
- id: weekend_party_mode
  name: "Weekend Party Mode"
  enabled: true
  priority: 95
  
  conditions:
    all:
      - day_of_week:
          days:
            - friday
            - saturday
      - time_between:
          start: "20:00"
          end: "02:00"
  
  actions:
    - type: telegram
      message: "🎉 Guest arriving (party mode active)"
      priority: low
```

---

## Priority Guidelines

**90-100: Critical/Urgent**
- Nighttime alerts
- Security concerns
- Authority detection

**70-89: High Priority**
- Unknown vehicles
- Loitering
- Unusual behavior

**50-69: Normal Priority**
- Known visitors
- Deliveries
- Standard notifications

**10-49: Low Priority**
- Informational
- Logging only
- Party mode notifications

---

## Testing Policies

### Via API

```bash
# Create test policy
curl -X POST http://localhost:8000/policies/ \
  -H "Content-Type: application/json" \
  -d @test_policy.json

# Check execution history
curl http://localhost:8000/policies/my_test_policy/history
```

### Via Python

```python
from packages.policy.policy_service import PolicyRulesService

service = PolicyRulesService("data/echoBell.db")

# Create test policy
policy = service.create_policy(
    policy_id="test_policy",
    name="Test Policy",
    enabled=False,  # Disabled for testing
    conditions={...},
    actions=[...]
)

# Enable when ready
service.toggle_policy("test_policy", enabled=True)
```

---

## Troubleshooting

### Policy Not Matching

1. **Check enabled flag**: `curl http://localhost:8000/policies/my_policy`
2. **Verify evidence exists**: Print evidence in classify_and_log
3. **Test conditions individually**: Simplify to single condition
4. **Check priority**: Higher priority policies evaluated first

### Actions Not Executing

1. **Check execution history**: `GET /policies/{id}/history`
2. **Verify environment variables**: Telegram bot token, etc.
3. **Check alert_history table**: May be spam-filtered
4. **Enable debug logging**: Set log level to DEBUG

### Variable Substitution Not Working

1. **Verify variable exists**: Check evidence or context
2. **Check spelling**: Variables are case-sensitive
3. **Use exact syntax**: `{variable_name}` with curly braces
4. **Database queries**: Ensure SQL is valid

---

## Complete Examples

### Camera-Specific Halloween Greeting

Different behavior per camera on Halloween night:

```yaml
policies:
  # High priority - Main door Halloween greeting
  - id: halloween_main_door
    name: Halloween Main Door Greeting
    description: Greet trick-or-treaters at main entrance
    enabled: true
    priority: 90
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_eq: main_door
        - active_event:
            policy_hint: halloween_event
        - time_between:
            start: "17:00"
            end: "21:00"
    actions:
      - type: speak
        text: "Happy Halloween! What a great costume!"
  
  # Medium priority - Normal alert for side door (even on Halloween)
  - id: side_door_alert
    name: Side Door Alert
    description: Alert for unexpected entry point
    enabled: true
    priority: 60
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_eq: side_door
    actions:
      - type: telegram
        message: "⚠️ Person at side door (unusual entry point)"
        priority: urgent
```

### Multi-Camera Front Entrance Group

Same greeting for all front-facing cameras:

```yaml
policies:
  - id: front_entrance_greeting
    name: Front Entrance Greeting
    description: Welcome visitors at any front camera
    enabled: true
    priority: 70
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_in:
            - front_door
            - main_door
            - driveway
            - porch
        - time_between:
            start: "08:00"
            end: "20:00"
    actions:
      - type: speak
        text: "Welcome! How can I help you today?"
```

---

## See Also

- [POLICY_API.md](POLICY_API.md) - REST API reference
- [POLICY_INTEGRATION_SUMMARY.md](POLICY_INTEGRATION_SUMMARY.md) - Setup guide
- [CAMERA_SPECIFIC_POLICIES.md](CAMERA_SPECIFIC_POLICIES.md) - Camera-specific examples
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
