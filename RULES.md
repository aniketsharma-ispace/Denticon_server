# Toolkit comparator rules (Star and Smile Partners)

Rules marked **[11/04]** were added for the 11/04 Smile review (Premier Lite fee schedules; the not-required fields removed). Rules marked **[11/03]** were added for the 11/03 Smile review (out-of-network benefits). Rules marked **[11/02]** were added for the 11/02 Smile review. Rules marked **[NEW]** were added in version 10/28. Rules marked **[10/26]** and **[10/23]** were added in earlier versions. Rules marked **[CLARIFIED]** keep their meaning but state how the code applies them.

The rules live in each client’s `portals/delta_toolkit.py` (reading the Toolkit JSON) and `sabrina/carriers/delta_toolkit/` (the audit; Toolkit-only rules are in its `rules.py`), under `star_dental/` and `smile_partners/`.

## Star only

- **Out-of-network sheets [NEW]:** a sheet whose In Network is **Out** records the plan's **Nonparticipating Dentist** benefits, and is compared with them instead of the PPO ones. The audit's Toolkit legend names the network used.
  - A code's % (and its Not Covered status and waiting period) comes from its `out_of_network` entry naming Nonparticipating Dentist. A network the plan offers but no lookup lists separately shares the PPO bucket, so the PPO figure applies. A code with no entry while other codes have one is not comparable.
  - An Optional code inherits from a Nonparticipating sibling, then from that network's own category rows; PPO category rows are never used for it.
  - Maximums and deductibles come from the export's `out_of_network.maximums_and_deductibles` rows for that network, or from the PPO table when it names that network (`maximums_and_deductibles.networks`) or `maximums_shared_with_ppo` is set. Exports made before extension 1.45 hold the PPO table alone: the 10 maximum/deductible amount rows are then not comparable, with a note to re-export.
  - Any other In Network answer, or none, is compared with PPO Dentist as before.
- **Frequency alias:** “No Frequency” equals “Frequency not available” on the Toolkit path. If both sides use an alias it’s a match. If only one does and the other states a real limit, it’s a mismatch.
  - **[10/26]** “Pre-D” is not a limit. Pre-D against an alias is not comparable.
  - **[NEW]** A portal “Frequency not available” against a real sheet limit is not comparable: the Toolkit states no frequency sentence for that code, which is silence, not proof the sheet is wrong (e.g. a sheet 1X36Months for fillings). A sheet alias against a real portal limit, and a portal “No Frequency” against a real sheet limit, are still mismatches.
- **Portal frequency Not Covered/NC/N/C:** the row matches if the sheet says 0, 0%, NC, N/C, not covered, no frequency or none. Any other sheet value is not comparable.
- **Subscriber Age Limit:** a sheet value of 0 or 00 with a blank portal is a forced match.
- **Age limit “NC”:** a sheet “NC” with a blank portal is not comparable.
- **Payer ID:** compared as a set, split on , ; / |. DDPOH is treated as DDPO, and any overlap is a match.
- **Payer ID source:** the claim payer ID wins over the display field (e.g. 07000 over DDMN). The fallback is the site domain: deltadentalmi.com gives DDPMI, deltadentalin.com gives DDPIN, any other deltadental*.com gives DDPOH.
  - **[10/26]** When the claim payer ID lists several IDs (e.g. “DDPOH, DDPMI, DDPIN”), it is narrowed to one, the way Smile reads the payer: the ID the plan names in the display fields (payorId, payor_id, payor_plan_id, plan), else the one the website domain gives. If neither names an ID in the list, the whole list is compared as a set, as before.
- **CDT % blank on both sides:** it’s a match if the code was requested and didn’t fail in the crawl.
- **SRP Quads per day:**
  - The value comes from a D4341 limitation sentence that names quadrants plus same date/per day.
  - **[CLARIFIED]** On the Toolkit path, the sentence is taken from D4341’s own record or from any other place in the Toolkit JSON where a sentence names D4341 or scaling and root planing (e.g. `ortho_information.notes`).
  - The cap phrase must read “limited to / maximum of / no more than / up to” one to five.
  - If the Toolkit has nothing, it falls back to the embedded Delta PDF.
  - Both paths need exactly one distinct value, otherwise the row stays blank.
