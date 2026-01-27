"""
QUICK GUIDE: Send Telegram Photos for Unknown Vehicles
========================================================

Your system ALREADY has all the pieces! Here's how to connect them:

STEP 1: Update Your Policy (config/policies.yaml)
-------------------------------------------------

Add this policy:

```yaml
policies:
  - name: unknown_vehicle_photo_alert
    description: Send photo when unknown vehicle detected
    priority: 80
    status: active
    
    conditions:
      all:
        - field: label
          operator: equals
          value: car
        - field: is_known_vehicle
          operator: equals  
          value: false
    
    actions:
      - type: telegram
        message: "🚗 Unknown vehicle detected!\n📸 See photo attached"
        priority: high
        send_photo: true  # <-- This is the key!
```


STEP 2: Make Sure Snapshot Path is Available
---------------------------------------------

Your camera-agent already does this! In apps/camera-agent/loop.py:

```python
bus.put({
    "source": "driveway",
    "type": "approach", 
    "kind": kind,
    "snapshot": vision.snapshot_path,  # <-- Already here!
})
```

The snapshot_path is already being passed. You just need to make sure
it gets into the context when evaluating policies.


STEP 3: Update Policy Executor to Use Snapshot Path
----------------------------------------------------

In packages/policy/action_handlers.py, the TelegramActionHandler needs to 
check the context for snapshot_path. Look at line 236-238:

```python
send_photo = action.get('send_photo', False)
photo_path = action.get('photo_path')

if send_photo and photo_path:
    success = notifier.send_photo(photo_path, caption=message)
```

The handler is ready! You just need to pass the snapshot_path from your
vision result to the action context.


IMPLEMENTATION EXAMPLE
======================

Here's what happens end-to-end:

1. Camera detects unknown vehicle
2. Vision service saves frame to data/img_log/xyz.jpg
3. Policy evaluator runs and matches the unknown_vehicle_photo_alert policy
4. Action executor gets called with:
   - action = {"type": "telegram", "send_photo": true, "message": "..."}
   - context = {"snapshot_path": "data/img_log/xyz.jpg", ...}
5. TelegramActionHandler reads the image and sends it


CODE CHANGES NEEDED
===================

Option A: Modify apps/policy-server/server.py receive_observations()
---------------------------------------------------------------------

Around line 540 where you execute actions:

```python
# When executing policy actions, pass snapshot_path in context
for obs in request.observations:
    context = {
        'camera_id': request.camera_id,
        'timestamp': request.timestamp,
        'snapshot_path': obs.get('snapshot_path'),  # Add this!
        # ... other context fields
    }
    
    # Execute actions with context containing snapshot_path
    for action in matched_policy.actions:
        result = await execute_action(action, variables, context)
```


Option B: Modify Observation Model
-----------------------------------

In apps/policy-server/server.py add snapshot_path to Observation:

```python
class Observation(BaseModel):
    """Single observation from camera."""
    label: str
    confidence: float  
    bbox: list[float]
    snapshot_path: Optional[str] = None  # ADD THIS LINE
```

Then your camera agent can send it:

```python
observations = [{
    "label": "car",
    "confidence": 0.95,
    "bbox": [x1, y1, x2, y2],
    "snapshot_path": vision.snapshot_path  # From snapshot_and_detect()
}]
```


Option C: Add snapshot_path at Vision Result Level  
--------------------------------------------------

The vision.snapshot_path is already available in your VisionResult.
Just make sure it flows through to the policy evaluator.

In apps/policy-server/server.py around line 250:

```python
vr = VisionResult(
    objects=[...],
    snapshot_path=obs.get('snapshot_path', ''),  # Preserve from edge
    ...
)
```


TESTING
=======

1. Set environment variables:
   ```
   export TELEGRAM_BOT_TOKEN="your_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   ```

2. Run the example:
   ```
   python examples/telegram_photo_alert.py
   ```

3. If that works, test with real camera:
   - Start camera agent
   - Trigger unknown vehicle detection
   - Check Telegram for photo


TROUBLESHOOTING
===============

Problem: No photo sent, only text message
Solution: Check that send_photo: true in policy

Problem: Telegram error "photo not found"
Solution: Verify snapshot_path is correct absolute path

Problem: Photo is wrong
Solution: Make sure snapshot_path from vision.snapshot_path is being passed

Problem: No alert at all
Solution: Check policy conditions match (is_known_vehicle = false)


WHAT YOU ALREADY HAVE
======================

✅ SnapshotService - saves images (packages/data/snapshot_service.py)
✅ TelegramNotifier.send_photo() - sends images (packages/integrations/telegram.py)
✅ snapshot_and_detect() - creates snapshot_path (packages/perception/vision.py)
✅ TelegramActionHandler - handles send_photo flag (packages/policy/action_handlers.py)

All the pieces exist! You just need to:
1. Add send_photo: true to your policy
2. Pass snapshot_path through the observation → context chain


RECOMMENDED APPROACH
====================

Start Simple:
1. Create the policy with send_photo: true
2. Add snapshot_path to Observation model (Option B above)
3. Update camera agent to include snapshot_path in observations
4. Test!

The image is already being saved by snapshot_and_detect().
The Telegram handler already supports send_photo.
You just need to connect them!

