-- Migration 002: add Echo-Bell feature flags and settings (no schema changes)

INSERT OR IGNORE INTO features(name,enabled,note)
  VALUES ('echobell_active',1,'Doorbell AI subsystem enabled');

INSERT OR IGNORE INTO settings(key,value,source)
  VALUES ('agent_echobell','enabled','user');

PRAGMA user_version = 2;