#!/usr/bin/env python3
"""
Voice Command Management CLI

Utility for managing voiceprint mappings and viewing voice command history.

Usage:
    python voice_cli.py mappings list
    python voice_cli.py mappings create <voiceprint_id> <person_id> [notes]
    python voice_cli.py commands list [--limit 20]
    python voice_cli.py commands show <correlation_id>
    python voice_cli.py tools list [--voice-only]
"""

import sys
import os
import sqlite3
import json
from typing import Optional
import argparse
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.getenv("ECHOBELL_DB_PATH", os.path.join(PROJECT_ROOT, "echoBell.db"))


def get_db():
    """Get database connection"""
    return sqlite3.connect(DB_PATH)


def list_mappings():
    """List all voiceprint to person mappings"""
    conn = get_db()
    cursor = conn.execute("""
        SELECT 
            vpm.id,
            vpm.voiceprint_user_id,
            vpm.trusted_person_id,
            tp.name as person_name,
            datetime(vpm.created_ts, 'unixepoch') as created_at,
            vpm.notes
        FROM voiceprint_person_mapping vpm
        LEFT JOIN trusted_person tp ON vpm.trusted_person_id = tp.trusted_id
        ORDER BY vpm.created_ts DESC
    """)
    
    print("\nVoiceprint Mappings:")
    print("-" * 80)
    print(f"{'ID':<5} {'Voiceprint ID':<20} {'Person':<20} {'Created':<20} {'Notes':<20}")
    print("-" * 80)
    
    count = 0
    for row in cursor.fetchall():
        mapping_id, voiceprint_id, person_id, person_name, created_at, notes = row
        print(f"{mapping_id:<5} {voiceprint_id:<20} {person_name or 'Unknown':<20} {created_at:<20} {notes or '':<20}")
        count += 1
    
    print(f"\nTotal: {count} mapping(s)")
    conn.close()


