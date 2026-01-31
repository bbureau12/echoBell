"""
Example policies using quiet hours conditions
"""

# Policy: Suppress TTS announcements during quiet hours
suppress_tts_quiet_hours = {
    "id": "suppress_tts_quiet_hours",
    "name": "Suppress TTS During Quiet Hours",
    "priority": 10,
    "enabled": True,
    "conditions": {
        "all": [
            {"evidence_exists": {"source": "vision", "feature": "person_detected"}},
            {"is_quiet_hours": True}  # Check if any quiet hours are active
        ]
    },
    "actions": [
        {"type": "log", "message": "Person detected during quiet hours - suppressing TTS announcement"}
        # No speak action - intentionally silent
    ]
}

# Policy: Send silent notification during quiet hours
silent_notification_quiet_hours = {
    "id": "silent_notification_quiet_hours",
    "name": "Silent Notifications During Sleep",
    "priority": 15,
    "enabled": True,
    "conditions": {
        "all": [
            {"evidence_exists": {"source": "vision", "feature": "unknown_person"}},
            {"is_quiet_hours": {"name": "Sleep"}}  # Only during "Sleep" quiet hours
        ]
    },
    "actions": [
        {
            "type": "telegram",
            "message": "🔕 Unknown person detected (quiet mode)",
            "disable_notification": True  # Silent notification
        }
    ]
}

# Policy: Normal alerts when NOT in quiet hours
normal_alerts_active_hours = {
    "id": "normal_alerts_active_hours",
    "name": "Normal Alerts During Active Hours",
    "priority": 5,
    "enabled": True,
    "conditions": {
        "all": [
            {"evidence_exists": {"source": "vision", "feature": "unknown_person"}},
            {"not_quiet_hours": True}  # Only when NOT in quiet hours
        ]
    },
    "actions": [
        {
            "type": "telegram",
            "message": "⚠️ Unknown person detected"
        },
        {
            "type": "speak",
            "message": "Unknown visitor detected at the front door"
        }
    ]
}

# Policy: Weekend quiet hours have different behavior
weekend_quiet_hours = {
    "id": "weekend_quiet_hours",
    "name": "Relaxed Alerts on Weekend Mornings",
    "priority": 20,
    "enabled": True,
    "conditions": {
        "all": [
            {"day_of_week": ["sat", "sun"]},
            {"is_quiet_hours": {"name": "Weekend Sleep"}},
            {"evidence_exists": {"source": "vision", "feature": "person_detected"}}
        ]
    },
    "actions": [
        {"type": "log", "message": "Weekend quiet hours - minimal alerts only"}
    ]
}

# Policy: Emergency override during quiet hours
emergency_alert_override = {
    "id": "emergency_alert_override",
    "name": "Emergency Alerts Override Quiet Hours",
    "priority": 100,  # Very high priority
    "enabled": True,
    "conditions": {
        "any": [
            {"evidence_exists": {"source": "vision", "feature": "police"}},
            {"evidence_exists": {"source": "vision", "feature": "fire"}},
            {
                "all": [
                    {"is_quiet_hours": True},
                    {"track_duration_gt": 300}  # Loitering for 5+ minutes
                ]
            }
        ]
    },
    "actions": [
        {
            "type": "telegram",
            "message": "🚨 EMERGENCY: {vision.detected_class} detected",
            "disable_notification": False  # Force notification even during quiet hours
        },
        {
            "type": "speak",
            "message": "Emergency alert. {vision.detected_class} detected.",
            "volume": 80  # Loud volume override
        }
    ]
}
