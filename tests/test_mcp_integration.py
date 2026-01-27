"""
MCP Protocol Integration Test

Tests the actual MCP server protocol layer by:
1. Starting the MCP server as a subprocess
2. Sending JSON-RPC tool call requests via stdin
3. Reading JSON-RPC responses from stdout
4. Validating MCP protocol compliance

This tests the FULL MCP stack, not just the service layer.
"""

import os
import sys
import json
import asyncio
import subprocess
import tempfile
import sqlite3
import time
from typing import Optional

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)


class MCPClient:
    """Simple MCP client for testing"""
    
    def __init__(self, server_script: str, db_path: str):
        self.server_script = server_script
        self.db_path = db_path
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 0
    
    def start(self):
        """Start the MCP server process"""
        env = os.environ.copy()
        env['ECHOBELL_DB_PATH'] = self.db_path
        
        self.process = subprocess.Popen(
            [sys.executable, self.server_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
            text=True
        )
        
        # Give server time to start
        time.sleep(0.5)
        
        # Check if process is still running
        if self.process.poll() is not None:
            stderr = self.process.stderr.read()
            raise RuntimeError(f"MCP server failed to start: {stderr}")
        
        # Perform MCP initialization handshake
        self._initialize()
    
    def _initialize(self):
        """Perform MCP protocol initialization"""
        # Send initialize request
        init_response = self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        })
        
        if "error" in init_response:
            raise RuntimeError(f"Initialization failed: {init_response['error']}")
        
        # Send initialized notification (no response expected)
        self.request_id += 1
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        notification_json = json.dumps(notification) + '\n'
        self.process.stdin.write(notification_json)
        self.process.stdin.flush()
    
    def stop(self):
        """Stop the MCP server process"""
        if self.process:
            self.process.stdin.close()
            self.process.terminate()
            self.process.wait(timeout=5)
    
    def send_request(self, method: str, params: dict = None) -> dict:
        """Send a JSON-RPC request and get response"""
        self.request_id += 1
        
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }
        
        # Debug: print request
        print(f"  → Sending: {method}")
        
        # Send request
        request_json = json.dumps(request) + '\n'
        self.process.stdin.write(request_json)
        self.process.stdin.flush()
        
        # Read response
        response_line = self.process.stdout.readline()
        if not response_line:
            stderr = self.process.stderr.read()
            raise RuntimeError(f"No response from server. stderr: {stderr}")
        
        try:
            response = json.loads(response_line)
            print(f"  ← Received: {list(response.keys())}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response: {response_line}") from e
        
        return response
    
    def call_tool(self, tool_name: str, arguments: dict = None) -> dict:
        """Call an MCP tool"""
        # MCP protocol expects params as a flat dict, not nested
        params = {
            "name": tool_name
        }
        if arguments:
            params["arguments"] = arguments
        
        response = self.send_request("tools/call", params)
        
        # Check for JSON-RPC error
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        
        # Extract result
        if "result" not in response:
            raise RuntimeError(f"No result in response: {response}")
        
        result = response["result"]
        
        # MCP tools return CallToolResult with content field
        # content is a list of TextContent objects
        if "content" in result and isinstance(result["content"], list):
            if len(result["content"]) > 0:
                text_content = result["content"][0]
                # TextContent has a "text" field with JSON string
                if isinstance(text_content, dict) and "text" in text_content:
                    return json.loads(text_content["text"])
        
        return result
    
    def list_tools(self) -> list:
        """List available MCP tools"""
        # MCP uses method without the "tools/" prefix
        response = self.send_request("tools/list", {})
        
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        
        result = response.get("result", {})
        # MCP returns {"tools": [...]}
        if isinstance(result, dict) and "tools" in result:
            return result["tools"]
        return result if isinstance(result, list) else []