def create_mapping(voiceprint_id: str, person_id: int, notes: Optional[str] = None):
    """Create a voiceprint to person mapping"""
    conn = get_db()
    
    # Verify person exists
    cursor = conn.execute("SELECT name FROM trusted_person WHERE trusted_id = ?", (person_id,))
    row = cursor.fetchone()
    
    if not row:
        print(f"Error: Trusted person {person_id} not found")
        conn.close()
        return False
    
    person_name = row[0]
    
    # Create mapping
    now = int(datetime.now().timestamp())
    try:
        conn.execute("""
            INSERT INTO voiceprint_person_mapping (voiceprint_user_id, trusted_person_id, created_ts, updated_ts, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (voiceprint_id, person_id, now, now, notes))
        conn.commit()
        print(f"✓ Created mapping: '{voiceprint_id}' → {person_name} (ID: {person_id})")
        if notes:
            print(f"  Notes: {notes}")
        return True
    except sqlite3.IntegrityError:
        print(f"Error: Mapping for '{voiceprint_id}' already exists")
        return False
    finally:
        conn.close()


def list_commands(limit: int = 20):
    """List recent voice commands"""
    conn = get_db()
    cursor = conn.execute("""
        SELECT 
            vc.id,
            vc.correlation_id,
            vc.text,
            vc.voiceprint_user_id,
            tp.name as person_name,
            vc.voiceprint_confidence,
            vc.auth_result,
            vc.llm_used,
            datetime(vc.timestamp, 'unixepoch') as timestamp,
            vc.processing_time_ms
        FROM voice_commands vc
        LEFT JOIN trusted_person tp ON vc.trusted_person_id = tp.trusted_id
        ORDER BY vc.timestamp DESC
        LIMIT ?
    """, (limit,))
    
    print(f"\nRecent Voice Commands (limit: {limit}):")
    print("-" * 120)
    print(f"{'ID':<5} {'Timestamp':<20} {'User':<15} {'Text':<30} {'Auth':<10} {'LLM':<5} {'Time(ms)':<10}")
    print("-" * 120)
    
    count = 0
    for row in cursor.fetchall():
        cmd_id, corr_id, text, vp_id, person_name, confidence, auth, llm, ts, proc_time = row
        user_display = person_name if person_name else vp_id or "Unknown"
        text_display = text[:27] + "..." if len(text) > 30 else text
        llm_display = "Yes" if llm else "No"
        print(f"{cmd_id:<5} {ts:<20} {user_display:<15} {text_display:<30} {auth:<10} {llm_display:<5} {proc_time or 0:<10}")
        count += 1
    
    if count == 0:
        print("No voice commands found")
    else:
        print(f"\nTotal: {count} command(s)")
    
    conn.close()


def show_command(correlation_id: str):
    """Show detailed information about a voice command"""
    conn = get_db()
    cursor = conn.execute("""
        SELECT 
            vc.id,
            vc.correlation_id,
            vc.echonet_event_id,
            vc.session_id,
            vc.voiceprint_user_id,
            vc.voiceprint_confidence,
            tp.name as person_name,
            vc.text,
            vc.speech_confidence,
            vc.mode,
            vc.source_device,
            vc.room,
            datetime(vc.timestamp, 'unixepoch') as timestamp,
            datetime(vc.received_ts, 'unixepoch') as received_at,
            vc.policy_matched,
            vc.llm_used,
            vc.response_text,
            vc.actions_taken,
            vc.auth_result,
            vc.auth_reason,
            vc.processing_time_ms
        FROM voice_commands vc
        LEFT JOIN trusted_person tp ON vc.trusted_person_id = tp.trusted_id
        WHERE vc.correlation_id = ?
    """, (correlation_id,))
    
    row = cursor.fetchone()
    if not row:
        print(f"Error: Voice command not found: {correlation_id}")
        conn.close()
        return
    
    (cmd_id, corr_id, echonet_id, session_id, vp_id, vp_conf, person_name,
     text, speech_conf, mode, source, room, ts, received, policy, llm,
     response, actions, auth_result, auth_reason, proc_time) = row
    
    print(f"\nVoice Command Details:")
    print("=" * 80)
    print(f"ID:                {cmd_id}")
    print(f"Correlation ID:    {corr_id}")
    print(f"Echonet Event ID:  {echonet_id}")
    print(f"Session ID:        {session_id or 'N/A'}")
    print()
    print(f"Speaker:")
    print(f"  Voiceprint ID:   {vp_id or 'Unknown'}")
    print(f"  Person:          {person_name or 'Not mapped'}")
    print(f"  Confidence:      {vp_conf:.2f}" if vp_conf else "  Confidence:      N/A")
    print()
    print(f"Command:")
    print(f"  Text:            {text}")
    print(f"  Mode:            {mode}")
    print(f"  Speech Conf:     {speech_conf:.2f}" if speech_conf else "  Speech Conf:     N/A")
    print(f"  Source:          {source}")
    print(f"  Room:            {room or 'N/A'}")
    print()
    print(f"Processing:")
    print(f"  Timestamp:       {ts}")
    print(f"  Received:        {received}")
    print(f"  Auth Result:     {auth_result}")
    print(f"  Auth Reason:     {auth_reason or 'N/A'}")
    print(f"  Policy Matched:  {policy or 'None (LLM fallback)'}")
    print(f"  LLM Used:        {'Yes' if llm else 'No'}")
    print(f"  Processing Time: {proc_time}ms" if proc_time else "  Processing Time: N/A")
    print()
    print(f"Response:")
    print(f"  {response or 'No response'}")
    print()
    if actions:
        print(f"Actions Taken:")
        try:
            actions_list = json.loads(actions)
            for action in actions_list:
                print(f"  - {action}")
        except:
            print(f"  {actions}")
    else:
        print("Actions Taken:     None")
    
    conn.close()


def list_tools(voice_only: bool = False):
    """List MCP tool permissions"""
    conn = get_db()
    
    query = """
        SELECT tool_name, voice_enabled, requires_confidence, requires_2fa, security_level, notes
        FROM mcp_tool_permissions
    """
    
    if voice_only:
        query += " WHERE voice_enabled = 1"
    
    query += " ORDER BY security_level, tool_name"
    
    cursor = conn.execute(query)
    
    print(f"\nMCP Tool Permissions {'(Voice-Enabled Only)' if voice_only else ''}:")
    print("-" * 100)
    print(f"{'Tool Name':<30} {'Voice':<8} {'Min Conf':<10} {'2FA':<6} {'Security':<10} {'Notes':<30}")
    print("-" * 100)
    
    count = 0
    for row in cursor.fetchall():
        tool_name, voice_enabled, min_conf, requires_2fa, security, notes = row
        voice_display = "✓" if voice_enabled else "✗"
        twofa_display = "Yes" if requires_2fa else "No"
        print(f"{tool_name:<30} {voice_display:<8} {min_conf:<10.2f} {twofa_display:<6} {security:<10} {notes or '':<30}")
        count += 1
    
    if count == 0:
        print("No tools found")
    else:
        print(f"\nTotal: {count} tool(s)")
    
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Voice Command Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Mappings commands
    mappings_parser = subparsers.add_parser("mappings", help="Manage voiceprint mappings")
    mappings_sub = mappings_parser.add_subparsers(dest="action")
    
    mappings_sub.add_parser("list", help="List all mappings")
    
    create_parser = mappings_sub.add_parser("create", help="Create a new mapping")
    create_parser.add_argument("voiceprint_id", help="Voiceprint user ID")
    create_parser.add_argument("person_id", type=int, help="Trusted person ID")
    create_parser.add_argument("notes", nargs="?", help="Optional notes")
    
    # Commands commands
    commands_parser = subparsers.add_parser("commands", help="View voice commands")
    commands_sub = commands_parser.add_subparsers(dest="action")
    
    list_cmd_parser = commands_sub.add_parser("list", help="List recent commands")
    list_cmd_parser.add_argument("--limit", type=int, default=20, help="Number of commands to show")
    
    show_parser = commands_sub.add_parser("show", help="Show command details")
    show_parser.add_argument("correlation_id", help="Correlation ID")
    
    # Tools commands
    tools_parser = subparsers.add_parser("tools", help="View MCP tool permissions")
    tools_sub = tools_parser.add_subparsers(dest="action")
    
    list_tools_parser = tools_sub.add_parser("list", help="List tool permissions")
    list_tools_parser.add_argument("--voice-only", action="store_true", help="Only show voice-enabled tools")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Handle commands
    if args.command == "mappings":
        if args.action == "list":
            list_mappings()
        elif args.action == "create":
            create_mapping(args.voiceprint_id, args.person_id, args.notes)
        else:
            mappings_parser.print_help()
    
    elif args.command == "commands":
        if args.action == "list":
            list_commands(args.limit)
        elif args.action == "show":
            show_command(args.correlation_id)
        else:
            commands_parser.print_help()
    
    elif args.command == "tools":
        if args.action == "list":
            list_tools(args.voice_only)
        else:
            tools_parser.print_help()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
