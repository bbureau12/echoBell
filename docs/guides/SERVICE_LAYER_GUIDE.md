# Quick Reference: Using the Service Layer

## For Developers

When adding new functionality to echoBell, follow the DRY service layer pattern:

### 1. Add Service Function

**File:** `apps/policy-server/services.py`

```python
def my_new_operation(
    conn: sqlite3.Connection,
    param1: str,
    param2: int,
    optional_param: Optional[str] = None
) -> Dict[str, Any]:
    """
    Brief description of what this operation does.
    
    Args:
        conn: Database connection
        param1: Description of param1
        param2: Description of param2
        optional_param: Optional parameter description
    
    Returns:
        Dict with result data
    """
    # Your business logic here
    cursor = conn.execute("SELECT ...", (param1, param2))
    result = cursor.fetchall()
    
    # Process and return
    return {
        "param1": param1,
        "param2": param2,
        "result": result
    }
```

### 2. Add FastAPI Endpoint (Optional)

**File:** `apps/policy-server/server.py`

```python
# Add Pydantic model for request validation
class MyOperationRequest(BaseModel):
    param1: str
    param2: int
    optional_param: Optional[str] = None

# Add endpoint
@app.post("/my_operation")
async def my_operation(request: MyOperationRequest):
    """HTTP endpoint - uses service layer"""
    try:
        with get_db() as conn:
            result = services.my_new_operation(
                conn=conn,
                param1=request.param1,
                param2=request.param2,
                optional_param=request.optional_param
            )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 3. Add MCP Tool (Optional)

**File:** `apps/policy-server/mcp_server.py`

```python
# Add tool definition (in TOOLS list)
Tool(
    name="my_operation",
    description="Brief description for AI clients",
    inputSchema={
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "Description shown to Claude"
            },
            "param2": {
                "type": "integer",
                "description": "Another param"
            },
            "optional_param": {
                "type": "string",
                "description": "Optional parameter"
            }
        },
        "required": ["param1", "param2"]
    }
)

# Add handler (in tool_handlers dict)
async def handle_my_operation(args: dict) -> dict:
    """Handle my_operation - uses service layer"""
    with get_db() as conn:
        result = services.my_new_operation(
            conn=conn,
            param1=args["param1"],
            param2=args["param2"],
            optional_param=args.get("optional_param")
        )
    return result

# Register in tool_handlers
tool_handlers = {
    # ... existing handlers
    "my_operation": handle_my_operation,
}
```

### 4. Add Test

**File:** `tests/test_service_layer.py`

```python
def test_my_new_operation(test_db):
    """Test my_new_operation service function"""
    # Call service function directly
    result = services.my_new_operation(
        conn=test_db,
        param1="test",
        param2=42,
        optional_param="optional"
    )
    
    # Assert expected behavior
    assert result["param1"] == "test"
    assert result["param2"] == 42
    # ... more assertions
```

## Common Patterns

### Read Operation (GET)

```python
def get_something(conn: sqlite3.Connection, id: int) -> Optional[Dict[str, Any]]:
    """Get single item by ID"""
    cursor = conn.execute("SELECT * FROM table WHERE id = ?", (id,))
    row = cursor.fetchone()
    
    if not row:
        return None
    
    return {
        "id": row[0],
        "name": row[1],
        # ... map columns
    }
