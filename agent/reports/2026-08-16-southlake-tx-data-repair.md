# Southlake (TX) data repair

**Summary:** Southlake was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Georgetown). All 2,000 rows are CivicPlus / EnerGov-style case payloads (`entity_core` 1,964; `entity_rich` 36). STATUS_NORMALIZED had 6 missing values (`1st Letter Issued`) and 10 stale mappings vs `entity.CaseStatus`. FILE_DATE is already complete and matches ApplyDate. The repair fills 2 missing PERMIT_DATE values from IssueDate, fills 3 missing FINAL_DATE values on Closed/CO Issued rows, and clears 200 spurious FINAL_DATE values on non-Final rows. Active/Final PERMIT_DATE gaps that remain lack IssueDate in DATA (mostly contractor registration and earth disturbance / irrigation shells).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Southlake, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_southlake.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_southlake_repaired.parquet`

## DATA schema

Flat CivicPlus / EnerGov case object with nested `entity` (status + primary dates) and `details` (duplicate Apply/Issue/Finalize timestamps):

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_core | 1,964 |
| entity_rich | 36 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` | — |
| FILE_DATE | `entity.ApplyDate` | `details.ApplyDate` |
| PERMIT_DATE | `entity.IssueDate` | `details.IssueDate` |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` (Final only) |

## Field assessment

### STATUS_NORMALIZED

`STATUS_ORIGINAL` is usually the lowercased `CaseStatus`, but 10 rows lag while CaseStatus has already advanced, and 6 rows have null STATUS_NORMALIZED:

| CaseStatus | STATUS_ORIGINAL | Before | After | n | Flag |
| --- | --- | --- | --- | ---: | --- |
| 1st Letter Issued | 1st letter issued | (missing) | Inactive | 6 | FILLED |
| Closed | issued | Active | Final | 2 | FIXED |
| CO Issued | issued | Active | Final | 1 | FIXED |
| Expired | issued | Active | Inactive | 3 | FIXED |
| Issued | expired | Inactive | Active | 2 | FIXED |
| Issued | reviewed | In Review | Active | 1 | FIXED |
| Withdrawn | in review | In Review | Inactive | 1 | FIXED |

Status map used: Closed / CO Issued → Final; Issued / Renewed → Active; In Review / Incomplete / Submitted / Submitted - Online / Reviewed / On Hold / Stop Work Order → In Review; Withdrawn / Expired / 1st Letter Issued → Inactive. `1st Letter Issued` is a backflow notice-letter workflow (no IssueDate), mapped to Inactive.

After repair: Final 1,592; Inactive 195; Active 161; In Review 52; missing 0.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `entity.ApplyDate` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

380 missing before repair. When both PERMIT_DATE and IssueDate are present they always match. Two Issued/Closed rows had IssueDate but null PERMIT_DATE → FILLED. After repair, 378 remain missing because IssueDate is null in DATA.

Coverage after repair:

- **Active:** 60 / 161 (37.3%) — remaining gaps are almost all contractor registration / renewal shells (50 + 50) plus 1 backflow
- **Final:** 1,463 / 1,592 (91.9%) — remaining gaps concentrate in Earth Disturbance (43), Irrigation (32), Backflow (18), temporary banners (14), and similar shells without IssueDate

### FINAL_DATE

211 missing before repair. When both FINAL_DATE and FinalDate are present they match. Three Closed/CO Issued rows still labeled Active lacked FINAL_DATE despite carrying FinalDate → FILLED after status correction. Non-Final rows frequently carry FinalDate (often equal to ApplyDate as a portal stub, or the bulk historical stamp `2008-12-02T00:43:42Z`) → 200 spurious FINAL_DATE values cleared (FIXED).

After repair: Final 1,592 / 1,592 (100%); Active / In Review / Inactive all 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 6 | 10 | 6 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 0 | 380 → 378 |
| FINAL_DATE | 3 | 200 | 211 → 408 |

Missing FINAL_DATE increases because clearing spurious non-Final values outweighs the 3 fills; that is intentional.

Date-order violations after repair (inherited from agency timestamps, not introduced by repair): FILE>PERMIT=39 (mostly early-2000s Closed historical rows with IssueDate a few days before ApplyDate), PERMIT>FINAL=27, FILE>FINAL=2.

## Not repairable

- Active/Final rows with null IssueDate (contractor registration, earth disturbance, irrigation, etc.) → PERMIT_DATE stays missing.
- `processing_status` is null on nearly all sample rows → no inspection-based date fallback.
- Historical FinalDate cluster on `2008-12-02` is retained for Closed/CO Issued rows as the agency’s recorded final timestamp (likely a migration backfill).
