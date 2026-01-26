"""
Policy Rule Engine for EchoBell
Evaluates policy rules against evidence and context.
Supports both YAML files (for seeding) and database storage (for dynamic updates).
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import yaml
import sqlite3
from datetime import datetime, time as datetime_time
import os
import re


@dataclass
class PolicyMatch:
    """Result of policy evaluation"""
    policy_id: str
    policy_name: str
    priority: int
    actions: List[Dict[str, Any]]
    variables: Dict[str, str]  # Resolved variable values


class PolicyEvaluator:
    """Evaluates policy rules against evidence and context"""
    
    def __init__(
        self, 
        conn: sqlite3.Connection, 
        policy_file: Optional[str] = None,
        use_database: bool = True
    ):
        """
        Initialize policy evaluator.
        
        Args:
            conn: Database connection
            policy_file: Path to YAML config (optional, for seeding)
            use_database: If True, load from database; if False, use YAML only
        """
        self.conn = conn
        self.use_database = use_database
        
        if use_database:
            # Load policies from database
            self.policies = self._load_from_database()
            self.variable_defs = {}  # Variables come from individual policies
        elif policy_file and os.path.exists(policy_file):
            # Fallback to YAML
            with open(policy_file, 'r') as f:
                self.config = yaml.safe_load(f)
            self.policies = self.config.get('policies', [])
            self.variable_defs = self.config.get('variables', {})
        else:
            self.policies = []
            self.variable_defs = {}
    
    def _load_from_database(self) -> List[Dict[str, Any]]:
        """Load enabled policies from database, sorted by priority"""
        from packages.policy.policy_service import PolicyRulesService
        
        # Get db_path from connection (hacky but works)
        db_path = self.conn.execute("PRAGMA database_list").fetchone()[2]
        service = PolicyRulesService(db_path)
        
        return service.get_all_policies(enabled_only=True)
    
    def evaluate_all(
        self,
        evidence: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> List[PolicyMatch]:
        """
        Evaluate all enabled policies against evidence.
        
        Args:
            evidence: List of evidence dicts with {source, feature, value, conf}
            context: Additional context (camera_id, track_key, track_duration_seconds, etc.)
        
        Returns:
            List of matching policies, sorted by priority (highest first)
        """
        matches = []
        
        for policy in self.policies:
            if not policy.get('enabled', True):
                continue
            
            if self._evaluate_conditions(policy['conditions'], evidence, context):
                # Resolve variables
                variables = self._resolve_variables(evidence, context)
                
                matches.append(PolicyMatch(
                    policy_id=policy['id'],
                    policy_name=policy['name'],
                    priority=policy.get('priority', 10),
                    actions=policy['actions'],
                    variables=variables
                ))
        
        # Sort by priority (highest first)
        matches.sort(key=lambda m: m.priority, reverse=True)
        return matches
    
    def _evaluate_conditions(
        self,
        conditions: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> bool:
        """Recursively evaluate condition tree"""
        
        # AND logic
        if 'all' in conditions:
            return all(
                self._evaluate_condition(cond, evidence, context)
                for cond in conditions['all']
            )
        
        # OR logic
        if 'any' in conditions:
            return any(
                self._evaluate_condition(cond, evidence, context)
                for cond in conditions['any']
            )
        
        # NOT logic
        if 'not' in conditions:
            return not self._evaluate_condition(conditions['not'], evidence, context)
        
        # Single condition
        return self._evaluate_condition(conditions, evidence, context)
    
    def _evaluate_condition(
        self,
        condition: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> bool:
        """Evaluate a single condition"""
        
        # Nested boolean logic
        if 'all' in condition or 'any' in condition or 'not' in condition:
            return self._evaluate_conditions(condition, evidence, context)
        
        # Evidence checks
        if 'evidence_exists' in condition:
            return self._check_evidence_exists(condition['evidence_exists'], evidence)
        
        if 'evidence_missing' in condition:
            return not self._check_evidence_exists(condition['evidence_missing'], evidence)
        
        if 'evidence_value_contains' in condition:
            return self._check_evidence_value_contains(condition['evidence_value_contains'], evidence)
        
        if 'evidence_value_gt' in condition:
            return self._check_evidence_value_gt(condition['evidence_value_gt'], evidence)
        
        if 'evidence_value_lt' in condition:
            return self._check_evidence_value_lt(condition['evidence_value_lt'], evidence)
        
        if 'evidence_value_eq' in condition:
            return self._check_evidence_value_eq(condition['evidence_value_eq'], evidence)
        
        # Trust registry checks
        if 'trust_check' in condition:
            return self._check_trust(condition['trust_check'], evidence, context)
        
        # Track duration checks
        if 'track_duration_gt' in condition:
            duration = context.get('track_duration_seconds', 0)
            return duration > condition['track_duration_gt']
        
        if 'track_duration_lt' in condition:
            duration = context.get('track_duration_seconds', 0)
            return duration < condition['track_duration_lt']
        
        # Alert history checks
        if 'no_recent_alert' in condition:
            return self._check_no_recent_alert(condition['no_recent_alert'], context)
        
        if 'alert_sent_within' in condition:
            return self._check_alert_sent_within(condition['alert_sent_within'], context)
        
        # Time checks
        if 'time_between' in condition:
            return self._check_time_between(condition['time_between'])
        
        if 'day_of_week' in condition:
            return self._check_day_of_week(condition['day_of_week'])
        
        # Scheduled event checks
        if 'active_event' in condition:
            return self._check_active_event(condition['active_event'], context)
        
        if 'no_active_event' in condition:
            return not self._check_active_event(condition['no_active_event'], context)
        
        # Future: delivery/appointment checks
        if 'no_expected_delivery' in condition:
            return True  # TODO: Implement delivery schedule check
        
        if 'no_scheduled_appointment' in condition:
            return True  # TODO: Implement appointment calendar check
        
        return False
    
    def _check_evidence_exists(self, spec: Dict[str, str], evidence: List[Dict]) -> bool:
        """Check if evidence with source/feature exists"""
        source = spec.get('source')
        feature = spec.get('feature')
        value = spec.get('value')
        
        for e in evidence:
            if e.get('source') == source and e.get('feature') == feature:
                if value is None:
                    return True
                if str(e.get('value')) == str(value):
                    return True
        return False
    
    def _check_evidence_value_contains(self, spec: Dict[str, str], evidence: List[Dict]) -> bool:
        """Check if evidence value contains substring"""
        source = spec.get('source')
        feature = spec.get('feature')
        contains = spec.get('contains', '')
        
        for e in evidence:
            if e.get('source') == source and e.get('feature') == feature:
                value = str(e.get('value', ''))
                if contains.lower() in value.lower():
                    return True
        return False
    
    def _check_evidence_value_gt(self, spec: Dict[str, Any], evidence: List[Dict]) -> bool:
        """Check if numeric evidence value > threshold"""
        source = spec.get('source')
        feature = spec.get('feature')
        threshold = spec.get('threshold', 0)
        
        for e in evidence:
            if e.get('source') == source and e.get('feature') == feature:
                try:
                    # Extract numeric value (e.g., "141.4px" → 141.4)
                    value_str = str(e.get('value', ''))
                    value_num = float(re.findall(r'[\d.]+', value_str)[0])
                    return value_num > threshold
                except (IndexError, ValueError):
                    return False
        return False
    
    def _check_evidence_value_lt(self, spec: Dict[str, Any], evidence: List[Dict]) -> bool:
        """Check if numeric evidence value < threshold"""
        source = spec.get('source')
        feature = spec.get('feature')
        threshold = spec.get('threshold', 0)
        
        for e in evidence:
            if e.get('source') == source and e.get('feature') == feature:
                try:
                    value_str = str(e.get('value', ''))
                    value_num = float(re.findall(r'[\d.]+', value_str)[0])
                    return value_num < threshold
                except (IndexError, ValueError):
                    return False
        return False
    
    def _check_evidence_value_eq(self, spec: Dict[str, Any], evidence: List[Dict]) -> bool:
        """Check if evidence value equals expected"""
        source = spec.get('source')
        feature = spec.get('feature')
        expected = spec.get('expected')
        
        for e in evidence:
            if e.get('source') == source and e.get('feature') == feature:
                return str(e.get('value')) == str(expected)
        return False
    
    def _check_trust(self, spec: Dict[str, Any], evidence: List[Dict], context: Dict) -> bool:
        """Check trust registry (trusted_person, trusted_plates)"""
        table = spec.get('table')  # 'trusted_person' or 'trusted_plates'
        match_field = spec.get('match_field', 'visitor_id')  # Field to match from context
        exists = spec.get('exists', True)  # True = must exist, False = must NOT exist
        
        # Get match value from context or evidence
        match_value = context.get(match_field)
        if not match_value:
            # Try to find in evidence
            for e in evidence:
                if e.get('feature') == match_field:
                    match_value = e.get('value')
                    break
        
        if not match_value:
            return not exists  # No value to check
        
        # Query trust table
        if table == 'trusted_person':
            row = self.conn.execute(
                "SELECT name FROM trusted_person WHERE trusted_id = ? AND active = 1",
                (match_value,)
            ).fetchone()
        elif table == 'trusted_plates':
            row = self.conn.execute(
                "SELECT label FROM trusted_plates WHERE plate_hmac = ? AND enabled = 1",
                (match_value,)
            ).fetchone()
        else:
            return False
        
        found = row is not None
        return found == exists
    
    def _check_no_recent_alert(self, spec: Dict[str, Any], context: Dict) -> bool:
        """Check that NO alert was sent recently"""
        track_key = context.get('track_key') if spec.get('track_key') == 'current' else spec.get('track_key')
        alert_type = spec.get('alert_type', 'telegram')
        within_seconds = spec.get('within_seconds', 300)
        
        if not track_key:
            return True  # No track_key, can't check history
        
        now_ts = int(datetime.now().timestamp())
        cutoff_ts = now_ts - within_seconds
        
        row = self.conn.execute("""
            SELECT sent_ts FROM alert_history
            WHERE track_key = ? AND alert_type = ?
            AND sent_ts > ?
            ORDER BY sent_ts DESC LIMIT 1
        """, (track_key, alert_type, cutoff_ts)).fetchone()
        
        return row is None  # True if no recent alert
    
    def _check_alert_sent_within(self, spec: Dict[str, Any], context: Dict) -> bool:
        """Check that alert WAS sent within time window"""
        track_key = context.get('track_key') if spec.get('track_key') == 'current' else spec.get('track_key')
        alert_type = spec.get('alert_type', 'telegram')
        min_seconds = spec.get('min_seconds', 0)
        max_seconds = spec.get('max_seconds', 600)
        
        if not track_key:
            return False
        
        now_ts = int(datetime.now().timestamp())
        min_cutoff = now_ts - max_seconds
        max_cutoff = now_ts - min_seconds
        
        row = self.conn.execute("""
            SELECT sent_ts FROM alert_history
            WHERE track_key = ? AND alert_type = ?
            AND sent_ts BETWEEN ? AND ?
            ORDER BY sent_ts DESC LIMIT 1
        """, (track_key, alert_type, min_cutoff, max_cutoff)).fetchone()
        
        return row is not None
    
    def _check_time_between(self, spec: Dict[str, str]) -> bool:
        """Check if current time is between start and end (24h format)"""
        start_str = spec.get('start', '00:00')
        end_str = spec.get('end', '23:59')
        
        now = datetime.now().time()
        start = datetime.strptime(start_str, '%H:%M').time()
        end = datetime.strptime(end_str, '%H:%M').time()
        
        if start <= end:
            # Normal range (e.g., 08:00-17:00)
            return start <= now <= end
        else:
            # Overnight range (e.g., 22:00-06:00)
            return now >= start or now <= end
    
    def _check_day_of_week(self, spec: Any) -> bool:
        """Check if current day matches"""
        days_map = {
            'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
            'fri': 4, 'sat': 5, 'sun': 6
        }
        
        current_day = datetime.now().weekday()
        
        if isinstance(spec, str):
            spec = [spec]
        
        for day in spec:
            if days_map.get(day.lower()) == current_day:
                return True
        return False
    
    def _check_active_event(self, spec: Dict[str, Any], context: Dict) -> bool:
        """
        Check if there's an active scheduled event matching criteria.
        
        Args:
            spec: Dict with optional 'policy_hint' to match specific event types
            context: Dict with 'timestamp' (defaults to now)
        
        Returns:
            True if matching active event exists
        
        Example conditions:
            {"active_event": {"policy_hint": "greet_visitors"}}
            {"active_event": {}}  # Any active event
        """
        policy_hint = spec.get('policy_hint')
        timestamp = context.get('timestamp', int(datetime.now().timestamp()))
        
        # Query for active events
        if policy_hint:
            # Match specific policy_hint
            cursor = self.conn.execute("""
                SELECT id, name, policy_hint
                FROM scheduled_event
                WHERE ? BETWEEN start_ts AND end_ts
                AND policy_hint = ?
                LIMIT 1
            """, (timestamp, policy_hint))
        else:
            # Any active event
            cursor = self.conn.execute("""
                SELECT id, name, policy_hint
                FROM scheduled_event
                WHERE ? BETWEEN start_ts AND end_ts
                LIMIT 1
            """, (timestamp,))
        
        active_event = cursor.fetchone()
        
        if active_event:
            # Store active event info in context for debugging/logging
            context['active_event_id'] = active_event[0]
            context['active_event_name'] = active_event[1]
            context['active_event_hint'] = active_event[2]
            return True
        
        return False
    
    def _resolve_variables(self, evidence: List[Dict], context: Dict) -> Dict[str, str]:
        """Resolve all variables from evidence and context"""
        resolved = {}
        
        # First, auto-extract common variables from evidence
        # This allows messages to use {vehicle_color}, {plate_text}, etc. automatically
        for e in evidence:
            source = e.get('source', '')
            feature = e.get('feature', '')
            value = e.get('value', '')
            
            # Create variable names like: vehicle_color, plate_text, intent, etc.
            # Map common evidence features to variable names
            if feature in ['color', 'vehicle_type', 'plate_text', 'intent', 'confidence', 'visitor_id']:
                resolved[feature] = str(value)
            
            # Also create source_feature combo (e.g., vision_color, ocr_plate_text)
            var_name = f"{source}_{feature}"
            resolved[var_name] = str(value)
        
        # Add context variables (camera_id, track_key, etc.)
        for key, value in context.items():
            if isinstance(value, (str, int, float)):
                resolved[key] = str(value)
        
        # Then apply explicit variable definitions from policy/config
        for var_name, var_def in self.variable_defs.items():
            # Evidence-based variables
            if 'source' in var_def:
                source = var_def['source']
                feature = var_def['feature']
                default = var_def.get('default', '')
                
                value = default
                for e in evidence:
                    if e.get('source') == source and e.get('feature') == feature:
                        value = str(e.get('value', default))
                        break
                resolved[var_name] = value
            
            # Context variables
            elif 'from_context' in var_def:
                field = var_def['from_context']
                resolved[var_name] = str(context.get(field, ''))
            
            # Database lookups
            elif 'lookup' in var_def:
                lookup = var_def['lookup']
                table = lookup['table']
                match_field = lookup['match_field']
                return_field = lookup['return_field']
                default = var_def.get('default', '')
                
                match_value = context.get(match_field)
                if match_value:
                    row = self.conn.execute(
                        f"SELECT {return_field} FROM {table} WHERE {match_field} = ?",
                        (match_value,)
                    ).fetchone()
                    resolved[var_name] = row[0] if row else default
                else:
                    resolved[var_name] = default
            
            # Calculated variables
            elif 'calculate' in var_def:
                # Simple eval for calculations (secure context)
                calc = var_def['calculate']
                try:
                    # Replace variable names with values
                    for k, v in context.items():
                        calc = calc.replace(k, str(v))
                    result = eval(calc)
                    fmt = var_def.get('format', '%s')
                    resolved[var_name] = fmt % result
                except:
                    resolved[var_name] = ''
            
            # Environment variables
            elif 'env' in var_def:
                resolved[var_name] = os.getenv(var_def['env'], var_def.get('default', ''))
        
        return resolved
