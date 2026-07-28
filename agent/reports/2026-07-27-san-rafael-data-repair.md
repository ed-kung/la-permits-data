# San Rafael (CA) data repair

**Summary:** San Rafael was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the PAT civic-portal `DATA` JSON (`permit_info` / `inspections` / `search_data`). Status is now fully populated (**FILLED 12 · FIXED 13**): FINALED/COMPLETED rows mislabeled Active or In Review were corrected, EXPIRED→Active and NO FINAL→Final without a finaled date were fixed, and blank / INDEFINITE nulls were filled from status text and date evidence. `FILE_DATE` was already correct for 1,990 / 1,998 rows (**FILLED 1** from search Issue Date on a CANCELED shell). `PERMIT_DATE` missingness fell from **144 → 110** (**FILLED 34**), using `PermitApprovedDate` when Issued is empty; Active/Final coverage is **94.0% / 98.9%**. `FINAL_DATE` missingness fell from **538 → 509** (**FILLED 38 · FIXED 9**), filling from `PermitFinaledDate` and final/resale inspections, and clearing spurious finals on Inactive rows. Remaining gaps are empty VOID/UNDER REVIEW shells (FILE_DATE), Active rows with neither Issued nor Approved, and FINALED/COMPLETED* rows with no finaled date and no usable inspection completion.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **San Rafael, CA** (n=1,998)
- Script: `agent/scripts/ca/data_repair_ca_san_rafael.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/san_rafael_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share the same top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Sub-schemas reflect which `permit_info` dates are populated and whether inspections exist:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_complete_insp` | 1,147 | Applied + Issued/Approved + Finaled, with inspections |
| `permit_info_complete` | 304 | Applied + Issued/Approved + Finaled, no inspections |
| `permit_info_issued` | 288 | Applied + Issued/Approved, no Finaled |
| `permit_info_issued_insp` | 161 | Issued variant with inspections |
| `permit_info_application` | 56 | Applied only |
| `permit_info_application_insp` | 18 | Applied only with inspections |
| `permit_info_partial[_insp]` | 17 | Incomplete non-applied combinations |
| `permit_info_empty` | 7 | No usable permit_info dates |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (upgrade to Final when `PermitFinaledDate` set, unless inactive) |
| `FILE_DATE` | `PermitAppliedDate`; else search `Issue Date` / earliest fee `Paid Date` / Issued / Approved |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else approved final inspection; for COMPLETED* resales, latest completed resale inspection |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,505 · Inactive 338 · Active 107 · In Review 36 · missing 12

Issues:
1. **13 mis-normalized rows** relative to `PermitStatus` / finaled date:
   - FINALED → Active (8) → Final (7 of these also had `PermitFinaledDate` but null `FINAL_DATE`)
   - COMPLETED → Active / In Review (2) → Final
   - EXPIRED → Active (1) → Inactive
   - NO FINAL → Final without finaled date (1) → Active
   - PENDING with `PermitFinaledDate` → In Review (1) → Final
2. **12 null `STATUS_NORMALIZED`**: blank `PermitStatus` (9) and `INDEFINITE` (3). Filled from description / issuance / finaled evidence → In Review 7 · Active 2 · Final 2 · Inactive 1.

When present, `PermitStatus` maps cleanly:

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, COMPLETED* | Final |
| ACTIVE, APPROVED, NO FINAL | Active |
| UNDER REVIEW, APPLIED*, PROCESSING, PENDING, READY 2 ISSUE, … | In Review |
| EXPIRED*, CANCELED, VOID, WITHDRAWN, BUSINESS CLOSED | Inactive |

Non-inactive rows with `PermitFinaledDate` are upgraded to Final (covers INDEFINITE / PENDING close-outs).

**After:** Final 1,517 · Inactive 340 · Active 100 · In Review 41 · missing 0  
Flags: **FILLED 12 · FIXED 13**

### FILE_DATE

**Before:** 8 missing (0.4%).

- 1,990 rows already match `PermitAppliedDate` exactly (0 disagreements).
- 8 missing: mostly VOID / UNDER REVIEW shells with empty applied and issue dates.
- 1 CANCELED row fillable from `search_data['Issue Date']` (also matches fee paid / Issued).

**After:** 7 missing.  
Flags: **FILLED 1 · FIXED 0**

### PERMIT_DATE

**Before:** 144 missing (7.2%). Among Active/Final: 56 / 1,612 missing.

Root cause: upstream used only `PermitIssuedDate`. 46 rows have Approved but empty Issued (31 of them Final).

Repairs (Active / Final only):
1. Prefer `PermitIssuedDate`.
2. Else `PermitApprovedDate`.

**After:** 110 missing overall; Active 94/100 (94.0%), Final 1,500/1,517 (98.9%).  
Remaining Active gaps (6) have neither Issued nor Approved.  
Flags: **FILLED 34 · FIXED 0**

### FINAL_DATE

**Before:** 538 missing (26.9%). Among Final: 57 / 1,505 missing. 10 non-Final rows carried a `PermitFinaledDate`-backed FINAL_DATE (8 EXPIRED, 1 CANCELED, 1 PENDING).

Repairs:
1. Clear FINAL_DATE when effective status ≠ Final (**FIXED 9** Inactive).
2. For Final rows, prefer `PermitFinaledDate` (**FILLED 7**, mostly former FINALED→Active).
3. Else approved final-titled inspection, or for COMPLETED* / RESALE types a completed resale inspection (**FILLED 31**).

**After:** 509 missing overall; Final 1,489/1,517 (98.2%); Active/In Review/Inactive all 0%.  
Remaining Final gaps (28): FINALED 12 · COMPLETED 10 · COMPLETED B/C 6 with no finaled date and no usable inspection completion.  
Flags: **FILLED 38 · FIXED 9**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 13 | 12 → 0 |
| FILE_DATE | 1 | 0 | 8 → 7 |
| PERMIT_DATE | 34 | 0 | 144 → 110 |
| FINAL_DATE | 38 | 9 | 538 → 509 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_san_rafael.py`
- Repaired sample: `AGENT_DATA_PATH/san_rafael_repaired_sample.parquet`
