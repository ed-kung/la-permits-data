# Santa Monica (CA) data repair — 2026-07-24

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Santa Monica (first LA-sample jurisdiction lacking a repair script). Wrote `agent/scripts/data_repair_ca_santa_monica.py`. On the 2,000-row sample: 35 status fixes, 51 permit fills + 2 permit fixes, 38 final fills + 17 final fixes; FILE_DATE already complete and correct. Large residual date gaps are mostly **pre–Accela migration stubs** (2009–2014 records with status/date but empty workflows), plus smaller pockets of incomplete or out-of-sync Accela filings.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in `permits_la_sample.parquet` order. All earlier CA cities already had `agent/scripts/data_repair_ca_*.py`. **Santa Monica (CA)** was the first without one.

## DATA schema

Accela Citizen Access scrape (same family as Santa Clarita / Monterey Park). Three key-set variants:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `tasks_full` | 1,988 | tasks + inspections + fees_details + conditions + related_records |
| `tasks_basic` | 10 | core keys only (no inspections/fees/contacts) |
| `tasks_contacts` | 2 | contacts + address_lines, no inspections/fees |

Useful fields: `status`, `date` / `search_data.Date`, workflow `tasks[].events` (`Marked as`, `on`).

Santa Monica differs from Santa Clarita on issuance: permits are marked **`Ready to Issue` / `Issued`** (663 events), not `Permit Issuance` (only 3 tasks).

## Field assessment

### STATUS_NORMALIZED

Before: Final 939, Inactive 567, In Review 335, Active 142, missing 17.

Issues:
- **23 seismic notices** (`Notice Issued`, `Retrofit Notice Issued`) labeled Final; these are open retrofit-program notices → should be Active.
- **12 stale STATUS_ORIGINAL** rows where `DATA.status` advanced (e.g. issued→Finaled/Expired/C of O; received→Issued; vacant→Inactive).
- **17 blank** `DATA.status` / search Status → not fillable.

### FILE_DATE

0 missing; all 2,000 match `DATA.date`. No repairs.

### PERMIT_DATE

1,263 missing. Ideal: populated for Active and Final.

- Canonical source `Ready to Issue` / `Issued|Re-Issue` present on 629 rows; existing PERMIT_DATE matched when present.
- Fillable gaps: Issued/Finaled rows with Application Submittal / Issued; Approved address-assignment / special-inspector rows with Application Review|Review / Approved; some City Report / Request Review / Issued.
- Not fillable: ~347 Final FINAL/COMPLETE/CLOSED stubs (2009–2014, empty tasks); 25 Active City Report / Special Inspector rows with only TBD events.

### FINAL_DATE

1,489 missing. Ideal: populated for Final.

- `Inspections` / `Finaled` (latest) is canonical; 11 rows used an earlier Finaled → fix to latest.
- Fillable: 15 Closed seismic (`Closed` / `Closed*`), 20 Express `Complete` (`Application Submittal` / `Complete`), a few Finaled/C of O.
- 6 spurious FINAL_DATE on non-Final (Expired / Received / Review Completed) → cleared.
- Not fillable: 225 FINAL + 122 COMPLETE + 4 CLOSED + 25 Finaled with no Finaled/C of O Issued/Closed events.

## Why so much data is missing

The residual gaps are not primarily scrape failure. Patterns in the sample point to a **system cutover around 2014–2015**, with a few smaller Accela quirks on top.

### Pre–Accela migration stubs (main cause)

**585 rows (29%) have zero workflow events, and every one is filed 2009–2014.** Their statuses are almost all ALL-CAPS legacy labels (`FINAL`, `COMPLETE`, `EXPIRED`, `CLOSED`, `PAID`, `PENDING`, `WITHDRAW`, `VACANT`) that essentially disappear after 2014. From 2015 onward the portal uses title-case statuses (`Finaled`, `Issued`, `Received`, …) and **every** row has task events.

| File-year band | n | Share with empty task events | Dominant statuses |
| --- | ---: | ---: | --- |
| 2009–2014 | 678 | 86.3% | `FINAL`, `Expired`/`EXPIRED`, `COMPLETE`, … |
| 2015–2019 | 632 | 0.0% | `Finaled`, `Expired`, `Review Completed`, … |
| 2020–2026 | 690 | 0.0% | `Finaled`, `Issued`, `Expired`, `Received`, … |

That break is too clean to be coincidence: older permits were likely **bulk-loaded into Accela with header fields** (`status`, `date`, record type, often fees) **but without the historical task/inspection timeline**. So `PERMIT_DATE` / `FINAL_DATE` cannot be recovered from `DATA` even though the record exists. Empty-workflow rows are concentrated in Commercial Building Permit and a few e-permit / city-report types.

### Smaller pockets (different causes)

- **Blank status (17 rows):** mostly 2015–2016 filings with only a TBD Application Submittal placeholder and empty search Status — incomplete/abandoned Accela records, not migrated history.
- **Finaled but no usable Finaled event (~25):** Accela status advanced (or set by staff) without a matching Inspections / Finaled click — status and workflow out of sync. Some have only `Application Submittal:Ready to Issue` or TBD/Notes.
- **Active City Report / Special Inspector with TBD only (~25 after repair):** record types that do not use the Ready-to-Issue path, so issuance dates were never written into tasks.

**Bottom line:** most “so much missing” is legacy permits that survived the Accela cutover as **shells**, not full workflow histories.

## Repair performance (n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 35 | 17 → 17 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 51 | 2 | 1,263 → 1,212 |
| FINAL_DATE | 38 | 17 | 1,489 → 1,457 |

Status after: Final 919, Inactive 570, In Review 330, Active 164, missing 17.

Coverage after repair:
- FILE_DATE: 100%
- PERMIT_DATE: Active 84.8%, Final 53.3%
- FINAL_DATE: Final 59.1%; 0% on non-Final (spurious cleared)

## Artifacts

- Script: `agent/scripts/data_repair_ca_santa_monica.py` (`data_repair`)
- Output: `$AGENT_DATA_PATH/processed_data/permits_ca_santa_monica_repaired.parquet`
