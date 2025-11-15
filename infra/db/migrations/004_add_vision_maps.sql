CREATE TABLE IF NOT EXISTS vision_class_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,       -- e.g. "yolov8n"
    raw_class TEXT NOT NULL,        -- e.g. "microwave"
    semantic_class TEXT NOT NULL,   -- e.g. "package"
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(model_name, raw_class)
);

-- Insert default mappings for yolov8n
INSERT OR IGNORE INTO vision_class_map (model_name, raw_class, semantic_class)
VALUES 
    ('yolov8n', 'person',     'person'),
    ('yolov8n', 'microwave',  'package'),
    ('yolov8n', 'oven',       'package'),
    ('yolov8n', 'suitcase',   'package'),
    ('yolov8n', 'truck',      'vehicle'),
    ('yolov8n', 'car',        'vehicle'),
    ('yolov8n', 'motorbike',  'vehicle'),
    ('yolov8n', 'dog',        'dog'),
    ('yolov8n', 'tie',        'tie');