# Insurance Auditor

Reads a patient's insurance benefits off a carrier's provider portal and checks
them against what the practice has on record. Two things are produced from that:
an **Insurance Plan Breakdown PDF**, and a **field-by-field audit** of a
breakdown sheet a BPO team filled in by hand.

## Layout

The top level is organised **one folder per client**. A client is a dental group
we do this work for; each has its own way of recording benefits, and each owns
its code outright.

```
DCA/                     the Denticon client
  portals/               reading each carrier's export
    common.py              conversions every carrier reader needs
    metlife.py             (MetLife needs no translation — see the file)
    cigna.py
    delta_dental.py
    aetna.py
  breakdown.py           the fields DCA uses, assembled from a portal export
  plan_pdf.py            the Insurance Plan Breakdown PDF
  compare_patients.py    matching a portal record to a Denticon plan
  patient_notes.py       the note written back into Denticon

smile_partners/          the Sabrina client
  portals/               its own copy of the same five readers
  breakdown.py           its own copy
  sabrina/               the breakdown sheet this client works from
    carriers/              one folder per insurance portal, each a whole audit
      aetna/  cigna/  delta_dental/  metlife/
        spec.py              what the sheet contains, field by field
        parser.py            reading the sheet out of the PDF
        vocabulary.py        making a stated value comparable
        compare.py           deciding whether two values agree
        portal.py            where each answer is found on the portal
        rules.py             this carrier's own rules
        audit.py             the audit itself
    sheet/                 recognizing an uploaded sheet before the portal is known
    cli.py                 tuning the parser against a real sheet
```

**The two `portals/` trees are separate copies on purpose.** A fix made for one
client cannot reach another — that is the point of the split, not an oversight.
When you change one, say so, and decide deliberately whether the other should
follow.

**The same holds for each carrier under `sabrina/carriers/`.** The uploaded
portal export decides which folder runs — an Aetna export is audited by
`aetna/` and no other folder is even imported — so a fix belongs in the folder
of the carrier it was reported for. An export from a portal with no folder
(Guardian, DentaQuest) is refused with a 422 rather than audited by the
nearest carrier's rules. `sheet/` only acknowledges the upload; a parsing fix
for an audit goes in the carrier's own `parser.py`.

Everything else supports those two:

```
main.py                  the HTTP API, and the client registry it dispatches on
shared/                  work that is neither client's (reading a carrier PDF)
web/                     the page the server serves
Extension/               browser scrapers, one per portal
Appointment_Scheduler/   the appointment-cleansing feature
tests/                   the regression suites
tools/                   build scripts
Material/                sample exports and sheets, used as fixtures
new_plan.py              compatibility shim -> DCA.plan_pdf
sabrina_compare.py       compatibility shim -> smile_partners.sabrina
```

## Choosing the client

Every request that runs client code names its client, and one that does not is
refused rather than defaulted — running DCA's rules against a Smile Partners
sheet would give a confident wrong answer instead of an error. The UI asks
first and unlocks nothing until it is answered.

`CLIENTS` in `main.py` is the single place that knows who exists and what each
can do:

```python
CLIENTS = {
    "dca":            {..., "supports": {"match", "notes", "new_plan", "parse_pdf"}},
    "smile_partners": {..., "supports": {"sabrina_audit", "parse_pdf"}},
}
```

`GET /api/clients` serves that list, and the dropdown is built from it — so
adding a client is one entry here plus a folder, with no change to the page.

## Running it

```bash
pip install -r requirements.txt
python main.py            # or start_server.bat
```

Then open <http://localhost:8000>.

## Tests

```bash
python tests/test_sabrina.py      # the Sabrina audit
python tests/test_regression.py   # plan matching and the PDF parsers
```

Both are plain scripts, not pytest, and print a pass/fail line per check. A
check that needs a fixture missing from `Material/` skips rather than fails, so
watch the skip count as well as the failures.

When changing how an export is read, prove the blast radius rather than
asserting it: run every export in `Material/**/*.json` through `_extract`
before and after, and diff. Ignore `appointment_date` — it is a clock value.
