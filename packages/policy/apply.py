def eval_rule(expr:str, ctx:dict) -> bool:
    # Safe-ish eval over a tiny context
    allowed = {"intent":ctx["intent"], "mode":ctx["mode"], "uniform":ctx["vision"].uniform}
    return eval(expr, {"__builtins__":{}}, allowed)

def choose_action(policies:dict, ctx:dict) -> dict:
    for rule in policies.get("rules", []):
        if eval_rule(rule["if"], ctx):
            return rule["then"]
    return policies.get("fallback", {"speak":"Sorry—could you repeat that?","notify":"normal"})
