"""Tests for Quiet Hours MCP tools"""
import pytest
import sqlite3
import sys
import os
from datetime import datetime

# Add project paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'central', 'policy-server'))

# Import MCP handlers
from mcp_server import (
    handle_list_quiet_hours,
    handle_create_quiet_hour,
    handle_update_quiet_hour,
    handle_delete_quiet_hour,
    handle_is_quiet_time,
    handle_get_active_quiet_hours,
)


@pytest.fixture
def test_db(tmp_path):
    """Create test database with quiet_hours table"""
    db_path = tmp_path / "test_mcp.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE quiet_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),
            start_time TEXT NOT NULL CHECK(length(start_time) = 5 AND start_time LIKE '__:__'),
            end_time TEXT NOT NULL CHECK(length(end_time) = 5 AND end_time LIKE '__:__'),
            enabled INTEGER DEFAULT 1 CHECK(enabled IN (0, 1)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    
    # Monkeypatch get_db to use our test database
    import mcp_server
    original_get_db = mcp_server.get_db
    
    from contextlib import contextmanager
    @contextmanager
    def mock_get_db():
        yield conn
    
    mcp_server.get_db = mock_get_db
    
    yield conn
    
    # Restore original
    mcp_server.get_db = original_get_db
    conn.close()


@pytest.mark.asyncio
async def test_create_quiet_hour_mcp(test_db):
    """Test creating quiet hour via MCP"""
    result = await handle_create_quiet_hour({
        "name": "Sleep",
        "weekday": 0,
        "start_time": "22:00",
        "end_time": "07:00",
        "enabled": True
    })
    
    assert result["status"] == "created"
    assert result["quiet_hour"]["name"] == "Sleep"
    assert result["quiet_hour"]["weekday"] == 0
    assert result["quiet_hour"]["is_overnight"] is True


@pytest.mark.asyncio
async def test_list_quiet_hours_mcp(test_db):
    """Test listing quiet hours via MCP"""
    # Create some quiet hours first
    await handle_create_quiet_hour({
        "name": "Sleep",
        "weekday": 0,
        "start_time": "22:00",
        "end_time": "07:00"
    })
    await handle_create_quiet_hour({
        "name": "Lunch",
        "weekday": 0,
        "start_time": "12:00",
        "end_time": "13:00"
    })
    
    # List all
    result = await handle_list_quiet_hours({})
    assert result["count"] == 2
    assert len(result["quiet_hours"]) == 2
    
    # List for specific weekday
    result = await handle_list_quiet_hours({"weekday": 0})
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_update_quiet_hour_mcp(test_db):
    """Test updating quiet hour via MCP"""
    # Create first
    created = await handle_create_quiet_hour({
        "name": "Sleep",
        "weekday": 0,
        "start_time": "22:00",
        "end_time": "07:00"
    })
    quiet_hour_id = created["quiet_hour"]["id"]
    
    # Update
    result = await handle_update_quiet_hour({
        "quiet_hour_id": quiet_hour_id,
        "start_time": "23:00"
    })
    
    assert result["status"] == "updated"
    assert result["quiet_hour"]["start_time"] == "23:00"
    assert result["quiet_hour"]["end_time"] == "07:00"  # Unchanged


@pytest.mark.asyncio
async def test_delete_quiet_hour_mcp(test_db):
    """Test deleting quiet hour via MCP"""
    # Create first
    created = await handle_create_quiet_hour({
        "name": "Sleep",
        "weekday": 0,
        "start_time": "22:00",
        "end_time": "07:00"
    })
    quiet_hour_id = created["quiet_hour"]["id"]
    
    # Delete
    result = await handle_delete_quiet_hour({"quiet_hour_id": quiet_hour_id})
    assert result["status"] == "deleted"
    
    # Verify it's gone
    list_result = await handle_list_quiet_hours({})
    assert list_result["count"] == 0


@pytest.mark.asyncio
async def test_is_quiet_time_mcp(test_db):
    """Test checking if it's quiet time via MCP"""
    # Create quiet hours for Monday 22:00-07:00
    await handle_create_quiet_hour({
        "name": "Sleep",
        "weekday": 0,
        "start_time": "22:00",
        "end_time": "07:00"
    })
    
    # Check during quiet hours (Monday 23:00)
    monday_23 = int(datetime(2026, 2, 2, 23, 0).timestamp())
    result = await handle_is_quiet_time({"timestamp": monday_23})
    assert result["is_quiet_time"] is True
    
    # Check outside quiet hours (Monday 15:00)
    monday_15 = int(datetime(2026, 2, 2, 15, 0).timestamp())
    result = await handle_is_quiet_time({"timestamp": monday_15})
    assert result["is_quiet_time"] is False


@pytest.mark.asyncio
async def test_get_active_quiet_hours_mcp(test_db):
    """Test getting active quiet hours via MCP"""
    # Create multiple quiet hours
    await handle_create_quiet_hour({
        "name": "Sleep",
        "weekday": 0,
        "start_time": "22:00",
        "end_time": "07:00"
    })
    await handle_create_quiet_hour({
        "name": "Lunch",
        "weekday": 0,
        "start_time": "12:00",
        "end_time": "13:00"
    })
    
    # Check during lunch time (Monday 12:30)
    monday_lunch = int(datetime(2026, 2, 2, 12, 30).timestamp())
    result = await handle_get_active_quiet_hours({"timestamp": monday_lunch})
    
    assert result["is_quiet_time"] is True
    assert result["count"] == 1
    assert result["active_quiet_hours"][0]["name"] == "Lunch"
    
    # Check during sleep time (Monday 23:00)
    monday_sleep = int(datetime(2026, 2, 2, 23, 0).timestamp())
    result = await handle_get_active_quiet_hours({"timestamp": monday_sleep})
    
    assert result["is_quiet_time"] is True
    assert result["count"] == 1
    assert result["active_quiet_hours"][0]["name"] == "Sleep"
    
    # Check outside all quiet hours (Monday 15:00)
    monday_afternoon = int(datetime(2026, 2, 2, 15, 0).timestamp())
    result = await handle_get_active_quiet_hours({"timestamp": monday_afternoon})
    
    assert result["is_quiet_time"] is False
    assert result["count"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
