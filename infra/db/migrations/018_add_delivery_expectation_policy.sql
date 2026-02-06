-- Migration 018: Add Delivery Expectation Policy
-- 
-- This migration adds the default policy for temporal context-based intent overrides.
-- When a user sets an expectation (e.g., "expecting pizza in 2 hours"), this policy
-- will override low-confidence classifications when unknown vehicles arrive during
-- the expected time window.
--
-- Example Flow:
-- 1. User: "Hey Echobell, expecting pizza in 2 hours"
-- 2. LLM creates scheduled_event with policy_hint="expecting_delivery"
-- 3. Unknown vehicle arrives (intent=authority, conf=0.42)
-- 4. Policy matches: active_event(expecting_delivery) AND not_trusted
-- 5. Action executes: reclassify to delivery_arriving with conf=0.85
-- 6. Result: "Your delivery has arrived!" announcement

-- Add index on policy_hint for performance
CREATE INDEX IF NOT EXISTS idx_scheduled_event_policy_hint 
ON scheduled_event(policy_hint);

-- Add index on active time windows for fast lookups
CREATE INDEX IF NOT EXISTS idx_scheduled_event_active 
ON scheduled_event(start_ts, end_ts);

-- Insert default delivery expectation policy
INSERT INTO policy_rules (
    name,
    priority,
    description,
    conditions_json,
    actions_json,
    enabled,
    created_ts
) VALUES (
    'expected_delivery_override',
    90,  -- High priority to override normal classification
    'Override low-confidence classifications when delivery is expected within scheduled time window',
    json_object(
        'all', json_array(
            -- Vehicle present at camera
            json_object(
                'type', 'evidence_exists',
                'evidence_key', 'vehicle_present',
                'value', true
            ),
            -- Active delivery expectation
            json_object(
                'type', 'active_event',
                'policy_hint', 'expecting_delivery'
            ),
            -- Not a trusted vehicle
            json_object(
                'type', 'trust_check',
                'operator', 'lt',
                'threshold', 0.6
            )
        )
    ),
    json_array(
        -- Reclassify to delivery
        json_object(
            'type', 'reclassify',
            'event_id', '{event_id}',
            'intent', 'delivery_arriving',
            'confidence', 0.85,
            'reason', 'Active delivery expectation: {event_name}'
        ),
        -- Announce arrival
        json_object(
            'type', 'speak',
            'message', 'Your delivery has arrived at {camera_name}!'
        ),
        -- Send notification
        json_object(
            'type', 'telegram',
            'message', '📦 Delivery arrived at {camera_name}\nExpected: {event_name}\nTime: {time_str}'
        )
    ),
    1,  -- enabled
    unixepoch()
);

-- Insert guest expectation policy
INSERT INTO policy_rules (
    name,
    priority,
    description,
    conditions_json,
    actions_json,
    enabled,
    created_ts
) VALUES (
    'expected_guest_boost',
    85,
    'Boost confidence for expected guests during scheduled time window',
    json_object(
        'all', json_array(
            -- Person detected
            json_object(
                'type', 'evidence_exists',
                'evidence_key', 'person_detected',
                'value', true
            ),
            -- Active guest expectation
            json_object(
                'type', 'active_event',
                'policy_hint', 'expecting_guest'
            ),
            -- Low confidence stranger or unknown
            json_object(
                'type', 'intent_match',
                'intents', json_array('stranger', 'unknown'),
                'confidence_max', 0.65
            )
        )
    ),
    json_array(
        -- Reclassify to friend
        json_object(
            'type', 'reclassify',
            'event_id', '{event_id}',
            'intent', 'friend_visit',
            'confidence', 0.80,
            'reason', 'Guest expected: {event_name}'
        ),
        -- Friendly greeting
        json_object(
            'type', 'speak',
            'message', 'Welcome! We\'ve been expecting you.'
        )
    ),
    1,  -- enabled
    unixepoch()
);

-- Insert service appointment policy
INSERT INTO policy_rules (
    name,
    priority,
    description,
    conditions_json,
    actions_json,
    enabled,
    created_ts
) VALUES (
    'service_appointment_window',
    85,
    'Handle service/technician visits during scheduled appointment windows',
    json_object(
        'all', json_array(
            -- Vehicle or person present
            json_object(
                'type', 'any',
                'conditions', json_array(
                    json_object('type', 'evidence_exists', 'evidence_key', 'vehicle_present', 'value', true),
                    json_object('type', 'evidence_exists', 'evidence_key', 'person_detected', 'value', true)
                )
            ),
            -- Active service appointment
            json_object(
                'type', 'active_event',
                'policy_hint', 'service_appointment'
            ),
            -- During business hours (8am-6pm)
            json_object(
                'type', 'time_between',
                'start_hour', 8,
                'end_hour', 18
            )
        )
    ),
    json_array(
        -- Reclassify to technician
        json_object(
            'type', 'reclassify',
            'event_id', '{event_id}',
            'intent', 'technician_visit',
            'confidence', 0.88,
            'reason', 'Scheduled service: {event_name}'
        ),
        -- Professional greeting
        json_object(
            'type', 'speak',
            'message', 'Service technician detected. Appointment: {event_name}.'
        ),
        -- Notify owner
        json_object(
            'type', 'telegram',
            'message', '🔧 Service Appointment\nProvider: {event_name}\nCamera: {camera_name}\nTime: {time_str}'
        )
    ),
    1,  -- enabled
    unixepoch()
);

-- Insert example scheduled events for demonstration/testing
-- (These can be removed after testing)
INSERT INTO scheduled_event (
    name,
    start_ts,
    end_ts,
    policy_hint,
    metadata_json
) VALUES (
    'Pizza delivery from Dominos',
    unixepoch() + 3600,  -- 1 hour from now
    unixepoch() + 10800,  -- 3 hours from now
    'expecting_delivery',
    json_object(
        'company', 'Dominos',
        'order_id', 'DEMO123',
        'notes', 'Example scheduled delivery expectation'
    )
);

INSERT INTO scheduled_event (
    name,
    start_ts,
    end_ts,
    policy_hint,
    metadata_json
) VALUES (
    'HVAC technician from CoolAir',
    unixepoch() + 7200,  -- 2 hours from now
    unixepoch() + 14400,  -- 4 hours from now
    'service_appointment',
    json_object(
        'company', 'CoolAir HVAC',
        'service_type', 'Annual maintenance',
        'notes', 'Example service appointment'
    )
);

-- Migration metadata
INSERT INTO schema_version (version, applied_ts, description)
VALUES (18, unixepoch(), 'Add delivery expectation policies and scheduled event indexes');

-- Rollback instructions (for reference):
-- DELETE FROM policy_rules WHERE name IN ('expected_delivery_override', 'expected_guest_boost', 'service_appointment_window');
-- DELETE FROM scheduled_event WHERE policy_hint IN ('expecting_delivery', 'service_appointment', 'expecting_guest');
-- DROP INDEX IF EXISTS idx_scheduled_event_policy_hint;
-- DROP INDEX IF EXISTS idx_scheduled_event_active;
-- DELETE FROM schema_version WHERE version = 18;
