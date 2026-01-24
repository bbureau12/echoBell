"""
Policy Rules Service - Database CRUD for dynamic policy management
Enables API-driven policy configuration without editing YAML files.
"""

import json
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime


class PolicyRulesService:
    """Manage policy rules in database."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def get_all_policies(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """
        Get all policies from database, sorted by priority (descending).
        
        Args:
            enabled_only: If True, only return enabled policies
            
        Returns:
            List of policy dicts with parsed JSON fields
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = """
                SELECT 
                    id, name, description, enabled, priority,
                    conditions_json, actions_json, variables_json,
                    created_ts, updated_ts, created_by, tags, version
                FROM policy_rules
            """
            
            if enabled_only:
                query += " WHERE enabled = 1"
            
            query += " ORDER BY priority DESC, id ASC"
            
            rows = conn.execute(query).fetchall()
            
            policies = []
            for row in rows:
                policy = dict(row)
                
                # Parse JSON fields
                policy['conditions'] = json.loads(policy.pop('conditions_json'))
                policy['actions'] = json.loads(policy.pop('actions_json'))
                
                if policy['variables_json']:
                    policy['variables'] = json.loads(policy.pop('variables_json'))
                else:
                    policy.pop('variables_json')
                    policy['variables'] = {}
                
                policies.append(policy)
            
            return policies
    
    def get_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        """Get a single policy by ID."""
        policies = self.get_all_policies()
        for policy in policies:
            if policy['id'] == policy_id:
                return policy
        return None
    
    def create_policy(
        self,
        policy_id: str,
        name: str,
        conditions: Dict[str, Any],
        actions: List[Dict[str, Any]],
        description: str = "",
        enabled: bool = True,
        priority: int = 50,
        variables: Optional[Dict[str, Any]] = None,
        created_by: str = "api",
        tags: str = ""
    ) -> Dict[str, Any]:
        """
        Create a new policy in the database.
        
        Args:
            policy_id: Unique policy identifier
            name: Human-readable policy name
            conditions: Condition tree (dict)
            actions: List of action dicts
            description: What the policy does
            enabled: Whether policy is active
            priority: Evaluation priority (higher = first)
            variables: Variable definitions (optional)
            created_by: Who created it (api, user, system)
            tags: Space-separated tags
            
        Returns:
            Created policy dict
            
        Raises:
            ValueError: If policy_id already exists
        """
        # Check if exists
        existing = self.get_policy(policy_id)
        if existing:
            raise ValueError(f"Policy with id '{policy_id}' already exists")
        
        now_ts = int(datetime.now().timestamp())
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO policy_rules (
                    id, name, description, enabled, priority,
                    conditions_json, actions_json, variables_json,
                    created_ts, updated_ts, created_by, tags, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                policy_id,
                name,
                description,
                1 if enabled else 0,
                priority,
                json.dumps(conditions),
                json.dumps(actions),
                json.dumps(variables) if variables else None,
                now_ts,
                now_ts,
                created_by,
                tags,
                1
            ))
            conn.commit()
        
        return self.get_policy(policy_id)
    
    def update_policy(
        self,
        policy_id: str,
        name: Optional[str] = None,
        conditions: Optional[Dict[str, Any]] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        description: Optional[str] = None,
        enabled: Optional[bool] = None,
        priority: Optional[int] = None,
        variables: Optional[Dict[str, Any]] = None,
        tags: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing policy (partial update).
        
        Args:
            policy_id: Policy to update
            **kwargs: Fields to update (only non-None values updated)
            
        Returns:
            Updated policy dict
            
        Raises:
            ValueError: If policy doesn't exist
        """
        existing = self.get_policy(policy_id)
        if not existing:
            raise ValueError(f"Policy '{policy_id}' not found")
        
        now_ts = int(datetime.now().timestamp())
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        
        if conditions is not None:
            updates.append("conditions_json = ?")
            params.append(json.dumps(conditions))
        
        if actions is not None:
            updates.append("actions_json = ?")
            params.append(json.dumps(actions))
        
        if variables is not None:
            updates.append("variables_json = ?")
            params.append(json.dumps(variables))
        
        if tags is not None:
            updates.append("tags = ?")
            params.append(tags)
        
        # Always update timestamp and version
        updates.append("updated_ts = ?")
        params.append(now_ts)
        updates.append("version = version + 1")
        
        params.append(policy_id)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                UPDATE policy_rules
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            conn.commit()
        
        return self.get_policy(policy_id)
    
    def delete_policy(self, policy_id: str) -> bool:
        """
        Delete a policy by ID.
        
        Returns:
            True if deleted, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM policy_rules WHERE id = ?",
                (policy_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def toggle_policy(self, policy_id: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a policy."""
        return self.update_policy(policy_id, enabled=enabled)
    
    def log_execution(
        self,
        policy_id: str,
        event_id: Optional[str] = None,
        track_key: Optional[str] = None,
        track_type: Optional[str] = None,
        camera_id: Optional[int] = None,
        matched_conditions: Optional[Dict[str, Any]] = None,
        executed_actions: Optional[List[Dict[str, Any]]] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ):
        """
        Log a policy execution to audit trail.
        
        Args:
            policy_id: Which policy executed
            event_id: Associated visitor event (optional)
            track_key: plate_hmac or visitor_id
            track_type: 'vehicle' or 'person'
            camera_id: Which camera triggered
            matched_conditions: Which conditions were true
            executed_actions: Which actions ran
            success: Whether execution succeeded
            error_message: Error details if failed
        """
        now_ts = int(datetime.now().timestamp())
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO policy_executions (
                    policy_id, event_id, track_key, track_type, camera_id,
                    matched_conditions, executed_actions,
                    execution_ts, success, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                policy_id,
                event_id,
                track_key,
                track_type,
                camera_id,
                json.dumps(matched_conditions) if matched_conditions else None,
                json.dumps(executed_actions) if executed_actions else None,
                now_ts,
                1 if success else 0,
                error_message
            ))
            conn.commit()
    
    def get_execution_history(
        self,
        policy_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get policy execution history.
        
        Args:
            policy_id: Filter by specific policy (None = all)
            limit: Max results to return
            
        Returns:
            List of execution records
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = """
                SELECT 
                    pe.*,
                    pr.name as policy_name
                FROM policy_executions pe
                LEFT JOIN policy_rules pr ON pe.policy_id = pr.id
            """
            
            params = []
            if policy_id:
                query += " WHERE pe.policy_id = ?"
                params.append(policy_id)
            
            query += " ORDER BY pe.execution_ts DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            
            executions = []
            for row in rows:
                execution = dict(row)
                
                # Parse JSON fields
                if execution['matched_conditions']:
                    execution['matched_conditions'] = json.loads(execution['matched_conditions'])
                if execution['executed_actions']:
                    execution['executed_actions'] = json.loads(execution['executed_actions'])
                
                executions.append(execution)
            
            return executions
    
    def import_from_yaml(self, yaml_policies: List[Dict[str, Any]], overwrite: bool = False):
        """
        Import policies from YAML config into database.
        
        Args:
            yaml_policies: List of policy dicts from YAML
            overwrite: If True, update existing policies; if False, skip existing
        """
        for policy in yaml_policies:
            policy_id = policy['id']
            existing = self.get_policy(policy_id)
            
            if existing and not overwrite:
                continue  # Skip existing
            
            if existing and overwrite:
                # Update existing
                self.update_policy(
                    policy_id=policy_id,
                    name=policy.get('name', policy_id),
                    description=policy.get('description', ''),
                    enabled=policy.get('enabled', True),
                    priority=policy.get('priority', 50),
                    conditions=policy['conditions'],
                    actions=policy['actions'],
                    variables=policy.get('variables')
                )
            else:
                # Create new
                self.create_policy(
                    policy_id=policy_id,
                    name=policy.get('name', policy_id),
                    description=policy.get('description', ''),
                    enabled=policy.get('enabled', True),
                    priority=policy.get('priority', 50),
                    conditions=policy['conditions'],
                    actions=policy['actions'],
                    variables=policy.get('variables'),
                    created_by='yaml_import'
                )
