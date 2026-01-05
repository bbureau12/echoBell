import sqlite3

conn = sqlite3.connect('data/doorbell.db')

print("Current signal_rules related to package_drop:")
rules = conn.execute("""
    SELECT id, source, feature, operator, value, intent_name, weight, contributes_standalone
    FROM signal_rule 
    WHERE intent_name = 'package_drop'
    ORDER BY id
""").fetchall()

for r in rules:
    print(f"  Rule {r[0]}: {r[1]}.{r[2]} {r[3]} '{r[4]}' w={r[6]} contrib={r[7]}")

print("\nCurrent signal_groups for package_drop:")
groups = conn.execute("""
    SELECT g.id, g.name, g.intent_name, g.base_weight, g.bind_scope
    FROM signal_group g
    WHERE g.intent_name = 'package_drop'
    ORDER BY g.id
""").fetchall()

for g in groups:
    print(f"\n  Group {g[0]}: {g[1]} (base_weight={g[3]}, scope={g[4]})")
    
    members = conn.execute("""
        SELECT gm.rule_id, gm.required, gm.weight_mul, sr.source, sr.feature, sr.value
        FROM signal_group_member gm
        JOIN signal_rule sr ON sr.id = gm.rule_id
        WHERE gm.group_id = ?
    """, (g[0],)).fetchall()
    
    for m in members:
        req = "REQUIRED" if m[1] else "optional"
        print(f"    - Rule {m[0]}: {m[3]}.{m[4]}={m[5]} ({req}, mul={m[2]})")

conn.close()
