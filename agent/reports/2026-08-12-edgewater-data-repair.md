# Edgewater (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Edgewater**. DATA is a sparse eGov WebPermits payload (`Address` / `Inspections` / `Parent Permit` / `Permit Number`, usually `Application Status`; 24 rows also have `Fees Due`). Upstream mapped only `PermitExpired` → Inactive and left the other 200 statuses null; `FILE_DATE` and `PERMIT_DATE` were entirely missing; `FINAL_DATE` was sparsely filled from Building Final `Scheduled Date` values that often included Disapproved attempts and ignored trade Final* approvals. The repair filled 200 statuses and fixed 1,417 Expired→Final upgrades, filled 1,973 `FILE_DATE` and 1,499 `PERMIT_DATE` values from the Permit Number YYMMDD stamp, filled 1,060 `FINAL_DATE` values and fixed 61 (disapproved-date corrections + non-Final clears). After repair: STATUS 100%; FILE_DATE 98.6%; Active/Final PERMIT_DATE 100%/100%; Final FINAL_DATE 100%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Edgewater, FL** → `agent/scripts/fl/data_repair_fl_edgewater.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `webpermits_status_issued_finaled` | 1,501 | Application Status + PN stamp + passed Final* |
| `webpermits_status_applied` | 312 | Status + PN stamp, no issuance/final evidence |
| `webpermits_status_issued` | 74 | Status + PN stamp + passed non-final inspection |
| `webpermits_nostatus_applied` | 58 | No Application Status; PN only |
| `webpermits_fees_shell` | 19 | Fees Due; PN stamp `00000000` |
| `webpermits_nostatus_issued` | 15 | No status; passed non-final inspection |
| `webpermits_nostatus_issued_finaled` | 8 | No status; passed Final* |
| `webpermits_status_shell` | 8 | Status present; no usable PN stamp |
| `webpermits_fees_applied` | 4 | Fees Due + PN stamp |
| `webpermits_fees_issued` | 1 | Fees Due + issuance evidence |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Application Status`, with Final/Active inference from passed inspections for PermitExpired / PermitStatusNotOK / blank status |
| FILE_DATE | YYMMDD embedded in `Permit Number` (`…YYMMDD00`; `00000000` → null) |
| PERMIT_DATE | Same PN stamp for Active / Final (no distinct issue-date field) |
| FINAL_DATE | Latest passed Final* inspection `Scheduled Date` |

## Field assessments

### STATUS_NORMALIZED

| Application Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| PermitExpired | 1,800 | Inactive | **Incorrect when a passed Final\* inspection exists** (1,417) → Final; remainder Inactive |
| *(blank / missing key)* | 81 | **null** | Fill from inspections / PN stamp (Final / Active / In Review) |
| PermitStatusNotOK | 67 | **null** | Fill → Final if passed Final*, else Active if issued evidence, else In Review |
| PermitCanceled | 28 | **null** | Fill → Inactive |
| PermitFeesDue | 9 | **null** | Fill → In Review |
| PermitNotIssued | 8 | **null** | Fill → In Review (label forced even when inspections exist) |
| PermitNoContractor | 6 | **null** | Fill → In Review |
| PermitOnHold | 1 | **null** | Fill → In Review |

**Root causes:**
1. Upstream mapper only handled `permitexpired` → Inactive; every other `STATUS_ORIGINAL` value was left null.
2. Edgewater’s portal dump labels many completed trade/building permits `PermitExpired` even after an approved Final* inspection — treating all Expired as Inactive drops the Final lifecycle and blocks `FINAL_DATE` coverage.

**Repair performance:** FILLED 200, FIXED 1,417; missing 200 → 0.

### FILE_DATE

- Before: missing on **2,000 / 2,000**. DATA has no Apply/Received/Submittal field.
- `Permit Number` encodes a calendar stamp as the last six digits before a trailing `00` (e.g. `MECH00017741014092600` → 2014-09-26). Parse succeeds for 1,973 rows; 27 rows use `00000000` (mostly Fees Due / On Hold / StatusNotOK shells).
- PN stamp precedes the earliest non-cancelled inspection on 1,597 / 1,613 comparable rows → usable as application / record-creation proxy.

**Repair performance:** FILLED 1,973, FIXED 0; missing 2,000 → 27 (98.6% coverage). Active/Final 100%.

### PERMIT_DATE

- Before: missing on **2,000 / 2,000**. No Issue Date field exists in DATA.
- For Active / Final rows the PN stamp is reused as the best available issuance proxy (same value as `FILE_DATE`). Cleared / kept null for In Review and Inactive.
- Three Final rows have PN stamp a few days–weeks after the approved Final* inspection (agency numbering quirk); left as-is.

**Repair performance:** FILLED 1,499, FIXED 0; missing 2,000 → 501. Active 100%; Final 100%; In Review 0%.

### FINAL_DATE

- Before: present on **432 / 2,000**, almost entirely from Building Final (`199`) `Scheduled Date`, including **47 Disapproved** Building Final dates and a handful of Pool / Driveway / Stormwater / Fence finals. Trade-only Final* approvals (MECH / ELEC / ROOF / etc.) were ignored → large false gap.
- After status repair, Final rows get the latest **passed** Final* inspection date; spurious finals on non-Final rows are cleared.

**Repair performance:** FILLED 1,060, FIXED 61; missing 1,568 → 521. Final coverage 100% (1,479 / 1,479). Active / In Review / Inactive FINAL_DATE all 0% after cleanup.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_edgewater.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_edgewater_repaired.parquet`
