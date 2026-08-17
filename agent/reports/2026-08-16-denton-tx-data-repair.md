# Denton (TX) data repair

**Summary:** Denton was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 1,999 rows share one portal schema (`permit_info` / 39 blank-status `permit_info_unstated`). STATUS_NORMALIZED is now fully populated (48 FILLED, 33 FIXED for mis-normalized FINALED/CLOSED/ARCHIVED/etc.). FILE_DATE is 99.8% complete via Issued fallback on legacy rows. PERMIT_DATE gained 93 Approved/Issued fills and 1 Issued correction. FINAL_DATE gained 46 fills and cleared 39 spurious non-Final finals (plus 1 wrong Final date).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Denton, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` after existing TX repairs through Irving)
- Script: `agent/scripts/tx/data_repair_tx_denton.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_denton_repaired.parquet`

## DATA schema

Every record has top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`.

| INFERRED_SCHEMA | n |
| --- | ---: |
| permit_info | 1,960 |
| permit_info_unstated | 39 |

Canonical source fields in `permit_info`:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | PermitStatus | Finaled / Issued / Approved / Applied dates when status blank |
| FILE_DATE | PermitAppliedDate | PermitIssuedDate (legacy blank-Applied rows) |
| PERMIT_DATE | PermitIssuedDate | PermitApprovedDate |
| FINAL_DATE | PermitFinaledDate | latest approved/pass / APP W* inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

Prior distribution: Final 1,242 · Active 368 · In Review 194 · Inactive 147 · missing 48.

Most existing mappings were already correct (FINALED/CLOSED → Final, ISSUED/APPROVED/ACTIVE → Active, SUBMITTED/PENDING* → In Review, CANCELLED/EXPIRED/VOID/DENIED/REVOKED/INACTIVE → Inactive). Issues:

**Missing (48) — FILLED:**

| PermitStatus | n | Repair mapping |
| --- | ---: | --- |
| (blank) | 39 | Active (33 with Issued) or In Review (6 Applied-only) |
| * PENDING INTAKE | 8 | In Review |
| FINALED | 1 | Final |

**Incorrect (33) — FIXED:**

| PermitStatus | Prior → Correct | n |
| --- | --- | ---: |
| FINALED | Active → Final | 14 |
| FINALED | In Review → Final | 1 |
| CLOSED | Active → Final | 3 |
| ARCHIVED | In Review → Inactive | 12 |
| ISSUED | In Review → Active | 1 |
| CURRENT | In Review → Active | 1 |
| PENDING CO | Final → Active | 1 |

After repair: Final 1,260 · Active 387 · In Review 193 · Inactive 159 · missing 0.

### FILE_DATE

- When present (1,958), always matched `PermitAppliedDate` at day resolution.
- 37 missing — legacy blank-status rows with blank Applied; recoverable from `PermitIssuedDate`.
- 4 unrecoverable (no Applied/Issued/Approved): 2 INACTIVE, 1 CANCELLED, 1 EXTENDED PERMIT.
- After repair: 1,995 / 1,999 populated (99.8%).

### PERMIT_DATE

- When present with Issued (1,547), almost always matched `PermitIssuedDate`; 1 mismatch (utilities permit whose PERMIT_DATE was 2022-06-10 while Issued/Finaled were 2024-04-24) → FIXED to Issued.
- 451 missing before; 4 recoverable from Issued and 89 from Approved → FILLED (93).
- Remaining 358 gaps have neither Issued nor Approved in DATA (13 Active, 72 Final, plus In Review / Inactive where PERMIT is optional). Active gaps are mostly `ACTIVE` / `CURRENT` / `EXTENDED PERMIT` with no issue dates; Final gaps are FINALED/CLOSED with blank Issued and Approved.

### FINAL_DATE

- When present with Finaled on Final rows, nearly always matched `PermitFinaledDate`; 1 Final row had FINAL_DATE = Approved (2024-03-19) while Finaled was 2024-08-19 → FIXED.
- 46 Final rows missing FINAL_DATE filled from FinaledDate (including 19 status-corrected FINALED/CLOSED) or approved/pass / APP W* inspection Completed dates.
- 39 incorrect values on non-Final rows (Active ISSUED/APPROVED, In Review SUBMITTED, Inactive INACTIVE/CANCELLED that still carried PermitFinaledDate) → cleared (FIXED).
- 43 Final rows remain without FinaledDate or usable inspection Completed dates (mostly FINALED/CLOSED with empty or non-pass inspections).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 48 | 33 | 48 → 0 |
| FILE_DATE | 37 | 0 | 41 → 4 |
| PERMIT_DATE | 93 | 1 | 451 → 358 |
| FINAL_DATE | 46 | 40 | 789 → 782 |

After repair, by status:

- **FILE_DATE:** 1,995 / 1,999 (99.8%)
- **PERMIT_DATE:** Active 374/387 (96.6%), Final 1,188/1,260 (94.3%)
- **FINAL_DATE:** Final 1,217/1,260 (96.6%); non-Final all clear (0%)

## Not repairable

- 4 rows with no Applied or Issued date in DATA (FILE_DATE).
- 85 Active/Final rows with no Issued or Approved date in DATA (13 Active + 72 Final).
- 43 Final rows with neither FinaledDate nor approved/pass inspection Completed dates.
