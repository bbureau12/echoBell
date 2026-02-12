-- Migration 021: Add Camera 1 Vehicle Detection Policy
-- 
-- Policy: Detect vehicles on camera 1 with alert cooldown and photo
-- 
-- Requirements:
--   1. Vehicle detected on camera_id = 1
--   2. No alerts sent in last 30 seconds
--   3. Send Telegram alert with photo
--
-- This policy prevents alert spam by checking alert_history for recent
-- alerts of the same track before sending a new notification.

INSERT OR IGNORE INTO policy_rules (
    id,
    name,
    description,
    enabled,
    priority,
    conditions_json,
    actions_json,
    created_ts,
    updated_ts,
    created_by,
    tags
)
VALUES (
    'camera1_vehicle_with_photo',
    'Camera 1 - Vehicle Detection with Photo',
    'Alert when vehicle detected on camera 1 (max once per 30 seconds per vehicle)',
    1,
    85,
    -- Conditions: camera=1, vehicle present, no recent alert
    json_object(
        'all', json_array(
            json_object('camera_id', json_object('equals', 1)),
            json_object('evidence_exists', json_object('source', 'vision', 'feature', 'vehicle_present')),
            json_object('no_recent_alert', json_object('track_type', 'vehicle', 'within_seconds', 30))
        )
    ),
    -- Actions: Send telegram with photo
    json_array(
        json_object(
            'type', 'telegram',
            'message', '🚗 Vehicle detected on Camera 1: {vehicle_color} {vehicle_type}',
            'priority', 'normal',
            'send_photo', json('true'),
            'photo_path', '{latest_frame_path}'
        )
    ),
    strftime('%s', 'now'),
    strftime('%s', 'now'),
    'migration_021',
    'vehicle camera1 photo alert'
);
