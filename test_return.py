import json
import asyncio
from compare_patients import match_insurance_plan

async def main():
    with open("william_j_flowers_metlife_audit.json", "r", encoding="utf-8") as f:
        portal_data = json.load(f)

    with open("Denticon_DeepAudit_NA_1781243649302.json", "r", encoding="utf-8") as f:
        d = json.load(f)
        denticon_data = d.get('denticon_data', d)

    result = await match_insurance_plan(portal_data, denticon_data)
    
    print("KEYS RETURNED:", result.keys())
    if "all_plans_ranked" in result:
        print("all_plans_ranked length:", len(result["all_plans_ranked"]))
    else:
        print("all_plans_ranked is MISSING!")

asyncio.run(main())