- **D0150 freq per provider [10/26]:** read from D0150’s own limitation sentences. A sentence scoped per provider/dentist/office/location/practice gives its frequency; otherwise the portal value is “Frequency not available”, compared under the frequency alias rule. Non-Toolkit exports are not read.
- **Eligibility Term Date [10/26]:** blank on both sides is a match when the Toolkit member is Active (no termination on either side). Otherwise it stays not stated.
- **Share-frequency confirmations:** D0120/D0140, D0210/D0330 and D1110/D4910.
  - Yes if both have the same counted frequency, No if they differ.
  - For D1110/D4910 with no perio frequency, it reads the prophy sentence: “in addition” gives No; a sentence naming periodontal maintenance/prophylaxes (or D4910) gives Yes. **[NEW]** A sentence that never mentions periodontal maintenance (“Prophylaxes (cleanings) are payable three times per calendar year.”) gives no answer, so a sheet value is not comparable (it used to be Yes).
  - **[NEW]** For D1110/D4910, a cleaning sentence that grants periodontal prophylaxes or maintenance on top of the cleanings (“Two additional periodontal prophylaxes are payable…”, “…in addition to periodontal maintenance”) gives No first, even when both counts are equal.
- **Posterior crown downgrade [10/23]:**
  - **No** if the JSON says “Posterior porcelain or resin crown(s) are covered services”. “Covered benefits” is read the same way.
  - **Yes** if the JSON says posterior porcelain or resin crowns are not covered.
  - Yes is also given for an explicit downgrade sentence: one that combines porcelain/ceramic/veneer, posterior/molar/bicuspid and full cast/optioned/alternate/downgrad, and isn’t a “covered” sentence.
  - Order of checks: not covered → Yes, then a downgrade sentence → Yes, then covered → No. Otherwise it stays blank.
  - Sentences are read from Exclusions and Limitations and from every code lookup’s limitations.
- **Age limits:** these come from orthoAgeLimitConfig filtered by the selected network.
  - Subscriber uses subscriberMaxAge.
  - Dependent uses minorMaxAge, then dependentMaxAge.
  - childMaxAgeLimit (26) is deliberately not used.
- **Family deductible:** if exported as 0 while the individual deductible is set, it’s derived as 3 × individual.
- **Frequency phrases added over Smile:**
  - D9110 matches only “emergency examinations/exams”.
  - D4341 matches either word order.
  - D6056/57/58 match “implants and/or the restorations”.
  - D9944 also matches “night guard/nightguard”.
  - **[10/26]** D1516 matches “space maintainers”, D2642 “cast restorations/onlays”, D2750 “cast restorations/crowns”, D6240 “bridgework”, and D9946 “occlusal guard/night guard/nightguard”. The 10/23 crawl attaches these sentences to the codes themselves.
- **“no age limitation” sentence:** it becomes 99.
- **D4910 frequency:** it is never inherited from D1110 (Smile does this).
- **Sheet constants:**
  - Age Limit rows exist only for D1206, D1208 and D1351.
  - History rows exist for 12 codes: D0120, D0140, D0150, D0210, D0274, D0330, D1110, D1206, D1208, D1351, D4341 and D4910.
  - 17 codes get no Frequency row: D3221, D3310, D3330, D3346, D3348, D4260, D4921, D7140, D7210, D7230, D7240, D7310, D7953, D8080, D8090, D8220 and D8680.
  - Critical keys include D0120, D2391 and D2740, plus term_date.
- **Parser:**
  - D2610 “Pre-D” printed in both the Frequency and % cells counts as the %.
  - Reversed labels like “Periodic Exam D0120” are matched by CDT token inside the Benefit Details table only.
  - Ortho Max and Used are paired from the two-header layout.
- **12 codes with no phrase:** D0367, D2610, D5511, D5650, D5810, D5821, D5912, D6104, D6190, D9612, D9630 and D9947 always come out as “Frequency not available” unless the source names the code directly. **[NEW]** A real sheet frequency on those rows (and on D4910, which never inherits) is not comparable; it used to show as a mismatch.

## Smile only

