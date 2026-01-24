"""
Policy application module.
Legacy mode: Simple intent-based rules from config/policies.yaml
New mode: Complex rule engine from config/policy_rules.yaml
"""
from typing import Dict, Any, List, Optional
import sqlite3
from .evaluator import PolicyEvaluator, PolicyMatch
from .executor import ActionExecutor


def eval_rule(expr:str, ctx:dict) -> bool:
    """Legacy: Safe-ish eval over a tiny context"""
    allowed = {"intent":ctx["intent"], "mode":ctx["mode"], "uniform":ctx["vision"].uniform}
    return eval(expr, {"__builtins__":{}}, allowed)


def choose_action(policies:dict, ctx:dict) -> dict:
    """Legacy: Choose action based on simple intent rules"""
    for rule in policies.get("rules", []):
        if eval_rule(rule["if"], ctx):
            return rule["then"]
    return policies.get("fallback", {"speak":"Sorry—could you repeat that?","notify":"normal"})


async def evaluate_policies(
    evidence: List[Dict[str, Any]],
    context: Dict[str, Any],
    conn: sqlite3.Connection,
    policy_file: str = "config/policy_rules.yaml"
) -> List[Dict[str, Any]]:
    """
    Evaluate evidence against policy rules and execute actions.
    
    Args:
        evidence: List of evidence dicts {source, feature, value, conf}
        context: Additional context (camera_id, track_key, track_duration_seconds, etc.)
        conn: Database connection
        policy_file: Path to policy YAML file
    
    Returns:
        List of executed actions with results
    """
    evaluator = PolicyEvaluator(policy_file, conn)
    executor = ActionExecutor(conn)
    
    # Find matching policies
    matches: List[PolicyMatch] = evaluator.evaluate_all(evidence, context)
    
    if not matches:
        return []
    
    # Execute actions for highest priority match only (or all matches if configured)
    # For now, execute all matching policies
    all_results = []
    for match in matches:
        results = await executor.execute_actions(
            actions=match.actions,
            variables=match.variables,
            context=context
        )
        
        all_results.extend([
            {
                'policy_id': match.policy_id,
                'policy_name': match.policy_name,
                'priority': match.priority,
                **result
            }
            for result in results
        ])
    
    return all_results
