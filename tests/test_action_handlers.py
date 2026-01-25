"""
Test action handler registry system
"""
import pytest
import sqlite3
from packages.policy.action_handlers import (
    ActionRegistry,
    register_action_handler,
    substitute_variables,
    substitute_variables_in_dict
)


def test_built_in_handlers_registered():
    """Test that built-in handlers are auto-registered"""
    handlers = ActionRegistry.list_handlers()
    
    assert 'telegram' in handlers
    assert 'speak' in handlers
    assert 'webhook' in handlers
    assert 'log' in handlers


def test_custom_handler_registration():
    """Test registering a custom handler"""
    
    @register_action_handler("test_custom")
    class TestCustomHandler:
        def __init__(self, conn):
            self.conn = conn
        
        async def execute(self, action, variables, context):
            return {
                'action_type': 'test_custom',
                'success': True,
                'test_value': action.get('test_param')
            }
    
    handlers = ActionRegistry.list_handlers()
    assert 'test_custom' in handlers


def test_handler_instantiation():
    """Test getting handler instance from registry"""
    conn = sqlite3.connect(":memory:")
    
    handler = ActionRegistry.get_handler('log', conn)
    assert handler is not None


def test_unknown_handler():
    """Test getting handler that doesn't exist"""
    conn = sqlite3.connect(":memory:")
    
    handler = ActionRegistry.get_handler('nonexistent_action', conn)
    assert handler is None


def test_substitute_variables():
    """Test variable substitution in strings"""
    template = "Hello {name}, you have {count} alerts"
    variables = {"name": "Alice", "count": "3"}
    
    result = substitute_variables(template, variables)
    assert result == "Hello Alice, you have 3 alerts"


def test_substitute_variables_missing():
    """Test variable substitution with missing variable"""
    template = "Hello {name}, missing {unknown}"
    variables = {"name": "Bob"}
    
    result = substitute_variables(template, variables)
    assert result == "Hello Bob, missing {unknown}"


def test_substitute_variables_in_dict():
    """Test variable substitution in nested dict"""
    data = {
        "message": "Hello {name}",
        "metadata": {
            "count": "{count}",
            "items": ["item1", "{item2}"]
        }
    }
    variables = {"name": "Charlie", "count": "5", "item2": "value"}
    
    result = substitute_variables_in_dict(data, variables)
    
    assert result["message"] == "Hello Charlie"
    assert result["metadata"]["count"] == "5"
    assert result["metadata"]["items"][1] == "value"


@pytest.mark.asyncio
async def test_log_handler_execution():
    """Test executing the log action handler"""
    conn = sqlite3.connect(":memory:")
    handler = ActionRegistry.get_handler('log', conn)
    
    result = await handler.execute(
        action={
            'type': 'log',
            'message': 'Test message: {value}',
            'level': 'INFO'
        },
        variables={'value': '42'},
        context={'camera_id': 1, 'track_key': 'test_123'}
    )
    
    assert result['success'] == True
    assert result['action_type'] == 'log'
    assert result['message'] == 'Test message: 42'
    assert result['level'] == 'INFO'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
