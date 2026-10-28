"""
Park Dental — a Sabrina client.

This client works in Sabrina rather than Denticon and exports a patient
insurance-breakdown PDF from it, which `sabrina/` audits field by field against
the insurance portal. The portal readers under `portals/` and the breakdown
builder in `breakdown.py` belong to Park Dental alone: DCA, Smile Partners,
Star Dental and Jefferson keep their own copies, so a change made for one
client can never reach another.

Everything here began on 2026-10-28 as a copy of `star_dental/`, so the portal
readers and every carrier's rules are Star Dental's (see RULES.md, "Star
only"). The field list is Park Dental's own: the "Park Dental" tab of
"Updated Sabrina Codes & C Q's Data - All Clients.xlsx". None of it has yet
been checked against a Park Dental sheet. Where their sheet or their rules
differ, change this folder only.
"""
