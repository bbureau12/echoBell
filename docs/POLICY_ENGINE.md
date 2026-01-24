# Policy Rule Engine User Guide

## Overview

The EchoBell policy rule engine provides a flexible, declarative system for defining complex decision logic using YAML configuration. It enables sophisticated scenarios like:

- **Trust-based filtering**: Different actions for known vs unknown people/vehicles
- **Temporal conditions**: Escalate alerts based on duration or time windows
- **Boolean logic**: Complex AND/OR/NOT conditions
- **Multi-action execution**: Trigger multiple actions (telegram, speak, webhook) for one policy
- **Alert spam prevention**: Check alert history to avoid notification fatigue
- **IoT integration**: Trigger external devices via webhooks

## Quick Start

### 1. Define Policies

Create a YAML file (e.g., `config/policy_rules.yaml`):

```yaml
policies:
  - id: unknown_vehicle_alert
    name: Unknown Vehicle Alert
    enabled: true
    priority: 10
    conditions:
      all:
        - evidence_exists:
            source: alpr
            feature: plate_hmac
        - trust_check:
            table: trusted_plates
            match_field: plate_hmac
            exists: false  # NOT trusted
    actions:
      - type: telegram
        message: "🚗 Unknown vehicle detected: {plate_number}"
        priority: normal
      - type: speak
        text: "Vehicle detected"

variables:
  plate_number:
    source: alpr
    feature: plate_hmac
    default: UNKNOWN
```

### 2. Evaluate Policies in Code

```python
from packages.policy.apply import evaluate_policies

# Evidence from edge device
evidence = [
    {'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate_xyz', 'conf': 0.95},
    {'source': 'movement', 'feature': 'significant_movement', 'value': '120px', 'conf': 1.0}
]

# Track context
context = {
    'camera_id': 'front_door',
    'track_key': 'vehicle_001',
    'track_duration_seconds': 45,
    'plate_hmac': 'plate_xyz'
}

# Evaluate and execute
results = await evaluate_policies(evidence, context, db_conn, policy_file="config/policy_rules.yaml")

# Results contain executed actions
for result in results:
    print(f"Policy: {result['policy_id']}")
    print(f"Action: {result['action_type']}")
    print(f"Success: {result['success']}")
```

## Condition Operators

### Evidence Checks

- **`evidence_exists`**: Check if evidence source/feature exists
  ```yaml
  evidence_exists:
    source: alpr
    feature: plate_hmac
    value: ABC123  # Optional: check specific value
  ```

- **`evidence_missing`**: Inverse of `evidence_exists`
  ```yaml
  evidence_missing:
    source: person
    feature: visitor_id
  ```

- **`evidence_value_contains`**: Check if evidence value contains substring
  ```yaml
  evidence_value_contains:
    source: alpr
    feature: plate_label
    contains: delivery
  ```

- **`evidence_value_gt/lt/eq`**: Numeric comparisons
  ```yaml
  evidence_value_gt:
    source: movement
    feature: distance_px
    threshold: 100  # Value > 100
  ```

### Trust Checks

- **`trust_check`**: Query trust registries
  ```yaml
  trust_check:
    table: trusted_person  # or trusted_plates
    match_field: visitor_id  # Field from context/evidence
    exists: false  # True = must be trusted, False = must NOT be trusted
  ```

### Temporal Conditions

- **`track_duration_gt/lt`**: Check track duration
  ```yaml
  track_duration_gt: 180  # Track > 3 minutes (180 seconds)
  ```

- **`time_between`**: Check current time of day
  ```yaml
  time_between:
    start: "22:00"
    end: "06:00"  # Nighttime (handles overnight ranges)
  ```

- **`day_of_week`**: Check current day
  ```yaml
  day_of_week: [sat, sun]  # Weekend only
  ```

### Alert History

- **`no_recent_alert`**: Spam prevention (no alert in time window)
  ```yaml
  no_recent_alert:
    track_key: current  # Use current track
    alert_type: telegram
    within_seconds: 300  # No alert in last 5 minutes
  ```

- **`alert_sent_within`**: Escalation (alert WAS sent in time window)
  ```yaml
  alert_sent_within:
    track_key: current
    alert_type: telegram
    min_seconds: 120  # Alert sent between 2-10 minutes ago
    max_seconds: 600
  ```

## Boolean Logic

### AND Logic (`all`)

All conditions must be true:

```yaml
conditions:
  all:
    - evidence_exists: {source: alpr, feature: plate_hmac}
    - trust_check: {table: trusted_plates, exists: false}
    - track_duration_gt: 60
```

### OR Logic (`any`)

At least one condition must be true:

```yaml
conditions:
  any:
    - evidence_exists: {source: movement, feature: loitering}
    - evidence_exists: {source: movement, feature: significant_movement}
    - time_between: {start: "22:00", end: "06:00"}
```

### NOT Logic (`not`)

Condition must be false:

```yaml
conditions:
  not:
    evidence_exists: {source: alpr, feature: plate_hmac}
```

### Nested Logic

Combine operators for complex logic:

```yaml
conditions:
  all:
    - evidence_exists: {source: movement, feature: loitering}
    - track_duration_gt: 180
    - any:
        - time_between: {start: "22:00", end: "06:00"}
        - trust_check: {table: trusted_person, exists: false}
```

## Actions

### Telegram

Send Telegram notification:

```yaml
- type: telegram
  message: "🚨 Alert: {person_name} detected at {camera_name}"
  priority: urgent  # normal | urgent | critical
```

### Speak (TTS)

Play text-to-speech announcement:

```yaml
- type: speak
  text: "Welcome home, {person_name}"
  voice: friendly  # Optional voice profile
```

