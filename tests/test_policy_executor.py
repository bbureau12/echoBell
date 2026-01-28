"""
Tests for policy action executor
"""
import pytest
import pytest_asyncio
import sqlite3
from datetime import datetime
from unittest.mock import patch, MagicMock
from packages.policy.executor import ActionExecutor

# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)


@pytest.fixture
def test_db():
    """Create in-memory test database with alert_history"""
    conn = sqlite3.connect(':memory:')
    
    conn.execute("""
        CREATE TABLE alert_history (
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
        )
    """)
    
    conn.commit()
    yield conn
    conn.close()


@pytest.mark.asyncio
async def test_telegram_action_execution(test_db, monkeypatch):
    """Test telegram action execution and alert_history recording (mocked)"""
    # Mock the telegram send to avoid actually sending messages
    def mock_send_message(self, message):
        return True
    
    from packages.integrations import telegram
    monkeypatch.setattr(telegram.TelegramNotifier, 'send_message', mock_send_message)
    
    executor = ActionExecutor(test_db)
    
    actions = [
        {
            'type': 'telegram',
            'message': 'Unknown vehicle detected at {camera_name}',
            'priority': 'normal'
        }
    ]
    
    variables = {
        'camera_name': 'front_door'
    }
    
    context = {
        'camera_id': 'cam1',
        'track_key': 'track_001'
    }
    
    results = await executor.execute_actions(actions, variables, context)
    
    assert len(results) == 1
    assert results[0]['action_type'] == 'telegram'
    assert results[0]['success'] is True
    assert results[0]['message'] == 'Unknown vehicle detected at front_door'
    assert results[0]['priority'] == 'normal'
    
    # Verify alert_history was recorded
    row = test_db.execute("""
        SELECT camera_id, track_key, alert_type, priority, message, success
        FROM alert_history
    """).fetchone()
    
    assert row is not None
    assert row[0] == 'cam1'
    assert row[1] == 'track_001'
    assert row[2] == 'telegram'
    assert row[3] == 'normal'
    assert row[4] == 'Unknown vehicle detected at front_door'
    assert row[5] == 1


@pytest.mark.asyncio
async def test_speak_action_execution(test_db):
    """Test speak (TTS) action execution"""
    executor = ActionExecutor(test_db)
    
    actions = [
        {
            'type': 'speak',
            'text': 'Welcome home, {person_name}',
            'voice': 'friendly'
        }
    ]
    
    variables = {
        'person_name': 'John'
    }
    
    context = {}
    
    results = await executor.execute_actions(actions, variables, context)
    
    assert len(results) == 1
    assert results[0]['action_type'] == 'speak'
    assert results[0]['success'] is True
    assert results[0]['text'] == 'Welcome home, John'
    assert results[0]['voice'] == 'friendly'


@pytest.mark.asyncio
async def test_multiple_actions_execution(test_db, monkeypatch):
    """Test executing multiple actions in sequence"""
    # Mock telegram
    def mock_send_message(self, message):
        return True
    from packages.integrations import telegram
    monkeypatch.setattr(telegram.TelegramNotifier, 'send_message', mock_send_message)
    
    executor = ActionExecutor(test_db)
    
    actions = [
        {
            'type': 'telegram',
            'message': 'Alert message',
            'priority': 'urgent'
        },
        {
            'type': 'speak',
            'text': 'Warning announcement',
            'voice': 'stern'
        }
    ]
    
    variables = {}
    context = {
        'camera_id': 'cam1',
        'track_key': 'track_002'
    }
    
    results = await executor.execute_actions(actions, variables, context)
    
    assert len(results) == 2
    assert results[0]['action_type'] == 'telegram'
    assert results[0]['success'] is True
    assert results[1]['action_type'] == 'speak'
    assert results[1]['success'] is True


@pytest.mark.asyncio
async def test_variable_substitution_in_message(test_db, monkeypatch):
    """Test variable substitution in action messages"""
    # Mock telegram
    def mock_send_message(self, message):
        return True
    from packages.integrations import telegram
    monkeypatch.setattr(telegram.TelegramNotifier, 'send_message', mock_send_message)
    
    executor = ActionExecutor(test_db)
    
    actions = [
        {
            'type': 'telegram',
            'message': 'Vehicle {plate_number} detected at {camera_name}. Confidence: {confidence}%',
            'priority': 'normal'
        }
    ]
    
    variables = {
        'plate_number': 'ABC123',
        'camera_name': 'driveway',
        'confidence': '95'
    }
    
    context = {
        'camera_id': 'cam1',
        'track_key': 'track_003'
    }
    
    results = await executor.execute_actions(actions, variables, context)
    
    assert results[0]['message'] == 'Vehicle ABC123 detected at driveway. Confidence: 95%'


@pytest.mark.asyncio
async def test_telegram_without_context(test_db, monkeypatch):
    """Test telegram action when context is incomplete (no track_key) - mocked"""
    # Mock the telegram send to avoid actually sending messages
    def mock_send_message(self, message):
        return True
    
    from packages.integrations import telegram
    monkeypatch.setattr(telegram.TelegramNotifier, 'send_message', mock_send_message)
    
    executor = ActionExecutor(test_db)
    
    actions = [
        {
            'type': 'telegram',
            'message': 'Test message',
            'priority': 'low'
        }
    ]
    
    variables = {}
    context = {}  # No camera_id or track_key
    
    results = await executor.execute_actions(actions, variables, context)
    
    assert len(results) == 1
    assert results[0]['success'] is True
    
    # Should NOT record in alert_history (no track_key)
    row_count = test_db.execute("SELECT COUNT(*) FROM alert_history").fetchone()[0]
    assert row_count == 0


@pytest.mark.asyncio
async def test_unknown_action_type(test_db):
    """Test handling of unknown action type"""
    executor = ActionExecutor(test_db)
    
    actions = [
        {
            'type': 'unknown_action_type',
            'data': 'some data'
        }
    ]
    
    variables = {}
    context = {}
    
    results = await executor.execute_actions(actions, variables, context)
    
    assert len(results) == 1
    assert results[0]['action_type'] == 'unknown_action_type'
    assert results[0]['success'] is False
    assert 'No handler registered' in results[0]['error'] or 'Unknown action type' in results[0]['error']


@pytest.mark.asyncio
async def test_variable_substitution_missing_variable(test_db, monkeypatch):
    """Test variable substitution when variable is missing"""
    # Mock telegram
    def mock_send_message(self, message):
        return True
    from packages.integrations import telegram
    monkeypatch.setattr(telegram.TelegramNotifier, 'send_message', mock_send_message)
    
    executor = ActionExecutor(test_db)
    
    actions = [
        {
            'type': 'telegram',
            'message': 'Message with {missing_var} placeholder',
            'priority': 'normal'
        }
    ]
    
    variables = {
        'existing_var': 'value'
    }
    
    context = {
        'camera_id': 'cam1',
        'track_key': 'track_004'
    }
    
    results = await executor.execute_actions(actions, variables, context)
    
    # Should still succeed, but leave placeholder unchanged
    assert results[0]['success'] is True
    assert results[0]['message'] == 'Message with {missing_var} placeholder'
