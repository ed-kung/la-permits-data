# Navasota (TX) data repair — 2026-08-20

**Summary:** Navasota was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. DATA is a CitizenServe-style portal payload in three shapes (`portal_full` 1,223; `portal_compact` 710; `portal_minimal` 67). Upstream STATUS was already correct except 5 In Review rows that already had Issue Date (Fixed → Active). FILE_DATE was often the Issue Permit Card Completion / Issue Date instead of earlier Plan/Application Review Start (21 Filled, 243 Fixed, 25 cleared as issue-date proxies). PERMIT_DATE already matched Issue Date wherever present (0 changes); Active/Final coverage is 100%. FINAL_DATE cannot be filled: the 3 Final (`Closed`) shells have no Pass inspections, and Issued rows with passed Final inspections remain Active per portal status.

## Jurisdiction selection

First pair in sample file order lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Navasota, TX** (n=2,000).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n |
| --- | ---: |
| portal_full_issued_finaled | 776 |
| portal_compact_issued | 626 |
| portal_full_issued | 269 |
| portal_full_status_only | 116 |
| portal_compact_status_only | 84 |
| portal_minimal_status_only | 67 |
| portal_full_applied | 57 |
| portal_full_finaled | 5 |

- **portal_full:** `Status:`, `Permit Details`, `Reviews`, `Inspections`
- **portal_compact:** `Status`, `Permit #`, `Issue Date` (no Reviews)
- **portal_minimal:** short form without Issue Date; `Status` often a work-description scrape

## Field assessment

### STATUS_NORMALIZED

| Portal status | n | Upstream |
| --- | ---: | --- |
| Issued | 1,648 | Active (correct) |
| Under Review / Online Application Received / Re-Submittal Required | 118 | In Review |
| Void / Denied | 103 | Inactive |
| Closed | 3 | Final |
| empty / work-description / shifted fields | 128 | null |

- **5 Fixed:** Under Review or Online Application Received with Issue Date → Active.
- **128 still missing:** empty `Status:` shells (60) and `portal_minimal` rows where `Status` holds project text (e.g. "New Construction"), not a portal lifecycle value. Left unrepaired.

### FILE_DATE

- Present before: 458 / 2,000 (all on `portal_full` with Reviews).
- Upstream often stored Issue Permit Card Completion or Issue Date rather than earlier Application/Plan Review Start.
- **Repair:** earliest non-issuance Review Start (else Completion) on/before Issue Date; clear FILE when no application Review source exists.
- After: **454 / 2,000** (21 FILLED, 268 FIXED including 25 clears). Compact/minimal have no Reviews → FILE stays missing.

### PERMIT_DATE

- Source: `Permit Details["Issue Date:"]` else top-level `Issue Date`.
- All non-null upstream values already matched Issue Date (**0 Fixed/Filled**).
- After repair: Active/Final **1,656 / 1,656 (100%)**; In Review **0 / 113** (the 5 that had Issue Date were reclassified Active).

### FINAL_DATE

- Missing on all 2,000 rows before and after.
- Proxy would be latest Pass/Complete/Approved inspection for Final only.
- All 3 `Closed` rows have empty Inspections → cannot fill.
- 507 `Issued` rows have passed Final inspections but remain Active (portal status authoritative).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 5 | 128 → 128 |
| FILE_DATE | 21 | 268 | 1,542 → 1,546 |
| PERMIT_DATE | 0 | 0 | 329 → 329 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

Ideal coverage after repair:

- FILE_DATE overall: 454 / 2,000 (22.7%)
- Active/Final PERMIT_DATE: 1,656 / 1,656 (100%)
- Final FINAL_DATE: 0 / 3 (0%)

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_navasota.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_navasota_repaired.parquet`
