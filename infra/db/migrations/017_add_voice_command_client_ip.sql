-- Migration 017: Add client IP address tracking to voice commands
-- Purpose: Audit trail for security monitoring and anomaly detection

-- Add client_ip column to voice_commands table
ALTER TABLE voice_commands 
ADD COLUMN client_ip TEXT;

-- Add index for IP-based queries (security monitoring)
CREATE INDEX IF NOT EXISTS idx_voice_cmd_client_ip 
    ON voice_commands(client_ip, timestamp DESC);

-- Add index for device+IP correlation (detect IP changes per device)
CREATE INDEX IF NOT EXISTS idx_voice_cmd_device_ip 
    ON voice_commands(source_device, client_ip, timestamp DESC);
