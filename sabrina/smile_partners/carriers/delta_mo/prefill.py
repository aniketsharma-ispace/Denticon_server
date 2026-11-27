"""
Delta Dental of Missouri's part of the Sabrina Fill Form prefill.

sabrina/smile_partners/prefill.py does the common work and calls these.
Change DD MO here; other carriers have their own carriers/<carrier>/prefill.py.

Since extension 1.67 (11/27) the DD MO pop-up picks PPO, Premier or
Non-participating before the crawl, as DD Toolkit and DD INS do, and the export
holds that network's figures only:

    network_choice     "ppo" | "premier" | "oon"
    selected_network   "PPO Dentist" | "Premier Dentist" | "Nonparticipating Dentist"
    networks_paying    the networks the plan pays any sheet code above 0% under
    coverage_levels[]  benefit_pct + deductible_applies (the picked network's)
    maximum_and_deductible   the picked network's accumulators

The audit (portals/delta_mo.py) still reads the older three-column exports
(ppo_pct / premier_pct / oon_pct side by side) and has not been changed for the
new shape (user decision, 11/27: prefill only for now). So the prefill recasts a
single-network export into the columns the audit's readers take, and leaves an
older export exactly as it is.
"""

_SCRAPE_NETWORK = {"ppo": "In", "premier": "In", "oon": "Out"}


def _choice(portal_raw) -> str:
    """The network picked before the crawl, or "" for an export from before 1.67."""
    if not isinstance(portal_raw, dict):
        return ""
    value = str(portal_raw.get("network_choice") or "").strip().lower()
    return value if value in _SCRAPE_NETWORK else ""


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under: PPO and Premier are "In",
    Non-participating is "Out". None for an older export holding every
    network, which the user's IN OR OON pick reads as before.
    """
    return _SCRAPE_NETWORK.get(_choice(portal_raw))


def prefill_export(portal_raw: dict) -> dict:
    """
    A single-network export in the columns the audit's readers take.

    With IN OR OON set from the scrape, the reader takes the In figures from
    `ppo_pct` and the Out figures from `oon_pct`, and the deductible flag from
    `ppo_deductible_applies`. The picked network's figures go there, so a
    Premier export fills the form with the Premier percentages (the reader's
    In column) — nothing of another network is made up. Maximums and
    deductibles are already the picked network's, under the same names.
    """
    choice = _choice(portal_raw)
    if not choice:
        return portal_raw
    column = "oon_pct" if choice == "oon" else "ppo_pct"
    rows = []
    for row in portal_raw.get("coverage_levels") or []:
        if isinstance(row, dict) and row.get("listed") and "benefit_pct" in row:
            row = {**row, column: row.get("benefit_pct"),
                   "ppo_deductible_applies": row.get("deductible_applies")}
        rows.append(row)
    return {**portal_raw, "coverage_levels": rows}


def form_only(view: dict, values: dict) -> list[dict]:
    """
    OON Benefits for an in-network export. The audit answers it from the
    out-of-network percentages, which a PPO or Premier export no longer
    carries; `networks_paying` still says whether the plan pays out of
    network. An Out export states its own percentages, and an older export
    all three, so the audit's answer stands for those.
    """
    raw = values.get("_raw") or {}
    if "oon_benefits" in values or _choice(raw) not in ("ppo", "premier"):
        return []
    paying = raw.get("networks_paying")
    if not isinstance(paying, list):
        return []
    return [{"name": "insuranceDetails.planHasOonBenefits",
             "value": "Yes" if "oon" in paying else "No",
             "level": "plan", "source": "networks_paying", "label": "OON Benefits"}]
