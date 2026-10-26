"""
Insurance portal readers, one module per carrier.

Each carrier's provider portal exports its own shape of JSON. A module here
recognizes its own export, translates it into the shared contract the rest of
the system reads, and applies the corrections that only make sense for that
carrier. Nothing in here knows anything about a breakdown sheet or about the
Breakdown PDF, so both can use the same readers.

MetLife is the exception and has no normalizer: its export already arrives in
the shared shape, so it is the default path rather than a translation. See
`portals/metlife.py`.
"""