- **“Frequency Not Available” / “Not Available”:** equal only if both sides say it. There is no “No Frequency” alias.
- **SRP Quads per day [10/26]** (workbook “Smile Partner Dental” line 21): the sheet’s value is the number Sabrina prints in D4341’s Age Limit cell, shown as the row “D4341 Scaling Root Planing · Quads”. The portal value is only a same-day/per-day quadrant cap stated in the Toolkit JSON (e.g. “limited to two quadrants … on the same date of service”). A per-quadrant frequency (“once per quadrant in 24 months”) is not a cap. With no stated cap the portal side stays blank and **[NEW]** the Quads cell reads Not on portal (it was not comparable), so a D4341 whose percentage, frequency and history agree reads Match. The identity gate still makes it not comparable.
- **Age limit of a code the Toolkit marks Not Covered [NEW]:** the portal age reads “Not Covered”, as the code’s frequency already does. A sheet age of 0, 00, NC, N/C or Not Covered matches; a positive age is a mismatch; anything else is not comparable. A blank sheet age stays not stated.
- **When Is First Perio Maintenance Allowed After SRP? [10/26]** (workbook line 74): the portal value is only an N-day post-operative period stated in one of D4910’s own limitation sentences that names periodontal treatment, read as “N Days”. Otherwise the portal side stays blank and the row is not comparable; the sheet’s “Not available in web” is never matched against a blank portal.
- **D4910 frequency:** it inherits D1110’s frequency when D4910 has none. This is skipped if D4910 is Not Covered or the prophy sentence says “in addition to periodontal”.
- **Fallback CDT codes:** the first code the portal states wins. Toolkit is exact-code only. The sheet-to-portal fallbacks are:
  - D0220 → D0230
  - D0274 → D0272
  - D1206 ↔ D1208
  - D2160 → D2140
  - D2391 → D2331
  - D5212 → D5213
  - D6010 → D6194
  - D6750 → D6245
  - D7210 → D7240
  - D9243 → D9223 → D9222
  - D6057 → D6056
  - D6058 → D6065
  - Ortho: D8080 → D8090 → D8010
- **Plan-level % rows:** Preventative = D0120, Basic = D2160, Major = D2740. Smile also has a “Preventative in Yearly Max” row, which Star lacks.
  - **[CLARIFIED]** On the Toolkit path these read the exact code’s %. A Not Covered code gives 0%.
- **Sheet constants:**
  - Age Limit rows exist for D1206, D1208, D1351, D1510 and D8080.
  - History rows exist for the same 12 codes as Star plus D1510.
  - No Frequency rows for D3310, D7140, D7210, D9230, D9243, D8080 and D8090.
- **The D8080 age row** reads the plan-level ortho age instead of the procedure.
- **Fixed “DD INS” code set:** 59 codes. Any not already on the sheet are added as portal-only, Toolkit-only rows.
- **Payor ID:** the display field’s payorId wins, with plain ID comparison and no DDPO/DDPOH alias.
  - **[CLARIFIED]** The display field is read as `payorId` or `payor_id`.
- **Deductible and max:** there is no 3× family deductible rule.
- **Critical keys:** this list adds pct_prev, pct_basic and pct_major.
- **Not-required fields [11/04, replaces 11/02]:** Fee Schedule, Insurance Phone and Eligibility Term Date are not compared and no longer appear on the UI (the reviewer marked them not required; 11/02 had kept them, with the JSON side copied from Sabrina). The sheet's Fee Schedule is still read, because it decides which network's benefits are compared (below).
- **UI order [11/02]:** sections, fields and CDT rows follow the Sabrina PDF top to bottom: Patient/Subscriber (Relationship after Member ID, Eligibility last), Insurance, Maximums & Deductibles, Plan Provisions, Orthodontics, Clauses (Missing Tooth, Preventative in Max, Major Services Paid on Prep or Seat, Posterior Composites, Posterior Crowns, Perio After SRP), then the Benefit Details codes in Sabrina's order. D4381 Arestin is printed on the sheet but is not compared: the comparator audits the workbook's “Smile Partner Dental” code list.
- **Which network's benefits [11/03, extends the 11/02 Premier rule]:** the sheet decides, in this order:
  1. A Fee Schedule naming Premier (“MI - DD Prem Reg6”, “MI Delta Premier Region 6”) → the plan's **Premier Dentist** benefits. A bare “Pr” (“MI - DD LITE Pr Reg6”) is not Premier: those sheets carry the PPO figures. A Premier fee schedule on a sheet whose In Network says **Out** still compares Premier, and the In Network row is a mismatch naming the conflict.
     **[11/04]** A **Premier Lite** schedule is not Premier: it carries the **PPO Dentist** benefits (Anna Tucker, “MI Delta Premier Lite Region 4”, was compared under Premier). From the office's fee schedule table:
     - Premier benefits: “#4 MI - DD Prem Reg6”, “MI Delta Premier Region 6”, “MI Delta Premier Perio”, “#199 MI - DD Prem Perio”.
     - PPO benefits: “#3 MI - DD LITE Pr Reg6”, “MI Delta Premier Lite Region 6”, “MI Delta Premier Lite Perio”, “#99 MI Delta Premier Lite Region 4”, “#203 MI - DD PremLT Perio”.

     Lite is checked first, since these schedules also name Premier: the word “Lite”, or “Prem”/“Premier” followed by “Lite” or “LT”. A Premier Lite sheet whose In Network says Out is compared out of network, like any PPO sheet (rule 2).
  2. In Network **Out**, or a **UCR** fee schedule (“IL General UCR”, “James Island UCR”) → the plan's **Nonparticipating Dentist** (out-of-network) benefits. A UCR fee schedule on a sheet whose In Network says **In** is flagged the same way.
  3. Anything else → PPO Dentist, as before.

  The audit's Toolkit legend names the network used and what chose it.
  - A code's % (and its Not Covered status and waiting period) comes from its `out_of_network` entry naming that network. A network the plan offers that no lookup lists separately is paid from the PPO bucket, so the PPO figure applies. A code with no entry while other codes have one is not comparable. An Optional code falls back to that network's category rows.
  - Maximums and deductibles: Premier uses the PPO table unless the export lists Premier rows of its own. Out of network uses the export's `out_of_network.maximums_and_deductibles` rows for Nonparticipating Dentist, or the PPO table when it names that network (`maximums_and_deductibles.networks`) or `maximums_shared_with_ppo` is set. Otherwise (exports before extension 1.45) the 10 maximum/deductible amount rows are not comparable, with a note to re-export, as in Star.
  - An export with no `out_of_network` data at all (made before 10/23) cannot state Premier or out-of-network figures: it keeps the PPO comparison and the legend says to re-export.
