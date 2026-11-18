"""
Sabrina Fill Form prefill (smile_partners/sabrina/prefill.py) and the scrape
store behind /api/scrapes and /api/prefill.

Run:  python tests/test_sabrina_prefill.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SCRAPE_DB"] = os.path.join(tempfile.mkdtemp(), "scrapes.db")

from smile_partners.sabrina.prefill import build_prefill, member_key   # noqa: E402
from shared import scrape_store                                         # noqa: E402

_failed = 0


def check(label, got, want):
    global _failed
    ok = got == want
    print(f"  [{'ok' if ok else 'FAIL'}] {label}")
    if not ok:
        _failed += 1
        print(f"         got  {got!r}\n         want {want!r}")


def _row(code, pct="", freq="N/A", hist="N/A", age="N/A", message=""):
    return {"procedure_code": code, "percentage_copay": pct, "frequency": freq,
            "history": hist, "age_limit": age, "message": message, "source": "in_and_out"}


def _network(basic):
    return {
        "maximums": [{"type": "DENTAL", "coverage": "Individual", "amount": "$1,500.00",
                      "remaining": "$1,200.00", "message": "Calendar Year", "source": "in_and_out"},
                     {"type": "Orthodontics", "coverage": "Individual", "amount": "$2,500.00",
                      "remaining": "$2,500.00", "message": "Lifetime", "source": "in_and_out"}],
        "deductibles": [],
        "co_insurance": [
            {"type": "Preventative", "percentage": "0% / 100%", "source": "in_and_out"},
            {"type": "Basic", "percentage": basic, "source": "in_and_out"},
            {"type": "Major", "percentage": "50% / 50%", "source": "in_and_out"},
        ],
        "service_level_benefits": [
            _row("D0120", "0% / 100%", "2 Units, for 1 Calendar Year PER FULL MOUTH.",
                 "1 Unit Remaining. Last paid date: 03/04/26", "Maximum Age: 99"),
            _row("D0274", "0% / 100%", "1 Unit, for 1 Calendar Year PER FULL MOUTH.",
                 "1 Unit Remaining.", "Maximum Age: 99"),
            _row("D1206", message="Not Covered"),
            _row("D2160", basic),
            _row("D4341", basic),
        ],
    }


# A made-up ClaimConnect (Aetna) export — no real patient.
EXPORT = {
    "source": "ClaimConnect - Extended Plan Benefits",
    "patient": {"name": "TEST PATIENT", "member_id_or_ssn": "W000111222",
                "date_of_birth": "02/03/1990"},
    "payer": {"name": "Aetna Dental Plans", "coverage": "Employee",
              "plan_type": "Preferred Provider Organization (PPO)",
              "group#": "012345678900001", "group_name": "TEST EMPLOYER"},
    "dates": {"plan_begin": "01/01/2026", "eligibility_begin": "01/01/2026"},
    "patient_information": {"name": "TEST PATIENT", "member_id_or_ssn": "W000111222",
                            "date_of_birth": "02/03/1990"},
    "coverage_details": {"payer": "Aetna Dental Plans", "group_number": "012345678900001",
                         "group_name": "TEST EMPLOYER"},
    "plan_level_remarks": ["MISSING TOOTH CLAUSE APPLIES",
                           "COMMERCIAL,CHLD TO 26 OR 26 IF FT STUDENT,Standard COB"],
    "claim_address": {"name": "Aetna Dental", "address": "PO Box 14094, Lexington, KY 40512"},
    "in_network": _network("20% / 80%"),
    "out_of_network": _network("40% / 60%"),
}


def field(result, name):
    return next((f["value"] for f in result["fields"] if f["name"] == name), None)


def cell(result, code, column):
    return next((g["value"] for g in result["grid"]
                 if g["code"] == code and g["column"] == column), None)


print("── PREFILL: AETNA ──")
r_in = build_prefill(EXPORT, "In")
r_out = build_prefill(EXPORT, "out")
check("carrier", r_in["carrier"], "aetna")
check("network echoed", (r_in["network"], r_out["network"]), ("In", "Out"))
check("yearly max: plain number, no commas or .00", field(r_in, "insuranceDetails.yearlyMaxAmount"), "1500")
check("yearly max used = max − remaining", field(r_in, "benefitsInfo.yearlyMaxUsed"), "300")
from smile_partners.sabrina.prefill import _money                      # noqa: E402
check("money formats", [_money("$1,250.00"), _money("154.37"), _money("0.00"), _money("$37.5")],
      ["1250", "154.37", "0", "37.50"])
check("plan start month", field(r_in, "insuranceDetails.planMonth"), "January")
check("PPO group number drops leading 0", field(r_in, "insuranceDetails.groupNumber"), "12345678900001")
check("basic % follows the picked network",
      (field(r_in, "insuranceDetails.basic"), field(r_out, "insuranceDetails.basic")), ("80", "60"))
check("grid % is the option text", cell(r_in, "D0120", "percentage"), "100%")
check("frequency in Sabrina's words", cell(r_in, "D0120", "frequency"), "2X1Year")
check("history date with 4-digit year", cell(r_in, "D0120", "history"), "03/04/2026")
check("no paid date → NH", cell(r_in, "D0274", "history"), "NH")
check("Not Covered → NC / 0",
      (cell(r_in, "D1206", "frequency"), cell(r_in, "D1206", "percentage")), ("NC", "0"))
check("Aetna D4341 quads standard 4", cell(r_in, "D4341", "quads"), "4")
check("history is appointment-level",
      next(g["level"] for g in r_in["grid"] if g["column"] == "history"), "appointment")
check("missing tooth clause question",
      next((q["value"] for q in r_in["questions"]
            if q["question"] == "DoesMissingToothClauseApply?"), None), "Yes")
check("COB is left to the user",
      field(r_in, "insuranceDetails.coordinationOfBenefits"), None)
check("relation: Employee → Self", field(r_in, "demographic.relationToInsured"), "Self")
check("plan type PPO", field(r_in, "insuranceDetails.planType"), "PPO")
check("calendar year", field(r_in, "insuranceDetails.calendarorfiscal"), "Calendar")
check("ortho maximum Lifetime", field(r_in, "benefitsInfo.orthoMaximumCovered"), "Lifetime")
spouse = dict(EXPORT, payer=dict(EXPORT["payer"], coverage="Spouse"))
check("relation: Spouse", field(build_prefill(spouse, "In"), "demographic.relationToInsured"), "Spouse")
no_ortho = dict(EXPORT, in_network=dict(EXPORT["in_network"],
                                         maximums=EXPORT["in_network"]["maximums"][:1]))
check("no ortho maximum row → left for the user",
      field(build_prefill(no_ortho, "In"), "benefitsInfo.orthoMaximumCovered"), None)
check("network is never filled",
      any(f["name"] == "insuranceDetails.network" for f in r_in["fields"]), False)
check("member key", member_key(EXPORT), ("W000111222", "02/03/1990"))
try:
    build_prefill(EXPORT, "")
    check("no network refused", "accepted", "ValueError")
except ValueError:
    check("no network refused", "ValueError", "ValueError")

print("── WAITING PERIODS (AETNA) ──")
import copy as _copy                                                    # noqa: E402


def _with_waits(waits):
    out = _copy.deepcopy(EXPORT)
    rows = out["in_network"]["service_level_benefits"]
    for code, wait in waits.items():
        row = next((r for r in rows if r["procedure_code"] == code), None)
        if row is None:
            row = _row(code)
            rows.append(row)
        row["waiting_period"] = wait
    return out


wp = build_prefill(_with_waits({"D2160": "6 months", "D2740": "12 months"}), "In")["waiting_periods"]
check("Basic from D2160, Major from D2740",
      [(w["applies_to"], w["period"], w["unit"], w["source"]) for w in wp],
      [("Basic", "6", "Months", "D2160"), ("Major", "12", "Months", "D2740")])
wp = build_prefill(_with_waits({"D2160": "", "D2391": "6 months"}), "In")["waiting_periods"]
check("Basic falls back to D2391", [(w["applies_to"], w["source"]) for w in wp], [("Basic", "D2391")])
wp = build_prefill(_with_waits({"D2740": "1 year"}), "In")
check("years read as Years", [(w["period"], w["unit"]) for w in wp["waiting_periods"]], [("1", "Years")])
check("rows set Is there a waiting period = Yes", field(wp, "insuranceDetails.waitingPeriodFlag"), "Yes")
check("no waiting periods stated → no rows", build_prefill(EXPORT, "In")["waiting_periods"], [])

print("── CIGNA: NETWORK FROM THE SCRAPE ──")
# Cigna's network is picked on the portal (Plan View) before the crawl, so the
# scrape holds one network: TOTAL / ADVANTAGE / … are In, Out-of-Network is Out.
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_sabrina.py"),
            encoding="utf-8").read()
_ns = {}
exec(_src[_src.index("def _cigna_proc"):_src.index("_CG = _cigna_payload()")], _ns)
cg_total = _ns["_cigna_payload"]()
cg_oon = _ns["_cigna_payload"]()
cg_oon["plan_details"]["network"] = {"id": "OONET", "name": "Out-of-Network"}
r_cg = build_prefill(cg_total, "")
check("Cigna TOTAL needs no pick → In", (r_cg["carrier"], r_cg["network"], r_cg["network_from_scrape"]),
      ("cigna", "In", True))
check("Cigna Out-of-Network → Out", build_prefill(cg_oon, "")["network"], "Out")
check("Cigna: a matching pick is fine", build_prefill(cg_total, "In")["network"], "In")
try:
    build_prefill(cg_total, "Out")
    check("Cigna: a pick against the scrape is refused", "accepted", "ValueError")
except ValueError:
    check("Cigna: a pick against the scrape is refused", "ValueError", "ValueError")
check("Cigna: IN OR OON not left for the user", "IN OR OON" in r_cg["left_for_user"], False)
check("Cigna frequency in Sabrina's words",
      [cell(r_cg, c, "frequency") for c in ("D0120", "D1208", "D1351")], ["2X1Year", "1X1Year", "1X3Year"])
check("Cigna 'Exclude after age 18' → 18", cell(r_cg, "D1208", "ageLimit"), "18")
from smile_partners.sabrina.prefill import _frequency                  # noqa: E402
check("frequency wordings",
      [_frequency(t) for t in ("Once Per 6 Consecutive Months", "Four Times Per Calendar Year",
                               "No benefits for this service", "Not Applicable", "2X1Year")],
      ["1X6Month", "4X1Year", "NC", "No Frequency", "2X1Year"])
check("Aetna still needs the pick", build_prefill(EXPORT, "In")["network_from_scrape"], False)

print("── DELTA DENTAL / TOOLKIT: NETWORK FROM THE SCRAPE ──")
# Both pick the network in the extension's pop-up before the crawl and scrape
# that network only: PPO and Premier are In, Out of Network is Out. A pick on
# the form against it is refused, as for Cigna, instead of filling the scraped
# network's figures under the other one.
from smile_partners.sabrina.prefill import scrape_network                # noqa: E402


def _refused(export, network):
    try:
        build_prefill(export, network)
        return "accepted"
    except ValueError as e:
        return "refused" if "only" in str(e) else f"other error: {e}"


def _dd(selected):
    return {"source": "Delta Dental", "primary_patient": {"name": "X", "plan": "Delta Dental PPO"},
            "tabs": {"benefits_search": [], "benefits_search_network": "",
                     "benefits_search_selected": selected}}


check("Delta Dental: PPO / Premier → In, Out of Network → Out, no pick → none",
      [scrape_network(_dd(s)) for s in ("ppo", "premier", "oon", "")], ["In", "In", "Out", None])
r_dd = build_prefill(_dd("oon"), "")
check("Delta Dental OON needs no pick → Out",
      (r_dd["carrier"], r_dd["network"], r_dd["network_from_scrape"]), ("delta_dental", "Out", True))
check("Delta Dental: In picked on a PPO scrape is fine", build_prefill(_dd("ppo"), "In")["network"], "In")
check("Delta Dental: Out picked on a Premier scrape is refused", _refused(_dd("premier"), "Out"), "refused")
check("Delta Dental: In picked on an OON scrape is refused", _refused(_dd("oon"), "In"), "refused")
check("Delta Dental before the pop-up still takes the pick",
      build_prefill(_dd(""), "Out")["network_from_scrape"], False)

exec(_src[_src.index("def _tk_result"):_src.index("_tk = _tk_export()")], _ns)


def _tk(choice, name):
    export = _ns["_tk_export"]()
    if choice:
        export["network_choice"] = choice
    export["selected_network"] = name
    return export


check("Toolkit: PPO / Premier → In, Nonparticipating / Non-PPO → Out",
      [scrape_network(_tk(c, n)) for c, n in (("ppo", "PPO Dentist"), ("premier", "Premier Dentist"),
                                               ("oon", "Nonparticipating Dentist"),
                                               ("oon", "Non-PPO Dentist"))],
      ["In", "In", "Out", "Out"])
r_tk = build_prefill(_tk("oon", "Nonparticipating Dentist"), "")
check("Toolkit Nonparticipating needs no pick → Out",
      (r_tk["carrier"], r_tk["network"], r_tk["network_from_scrape"]), ("delta_toolkit", "Out", True))
check("Toolkit: Out picked on a PPO scrape is refused", _refused(_tk("ppo", "PPO Dentist"), "Out"), "refused")
check("Toolkit: In picked on a Nonparticipating scrape is refused",
      _refused(_tk("oon", "Nonparticipating Dentist"), "In"), "refused")
check("Toolkit before the pop-up (no network_choice) still takes the pick",
      scrape_network(_tk(None, "PPO Dentist")), None)

print("── SCRAPE STORE ──")
sid = scrape_store.save("smile_partners", "aetna", "w000-111 222", "2/3/1990", EXPORT)
check("found by member ID, any format",
      (scrape_store.find_pending("smile_partners", "W000111222") or {}).get("id"), sid)
check("DOB must agree when both state one",
      scrape_store.find_pending("smile_partners", "W000111222", "01/01/1980"), None)
check("other client cannot see it",
      scrape_store.find_pending("star_dental", "W000111222"), None)
check("the user's own scrape by id",
      (scrape_store.get_pending("smile_partners", sid) or {}).get("member_id"), "W000111222")
check("own scrape id is per client", scrape_store.get_pending("star_dental", sid), None)
check("mark used", scrape_store.mark_used(sid), True)
check("used scrape not returned by id", scrape_store.get_pending("smile_partners", sid), None)
check("used scrape is not returned again",
      scrape_store.find_pending("smile_partners", "W000111222"), None)

print("── ENDPOINTS: PORTALS WITHOUT A MEMBER ID ──")
# Guardian states no member ID, the Toolkit not always, MetLife masks it:
# such a scrape is kept and matched on the DOB.
import copy                                                             # noqa: E402
import logging                                                          # noqa: E402
logging.disable(logging.INFO)
from fastapi.testclient import TestClient                              # noqa: E402
import main                                                             # noqa: E402
api = TestClient(main.app)

no_id = copy.deepcopy(EXPORT)
for block in ("patient", "patient_information"):
    no_id[block]["member_id_or_ssn"] = ""
saved = api.post("/api/scrapes", json={"portal_data": no_id})
check("scrape with only a DOB is kept", (saved.status_code, saved.json().get("dob")), (200, "02/03/1990"))
sid2 = saved.json().get("id")
ask = lambda **q: api.get("/api/prefill", params={"sabrina_client": "26", "network": "In",
                                                   "scrape_id": sid2, "only_own": "true", **q})
check("fills the form with the same DOB", ask(member_id="123456789", dob="02/03/1990").status_code, 200)
check("refused for another DOB", ask(member_id="123456789", dob="05/05/1980").status_code, 409)
check("blank member IDs are not a match", ask(member_id="", dob="05/05/1980").status_code, 409)
check("Aetna with no pick asks for it (422)",
      api.get("/api/prefill", params=dict(sabrina_client="26", member_id="x", dob="02/03/1990",
                                          scrape_id=sid2, only_own="true")).status_code, 422)
nothing = copy.deepcopy(no_id)
for block in ("patient", "patient_information"):
    nothing[block]["date_of_birth"] = ""
check("no member ID and no DOB is refused",
      api.post("/api/scrapes", json={"portal_data": nothing}).status_code, 422)

print("── WHICH CLIENT: SABRINA'S selectedClient ──")
filled = ask(member_id="123456789", dob="02/03/1990")
check("Sabrina client 26 fills with Smile Partners' rules", filled.json().get("client"), "smile_partners")
star = ask(member_id="123456789", dob="02/03/1990", sabrina_client="19")
check("Star Dental (19): not set up yet, says so",
      (star.status_code, "not set up for Star Dental" in star.json().get("detail", "")), (400, True))
other = ask(member_id="123456789", dob="02/03/1990", sabrina_client="2")
check("a Sabrina client we have no folder for (2) is refused",
      (other.status_code, "not set up" in other.json().get("detail", "")), (400, True))
check("no client at all is refused", ask(member_id="123456789", dob="02/03/1990", sabrina_client="").status_code, 400)
check("Absolute Dental (2) named in the refusal", "Absolute Dental" in other.json().get("detail", ""), True)
info = lambda cid: api.get("/api/sabrina-client", params={"id": cid}).json()
check("panel: 26 → Smile Partners, ready",
      (info("26")["name"], info("26")["ready"], info("26")["client"]), ("Smile Partners", True, "smile_partners"))
check("panel: 19 → Star Dental, has a folder, not ready",
      (info("19")["name"], info("19")["ready"], info("19")["client"]), ("Star Dental", False, "star_dental"))
check("panel: 3 → Kidscare Dental, no folder",
      (info("3")["name"], info("3")["ready"], info("3")["client"]), ("Kidscare Dental", False, None))
check("panel: an id Sabrina hasn't told us about", (info("99")["known"], info("99")["ready"]), (False, False))
check("every Sabrina client in CLIENTS has its id",
      sorted(s.get("sabrina_client_id", "") for k, s in main.CLIENTS.items() if s["system"] == "Sabrina"),
      ["11", "19", "26", "27"])

print("── ENDPOINTS: FAMILY MEMBERS ON ONE MEMBER ID ──")
# Delta, Cigna and MetLife often give a whole family the subscriber's member
# ID: when the form and the scrape both state a DOB, the DOB decides.
saved = api.post("/api/scrapes", json={"client": "smile_partners", "portal_data": EXPORT})
sid3 = saved.json().get("id")
own = lambda **q: api.get("/api/prefill", params=dict(client="smile_partners", network="In",
                                                       scrape_id=sid3, only_own="true", **q))
check("same member ID and DOB fills", own(member_id="W000111222", dob="02/03/1990").status_code, 200)
child = own(member_id="W000111222", dob="03/14/2012")
check("same member ID, another DOB is refused (a family member)", child.status_code, 409)
check("the refusal names the family member case",
      "family member" in str(child.json().get("detail")), True)
check("same member ID, no DOB on the form still fills",
      own(member_id="W000111222", dob="").status_code, 200)
check("member ID worded differently, same DOB still fills",
      own(member_id="123-45-6789", dob="2/3/1990").status_code, 200)
check("not the user's own scrape: same member ID, another DOB finds nothing",
      api.get("/api/prefill", params=dict(client="smile_partners", network="In",
                                          member_id="W000111222", dob="03/14/2012")).status_code, 404)
two_digit = copy.deepcopy(EXPORT)
for block in ("patient", "patient_information"):
    two_digit[block]["date_of_birth"] = "02/03/90"
check("a 2-digit portal DOB is stored in the right century",
      member_key(two_digit)[1], "02/03/1990")

print(f"\n{'all passed' if not _failed else f'{_failed} failed'}")
sys.exit(1 if _failed else 0)