# Camera-Specific Policy Example

## Overview
You can now create policies that only trigger on specific cameras using `camera_id_eq` or `camera_id_in` conditions.

## Use Cases

### 1. Halloween Greeting on Main Door Only
On Halloween night, greet trick-or-treaters at the main door, but keep normal alerts for other cameras.

```yaml
policies:
  - id: halloween_main_door
    name: Halloween Greeting - Main Door
    description: Greet visitors at main door on Halloween
    enabled: true
    priority: 90  # Higher priority than normal alerts
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_eq: main_door  # Only main door
        - active_event:
            policy_hint: halloween_event
    actions:
      - type: speak
        text: "Happy Halloween! Enjoy your treats!"
  
  - id: garage_normal_alert
    name: Garage Normal Alert
    description: Normal security alert for garage
    enabled: true
    priority: 50
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_eq: garage  # Only garage
    actions:
      - type: telegram
        message: "⚠️ Person detected in garage"
        priority: urgent
```

### 2. Front Cameras Group Alert
Alert only for front-facing cameras (multiple cameras):

```yaml
policies:
  - id: front_entrance_alert
    name: Front Entrance Alert
    description: Alert for any front entrance camera
    enabled: true
    priority: 60
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
    actions:
      - type: speak
        text: "Welcome! How can I help you?"
      - type: telegram
        message: "Person at front entrance (camera: {camera_id})"
        priority: normal
```

### 3. Different Responses Per Camera
Different greetings for different cameras:

```yaml
policies:
  # Main entrance - formal greeting
  - id: main_entrance_greeting
    name: Main Entrance Greeting
    enabled: true
    priority: 80
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_eq: main_door
    actions:
      - type: speak
        text: "Welcome to the main entrance. Please state your business."
  
  # Back door - security alert
  - id: back_door_alert
    name: Back Door Security Alert
    enabled: true
    priority: 80
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_eq: back_door
    actions:
      - type: speak
        text: "This is private property. Please use the main entrance."
      - type: telegram
        message: "🚨 ALERT: Person at back door (unauthorized entry point)"
        priority: urgent
  
  # Garage - motion sensor backup
  - id: garage_motion
    name: Garage Motion Alert
    enabled: true
    priority: 70
    conditions:
      all:
        - evidence_exists:
            source: vision
            feature: person_present
        - camera_id_eq: garage
        - time_between:
            start: "22:00"  # 10 PM
            end: "06:00"    # 6 AM
    actions:
      - type: telegram
        message: "🌙 Night motion in garage: {track_type} detected"
        priority: urgent
```

### 4. Combined with Scheduled Events
Halloween greeting only on main door, normal alerts elsewhere:

```yaml
policies:
  # High priority - Halloween greeting at main door
  - id: halloween_main_door
    name: Halloween Main Door Greeting
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
    actions:
      - type: speak
        text: "Happy Halloween! What a great costume!"
  
  # Medium priority - Normal alert for side door (even on Halloween)
  - id: side_door_alert
    name: Side Door Alert
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
        message: "Person at side door (unusual entry point)"
        priority: normal
```

## Available Conditions

### `camera_id_eq`
Matches exactly one camera ID:
```yaml
camera_id_eq: main_door
```

### `camera_id_in`
Matches any camera in a list:
```yaml
camera_id_in:
  - front_door
  - main_door
  - driveway
```

## Camera ID Values

The `camera_id` comes from the context passed to the policy engine. It's typically set by:
- Edge agents when sending evidence
- The policy server when receiving `/evidence` requests
- Scene tracking when linking detections to cameras

Make sure your camera IDs are consistent across:
- Camera configuration (`camera` table)
- Evidence submission
- Policy definitions

## Testing

See `tests/test_camera_specific_policy.py` for examples of:
- Single camera matching with `camera_id_eq`
- Multiple camera matching with `camera_id_in`
- No match scenarios
- Combined with other conditions

## Example Database Policy

To store in the `policy_rules` table:

```python
import json
import time

policy = {
    "id": "halloween_main_door",
    "name": "Halloween Main Door Greeting",
    "description": "Greet trick-or-treaters at main door",
    "enabled": 1,
    "priority": 90,
    "conditions_json": json.dumps({
        "all": [
            {"evidence_exists": {"source": "vision", "feature": "person_present"}},
            {"camera_id_eq": "main_door"}
        ]
    }),
    "actions_json": json.dumps([
        {
            "type": "speak",
            "text": "Happy Halloween! Enjoy your treats!"
        }
    ]),
    "variables_json": "{}",
    "created_ts": int(time.time()),
    "updated_ts": int(time.time()),
    "created_by": "admin",
    "tags": "halloween,main_door,greeting",
    "version": 1
}
```
