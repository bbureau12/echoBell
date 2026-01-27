"""
Shared database setup utilities for integration tests.

Provides common schema creation functions to avoid duplication across test files.
"""
import sqlite3
from packages.scene import scene_linkage


def _create_table(conn: sqlite3.Connection, name: str, schema: str):
    """Helper to create a table with cleaner syntax."""
    conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({schema})")


def create_test_schema(conn: sqlite3.Connection, include_facial_recognition: bool = True):
    """
    Create all required database tables for integration tests.
    
    Args:
        conn: Database connection
        include_facial_recognition: Whether to include tables needed for facial recognition
                                   (visitor_embeddings, known_visitors)
    """
    
    # Capability levels
    _create_table(conn, "capability_level", """
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        allow_facial_detail INTEGER DEFAULT 0,
        allow_plate_ocr INTEGER DEFAULT 1,
        allow_visitor_snapshot INTEGER DEFAULT 1
    """)
    
    conn.execute("""
        INSERT OR IGNORE INTO capability_level (id, name, allow_facial_detail, allow_plate_ocr)
        VALUES 
            (1, 'Vehicle ID Only', 0, 1),
            (2, 'Facial Recognition Enabled', 1, 1)
    """)
    
    # Camera
    _create_table(conn, "camera", """
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        location_id INTEGER,
        description TEXT,
        capability_level_id INTEGER,
        hostname TEXT,
        ip_address TEXT,
        port INTEGER,
        protocol TEXT,
        endpoint TEXT,
        stream_url TEXT,
        auth_profile_id INTEGER
    """)
    
    # Scene tracks
    _create_table(conn, "scene_tracks", """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER NOT NULL,
        track_type TEXT NOT NULL,
        key_kind TEXT NOT NULL,
        track_key TEXT NOT NULL,
        first_seen_ts INTEGER NOT NULL,
        last_seen_ts INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        last_box_json TEXT,
        raw_class TEXT,
        color TEXT,
        tags TEXT,
        last_event_id TEXT,
        UNIQUE(camera_id, track_type, track_key)
    """)
    
    # Visit entity links (person-vehicle relationships)
    scene_linkage.ensure_schema(conn)
    
    # Visitor events
    _create_table(conn, "visitor_events", """
        event_id TEXT PRIMARY KEY,
        visitor_id TEXT,
        camera_id INTEGER,
        detected_ts TEXT NOT NULL,
        intent_inferred TEXT,
        intent_confidence REAL,
        intent_locked INTEGER NOT NULL DEFAULT 0,
        duration_s REAL,
        evidence_json TEXT,
        snapshot_path TEXT,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    """)
    
    # Intent/signal tables (required for classify_and_log)
    _create_table(conn, "intent_def", """
        name TEXT PRIMARY KEY,
        description TEXT,
        urgency INTEGER DEFAULT 0
    """)
    
    _create_table(conn, "pattern_def", """
        pattern TEXT NOT NULL,
        is_regex INTEGER DEFAULT 0,
        intent_name TEXT,
        entity_name TEXT,
        weight REAL DEFAULT 1.0,
        enabled INTEGER DEFAULT 1
    """)
    
    _create_table(conn, "entity_def", """
        name TEXT PRIMARY KEY,
        tag TEXT,
        weight REAL DEFAULT 0.5,
        description TEXT
    """)
    
    _create_table(conn, "signal_rule", """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        feature TEXT NOT NULL,
        operator TEXT NOT NULL,
        value TEXT NOT NULL,
        intent_name TEXT NOT NULL,
        weight REAL DEFAULT 1.0,
        min_conf REAL DEFAULT 0.0,
        urgency INTEGER DEFAULT 0,
        scope_any_of TEXT,
        contributes_standalone INTEGER DEFAULT 1,
        enabled INTEGER DEFAULT 1
    """)
    
    _create_table(conn, "signal_group", """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        intent_name TEXT NOT NULL,
        group_mode TEXT DEFAULT 'all',
        bind_scope TEXT,
        base_weight REAL DEFAULT 1.0,
        urgency INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1
    """)
    
    _create_table(conn, "signal_group_member", """
        group_id INTEGER NOT NULL,
        rule_id INTEGER NOT NULL,
        required INTEGER DEFAULT 0,
        weight_mul REAL DEFAULT 1.0,
        enabled INTEGER DEFAULT 1,
        PRIMARY KEY (group_id, rule_id)
    """)
    
    # Vision class map
    _create_table(conn, "vision_class_map", """
        id INTEGER PRIMARY KEY,
        model_name TEXT NOT NULL,
        raw_class TEXT NOT NULL,
        semantic_class TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1
    """)
    
    conn.execute("""
        INSERT OR IGNORE INTO vision_class_map (model_name, raw_class, semantic_class, enabled)
        VALUES 
            ('yolov8n', 'person', 'person', 1),
            ('yolov8n', 'car', 'vehicle', 1),
            ('yolov8n', 'truck', 'vehicle', 1),
            ('yolov8n', 'bus', 'vehicle', 1),
            ('yolov8n', 'airplane', 'vehicle', 1)
    """)
    
    # Attach rule (for parent-child object relationships)
    _create_table(conn, "attach_rule", """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        child_label TEXT NOT NULL,
        parent_any_of TEXT NOT NULL,
        min_containment REAL DEFAULT 0.5,
        min_parent_conf REAL DEFAULT 0.4,
        prefer_parent TEXT,
        enabled INTEGER DEFAULT 1
    """)
    
    # Policy rules (dynamic policy management)
    _create_table(conn, "policy_rules", """
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        enabled INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 50,
        conditions_json TEXT,
        actions_json TEXT,
        variables_json TEXT,
        created_ts INTEGER,
        updated_ts INTEGER,
        created_by TEXT,
        tags TEXT,
        version INTEGER DEFAULT 1
    """)
    
    # Alert history (for tracking sent alerts)
    _create_table(conn, "alert_history", """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT,
        track_key TEXT,
        track_type TEXT,
        alert_type TEXT,
        policy_id TEXT,
        priority TEXT,
        sent_ts INTEGER,
        message TEXT,
        success INTEGER,
        error_message TEXT
    """)
    
    # Optional facial recognition tables
    if include_facial_recognition:
        # Known visitors
        _create_table(conn, "known_visitors", """
            visitor_id TEXT PRIMARY KEY,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            visit_count_total INTEGER NOT NULL DEFAULT 1,
            visit_count_7d INTEGER NOT NULL DEFAULT 1,
            visit_count_30d INTEGER NOT NULL DEFAULT 1,
            confidence_score REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'active',
            intent_last TEXT,
            intent_last_ts INTEGER,
            notes TEXT
        """)
        
        # Visitor embeddings
        _create_table(conn, "visitor_embeddings", """
            embedding_id TEXT PRIMARY KEY,
            visitor_id TEXT NOT NULL,
            model_name TEXT NOT NULL,
            embedding_dim INTEGER NOT NULL,
            embedding_blob BLOB NOT NULL,
            source_event_id TEXT,
            created_ts INTEGER NOT NULL,
            quality_score REAL NOT NULL DEFAULT 1.0,
            camera_id INTEGER
        """)
    
    conn.commit()


def create_test_cameras(conn: sqlite3.Connection, camera_configs: list[dict]):
    """
    Create test cameras in the database.
    
    Args:
        conn: Database connection
        camera_configs: List of camera configurations, e.g.:
            [
                {'id': 1, 'name': 'Driveway', 'capability_level_id': 1, 'stream_url': 'rtsp://test1'},
                {'id': 2, 'name': 'Front Door', 'capability_level_id': 2, 'stream_url': 'rtsp://test2'}
            ]
    """
    for config in camera_configs:
        conn.execute(
            """
            INSERT INTO camera (id, name, capability_level_id, stream_url)
            VALUES (?, ?, ?, ?)
            """,
            (config['id'], config['name'], config['capability_level_id'], config['stream_url'])
        )
    conn.commit()
