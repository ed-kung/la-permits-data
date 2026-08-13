# Fernandina Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Fernandina Beach**. DATA is Tyler EnerGov JSON (`entity` / `details` / `fees` / `processing_status`, with a small `energov_full` subset). Upstream `STATUS_NORMALIZED` was driven by a stale `STATUS_ORIGINAL` that disagrees with live `CaseStatus` on 58 rows, leaving 12 statuses null and mislabeling 28 `Complete` records away from Final. After repair: STATUS 100% non-null and aligned with `CaseStatus`; `FILE_DATE` unchanged at 100%; Active/Final `PERMIT_DATE` 100%/99.9%; Final `FINAL_DATE` 100%. The only Active/Final `PERMIT_DATE` gap is one `Complete` shell with blank `IssueDate`.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Fernandina Beach, FL** → `agent/scripts/fl/data_repair_fl_fernandina_beach.py` (2,001 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,208 | Apply + Issue + Final dates |
| `energov_issued` | 389 | Apply + Issue, no Final |
| `energov_finaled` | 168 | Apply + Final, no Issue |
| `energov_applied` | 80 | Apply only |
| `energov_full_issued` | 69 | extras + Issue |
| `energov_full_issued_finaled` | 40 | extras + Issue + Final |
| `energov_full_applied` | 24 | extras + Apply only |
| `energov_full_finaled` | 23 | extras + Final, no Issue |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` / `details.ApplyDate` |
| PERMIT_DATE | `entity.IssueDate` / `details.IssueDate` |
| FINAL_DATE | `entity.FinalDate` / `details.FinalizeDate`; else latest passed final-ish `processing_status` inspection |

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Complete | 1,206 | Final 1,178 / Active 24 / Inactive 3 / In Review 1 | **28 incorrect** — should be Final |
| Issued | 224 | Active 217 / In Review 6 / Inactive 1 | **7 incorrect** |
| Expired | 255 | Inactive 241 / Active 11 / In Review 2 / … | **mostly Inactive; 14 wrong** when `STATUS_ORIGINAL` stale |
| Void | 198 | Inactive 195 / In Review 2 / null 1 | mostly OK |
| Void -Duplicate | 7 | **null** | Fill → Inactive |
| Awaiting Corrections | 4 | **null** | Fill → In Review |
| In Review / On Hold / Fees Due / Fees Paid / Submitted - Online / Stop Work Order | 93 | In Review (with a few stale mismatches) | Fill/fix to In Review |
| Denied / Withdrawn / Plan Approval Expired | 14 | Inactive | OK |

**Root causes:**
1. `STATUS_ORIGINAL` is stale relative to live EnerGov `CaseStatus` / `PermitStatus` on **58** rows (e.g. `STATUS_ORIGINAL=issued` while `CaseStatus=Complete`). Upstream normalization followed the stale label.
2. Unmapped statuses `Void -Duplicate` and `Awaiting Corrections` were left null.

**Repair performance:** FILLED 12, FIXED 54; missing 12 → 0. After: Final 1,206 / Inactive 474 / Active 224 / In Review 97.

### FILE_DATE

- Before: present on **2,001 / 2,001**.
- Calendar day matches `entity.ApplyDate` (= `details.ApplyDate`) on every row.
- No fills or fixes needed.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100%).

### PERMIT_DATE

- When present, always matched `IssueDate` (no incorrect non-null values).
- Filled 7 rows that had `IssueDate` but null `PERMIT_DATE` (mostly Issued/Complete shells labeled In Review).
- Cleared 8 spurious In Review `PERMIT_DATE` values.
- After repair, Active/Final still missing `PERMIT_DATE`: **1** — a `Complete` row with blank `IssueDate` and `details.Issued=false` (not recoverable from DATA).

**Repair performance:** FILLED 7, FIXED 8; missing 302 → 303. Active 100%; Final 99.9%; In Review 0%.

### FINAL_DATE

- Before: present on **1,382 / 2,001**, including **204** on non-Final statuses (mostly Expired / Void) and **28** `Complete` shells that lacked `FINAL_DATE` because they were mislabeled Active/Inactive/In Review.
- After status repair, every Final row has `FinalDate` / `FinalizeDate`; non-Final finals are cleared.
- `processing_status` is populated for many rows but was not needed for Final coverage in this sample (all Complete rows already carry `FinalDate`).

**Repair performance:** FILLED 28, FIXED 204; missing 619 → 795 (rise from intentional non-Final clears). Final coverage 100% (1,206 / 1,206).

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 54 | 12 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 7 | 8 | 302 → 303 |
| FINAL_DATE | 28 | 204 | 619 → 795 |

Post-repair coverage:

- `FILE_DATE`: 100% all statuses
- `PERMIT_DATE`: Active 100%, Final 99.9%, In Review 0%, Inactive 56.8%
- `FINAL_DATE`: Final 100%; other statuses 0%

Agency date-order quirks left as-is: 2 rows with `FILE_DATE` > `PERMIT_DATE`, 2 with `PERMIT_DATE` > `FINAL_DATE` (both dates taken from EnerGov).

## Mapping used

| CaseStatus | STATUS_NORMALIZED |
| --- | --- |
| Complete | Final |
| Issued | Active |
| In Review, On Hold, Fees Due, Fees Paid, Submitted - Online, Stop Work Order, Awaiting Corrections | In Review |
| Expired, Void, Void -Duplicate, Denied, Withdrawn, Plan Approval Expired | Inactive |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_fernandina_beach.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_fernandina_beach_repaired.parquet`