```

### List Operation (GET collection)

```python
def list_something(
    conn: sqlite3.Connection,
    filter_param: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """List items with optional filter"""
    query = "SELECT * FROM table"
    params = []
    
    if filter_param:
        query += " WHERE column = ?"
        params.append(filter_param)
    
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    cursor = conn.execute(query, params)
    
    items = []
    for row in cursor.fetchall():
        items.append({
            "id": row[0],
            "name": row[1],
            # ... map columns
        })
    
    return items
```

### Create Operation (POST)

```python
def create_something(
    conn: sqlite3.Connection,
    name: str,
    value: int,
    description: str = ""
) -> Dict[str, Any]:
    """Create new item"""
    now = int(time.time())
    
    cursor = conn.execute(
        """
        INSERT INTO table (name, value, description, created_ts)
        VALUES (?, ?, ?, ?)
        """,
        (name, value, description, now)
    )
    
    item_id = cursor.lastrowid
    conn.commit()
    
    return {
        "id": item_id,
        "name": name,
        "value": value,
        "description": description,
        "created_ts": now
    }
```

### Update Operation (PATCH)

```python
def update_something(
    conn: sqlite3.Connection,
    id: int,
    name: Optional[str] = None,
    value: Optional[int] = None,
    description: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Partial update - only update provided fields"""
    # Check if exists
    existing = get_something(conn, id)
    if not existing:
        return None
    
    # Build dynamic update
    updates = []
    params = []
    
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    
    if value is not None:
        updates.append("value = ?")
        params.append(value)
    
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    
    if not updates:
        return existing  # No changes
    
    # Add updated timestamp
    updates.append("updated_ts = ?")
    params.append(int(time.time()))
    
    # Add ID for WHERE clause
    params.append(id)
    
    query = f"UPDATE table SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, params)
    conn.commit()
    
    # Return updated item
    return get_something(conn, id)
```

### Delete Operation (DELETE)

```python
def delete_something(conn: sqlite3.Connection, id: int) -> bool:
    """Delete item by ID"""
    cursor = conn.execute("DELETE FROM table WHERE id = ?", (id,))
    conn.commit()
    
    return cursor.rowcount > 0
```

## Testing Pattern

```python
@pytest.fixture
def test_db():
    """Create temp database with schema"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    conn = sqlite3.connect(db_path)
    
    # Create schema
    conn.execute("CREATE TABLE ...")
    conn.commit()
    
    yield conn
    
    conn.close()
    os.unlink(db_path)


def test_operation(test_db):
    """Test the operation"""
    # Setup
    # ... insert test data if needed
    
    # Execute
    result = services.my_operation(test_db, ...)
    
    # Assert
    assert result["key"] == "expected_value"
```

## Best Practices

### ✅ Do

- Put ALL business logic in service functions
- Type hint all parameters and return values
- Document with docstrings (Args, Returns)
- Test service functions directly
- Use database transactions (get_db() context manager)
- Return dicts (easy to serialize to JSON)
- Handle None/optional parameters gracefully

### ❌ Don't

- Put business logic in endpoint handlers
- Mix HTTP/MCP concerns with business logic
- Hardcode configuration values
- Forget to commit transactions
- Raise HTTP exceptions from service layer (return None/False instead)
- Return complex objects (use dicts)

## Quick Commands

**Run service layer tests:**
```bash
pytest tests/test_service_layer.py -v
```

**Check syntax:**
```bash
python -m py_compile apps/policy-server/services.py
```

**Start FastAPI server:**
```bash
cd apps/policy-server
python server.py
```

**Start MCP server:**
```bash
python apps/policy-server/mcp_server.py
```

**Test HTTP endpoint:**
```bash
curl http://localhost:8000/my_endpoint
```

## File Organization

```
apps/policy-server/
  ├── services.py          # ← Business logic (service layer)
  ├── server.py            # ← FastAPI HTTP endpoints
  └── mcp_server.py        # ← MCP tools

tests/
  └── test_service_layer.py  # ← Service layer tests

docs/
  ├── MCP_SERVER.md          # ← MCP documentation
  └── POLICY_API.md          # ← API documentation
```

## Summary

**Golden Rule:** If it touches the database or implements business logic, it belongs in `services.py`.

This ensures:
- ✅ DRY code (no duplication)
- ✅ Easy testing (no server overhead)
- ✅ Consistency (same logic everywhere)
- ✅ Flexibility (easy to add new interfaces)
