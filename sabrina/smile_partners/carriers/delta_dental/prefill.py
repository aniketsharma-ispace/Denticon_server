"""
Delta Dental's part of the Sabrina Fill Form prefill.

sabrina/smile_partners/prefill.py does the common work and calls these.
Change Delta Dental here; other carriers have their own carriers/<carrier>/prefill.py.
"""

import json
import re
from datetime import date, datetime, timedelta


def scrape_network(portal_raw: dict) -> str | None:
    """
    The network the crawl ran under. Since 10/16 the extension's pop-up picks
    PPO, Premier or Out of Network before the procedure-code search, and only
    that network is searched (`tabs.benefits_search_selected`): PPO and
    Premier are "In", Out of Network is "Out". None for an export made before
    the pop-up, which the user's IN OR OON pick reads as before.
    """
    from .rules import _dd_selected_network
    return {"ppo": "In", "premier": "In", "oon": "Out"}.get(_dd_selected_network(portal_raw))


# ══════════════════════════════════════════════════════════════════════════════
#  FILL FORM CELLS THE AUDIT DOESN'T READ (11/26 review, DDINS QA sheet)
# ══════════════════════════════════════════════════════════════════════════════

_CALENDAR_RE = re.compile(r"\bcalendar\s+year\b", re.IGNORECASE)
_FISCAL_RE = re.compile(r"\b(?:contract|benefit|plan|policy|fiscal)\s+year\b", re.IGNORECASE)


def _plan_type(raw: dict) -> str | None:
    """The member's plan ("Delta Dental PPO") → PPO. Other products are left to the user."""
    plans = [str((raw.get("primary_patient") or {}).get("plan") or "")]
    plans += [str(m.get("plan") or "") for m in ((raw.get("tabs") or {}).get("family_members") or [])
              if isinstance(m, dict)]
    return "PPO" if any(re.search(r"\bPPO\b", p, re.IGNORECASE) for p in plans) else None


def _calendar_or_fiscal(raw: dict) -> str | None:
    """
    Delta INS has no plan-year field. The benefit limitations say which year a
    limit counts in: "within a calendar year" → Calendar; contract / benefit /
    plan year → Fiscal. Both or neither → left to the user (user decision, 11/26).
    """
    text = json.dumps((raw.get("tabs") or {}).get("benefits_search") or {})
    cal, fis = bool(_CALENDAR_RE.search(text)), bool(_FISCAL_RE.search(text))
    if cal != fis:
        return "Calendar" if cal else "Fiscal"
    return None


def form_only(view: dict, values: dict) -> list[dict]:
    """Plan Type and Calendar/Fiscal Year (11/26: both blank on every DDINS new plan)."""
    raw = values.get("_raw") or {}
    out = []
    plan_type = _plan_type(raw)
    if plan_type:
        out.append({"name": "insuranceDetails.planType", "value": plan_type, "level": "plan",
                    "source": "primary_patient.plan", "label": "Plan Type"})
    cal = _calendar_or_fiscal(raw)
    if cal:
        out.append({"name": "insuranceDetails.calendarorfiscal", "value": cal, "level": "plan",
                    "source": "benefits_search limitations", "label": "Calendar/Fiscal Year"})
    return out


def _parse_date(text) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text or "").strip(), fmt).date()
        except ValueError:
            pass
    return None


def _months_between(begins, ends) -> int | None:
    """12/01/2025 – 08/31/2026 → 9: whole months from the first day to the day after the last."""
    b, e = _parse_date(begins), _parse_date(ends)
    if not b or not e or e < b:
        return None
    after = e + timedelta(days=1)
    months = (after.year - b.year) * 12 + after.month - b.month
    if after.day < b.day:
        months -= 1
    return months if months > 0 else None


def waiting_periods(view: dict) -> list[dict]:
    """
    The Waiting Periods tab: each row's dates and the services it covers. A
    Basic / Major row is given when its representative code is listed, even if
    the waiting period has already ended (user decision, 11/26: the plan's
    waiting period is recorded, not only one still running).
    """
    from ...prefill import _WAITING_CODES

    raw = view.get("_raw_export") or {}
    tab = (raw.get("tabs") or {}).get("waiting_periods") or {}
    out = []
    for applies_to, codes in _WAITING_CODES:
        for row in tab.get("rows") or []:
            months = _months_between(row.get("waiting_period_begins"), row.get("waiting_period_ends"))
            if not months:
                continue
            listed = " ".join(f"{t.get('treatment_type') or ''} {t.get('procedure_codes') or ''}"
                              for t in row.get("treatments_and_procedures") or [] if isinstance(t, dict))
            code = next((c for c in codes if re.search(rf"\b{c}\b", listed)), None)
            if code:
                out.append({"applies_to": applies_to, "period": str(months), "unit": "Months",
                            "source": f"waiting_periods ({code})"})
                break
    return out


# The Add codes below the grid (D8090 …). One not covered gets Frequency NC
# and a blank Percentage, not 0 (DDINS QA, 11/25; user decision 11/26: Delta
# INS only, Add codes only).
_ADD_CODES = {"D8090", "D5995", "D6057", "D6058", "D9310"}


def adjust_grid(grid: list[dict]) -> list[dict]:
    return [g for g in grid
            if not (g.get("code") in _ADD_CODES and g.get("column") == "percentage"
                    and str(g.get("value")).strip() in ("0", "0%"))]
