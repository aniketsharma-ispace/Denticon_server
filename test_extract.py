import json
from compare_patients import extract_portal_fields, extract_denticon_plan_fields, _python_score

with open("william_j_flowers_metlife_audit.json", "r", encoding="utf-8") as f:
    portal_data = json.load(f)

with open("Denticon_DeepAudit_NA_1781243649302.json", "r", encoding="utf-8") as f:
    d = json.load(f)
    denticon_data = d.get('denticon_data', d)

portal_sim = extract_portal_fields(portal_data)
print("PORTAL:")
print(json.dumps(portal_sim, indent=2))

print("\nDENTICON 32321:")
for p in denticon_data.get("plans", []):
    if str(p.get("ins_plan_id")) == "32321":
        dent_sim = extract_denticon_plan_fields(p)
        print(json.dumps(dent_sim, indent=2))
        s = _python_score(portal_sim, dent_sim)
        score, mm = s["score"], s["mismatches"]
        print("SCORE 32321:", score)
        print("MISMATCHES:", mm)

print("\nDENTICON 23183:")
for p in denticon_data.get("plans", []):
    if str(p.get("ins_plan_id")) == "23183":
        dent_sim = extract_denticon_plan_fields(p)
        print(json.dumps(dent_sim, indent=2))
        s = _python_score(portal_sim, dent_sim)
        score, mm = s["score"], s["mismatches"]
        print("SCORE 23183:", score)
        print("MISMATCHES:", mm)
