# Contributing to echoBell

Thank you for your interest in contributing to echoBell! This guide will help you get started and follow best practices.

## Table of Contents

- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Database Migrations](#database-migrations)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

## Development Setup

### Prerequisites

- Python 3.11+
- Git
- Virtual environment tool (venv)

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/bbureau12/echoBell.git
cd echoBell

# Create and activate virtual environment
python -m venv .venv-vision
.venv-vision\Scripts\activate  # Windows
# or
source .venv-vision/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Initialize database
python -c "from storage.dao import ensure_db_exists, migrate; ensure_db_exists(); migrate()"

# Run tests to verify setup
pytest
```

## Project Structure

```
echoBell/
├── apps/               # Application entry points
│   └── doorbell-agent/ # Main doorbell orchestration
├── config/            # YAML configuration files
├── data/              # SQLite database location
├── docs/              # Documentation
├── infra/             # Infrastructure (migrations, schema)
│   └── db/
│       ├── migrations/ # Database migrations (numbered)
│       └── schema.sql  # Reference schema
├── packages/          # Core modules
│   ├── classify/      # Intent classification
│   ├── data/          # Data services (evidence, etc.)
│   ├── notifiers/     # Notification systems
│   ├── perception/    # Vision, ASR, OCR
│   ├── policy/        # Policy engine
│   └── tts/           # Text-to-speech
├── storage/           # Database access layer
├── tests/             # Test suite
└── tools/             # Development tools
```

## Coding Standards

### Python Style

- **PEP 8** compliance (use `black` for formatting)
- **Type hints** for function signatures
- **Docstrings** for public functions and classes
- **Descriptive variable names** - avoid abbreviations

### Dataclasses

When working with dataclasses in `packages/common/types.py`:

- **Constructor parameters** are defined fields (e.g., `object_id`, `label`)
- **Props dictionary** stores dynamic/optional attributes (e.g., `color`, `visitor_id`)
- **Don't add direct attributes** - use `props` for extensibility

Example:
```python
# ❌ Wrong
obj = SceneObject(object_id=1, label="person", color="blue")

# ✅ Correct
obj = SceneObject(object_id=1, label="person")
obj.props["color"] = "blue"
```

### Evidence Pattern

Evidence should capture raw perception signals:
```python
Evidence(
    source="vision",     # Module that produced it (vision/ocr/fashion)
    feature="class",     # What was observed (class/color/token)
    value="person",      # Observed value
    conf=0.95,          # Confidence (0.0-1.0)
    object_id=0         # Optional: which object in scene
)
```

## Database Migrations

### Creating a Migration

1. **Check current version:**
   ```python
   python -c "from storage.dao import get_db_version; print(get_db_version())"
   ```

2. **Create new migration file:**
   ```
   infra/db/migrations/0XX_description.sql
   ```

3. **Follow migration standards:**

   ```sql
   -- Migration XX: Brief description
   -- Date: YYYY-MM-DD
   -- Purpose: Detailed explanation
   
   PRAGMA foreign_keys = ON;
   
   -- Use CREATE TABLE IF NOT EXISTS for idempotency
   CREATE TABLE IF NOT EXISTS my_table (
       id INTEGER PRIMARY KEY,
       name TEXT NOT NULL
   );
   
   -- Create indexes
   CREATE INDEX IF NOT EXISTS idx_my_table_name ON my_table(name);
   
   -- Set version at end
   PRAGMA user_version = XX;
   ```

### Migration Best Practices

✅ **DO:**
- Use `CREATE TABLE IF NOT EXISTS` for new tables
- Use `CREATE INDEX IF NOT EXISTS` for indexes
- Make migrations idempotent (safe to run multiple times)
- Test migrations on a copy of production database
- Document the purpose and any breaking changes

❌ **DON'T:**
- Use `ALTER TABLE ADD COLUMN` without checking if column exists
- Assume tables exist from previous migrations (use IF NOT EXISTS)
- Modify existing migrations after they've been committed
- Create migrations with non-sequential numbers

### Common Migration Patterns

**Adding a table:**
```sql
CREATE TABLE IF NOT EXISTS new_table (
    id INTEGER PRIMARY KEY,
    created_ts INTEGER NOT NULL,
    data TEXT
);

CREATE INDEX IF NOT EXISTS idx_new_table_created 
    ON new_table(created_ts DESC);
```

**Handling existing vs new databases:**
```sql
-- Create table with all columns
CREATE TABLE IF NOT EXISTS my_table (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    new_column TEXT  -- Column we're adding
);

-- For existing databases, update existing rows
UPDATE my_table 
SET new_column = 'default_value' 
WHERE new_column IS NULL;
```

### Testing Migrations

```bash
# Run all tests including migration tests
pytest tests/

# Test specific migration integration
pytest tests/test_evidence_service.py -v
```

## Testing

### Test Structure

```
tests/
├── test_<module>_unit.py       # Unit tests (isolated)
├── test_<module>_integration.py # Integration tests
└── test_<module>_regression.py  # Regression tests
```

### Writing Tests

**Unit tests** - Test individual functions:
```python
def test_function_name():
    """Brief description of what's being tested."""
    # Arrange
    input_data = "test"
    
    # Act
    result = my_function(input_data)
    
    # Assert
    assert result == expected_output
```

**Integration tests** - Test component interactions:
```python
@pytest.fixture
def temp_db():
    """Create temporary database with required schema."""
    # Setup
    db_path = create_temp_db()
    yield db_path
    # Teardown
    cleanup(db_path)

def test_integration(temp_db):
    """Test components working together."""
    result = component_a_and_b(temp_db)
    assert result.success
```

### Test Database Setup

When creating test fixtures that need a database:

1. **Use temporary files:**
   ```python
   import tempfile
   from pathlib import Path
   
   with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
       db_path = Path(f.name)
   ```

2. **Apply minimal schema needed:**
   ```python
   conn.executescript("""
       CREATE TABLE IF NOT EXISTS required_table (...);
       INSERT INTO required_table VALUES (...);
   """)
   ```

3. **Handle Windows file locks:**
   ```python
   try:
       db_path.unlink()
   except PermissionError:
       pass  # Windows may still have file locked
   ```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_evidence_service.py

# Run with verbose output
pytest -v

# Run specific test
pytest tests/test_evidence_service.py::test_log_evidence

# Run with coverage
pytest --cov=packages --cov-report=html
```

## Submitting Changes

### Branch Strategy

- `main` - Stable production code
- `intent_tracking` - Current development branch
- Feature branches - `feature/description`
- Bug fixes - `fix/description`

### Commit Messages

Follow conventional commits:

```
type(scope): brief description

Detailed explanation of changes and why they were made.

- Key change 1
- Key change 2

Refs: #issue-number
```

**Types:**
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Adding/fixing tests
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

**Examples:**
```
feat(evidence): add queryable evidence logging to classify_and_log

Integrates EvidenceService into the classify_and_log pipeline to
automatically persist all evidence to the evidence_log table with
track associations for people and vehicles.

- Added optional evidence_service parameter
- Log evidence after event creation (Phase 3d)
- Includes track_key associations for queryability
- Backward compatible (evidence_service=None works)

Refs: #123

---

fix(migrations): create visitor_events table in migration 007

Migration 007 was trying to ALTER visitor_events but the table
didn't exist in the migration chain. Changed to CREATE TABLE IF
NOT EXISTS to handle both new and existing databases.

Refs: #124
```

### Pull Request Process

1. **Create feature branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make changes and test**
   ```bash
   pytest
   ```

3. **Commit with clear messages**
   ```bash
   git add .
   git commit -m "feat(module): description"
   ```

4. **Push and create PR**
   ```bash
   git push origin feature/my-feature
   ```

5. **PR should include:**
   - Clear description of changes
   - Test coverage
   - Documentation updates
   - Migration notes (if applicable)

### Checklist Before Submitting

- [ ] All tests pass (`pytest`)
- [ ] New code has tests
- [ ] Documentation updated
- [ ] Migration tested (if applicable)
- [ ] Code follows style guide
- [ ] Commit messages are clear
- [ ] No debug code or TODOs left

## Architecture Decisions

For significant architectural changes, create an ADR (Architecture Decision Record):

```bash
docs/adr/ADR-XXXX-description.md
```

See existing ADRs for format. Create ADRs for:
- New major features
- Database schema changes affecting multiple tables
- Integration patterns
- API design decisions

**Don't create ADRs for:**
- Bug fixes
- Test improvements
- Documentation updates
- Code refactoring without design changes

## Getting Help

- **Documentation:** See `docs/` directory
- **Database Schema:** See `docs/DATABASE_SCHEMA.md`
- **Types Reference:** See `docs/TYPES_REFERENCE.md`
- **Architecture:** See `docs/ARCHITECTURE.md`
- **Questions:** Open a GitHub issue with label `question`

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.