def create_test_database() -> str:
    """Create a temporary test database with schema"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    conn = sqlite3.connect(db_path)
    
    # Create schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS policy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            conditions_json TEXT,
            actions_json TEXT,
            priority INTEGER DEFAULT 50,
            status TEXT DEFAULT 'active',
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            start_ts INTEGER NOT NULL,
            end_ts INTEGER NOT NULL,
            policy_hint TEXT,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            track_key TEXT NOT NULL,
            track_type TEXT NOT NULL,
            last_box_json TEXT,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            timestamp INTEGER NOT NULL,
            policy_name TEXT NOT NULL,
            evidence_json TEXT,
            delivered INTEGER DEFAULT 0
        )
    """)
    
    # Add some test data
    now = int(time.time())
    
    conn.execute("""
        INSERT INTO policy_rules (name, description, conditions_json, actions_json, priority, status, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("Test Policy", "Test policy for MCP", '{"label": {"equals": "person"}}', 
          '{"send_alert": {"message": "Test"}}', 60, "active", now, now))
    
    conn.execute("""
        INSERT INTO scheduled_event (name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("Test Event", "Test event", now - 3600, now + 3600, "test_hint", now, now))
    
    conn.execute("""
        INSERT INTO scene_tracks (camera_id, track_key, track_type, first_seen_ts, last_seen_ts, active)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (1, "person_123", "person", now - 60, now, 1))
    
    conn.commit()
    conn.close()
    
    return db_path


def test_mcp_server_startup():
    """Test that MCP server starts without errors"""
    print("\n=== Test: MCP Server Startup ===")
    
    db_path = create_test_database()
    server_script = os.path.join(PROJECT_ROOT, "apps", "policy-server", "mcp_server.py")
    
    try:
        client = MCPClient(server_script, db_path)
        client.start()
        
        print("✓ MCP server started successfully")
        
        client.stop()
        return True
        
    except Exception as e:
        print(f"✗ Server startup failed: {e}")
        return False
    finally:
        os.unlink(db_path)


def test_mcp_list_tools():
    """Test MCP tools/list protocol"""
    print("\n=== Test: MCP Protocol - tools/list ===")
    
    db_path = create_test_database()
    server_script = os.path.join(PROJECT_ROOT, "apps", "policy-server", "mcp_server.py")
    
    try:
        client = MCPClient(server_script, db_path)
        client.start()
        
        # List tools via MCP protocol
        tools = client.list_tools()
        
        print(f"✓ Received {len(tools)} tools from MCP server")
        
        # Verify expected tools
        tool_names = [tool.get("name") for tool in tools]
        expected_tools = [
            "list_policies", "get_policy", "create_policy",
            "list_events", "create_event", "active_events_now",
            "get_active_tracks", "query_scene_context"
        ]
        
        for expected in expected_tools:
            if expected in tool_names:
                print(f"  ✓ Found tool: {expected}")
            else:
                print(f"  ✗ Missing tool: {expected}")
                return False
        
        client.stop()
        return True
        
    except Exception as e:
        print(f"✗ tools/list failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.unlink(db_path)


def test_mcp_list_policies_tool():
    """Test calling list_policies tool via MCP protocol"""
    print("\n=== Test: MCP Tool Call - list_policies ===")
    
    db_path = create_test_database()
    server_script = os.path.join(PROJECT_ROOT, "apps", "policy-server", "mcp_server.py")
    
    try:
        client = MCPClient(server_script, db_path)
        client.start()
        
        # Call tool via MCP protocol
        result = client.call_tool("list_policies", {"status": "active"})
        
        print(f"✓ MCP tool call successful")
        print(f"  Response keys: {list(result.keys())}")
        print(f"  Policy count: {result.get('count', 0)}")
        
        # Validate response structure
        assert "count" in result, "Missing 'count' in response"
        assert "policies" in result, "Missing 'policies' in response"
        assert isinstance(result["policies"], list), "policies should be a list"
        assert result["count"] == 1, "Expected 1 policy"
        assert result["policies"][0]["name"] == "Test Policy"
        
        print("  ✓ Response structure valid")
        print(f"  ✓ Found policy: {result['policies'][0]['name']}")
        
        client.stop()
        return True
        
    except Exception as e:
        print(f"✗ list_policies tool call failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.unlink(db_path)


def test_mcp_list_events_tool():
    """Test calling list_events tool via MCP protocol"""
    print("\n=== Test: MCP Tool Call - list_events ===")
    
    db_path = create_test_database()
    server_script = os.path.join(PROJECT_ROOT, "apps", "policy-server", "mcp_server.py")
    
    try:
        client = MCPClient(server_script, db_path)
        client.start()
        
        # Call tool via MCP protocol
        result = client.call_tool("list_events", {"active_only": False})
        
        print(f"✓ MCP tool call successful")
        print(f"  Event count: {result.get('count', 0)}")
        
        # Validate response
        assert "count" in result, "Missing 'count' in response"
        assert "events" in result, "Missing 'events' in response"
        assert result["count"] == 1, "Expected 1 event"
        assert result["events"][0]["name"] == "Test Event"
        assert result["events"][0]["policy_hint"] == "test_hint"
        
        print(f"  ✓ Found event: {result['events'][0]['name']}")
        print(f"  ✓ Policy hint: {result['events'][0]['policy_hint']}")
        
        client.stop()
        return True
        
    except Exception as e:
        print(f"✗ list_events tool call failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.unlink(db_path)


def test_mcp_active_events_tool():
    """Test calling active_events_now tool via MCP protocol"""
    print("\n=== Test: MCP Tool Call - active_events_now ===")
    
    db_path = create_test_database()
    server_script = os.path.join(PROJECT_ROOT, "apps", "policy-server", "mcp_server.py")
    
    try:
        client = MCPClient(server_script, db_path)
        client.start()
        
        # Call tool via MCP protocol (should find active test event)
        result = client.call_tool("active_events_now", {})
        
        print(f"✓ MCP tool call successful")
        print(f"  Active event count: {result.get('count', 0)}")
        
        # Validate response
        assert "count" in result, "Missing 'count' in response"
        assert "events" in result, "Missing 'events' in response"
        assert result["count"] == 1, "Expected 1 active event"
        assert result["events"][0]["name"] == "Test Event"
        
        print(f"  ✓ Found active event: {result['events'][0]['name']}")
        
        client.stop()
        return True
        
    except Exception as e:
        print(f"✗ active_events_now tool call failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.unlink(db_path)


def test_mcp_get_active_tracks_tool():
    """Test calling get_active_tracks tool via MCP protocol"""
    print("\n=== Test: MCP Tool Call - get_active_tracks ===")
    
    db_path = create_test_database()
    server_script = os.path.join(PROJECT_ROOT, "apps", "policy-server", "mcp_server.py")
    
    try:
        client = MCPClient(server_script, db_path)
        client.start()
        
        # Call tool via MCP protocol
        result = client.call_tool("get_active_tracks", {"camera_id": 1})
        
        print(f"✓ MCP tool call successful")
        print(f"  Track count: {result.get('count', 0)}")
        
        # Validate response
        assert "count" in result, "Missing 'count' in response"
        assert "tracks" in result, "Missing 'tracks' in response"
        assert result["count"] == 1, "Expected 1 track"
        assert result["tracks"][0]["track_key"] == "person_123"
        
        print(f"  ✓ Found track: {result['tracks'][0]['track_key']}")
        
        client.stop()
        return True
        
    except Exception as e:
        print(f"✗ get_active_tracks tool call failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.unlink(db_path)


def test_mcp_create_event_tool():
    """Test calling create_event tool via MCP protocol"""
    print("\n=== Test: MCP Tool Call - create_event ===")
    
    db_path = create_test_database()
    server_script = os.path.join(PROJECT_ROOT, "apps", "policy-server", "mcp_server.py")
    
    try:
        client = MCPClient(server_script, db_path)
        client.start()
        
        now = int(time.time())
        
        # Call tool via MCP protocol
        result = client.call_tool("create_event", {
            "name": "New MCP Event",
            "start_ts": now + 100,
            "end_ts": now + 200,
            "description": "Created via MCP",
            "policy_hint": "mcp_test"
        })
        
        print(f"✓ MCP tool call successful")
        print(f"  Status: {result.get('status')}")
        
        # Validate response
        assert result["status"] == "created", "Expected status='created'"
        assert "event" in result, "Missing 'event' in response"
        assert result["event"]["name"] == "New MCP Event"
        assert result["event"]["policy_hint"] == "mcp_test"
        
        print(f"  ✓ Created event ID: {result['event']['id']}")
        print(f"  ✓ Event name: {result['event']['name']}")
        
        # Verify it was actually created
        list_result = client.call_tool("list_events", {})
        assert list_result["count"] == 2, "Should have 2 events now"
        
        print(f"  ✓ Event persisted (total: {list_result['count']})")
        
        client.stop()
        return True
        
    except Exception as e:
        print(f"✗ create_event tool call failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.unlink(db_path)


def main():
    """Run all MCP protocol tests"""
    print("=" * 60)
    print("MCP Protocol Integration Tests")
    print("Testing the FULL MCP stack (protocol + handlers + services)")
    print("=" * 60)
    
    tests = [
        ("MCP Server Startup", test_mcp_server_startup),
        ("MCP tools/list Protocol", test_mcp_list_tools),
        ("MCP Tool: list_policies", test_mcp_list_policies_tool),
        ("MCP Tool: list_events", test_mcp_list_events_tool),
        ("MCP Tool: active_events_now", test_mcp_active_events_tool),
        ("MCP Tool: get_active_tracks", test_mcp_get_active_tracks_tool),
        ("MCP Tool: create_event", test_mcp_create_event_tool),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All MCP protocol tests passed!")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
