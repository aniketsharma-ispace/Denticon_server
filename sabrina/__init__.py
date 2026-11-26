"""
The Sabrina clients — one folder each.

    sabrina/
      smile_partners/   Smile Partners   (Sabrina ClientID 26)
      star_dental/      Star Dental      (Sabrina ClientID 19)
      jefferson/        Jefferson
      park_dental/      Park Dental

Every client folder has the same shape and keeps all of its own logic:

      carriers/<portal>/   the audit for one insurance portal: what the sheet
                           holds (spec), reading it (parser), comparing
                           (vocabulary, compare), the portal side (portal),
                           that portal's rules (rules), and its Fill Form
                           extras (prefill, where the client fills forms)
      portals/             reading each portal's export
      breakdown.py         the breakdown built from a portal export
      sheet/               recognising an uploaded sheet before the portal is known
      prefill.py           the Sabrina Fill Form prefill (Smile Partners, Star Dental)
      cli.py               run an audit from the command line

The folders are copies on purpose: a change for one client never reaches
another. main.py (common to every client) picks the folder by the client the
request names, or by the Fill Form's Sabrina ClientID. DCA works in Denticon,
not Sabrina, and keeps its own folder at the top level.
"""
