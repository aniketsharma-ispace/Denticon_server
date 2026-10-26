"""
Jefferson — a Sabrina client.

This client works in Sabrina rather than Denticon and exports a patient
insurance-breakdown PDF from it, which `sabrina/` audits field by field against
the insurance portal. The portal readers under `portals/` and the breakdown
builder in `breakdown.py` belong to Jefferson alone: DCA, Smile Partners and
Star Dental keep their own copies, so a change made for one client can never
reach another.

Everything here began on 2026-10-26 as a copy of `star_dental/`, with the
field list replaced by Jefferson's own (the "Jefferson " tab of "Updated
Sabrina Codes & C Q's Data - All Clients.xlsx"). The portal readers and every
carrier's rules are Star Dental's, and none of it has yet been checked against
a Jefferson sheet. Where their sheet or their rules differ, change this folder
only.
"""
