import asyncio
from compare_patients import ask_ollama

test_text = """
Benefits, Eligibility, Claims
Dentist Connection Date: 06/04/2026
Electronic Claims Payer ID: 39069
Benefit Verification Number: 0006088431
Delta Dental of Wisconsin
PO Box 828
Stevens Point WI 54481
This is not a guarantee of benefits and does not cover all plan details. If there are any differences between the information
stated here and the group contract, the group contract will govern. All benefits are subject to deductibles, contract maximums
and eligibility on the date of service. The eligibility and benefit information is only valid for the following subscriber on the date
shown above. Pre-treatment estimate is recommended for treatment plans that include crowns, fixed bridge work, implants, or
partial or complete dentures. Benefit for multiple-appointment procedures is payable on completion date.
Eligibility and Accumulations
To calculate remaining maximum amounts, subtract "Amount Used" from corresponding maximum amounts displayed in the
"Maximums & Deductibles" section.
Program deductibles and maximums are calculated for a "Benefit Year" defined as: 01/01/2026 - 12/31/2026. Subscribers
are responsible for paying the following deductible before Delta Dental will make payment.
Subscriber Name: TYLER M BERG Group Number: 08319-001-00000-00000
Coverage Type: Family Group Name: RACINE UNIFIED SCHOOL DISTRICT
Name and
Coverage Dates
Regular
Annual
Deductible
Satisfied
Regular
Annual
Maximum
Used
Orthodontic
Annual
Maximum
Used
Orthodontic
Lifetime
Maximum
Used
Custom
Annual
Maximum
Used
Out of
Pocket
Maximum
Satisfied
TYLER M BERG
Start 03/14/2023
End
$.00 $.00 $.00 $.00 $.00 $.00
JILL M WORZALA
Start 03/14/2023
End
$.00 $960.00 $.00 $.00 $.00 $.00
FAMILY
DEDUCTIBLES &
MAXIMUMS
$.00 $960.00 $.00 $.00 $.00 $.00
SPECIAL HEALTH CARE NEEDS BENEFIT (SHCNB) INCLUDED ON THIS PLAN; PROVIDERS MUST
VERIFY MEMBER MEETS CONDITION CRITERIA TO BE ELIGIBLE FOR ADDITIONAL SERVICES;
MORE INFO AVAILABLE AT: WWW.DELTADENTALWI.COM/SHCNB
Age Limits
TYLER M BERG
Birthdate 01/27/1993
JILL M WORZALA
Birthdate 01/20/1993
Child Coverage Age: 26 Student Coverage Age: 26
Adult Orthodontic: Yes Dependent Orthodontic Age: 26/26
Coordination of Benefits
Standard Coordination of Benefits
Maximums and Deductibles
TYLER M BERG
Birthdate 01/27/1993
JILL M WORZALA
Birthdate 01/20/1993
Questions? - Call 800-236-3712 or visit our website at www.deltadentalwi.com
Page 2 of 5
Program deductibles and maximums are calculated for a "Benefit Year" defined as: 01/01/2026 - 12/31/2026.
Subscribers are responsible for paying the following deductible before Delta Dental will make payment.
Delta Dental
PPO
Delta Dental
Premier
Out of Network
Annual Maximums $99,999.99 None None
Annual Deductibles None None None
Lifetime Maximums None None None
Lifetime Deductibles None None None
Ortho Annual Maximums $99,999.99 None None
Ortho Annual Deductibles $450.00 None None
Ortho Lifetime Maximums None None None
Ortho Lifetime Deductibles $450.00 None None
Custom Annual Maximums None None None
Custom Annual Deductibles None None None
Custom Lifetime Maximums None None None
Custom Lifetime Deductibles None None None
Annual Family Maximums None None None
Annual Family Deductibles None None None
Lifetime Family Maximums None None None
Lifetime Family Deductibles None None None
Annual Out-of-Pocket Maximum None None None
Annual Family Out-of-Pocket Maximum None None None
Benefit Levels
TYLER M BERG
Birthdate 01/27/1993
JILL M WORZALA
Birthdate 01/20/1993
Benefit payments are calculated on Delta Dental's Maximum Plan Allowance (MPA) for Delta Dental Premier dentists or on
the Delta Dental PPO fee schedule for Delta Dental PPO dentists.
Services
(Sample code
displayed)
Delta Dental PPO Delta Dental Premier Out of Network
Benefit
Level
Deductible
Applies
Benefit
Level
Deductible
Applies
Benefit
Level
Deductible
Applies
Diagnostic(0150) 100% No None No None No
Full Mouth
Xrays(0210)
100% No None No None No
Bitewing
Xrays(0272)
100% No None No None No
Pre-Diag(0431) None No None No None No
Preventive(1110) 100% No None No None No
Sealants(1351) 100% No None No None No
Basic Restor(2140) 100% No None No None No
Inlays(2630) 100% No None No None No
Onlays(2643) 100% No None No None No
Major Restor(2750) 100% No None No None No
Buildup/Post &
Core(2950)
100% No None No None No
Endodontics(3320) 100% No None No None No
Surg Perio(4260) 100% No None No None No
Periodontics(4341) 100% No None No None No
Antimicrobial(4381) 100% No None No None No
Perio Maint(4910) 100% No None No None No
Rmvbl Prosth(5110) 100% No None No None No
Prosth Repair(5670) 100% No None No None No
Prosth (Reb)(5710) 100% No None No None No
Prosth (Rel)(5730) 100% No None No None No
Questions? - Call 800-236-3712 or visit our website at www.deltadentalwi.com
Page 3 of 5
Surg Implants(6010) 100% No None No None No
Implants(6059) 100% No None No None No
Fixed Prosth(6750) 100% No None No None No
Simple
Extract(7140)
100% No None No None No
Oral Surgery(7240) 100% No None No None No
Brush Biopsy(7288) 100% No None No None No
Orthodontics(8010) 100% Yes None No None No
Palliative(9110) 100% No None No None No
Gen Anesth(9222) 100% No None No None No
Nitrous Oxide(9230) 100% No None No None No
Ther Drug Inj(9610) 100% No None No None No
Desensitize(9910) None No None No None No
Occl Guard(9944) 100% No None No None No
Frequency, Age, and Other Benefit Limitations
TYLER M BERG
Birthdate 01/27/1993
JILL M WORZALA
Birthdate 01/20/1993
Services Frequency and Other Benefit Limitations Age Limitations
Which Procedures Require
Pre-treatment estimate?
Pre-treatment estimate is not required; however, it is highly
recommended.
None
Initial/Periodic Exam 2 in a benefit year None
Full Mouth or Panoramic X-rays 2 year intervals None
Bitewing X-rays 2 in a benefit year. Bitewing benefit for children under 10 limited to two
films.
None
Child Cleaning 2 in a benefit year Ages 0-13
Adult Cleaning 2 in a benefit year Ages 14 and up
Fluoride Gel 2 in a benefit year Ages 6-19
Fluoride Varnish 2 in a benefit year Ages 0-18
Sealants Sealants are a benefit on unrestored bicuspids, primary and permanent
molars; generally limited to one placement per tooth in a lifetime.
Ages 0-18
"""