### Webhook

Trigger external device/service:

```yaml
- type: webhook
  url: "{remote_lights_url}"
  method: POST  # GET | POST | PUT
  payload:
    action: turn_on
    duration: 60
    brightness: 100
  headers:
    Authorization: "Bearer {api_token}"
```

## Variables

Variables enable dynamic message formatting and URL construction:

### From Evidence

```yaml
variables:
  plate_number:
    source: alpr
    feature: plate_hmac
    default: UNKNOWN
```

### From Context

```yaml
variables:
  camera_name:
    from_context: camera_id
```

### Database Lookup

```yaml
variables:
  person_name:
    lookup:
      table: trusted_person
      match_field: visitor_id
      return_field: name
    default: Guest
```

### Calculated

```yaml
variables:
  duration_min:
    calculate: "track_duration_seconds / 60"
    format: "%.1f"
```

### Environment

```yaml
variables:
  api_token:
    env: WEBHOOK_API_TOKEN
    default: default_token
```

## Real-World Example: Loitering Escalation

```yaml
policies:
  # Initial alert after 3 minutes
  - id: initial_loitering
    name: Initial Loitering Alert
    enabled: true
    priority: 10
    conditions:
      all:
        - evidence_exists: {source: movement, feature: loitering}
        - track_duration_gt: 180  # 3 minutes
        - trust_check: {table: trusted_person, exists: false}
        - no_recent_alert: {track_key: current, alert_type: telegram, within_seconds: 600}
    actions:
      - type: telegram
        message: "Person loitering for {duration_min} minutes"
        priority: normal
      - type: speak
        text: "Please state your business"

  # Escalation if still loitering after initial alert
  - id: loitering_escalation
    name: Loitering Escalation with Lights
    enabled: true
    priority: 20  # Higher priority = evaluated first
    conditions:
      all:
        - evidence_exists: {source: movement, feature: loitering}
        - track_duration_gt: 180
        - trust_check: {table: trusted_person, exists: false}
        - alert_sent_within: {track_key: current, alert_type: telegram, min_seconds: 120, max_seconds: 600}
    actions:
      - type: telegram
        message: "🚨 URGENT: Person STILL loitering after {duration_min} minutes!"
        priority: urgent
      - type: speak
        text: "This is private property. Leave immediately."
      - type: webhook
        url: "{remote_lights_url}"
        payload:
          action: turn_on
          duration: 60

variables:
  duration_min:
    calculate: "track_duration_seconds / 60"
    format: "%.1f"
  remote_lights_url:
    env: REMOTE_LIGHTS_URL
    default: http://localhost:8080/lights
```

## Policy Priority

Policies are evaluated in priority order (highest first). Use priority to control which policy executes when multiple policies match:

- **Critical**: 30+ (security threats, immediate danger)
- **Urgent**: 20-29 (escalations, nighttime activity)
- **Normal**: 10-19 (routine alerts, known visitors)
- **Low**: 1-9 (informational, delivery notifications)

## Testing Policies

Run comprehensive tests:

```bash
pytest tests/test_policy_evaluator.py -v  # Test condition evaluation
pytest tests/test_policy_executor.py -v   # Test action execution
pytest tests/test_policy_integration.py -v  # Test complete scenarios
```

## Integration with Evidence API

The policy engine integrates with `POST /evidence`:

```python
# In apps/doorbell-agent/orchestrator.py or similar
from packages.policy.apply import evaluate_policies

@app.post("/evidence")
async def submit_evidence(request: EvidenceRequest):
    # Store evidence in database
    # ... existing code ...
    
    # Evaluate policies
    policy_results = await evaluate_policies(
        evidence=request.evidence,
        context={
            'camera_id': request.camera_id,
            'track_key': request.track_key,
            'track_duration_seconds': calculate_duration(request.track_key),
            # ... additional context fields
        },
        conn=db_conn
    )
    
    return {
        'success': True,
        'evidence_count': len(request.evidence),
        'actions_executed': len(policy_results),
        'actions': policy_results
    }
```

## Best Practices

1. **Start simple**: Begin with single-condition policies, then add complexity
2. **Use priority wisely**: Reserve high priorities for true emergencies
3. **Prevent spam**: Always use `no_recent_alert` for repeated notifications
4. **Test policies**: Write integration tests for complex scenarios
5. **Log actions**: Action executor logs all executions for debugging
6. **Variable defaults**: Always provide default values for variables
7. **Trust checks**: Use trust registries to reduce false positives
8. **Escalation patterns**: Use `alert_sent_within` for time-based escalation

## Troubleshooting

### Policy Not Triggering

1. Check policy enabled: `enabled: true`
2. Verify evidence exists: Use correct `source` and `feature` names
3. Check trust registries: Ensure trust checks match database state
4. Review alert history: May be blocked by spam prevention
5. Inspect logs: Action executor logs all evaluations

### Variable Not Substituting

1. Check variable definition in `variables` section
2. Verify evidence contains expected source/feature
3. Ensure context has required fields
4. Use default values for missing data

### Webhook Failing

1. Check URL reachability: Test endpoint independently
2. Verify payload format: Ensure JSON structure is correct
3. Check auth headers: Include required authentication
4. Review timeout: Default 5s timeout may be too short

## Future Enhancements

- **Delivery schedule integration**: `no_expected_delivery` condition
- **Calendar appointments**: `no_scheduled_appointment` condition
- **Cross-camera policies**: Trigger on multi-camera patterns
- **Time-series analysis**: Detect unusual patterns over days/weeks
- **Machine learning integration**: Anomaly detection conditions
- **Policy templates**: Pre-built policies for common scenarios
