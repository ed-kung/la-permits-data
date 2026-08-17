# Pearland (TX) data repair

**Summary:** Pearland was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 1,998 rows share one portal schema (`permit_info`). STATUS_NORMALIZED was missing on 2 uncommon statuses (now filled); FILE_DATE was already complete and correct; PERMIT_DATE gained 478 fills from `PermitApprovedDate` when Issued was blank; FINAL_DATE gained 48 fills from approved inspections and 1 spurious Active-row final date was cleared.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Pearland, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_pearland.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_pearland_repaired.parquet`

## DATA schema

Every record has top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. `INFERRED_SCHEMA` is `permit_info` for all 1,998 rows (PermitStatus always populated).

Canonical source fields in `permit_info`:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | PermitStatus | — |
| FILE_DATE | PermitAppliedDate | — |
| PERMIT_DATE | PermitIssuedDate | PermitApprovedDate |
| FINAL_DATE | PermitFinaledDate | latest APPROVED / APPROVED W/ EXCEPTN inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

| PermitStatus | n | Prior STATUS_NORMALIZED |
| --- | --- | --- |
| CLOSED | 1,586 | Final |
| FINALED | 225 | Final |
| ISSUED | 143 | Active |
| CO | 25 | Final |
| SUBMITTED | 8 | In Review |
| APPROVED | 5 | Active |
| UNDER REVIEW | 2 | In Review |
| CERT OF COMPLETION | 1 | Final |
| EXPIRED | 1 | Inactive |
| APPROVED, FEES DUE | 1 | **missing** |
| ACTIVATED | 1 | **missing** |

Existing mappings were correct. The two nulls were unmapped uncommon statuses: `APPROVED, FEES DUE` → In Review (approved but not issued), `ACTIVATED` → Active.

### FILE_DATE

Fully populated (0 missing). All 1,998 values match `PermitAppliedDate` at day resolution. No fills or fixes.

### PERMIT_DATE

- When present (1,376), always matched `PermitIssuedDate`.
- 622 missing before repair; 478 of those had blank Issued but a usable `PermitApprovedDate` (mostly CLOSED/Final rows where the portal never stored Issued).
- Remaining gaps: 140 Final + 1 Active with neither Issued nor Approved in DATA (no recoverable source).

### FINAL_DATE

- When present (1,684), always matched `PermitFinaledDate`.
- 154 Final rows missing FINAL_DATE with blank FinaledDate; 48 recoverable from approved inspection completion dates; 106 remain without a date source (often empty inspections).
- 1 incorrect value: Active/ISSUED garage-sale permit `GS18-01295` carried `PermitFinaledDate` / FINAL_DATE while status stayed Active → cleared (FIXED).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 2 | 0 | 2 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 478 | 0 | 622 → 144 |
| FINAL_DATE | 48 | 1 | 314 → 267 |

After repair, by status:

- **PERMIT_DATE:** Active 148/149 (99.3%), Final 1,697/1,837 (92.4%)
- **FINAL_DATE:** Final 1,731/1,837 (94.2%); non-Final all clear (0%)

## Not repairable

- 141 Active/Final rows with no Issued or Approved date in DATA.
- 106 Final rows with neither FinaledDate nor approved inspection Completed dates.
