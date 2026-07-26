# El Dorado County (CA) data repair

**Summary:** Among CA sample jurisdictions, El Dorado County was the first `(JURISDICTION, STATE)` pair without a repair script. Its DATA JSON is a uniform civic-portal `permit_info` payload. `FILE_DATE` was already correct for all 2,000 rows. Status errors came from stale `STATUS_ORIGINAL` (7 FIXED). Twelve Active/Final `PERMIT_DATE` gaps were fillable from `PermitApprovedDate`; one Final `FINAL_DATE` was filled and one spurious Active `FINAL_DATE` was cleared. Remaining Final date gaps are mostly CLOSED/GREEN shells with blank Issued/Finaled fields in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **El Dorado County, CA** (2,000 rows) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_el_dorado_county.py`
- Artifact: `AGENT_DATA_PATH/el_dorado_county_repaired_sample.parquet`

## DATA schema

Every record has top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Canonical fields are under `permit_info`:

| DATA field | Target column |
| --- | --- |
| `PermitStatus` | `STATUS_NORMALIZED` |
| `PermitAppliedDate` | `FILE_DATE` |
| `PermitIssuedDate` (fallback `PermitApprovedDate`) | `PERMIT_DATE` |
| `PermitFinaledDate` (fallback finaling inspection `Completed`) | `FINAL_DATE` |

`INFERRED_SCHEMA` variants (same repair logic):

- `permit_info` — 1,303 rows
- `permit_info_with_notes` — 697 rows (adds optional `PermitNotes`)

## Field assessment

### STATUS_NORMALIZED

- **Missing:** 0 / 2,000
- **Correctness:** Mostly aligned with `PermitStatus`, but 7 rows used stale `STATUS_ORIGINAL` instead of current `PermitStatus`:
  - 5× `EXPIRED PERMIT` with `STATUS_ORIGINAL` in {issued, approved} → labeled **Active** (should be **Inactive**)
  - 1× `FINALED` with `STATUS_ORIGINAL=issued` → labeled **Active** (should be **Final**)
  - 1× `NONCOMPL` → labeled **In Review** while sibling `NON COMPLIANT` was already **Inactive**
- **Repair:** 0 FILLED, **7 FIXED**
- After: Final 1,554 · Inactive 225 · Active 116 · In Review 105

### FILE_DATE

- **Missing:** 0 / 2,000
- **Correctness:** Calendar-day match to `PermitAppliedDate` for all rows
- **Repair:** 0 FILLED, 0 FIXED (already complete)

### PERMIT_DATE

- **Missing before:** 275 / 2,000
- **Correctness:** Where both `PERMIT_DATE` and `PermitIssuedDate` exist (1,725), they always match. Gaps are rows with blank Issued.
- **Fillable:** 12 Active/Final rows have blank Issued but a usable `PermitApprovedDate`
- **Repair:** **12 FILLED**, 0 FIXED · missing after: 263
- Post-repair coverage: Active 100%; Final 94.9% (1,475 / 1,554)
- **Not fillable:** ~79 Final rows (mostly `CLOSED` / `GREEN` shells, plus a few `FINALED`) with neither Issued nor Approved in DATA

### FINAL_DATE

- **Missing before:** 550 / 2,000
- **Correctness:** Where both exist (1,450), they always match `PermitFinaledDate`. One Active `HOLD FINAL` row incorrectly carried `FINAL_DATE`.
- **Repair:** **1 FILLED** (FINALED remapped to Final → `PermitFinaledDate` / matching PERMIT FINAL** inspection), **1 FIXED** (cleared spurious Active `FINAL_DATE`)
- Net missing stays 550 (one fill + one clear), but Active FINAL coverage goes 1→0 and Final FINAL coverage improves for the remapped row
- Post-repair: Final 93.3% (1,450 / 1,554); Active / In Review / Inactive all 0%
- **Not fillable:** ~103 Final rows (`CLOSED`, `GREEN`, and 7 `FINALED` with blank Finaled and empty inspections) have no completion timestamp in DATA

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 7 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 12 | 0 | 275 | 263 |
| FINAL_DATE | 1 | 1 | 550 | 550 |

Root cause of status errors: pipeline normalized from `STATUS_ORIGINAL` (often an earlier lifecycle label like `issued`) rather than current `permit_info.PermitStatus`. Date fields that were populated were already consistent with DATA; remaining gaps reflect blank Issued/Finaled fields on closed or converted records, not mapping bugs.
