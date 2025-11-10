-- Migration 003: keyword + entity-driven classification

PRAGMA foreign_keys = ON;

-- Canonical intents
CREATE TABLE IF NOT EXISTS intent_def (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,             -- package_drop | sales_solicit | neighbor_help | authority_urgent | technician_visit | unknown
  description TEXT
);

-- Entities like companies/roles; can hint intent or set uniform tag
CREATE TABLE IF NOT EXISTS entity_def (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,             -- "midco", "xcel", "connexus", "ups", "fedex", "amazon", "police"
  tag TEXT,                              -- utility|delivery|authority|sales|neighbor
  intent_hint TEXT,                      -- optional: default intent to boost (e.g., technician_visit)
  weight REAL DEFAULT 0.5                -- relative contribution to score (0..1)
);

-- Patterns that map text → entity and/or intent with weights
CREATE TABLE IF NOT EXISTS pattern_def (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pattern TEXT NOT NULL,                 -- "midco", "xcel energy", "internet technician", "solar quote"
  is_regex INTEGER NOT NULL DEFAULT 0,   -- 0=substring, 1=regex (case-insensitive)
  entity_name TEXT,                      -- FK by name for convenience
  intent_name TEXT,                      -- optional direct intent mapping
  weight REAL NOT NULL DEFAULT 1.0,
  FOREIGN KEY (intent_name) REFERENCES intent_def(name) ON DELETE SET NULL,
  FOREIGN KEY (entity_name) REFERENCES entity_def(name) ON DELETE SET NULL
);

-- Seed standard intents (idempotent)
INSERT OR IGNORE INTO intent_def(name, description) VALUES
 ('package_drop','Delivery person dropping a package'),
 ('sales_solicit','Salesperson or solicitation'),
 ('neighbor_help','Neighbor asking for help or to notify'),
 ('authority_urgent','Police/Fire or urgent authority'),
 ('technician_visit','Utility/ISP scheduled/unscheduled technician'),
 ('unknown','Unclear/other');

-- Seed entities
INSERT OR IGNORE INTO entity_def(name, tag, intent_hint, weight) VALUES
 ('midco','utility','technician_visit',0.7),
 ('xcel','utility','technician_visit',0.7),
 ('connexus','utility','technician_visit',0.7),
 ('ups','delivery','package_drop',0.8),
 ('fedex','delivery','package_drop',0.8),
 ('amazon','delivery','package_drop',0.8),
 ('police','authority','authority_urgent',1.0),
 ('sheriff','authority','authority_urgent',1.0),
 ('fire','authority','authority_urgent',1.0);

-- Seed patterns (simple substrings first)
INSERT OR IGNORE INTO pattern_def(pattern, is_regex, entity_name, intent_name, weight) VALUES
 ('midco',0,'midco','technician_visit',1.0),
 ('xcel',0,'xcel','technician_visit',1.0),
 ('xcel energy',0,'xcel','technician_visit',1.0),
 ('connexus',0,'connexus','technician_visit',1.0),
 ('technician',0,NULL,'technician_visit',0.6),
 ('service call',0,NULL,'technician_visit',0.6),
 ('internet',0,'midco','technician_visit',0.4),
 ('gas',0,'xcel','technician_visit',0.4),
 ('appointment',0,'xcel','technician_visit',0.6),
 ('plumber',0,'xcel','technician_visit',0.6),
 ('tech',0,'xcel','technician_visit',0.5),
 ('furnace',0,'xcel','technician_visit',0.2),
 ('power',0,'connexus','technician_visit',0.4),

 ('ups',0,'ups','package_drop',1.0),
 ('fedex',0,'fedex','package_drop',1.0),
 ('amazon',0,'amazon','package_drop',0.8),
 ('package',0,NULL,'package_drop',0.5),
 ('delivery',0,NULL,'package_drop',0.6),

 ('police',0,'police','authority_urgent',1.0),
 ('officer',0,'police','authority_urgent',0.9),
 ('sheriff',0,'sheriff','authority_urgent',0.9),
 ('fire department',0,'fire','authority_urgent',1.0),
 ('emergency',0,NULL,'authority_urgent',0.8),

 ('neighbor',0,NULL,'neighbor_help',0.7),
 ('next door',0,NULL,'neighbor_help',0.6),
 ('borrow',0,NULL,'neighbor_help',0.5),
 ('fence',0,NULL,'neighbor_help',0.5),
 ('tree',0,NULL,'neighbor_help',0.4),

 ('solar',0,NULL,'sales_solicit',0.9),
 ('free',0,NULL,'sales_solicit',0.9),
 ('estimate',0,NULL,'sales_solicit',0.7),
 ('promotion',0,NULL,'sales_solicit',0.7),
 ('contract',0,NULL,'sales_solicit',0.2),
 ('sign up',0,NULL,'sales_solicit',0.4),
 ('going around',0,NULL,'sales_solicit',0.3),
 ('services',0,NULL,'sales_solicit',0.5);

PRAGMA user_version = 3;
