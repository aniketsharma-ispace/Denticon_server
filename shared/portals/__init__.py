"""
Insurer portal readers shared by every client: one file per insurer.

Each file reads one insurer\x27s page (via the extension\x27s JSON) into clean
values. Client business rules never live here; they stay in the client\x27s
folder and read from these files.
"""
