# San Jose (CA) data repair — 2026-07-24

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for San Jose (first CA-sample jurisdiction lacking a repair script after LA / San Diego / Oakland). Wrote `agent/scripts/data_repair_ca_san_jose.py`. On the 1,997-row sample: 8 status fixes (Estimate→In Review); 31 permit fills + 235 permit fixes; 609 final fills + 17 final fixes (11 clears of spurious non-Final finals); FILE_DATE already 99.7% complete with no recoverable gaps. Residual Active/Final permit gaps and Final final-date gaps are mostly Closed/Completed/Approved-style rows without Issue Date or Final workflow stamps.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in `permits_ca_sample.parquet` first-appearance order. Los Angeles, San Diego, and Oakland already had repair scripts. **San Jose (CA)** was the first without `agent/scripts/data_repair_ca_san_jose.py`.

## DATA schema

City of San Jose permit-portal scrape wrapped as `{number, old, new}`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `new_details` | 1,758 | `new.details` / `process` / `process_dates` present |
| `old_only` | 239 | `new` empty; use `old.status`, `old.file_date`, `old.processing_status` |

Useful fields:
- Status: `new.details.Status` (prefer) else `old.status`
- File date: `new.details['Folder Date']` else `old.file_date`
- Permit date: `new.details['Issue Date']` and/or closed **Issuance Review** process step
- Final date: `new.details['Final Date']` else latest closed `*Final*` / Certificate of Occupancy / Closed Out process step

## Field assessment

### STATUS_NORMALIZED

Before: Final 985, Inactive 374, Active 369, In Review 269; **0 missing**.

Almost all raw statuses already mapped correctly into the four normalized buckets. One systematic error:

- **8 `Estimate` rows** were labeled Final. These are valuation/estimate folders with no Issue Date / issuance workflow → FIXED to **In Review**.

After: Final 977, Inactive 374, Active 369, In Review 277.

### FILE_DATE

5 missing (0.3%). Where populated, FILE_DATE matches Folder Date / `old.file_date` on all comparable rows. The 5 gaps have blank Folder Date and blank `old.file_date` (no alternate application date in DATA) → left missing. No FILLED/FIXED.

### PERMIT_DATE

563 missing. Ideal: populated for Active and Final.

Issues and repairs:
- Canonical stamp = **later of** `Issue Date` and closed **Issuance Review**. Issue Date is usually a few days after Issuance Review; but when Issue Date equals Folder Date and Issuance Review is later, Issue Date is a stale/placeholder stamp — taking the later value handles both cases.
- **235 FIXED** (all moved later): prior PERMIT_DATE matched Issuance Review while Issue Date was later (or vice versa when Issuance Review was the true later stamp).
- **31 FILLED** on Active/Final from Issue Date / Issuance Review.
- Remaining Active/Final gaps (134): mostly `Closed` (46), `Finaled` (30), `Completed` (23), `Approved` (16), `Under Inspection` (9) with neither Issue Date nor Issuance Review in DATA.

After repair, PERMIT_DATE coverage: Active 92.4%, Final 89.2%.

### FINAL_DATE

1,701 missing. Ideal: populated for Final.

Issues and repairs:
- Prefer `details['Final Date']`; else latest closed Final inspection / C of O / Closed Out step (rich `process` / `process_dates`, or lean `processing_status`).
- **609 FILLED** on Final rows (398+ from details.Final Date; remainder from Final process steps, including 81 lean-schema recoveries).
- **6 FIXED** where FINAL_DATE matched an earlier Building Final inspection but details.Final Date was later.
- **11 FIXED clears** of spurious FINAL_DATE on Active (3) / Inactive Expired (8).
- Remaining Final gaps (83): mostly `Closed` / `Completed` / `Complete` / `Legacy` / `Recorded` with no Final Date and no closed Final process step.

After repair, FINAL_DATE coverage on Final: **91.5%** (0% on non-Final, as required).

## Why some records stay incorrect / incomplete

1. **Estimate mislabeled as Final** — fixed by status remap; no dates expected beyond FILE_DATE.
2. **Issuance Review vs Issue Date drift** — prior pipeline used Issuance Review; official Issue Date often differs by 1–12 days (sometimes months when Issue Date was never updated). Repair uses the later stamp.
3. **Closed / Completed / Approved without issuance fields** — planning- or closure-style statuses often lack Issue Date and Issuance Review, so PERMIT_DATE cannot be recovered.
4. **Final without Final Date or Final inspections** — especially Closed/Completed folders and some lean stubs; no completion stamp in DATA.
5. **Blank file dates (5)** — Folder Date and `old.file_date` both empty; not inventing FILE_DATE from Issue Date (Issue Date on those rows can be decades earlier than the folder number year).

## Repair performance (n=1,997)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 8 | 0 → 0 |
| FILE_DATE | 0 | 0 | 5 → 5 |
| PERMIT_DATE | 31 | 235 | 563 → 532 |
| FINAL_DATE | 609 | 17 | 1,701 → 1,103 |

Post-repair coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: |
| Active | 341 / 369 (92.4%) | 0 / 369 (0%) |
| Final | 871 / 977 (89.2%) | 894 / 977 (91.5%) |
| In Review | 40 / 277 (14.4%) | 0 / 277 (0%) |
| Inactive | 213 / 374 (57.0%) | 0 / 374 (0%) |

FILE_DATE after repair: 1,992 / 1,997 (99.7%).

## Artifacts

- Repair script: `agent/scripts/data_repair_ca_san_jose.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/processed_data/permits_ca_san_jose_repaired.parquet`