- **History [11/02]:**
  - The Toolkit's routine **Exam** row (looked up as D0120) is the history of D0120, D0140 and D0150; its **Bitewings** row (looked up as D0272) is D0274's. A code with its own row keeps it. This reverses the earlier code-specific bitewing reading.
  - A routine row whose **Eligible** column reads Yes gives **NH**, whatever dates it or the code's own lookup list, and the panorex never takes a date from an eligible FMX row.
  - Every service date is kept, newest first and joined with “, ”, on the portal side. The sheet's wrapped History cell (“08/31/2026;” / “04/20/2026”) is read whole, so both sides show every date; history compares as sets of dates.
- **Posterior crowns [11/02]:** “Posterior porcelain or resin crowns are covered benefits/services” anywhere in the export (Exclusions and Limitations, or any code lookup's limitations) answers “Are Posterior Crowns Downgraded?” with **No**. Without it, an explicit downgrade sentence on D2740 still gives Yes; otherwise the answer stays blank. A sheet answer of “Not Available In Web” against a stated Yes/No is a mismatch: the website does state it.
- **Frequency wording [11/02]:** a count tied to the lifetime in any wording is a lifetime limit (“Limited to one per tooth per lifetime” → 1XLifetime, not only “once”); “once in any five consecutive calendar years” → 1X5Years.

## Shared Toolkit rules

- **Member ID:** read from memberAlternateId (the Toolkit's “Member Alternate ID”). A lone “N”, “N/A” or blank counts as absent. **[11/02]** Smile now reads it too; before, the Smile portal side was always blank.
- **Max vs deductible:** both rows share category “General”, so the max and ortho max require type == maximum. **[11/03]** Smile now does this too: Lisa Rawlinson's export lists the General deductible first, and it used to be read as a $50 annual maximum.
- **In Network [10/23]:**
  - It is **In** if the Fee Schedule in the Toolkit JSON contains “Delta Dental” or “Premier”.
  - It is **Out** if the Fee Schedule contains “UCR”. UCR is checked first, so “Delta Dental UCR” is Out.
  - The Fee Schedule is any JSON key named feeSchedule / fee_schedule / “Fee Schedule”, or a note line “Fee Schedule: …”.
  - With no Fee Schedule, or one with none of those words, In Network keeps the previous logic, which is the networks the coverage rows pay under.
- **Identity gate:**
  - Patient name, DOB, eligibility, group/client and the network must be exactly “PPO Dentist”. Any failure makes every row not comparable.
  - **[CLARIFIED]** Every one of these must be present on both sides and agree. A missing eligibility or group is a failure.
  - The name check passes if the Delta page inside the PDF prints the portal’s name and the sheet’s name is a subset of it.
  - **[NEW]** Names are compared with apostrophes removed: the Toolkit prints O’Callaghan as OCALLAGHAN. (An apostrophe used to split the name and drop the “O” as an initial, failing the gate for every row.)
- **Failed CDT lookup:** it is not comparable, never a mismatch.
  - **[CLARIFIED]** Codes the Toolkit lists in `codes_not_in_portal` are treated like failed lookups.
- **Portal blank with the sheet filled:** it is not comparable.
- **Frequency source:**
  - A sentence is used only if it names the code or contains a whitelisted phrase for that code. There is no category inheritance.
  - The “(which include…)” aside is stripped.
  - **[NEW]** The exam codes (D0120, D0140, D0150, D0180) take “oral exams” as well as “oral examinations”, e.g. “Oral exams rendered by general dentists and pedodontists are payable twice per calendar year.”
  - A Not Covered code gets “Not Covered”.
- **Frequency conversion:**
  - “once … lifetime” becomes 1XLifetime.
  - “no limitation/no frequency” becomes No Frequency.
  - Calendar/benefit/plan/contract year or period becomes X1Year.
  - Per date of service or per day becomes X1Day.
- **Age limit:** the highest age in the sentence wins. Only D1206, D1208, D1351 and D1510 have age phrases.
- **D1110/D1120:** they share a frequency only when both are covered.
- **“Optional” coverage:** it inherits the % of a numeric sibling in the same top-level category, then the category row.
- **History:**
  - It is read per exact code, with one exception:
  - **Radiograph history** (Star since 10/23, **[NEW]** for Smile): FMX and Pano share history when a sentence mentions both full mouth and panorex/panoramic. A blank D0330 takes D0210’s date (and the reverse); a code with its own date keeps it. Bitewings (D0272/D0274) are not shared.
  - Service dates come from the code’s own lookup (serviceDates / utilization_history) or its routine-procedure row.
  - A routine-procedure row with no dates becomes NH.
  - No row means not stated. A lookup’s `history_status: NO_HISTORY_ON_FILE` on its own is not turned into NH.
- **Waiting period:** active if the duration is greater than 0 and not satisfied, or the met-date is in the future.
- **Eligibility mapping:** active/eligible/yes/y gives Yes, and inactive/terminated/ineligible/no/n gives No.
- **Relationship mapping:** Subscriber becomes Self.
- **Major payment timing:** “seat date” gives Seat Date, and “prep” gives Prep Date.
- **No deductible:** “There is no deductible for this contract” sets every deductible to 0.
  - **[NEW]** So does a Maximums and Deductibles table that has rows but none of type Deductible: the table lists every accumulator the plan has. Exports made since 10/23 no longer carry the banner. An empty table says nothing.
- **Plan year start:** it is January when the accumulation type is calendar year.
- **Alternate benefit composite:** No only if “posterior composite resin restorations are covered services”, otherwise Yes.
- **Missing tooth clause:** Yes only if the “payment will be made to replace a tooth missing prior to the effective date” sentence is present.
- **OON benefits:** stated only if the notes say “non-participating” and “may be responsible for more than the percentage indicated”.
- **Deductible applies:** it is No when the deductible is 0 or the description exempts the category (“does not apply to…” or “except…”).
- **Ortho:**
  - Not covered if the % is “Not covered” or 0.
  - Payment timing is blanked when ortho isn’t covered.
  - Max type is “Lifetime” if isLifetime.
  - The age cap comes from the sentence “orthodontic age limit … covered for age N”. Otherwise it takes the highest positive cap for the “ppo dentist” network, then ortho_age_limit_under.

# Delta Dental of Missouri comparator rules (Smile Partners only) [10/30]

The rules live in `smile_partners/portals/delta_mo.py` (reading the export of providers.deltadentalmo.com, made by the extension’s `content_DD_MO.js`) and `smile_partners/sabrina/carriers/delta_mo/` (the audit, begun as a copy of `delta_dental/`; this portal’s own rules are in its `rules.py`). Star Dental has no Delta Dental of Missouri folder, so it refuses these exports.

- **Recognized by** `carrier: "DELTA_MO"` (or a source naming Delta Dental of Missouri) and a `coverage_levels` list. The plan’s own insurer is the carrier name (a “Delta Dental South Carolina” plan is served by this portal too); the carrier row compares the Delta Dental brand.
- **Network:** each coverage row states PPO, Premier and out-of-network percentages. An Out sheet reads the out-of-network ones, an in-network sheet whose fee schedule names Premier (not Premier Lite) reads Premier, anything else PPO. The export holds the PPO accumulators only, so an Out sheet’s maximums and deductibles are not on portal. **[11/02]** That includes the deductible paid to date and the orthodontic deductible, which used to read an invented 0.00. (The portal itself shows the Premier and Out of Network columns; `content_DD_MO.js` publishes only the PPO one.)
- **Not covered:** a requested code with `listed: false` is missing from the plan’s coverage table, which lists every procedure the plan pays for. It reads Not Covered, frequency NC, and its age is 0 where the sheet states one. A code absent from `coverage_levels` altogether (exports made before the code was requested) is not stated.
- **Frequency:** “N per Calendar/Benefit/Plan Year” is NX1Year, “N every K Months …” NXKMonths, “N every K Years” NXKYears, “N per Lifetime” NXLifetime, “N per Day” NX1Day. A listed code with no frequency is No Frequency. Any other wording is passed through and reads not comparable.
- **Age limit:** “0 to 18” is 0-18 (ceiling 18), “14+” is 14-99 (a floor, never “no limit”), none is 99. Orthodontic codes take the plan’s ortho age: “No age limit.” is 99, “Dependents through age 18.” is 18.
- **Date of birth:** the portal masks the year (“08/17/XXXX”). The year is the one that gives the stated age on the day the portal was read. The portal states no subscriber date of birth for a dependent; it is not on portal (the shared extraction would otherwise copy the patient’s).
- **History [11/02]:** each code’s history is the dates billed under that code. Nothing is shared by default: the coverage table states each code’s frequency on its own (“1 every 36 Months from the last date of service of the same treatment”), so a D0120 exam is not D0150 history and a full-mouth series is not panoramic history. Two codes share history only where a limitation in the export says they share a limit (“also applies to D0330”, “shared with D1208”, “combined with D0150”); a limitation that merely names another code is not enough. No export so far states one. (This replaced the fixed D0120/D0150/D0180, D0210/D0330 and D1206/D1208 groups.) A sheet listing more dates than the portal still agrees where the dates overlap, and a sheet NH is held to the frequency window, as on the Delta Dental path.
- **Maximums and deductibles:** read from the named accumulators (`amount`, `used`/`met`, `remaining`); exports made before `amount` take used + remaining, and the older row-list layout is read too. A table stating the annual maximum but no deductible means $0 deductibles. A family deductible the export does not state stays not stated (no 3× rule). An orthodontic deductible marked SHARED is not a separate one, so it is 0. **[11/02]** A plan whose member record reads Ortho coverage: No has an orthodontic maximum, used amount, deductible and deductible met of 0, in any network.
- **Deductible applies:** D0120 (preventive) and D0220 (diagnostic) state it per code: Yes is Yes, No or NA is No. A plan with no deductible is No for both.
- **Preventative Included in Yearly Max [11/02]:** the export’s own figures decide first. This benefit year, a paid Preventative-group service with nothing used from the annual maximum is No (Umar Aamer: MAXAdvantage “No”, five preventive services, $0 of $2,000 used); money used when only Preventative-group services were paid is Yes (Christine White: $378 of $500). Otherwise it follows the MAXAdvantage option: No when the plan has it (exams, cleanings, x-rays and fluoride do not count toward the maximum), Yes when it does not.
- **Missing tooth clause:** the member record’s Existing Tooth Clause Yes/No. **Waiting period:** the member record’s Yes/No.
- **Major paid on prep or seat:** Seat Date where D2740 is covered, as for Delta Dental. **Perio maintenance after SRP:** a post-operative period in D4910’s limitation, otherwise “Not available in website”.
- **Downgrades:** posterior composites are downgraded when the plan pays the amalgam (D2160) and not the composite (D2391), and not downgraded when it pays the composite. **[11/02]** A plan paying neither (Christine White’s preventive-only plan) leaves the question unanswered; it used to read Yes. Posterior crowns are not downgraded where D2740 is covered. (Delta Dental’s own path, `portals/delta_dental.py`, still has the old “unless both are covered” rule.)
- **Not on this portal:** payer ID, claims address, insurance phone and the D4341 quadrant cap. Those rows read not on portal.
