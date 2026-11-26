"""DD RI-specific interpretations of the portal export."""

from __future__ import annotations

import re


def ddri_export(portal_raw: dict) -> dict:
    """Return the DD RI export, allowing the standard portal_data wrapper."""
    if not isinstance(portal_raw, dict):
        return {}
    normalized_raw = portal_raw.get("_raw_export")
    if portal_raw.get("_ddri") is True and isinstance(normalized_raw, dict):
        return normalized_raw
    if portal_raw.get("ddri_data") is True:
        return portal_raw
    wrapped = portal_raw.get("portal_data")
    return wrapped if isinstance(wrapped, dict) and wrapped.get("ddri_data") is True else {}


def network_status(portal_raw: dict) -> str | None:
    """Apply the agreed mapping: PPO/Premier is IN; other stated products are OUT."""
    raw = ddri_export(portal_raw)
    plan = raw.get("plan_details") or {}
    value = str(plan.get("network_status") or "").strip()
    if not value or value.lower() in {"n/a", "na", "not available", "unknown"}:
        return None
    return "In" if re.search(r"\b(?:ppo|premier)\b", value, re.IGNORECASE) else "Out"


def oon_benefits(_portal_raw: dict) -> None:
    """DD RI OON benefits are not captured by the extension."""
    return None


def coordination_of_benefits(portal_raw: dict) -> str:
    """DD RI's confirmed default COB classification."""
    return "Standard"
