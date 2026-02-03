# EchoBell MCP Server Setup Guide

## What is MCP?

The Model Context Protocol (MCP) allows AI assistants like Claude to interact with your local tools and data. The echoBell MCP server exposes your policy management, scene tracking, scheduled events, and quiet hours features to Claude through natural language.

## Prerequisites

1. **Python 3.11+** with echoBell dependencies installed
2. **Claude Desktop** (download from: https://claude.ai/download)
3. **MCP SDK**: Already installed if you ran `pip install -r requirements.txt`

## Quick Start

### 1. Verify MCP Server Works

Test the server manually:

```bash
cd D:\Projects\echoBell\echoBell
python central\policy-server\mcp_server.py
```

You should see the server start without errors. Press `Ctrl+C` to stop.

### 2. Configure Claude Desktop

#### Windows

1. Open file explorer and navigate to: `%APPDATA%\Claude\`
2. Create or edit `claude_desktop_config.json`
3. Add this configuration:

```json
{
  "mcpServers": {
    "echobell": {
      "command": "python",
      "args": ["D:\\Projects\\echoBell\\echoBell\\central\\policy-server\\mcp_server.py"],
      "env": {
        "ECHOBELL_DB_PATH": "D:\\Projects\\echoBell\\echoBell\\echoBell.db"
      }
    }
  }
}
```

**Important:** Adjust the paths to match your actual installation location!

#### macOS/Linux

1. Open terminal and navigate to: `~/.config/Claude/`
2. Create or edit `claude_desktop_config.json`
3. Add this configuration:

```json
{
  "mcpServers": {
    "echobell": {
      "command": "python3",
      "args": ["/path/to/echoBell/central/policy-server/mcp_server.py"],
      "env": {
        "ECHOBELL_DB_PATH": "/path/to/echoBell/echoBell.db"
      }
    }
  }
}
```

### 3. Restart Claude Desktop

Close and reopen Claude Desktop completely for the configuration to take effect.

### 4. Verify Connection

In Claude Desktop, look for a 🔌 icon or "Connected tools" indicator. You should see "echobell" listed.

Ask Claude: **"What tools do you have available from echobell?"**

Claude should list 19 tools including quiet hours management.

## Available Tools

### Policy Management (6 tools)
- `list_policies` - List all policy rules
- `get_policy` - Get policy details by ID  
- `create_policy` - Create new policy rule
- `update_policy` - Update existing policy
- `delete_policy` - Delete a policy
- `evaluate_policy` - Test policy conditions against evidence

### Quiet Hours Management (6 tools)
- `list_quiet_hours` - List quiet hour schedules
- `get_quiet_hour` - Get specific quiet hour by ID
- `create_quiet_hour` - Create new quiet hour schedule
- `update_quiet_hour` - Update quiet hour schedule
- `delete_quiet_hour` - Delete quiet hour schedule
- `is_quiet_time` - Check if current/specified time is quiet

### Scene Tracking (3 tools)
- `get_active_tracks` - Get active scene tracks
- `query_scene_context` - Query recent scene context
- `get_visit_history` - Get visit history

### Scheduled Events (3 tools)
- `list_events` - List scheduled events
- `create_event` - Create scheduled event
- `active_events_now` - Get currently active events

### Alert History (1 tool)
- `get_alert_history` - Get recent alert history

## Usage Examples

### Example 1: Create Quiet Hours

**You say to Claude:**
> "Create quiet hours for weeknights from 10pm to 7am called 'Sleep'"

**Claude will:**
1. Call `create_quiet_hour` 5 times (Monday-Friday)
2. Set start_time="22:00", end_time="07:00"
3. Confirm creation with the IDs

### Example 2: Check Current Quiet Status

**You say to Claude:**
> "Is it currently quiet hours?"

**Claude will:**
1. Call `is_quiet_time` with no timestamp (uses current time)
2. Tell you yes/no and which quiet hour is active

### Example 3: List All Policies

**You say to Claude:**
> "Show me all active policies"

**Claude will:**
1. Call `list_policies` with status="active"
2. Display the policies in a readable format

### Example 4: Create Policy with Quiet Hours

**You say to Claude:**
> "Create a policy that suppresses TTS during quiet hours when a person is detected"

**Claude will:**
1. Call `create_policy` with appropriate conditions:
   - `is_quiet_hours: true`
   - `evidence_exists: {source: "vision", feature: "person_detected"}`
2. Set actions to suppress TTS
3. Confirm creation

### Example 5: Manage Quiet Hours by Day

**You say to Claude:**
> "What quiet hours do I have on Saturdays?"

**Claude will:**
1. Call `list_quiet_hours` 
2. Filter results where weekday=5 (Saturday in ISO format)
3. Display the schedule(s)

## Troubleshooting

### Claude doesn't show echobell tools

**Check:**
1. ✅ Config file is in correct location (`%APPDATA%\Claude\claude_desktop_config.json`)
2. ✅ JSON syntax is valid (use a JSON validator)
3. ✅ Paths are absolute and correct
4. ✅ Claude Desktop was fully restarted
5. ✅ Check Claude logs: `%APPDATA%\Claude\logs\`

### MCP server fails to start

**Check:**
1. ✅ Python is in PATH
2. ✅ All dependencies installed (`pip install mcp`)
3. ✅ Database path exists
4. ✅ Run manually: `python central\policy-server\mcp_server.py`

### Tools execute but fail

**Check:**
1. ✅ Database exists at specified path
2. ✅ Database has required tables (run migrations)
3. ✅ Check server logs in Claude Desktop logs folder

## Advanced Configuration

### Using Virtual Environment

If echoBell uses a virtual environment:

```json
{
  "mcpServers": {
    "echobell": {
      "command": "D:\\Projects\\echoBell\\echoBell\\.venv-vision\\Scripts\\python.exe",
      "args": ["D:\\Projects\\echoBell\\echoBell\\central\\policy-server\\mcp_server.py"],
      "env": {
        "ECHOBELL_DB_PATH": "D:\\Projects\\echoBell\\echoBell\\echoBell.db"
      }
    }
  }
}
```

### Custom Database Location

Change the `ECHOBELL_DB_PATH` environment variable:

```json
"env": {
  "ECHOBELL_DB_PATH": "C:\\custom\\path\\to\\database.db"
}
```

### Multiple Database Profiles

You can configure multiple MCP servers for different databases:

```json
{
  "mcpServers": {
    "echobell-production": {
      "command": "python",
      "args": ["D:\\Projects\\echoBell\\echoBell\\central\\policy-server\\mcp_server.py"],
      "env": {
        "ECHOBELL_DB_PATH": "D:\\echoBell\\production\\echoBell.db"
      }
    },
    "echobell-testing": {
      "command": "python",
      "args": ["D:\\Projects\\echoBell\\echoBell\\central\\policy-server\\mcp_server.py"],
      "env": {
        "ECHOBELL_DB_PATH": "D:\\echoBell\\test\\echoBell.db"
      }
    }
  }
}
```

## Security Considerations

⚠️ **Important:**

- The MCP server has **full access** to your echoBell database
- Claude can create, modify, and delete policies, quiet hours, and events
- Only configure MCP for databases you trust Claude to manage
- Review Claude's actions before approving database changes
- Keep backups of your database

## Testing MCP Tools

You can test individual tools from the command line using the test suite:

```bash
# Test all MCP quiet hours tools
pytest tests/test_mcp_quiet_hours.py -v

# Test specific tool
pytest tests/test_mcp_quiet_hours.py::test_create_quiet_hour -v
```

## Example Conversation Flow

```
You: "Set up quiet hours for my household"

Claude: "I can help you set up quiet hours. Could you tell me:
1. Which days of the week?
2. What time should quiet hours start?
3. What time should they end?"

You: "Weeknights 10pm to 7am, weekends midnight to 9am"

Claude: [Calls create_quiet_hour 7 times]
"I've created quiet hours:
- Monday-Friday: 22:00 to 07:00 (IDs: 1-5)
- Saturday-Sunday: 00:00 to 09:00 (IDs: 6-7)

Would you like me to create a policy to suppress notifications during these hours?"

You: "Yes, suppress TTS but allow Telegram notifications"

Claude: [Calls create_policy]
"I've created policy 'quiet_hours_suppress' (ID: 10) that will:
- Trigger during quiet hours when person detected
- Send silent Telegram notification
- Suppress TTS announcements"
```

## Next Steps

1. ✅ Configure Claude Desktop with your echoBell paths
2. ✅ Restart Claude Desktop
3. ✅ Verify tools are available
4. ✅ Try creating a simple quiet hour schedule
5. ✅ Experiment with policy creation through Claude

## Resources

- **MCP Documentation:** https://modelcontextprotocol.io/
- **Claude Desktop:** https://claude.ai/download
- **EchoBell Policy Docs:** `docs/POLICY_REFERENCE.md`
- **Quiet Hours Service:** `packages/data/quiet_hours_service.py`

## Support

If you encounter issues:

1. Check Claude Desktop logs: `%APPDATA%\Claude\logs\`
2. Test MCP server manually: `python central\policy-server\mcp_server.py`
3. Verify database exists and has migrations applied
4. Check MCP test suite: `pytest tests/test_mcp_quiet_hours.py -v`

---

**Last Updated:** February 1, 2026  
**MCP Version:** stdio  
**echoBell Version:** See `VERSION` file
