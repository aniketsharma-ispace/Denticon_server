"""
Star Dental — a Sabrina client.

This client works in Sabrina rather than Denticon and exports a patient
insurance-breakdown PDF from it, which `sabrina/` audits field by field against
the insurance portal. The portal readers under `portals/` and the breakdown
builder in `breakdown.py` belong to Star Dental alone: DCA and Smile
Partners keep their own copies, so a change made for one client can never reach
another.

Everything here began on 2026-10-22 as a copy of `smile_partners/` — the sheet
layout, the portal readers and every carrier's rules — and none of it has yet
been checked against a Star Dental sheet. Where their sheet or their rules
differ, change this folder only.
"""
