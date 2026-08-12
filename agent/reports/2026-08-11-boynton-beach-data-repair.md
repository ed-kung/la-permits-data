# Boynton Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (groupby encounter order after Margate) was Boynton Beach (2,000 records). DATA is a City portal family with only nested `Updated On` timestamps (`permit_single` 740 + `case_only` 636 + `permits_list` 624). STATUS_NORMALIZED: 712 FILLED + 32 FIXED (nulls 712→0). FILE_DATE: 26 FILLED + 911 FIXED to earliest Fees/Reviews `Updated On` (gaps 604→578). PERMIT_DATE: 181 FILLED from Issued permit stamps (was 100% missing; Active now 100%). FINAL_DATE: 637 FILLED from approved final/affidavit inspections or Finaled stamps (Final coverage 53.7%).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Boynton Beach, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/fl/data_repair_fl_boynton_beach.py`
- Artifact: `AGENT_DATA_PATH/boynton_beach_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `permit_single` | 740 | Top-level `Permit` object (often with `project_no`) |
| `case_only` | 636 | `Status` + `Process Type` only — no `Permit` / `Permits` |
| `permits_list` | 624 | Top-level `Permits` array, no singular `Permit` |

All rows share Fees / Reviews / Inspections / Contacts / Address / Project/Case. The only date-like field in DATA is nested `Updated On`.

## Field assessment

### STATUS_NORMALIZED

- Before: Final 813; null 712; Inactive 245; Active 148; In Review 82
- Upstream mapped from `STATUS_ORIGINAL` (mostly `Permit.Status` lowercased: finaled / issued / required / …). When that was blank, top-level `Status` was ignored → 712 nulls despite values like Completed, Submission in Progress, Abandoned, Review Cycle Disapproved.
- Canonical rule: `Finaled` → Final; case-level `Completed` outweighs permit still showing `Issued` (instant/affidavit permits); `Issued` → Active; top-level `Permit Issued` with `Permit.Status=Required` treated as In Review (portal lag); Abandoned / Withdrawn / Intake Rejected / Permit Expired / Voided / Expired → Inactive; review / submission / fees-pending states → In Review.
- **712 FILLED + 32 FIXED** (26 Active→Final on Completed+Issued instant permits; 4 Active→In Review on Review Cycle Approved; 2 Active→Inactive on Abandoned).
- After: Final 1,186; Inactive 347; In Review 317; Active 150; null 0

### FILE_DATE

- Ideal: populated for all records (application / submittal).
- Before: 604 missing. Among present values, many matched a mid-stream Reviews `Updated On` while earlier Fees timestamps existed (~872 rows with FILE after fee minimum; median lag ~10 days).
- Canonical: earliest Fees `Updated On`; else earliest Reviews; else (fill-only) earliest Permit/Inspections `Updated On`. Existing values earlier than the fee/review candidate are preserved.
- **26 FILLED + 911 FIXED.**
- Remaining 578 gaps are empty shells (no Fees/Reviews/Permit/Inspection dates): case_only 333 + permits_list 245.
- After coverage: Active 100%; Final 83.2%; In Review 44.5%; Inactive 41.5%

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Before: **2,000 / 2,000 missing** — issuance dates were never ingested.
- Source: `Permit` / `Permits[]` with Status `Issued` → `Updated On`. Finaled permits do not retain an Issued stamp, so most Final rows cannot be filled from DATA.
- **181 FILLED + 0 FIXED.**
- After: Active 150/150 (100%); Final 31/1,186 (2.6% — Completed+Issued instant/affidavit cases); In Review / Inactive 0%.

### FINAL_DATE

- Ideal: populated for Final.
- Before: **2,000 / 2,000 missing.**
- Source: latest Approved inspection whose Record Type matches final / FNL / closeout / certificate / TCO / affidavit; else Finaled Permit `Updated On`; else latest Approved inspection.
- **637 FILLED + 0 FIXED.**
- Not repairable: 549 Final shells with empty / non-approved inspection history (case_only 364 + permits_list 184 + 1 permit_single).
- After: Final 637/1,186 (53.7%); non-Final FINAL_DATE all null. PERMIT>FINAL inversions: 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 712 | 32 | 712 → 0 |
| FILE_DATE | 26 | 911 | 604 → 578 |
| PERMIT_DATE | 181 | 0 | 2,000 → 1,819 |
| FINAL_DATE | 637 | 0 | 2,000 → 1,363 |

Ideal-field coverage after repair (among non-null STATUS_NORMALIZED):

- FILE_DATE: 100% Active; 83.2% Final; 44.5% In Review; 41.5% Inactive
- PERMIT_DATE: 100% Active; 2.6% Final; 0% In Review / Inactive
- FINAL_DATE: 53.7% Final; 0% non-Final

Post-repair checks: all STATUS nulls resolved; FILE_DATE no longer anchored to late review stamps when fees exist; Active fully dated for FILE + PERMIT; Final FINAL_DATE filled wherever inspections/Finaled stamps exist; no PERMIT>FINAL inversions.

## Artifacts

- `agent/scripts/fl/data_repair_fl_boynton_beach.py`
- `AGENT_DATA_PATH/boynton_beach_repaired_sample.parquet`
