"""
Smile Partners — the Sabrina client.

This client works in Sabrina rather than Denticon and exports a patient
insurance-breakdown PDF from it, which `sabrina/` audits field by field against
the insurance portal. The portal readers under `portals/` and the breakdown
builder in `breakdown.py` belong to Smile Partners alone: DCA keeps its own
copy, so a change made for one client can never reach the other.
"""