prompt = f"""You are a dental insurance data extraction assistant.
I will provide the raw text extracted from a Delta Dental PDF.
Extract the relevant fields and format them EXACTLY in this JSON structure.
Do NOT include any markdown, just output the JSON object.

EXPECTED JSON FORMAT:
{{
  "summary": {{
    "group_name": "<Employer/Group Name (e.g. RACINE UNIFIED SCHOOL DISTRICT)>",
    "group_number": "<Group Number (e.g. 08319-001)>"
  }},
  "financials": {{
    "individual_deductible": {{"total": "<Individual Annual Deductible amount, e.g. $ 50.00>"}},
    "family_deductible": {{"total": "<Family Deductible amount, e.g. $ 150.00>"}},
    "annual_max": {{"total": "<Regular Annual Maximum amount, e.g. $ 1000.00>"}},
    "ortho_lifetime": {{"total": "<Orthodontic Lifetime Maximum, e.g. $ 1500.00>"}}
  }},
  "patient": {{
    "relationship": "<Self, Spouse, or Dependent>"
  }},
  "benefit_coverage": {{
    "procedures": [
      {{"procedure_code": "D0120", "benefit_level": "<Preventive/Diagnostic coverage %, e.g. 100%>", "age_limit": "<if applicable, e.g. 0-14, else 0-99>"}},
      {{"procedure_code": "D1206", "benefit_level": "<Fluoride coverage %, e.g. 100%>", "age_limit": "<Fluoride age limit, e.g. 0-18>"}},
      {{"procedure_code": "D1351", "benefit_level": "<Sealants coverage %, e.g. 100%>", "age_limit": "<Sealants age limit, e.g. 0-18>"}},
      {{"procedure_code": "D1510", "benefit_level": "<Space Maintainers coverage %, e.g. 100%>", "age_limit": "<Space Maintainers age limit, e.g. 0-18>"}},
      {{"procedure_code": "D2331", "benefit_level": "<Basic Restorative/Fillings %, e.g. 80%>"}},
      {{"procedure_code": "D2140", "benefit_level": "<Basic Restorative/Fillings %, e.g. 80%>"}},
      {{"procedure_code": "D2740", "benefit_level": "<Major Restorative/Crowns %, e.g. 50%>"}},
      {{"procedure_code": "D8080", "benefit_level": "<Orthodontics %, e.g. 50%>", "age_limit": "<Ortho age limit if any, e.g. 0-26>"}}
    ]
  }}
}}

RAW TEXT FROM DELTA DENTAL PDF:
{test_text}
"""

async def test_ollama():
    print("Sending prompt to Ollama...")
    res = await ask_ollama(prompt)
    print(res)

if __name__ == "__main__":
    asyncio.run(test_ollama())
