# Ocoee (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Ocoee**. DATA is a flat city-portal payload (`Status`, `Submission Date`, `Expiration Date`, optionally `Completed Date` / `CO Date`). Upstream left 1 null `STATUS_NORMALIZED` and 33 stale statuses where `STATUS_ORIGINAL` lagged live `Status`. `FILE_DATE` already matched `Submission Date` on all 2,000 rows. `PERMIT_DATE` is entirely missing and **cannot** be filled — DATA has no issue/approval date. `FINAL_DATE` was almost entirely a copy of `Expiration Date` (not a completion date); repair cleared 1,625 spurious finals and filled 21 true `Completed Date` / `CO Date` values. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 1.3% (residual Final gaps lack Completed/CO in DATA).

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Ocoee, FL** → `agent/scripts/fl/data_repair_fl_ocoee.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `portal_basic_submitted` | 1,892 | Core 7 keys only |
| `portal_extended_city_rev_submitted` | 57 | + Completed/CO keys, City, Revision Number (dates blank) |
| `portal_extended_submitted` | 23 | + Completed/CO keys (dates blank) |
| `portal_extended_city_rev_completed` | 14 | Real Completed Date |
| `portal_extended_city_submitted` | 7 | + City |
| `portal_extended_completed` | 6 | Real Completed Date |
| `portal_extended_city_rev_completed_co` | 1 | Completed Date + CO Date |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status` |
| FILE_DATE | `Submission Date` |
| PERMIT_DATE | *(none — not present in DATA)* |
| FINAL_DATE | `Completed Date` (fallback `CO Date`) |

Status → normalized: Completed → Final; Issued / Approved → Active; In Process → In Review; Voided / Rejected / Expired → Inactive.

## Field assessments

### STATUS_NORMALIZED

| DATA Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Completed | 1,659 | Final (1,639); Active (17); Inactive (1); In Review (1); null (1) | Fix/fill 20 → Final |
| Issued | 131 | Active (123); In Review (4); Inactive (2); Active via Approved STATUS_ORIGINAL (2) | Fix 6 → Active |
| Voided | 108 | Inactive (105); In Review (2); Active (1) | Fix 3 → Inactive |
| In Process | 47 | In Review | Correct |
| Rejected | 38 | Inactive | Correct |
| Approved | 12 | Active (9); Inactive (2); In Review (1) | Fix 3 → Active |
| Expired | 5 | Inactive (3); Active (2) | Fix 2 → Inactive |

**Root cause:** Upstream normalized from `STATUS_ORIGINAL`, which lagged the live portal `Status` (e.g. Completed still stored as issued/approved/in process/rejected; awaitingcompletion left unmapped → null).

**Repair performance:** FILLED 1, FIXED 33; missing 1 → 0. After: Final 1,659; Inactive 151; Active 143; In Review 47.

### FILE_DATE

Ideal: populated for all records.

- Before: present on **2,000 / 2,000**; every value matches `Submission Date` at day resolution.
- **0 FILLED, 0 FIXED.** Coverage remains 100% across all statuses.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before/after: **0 / 2,000** present.
- DATA keys never include an issue, approval, or permit-issuance date (only Submission / Expiration / optional Completed / CO).
- **0 FILLED, 0 FIXED.** Not repairable from DATA.
- Residual Active/Final gaps: all 143 Active + 1,659 Final (Issued / Approved / Completed shells).

### FINAL_DATE

Ideal: populated for Final records.

- Before: 1,625 non-null. Of Final rows with FINAL_DATE and no Completed/CO (1,518), **100% equaled `Expiration Date`**. Active (56) and Inactive (51) also carried FINAL_DATE almost entirely equal to Expiration — expiration is not a completion/sign-off date.
- Extended schema rows with real `Completed Date` (21) all had **null** FINAL_DATE upstream.
- **21 FILLED** from `Completed Date` (1 also has `CO Date`; Completed preferred).
- **1,625 FIXED** by clearing Expiration-based and other unvalidated FINAL_DATE values (including all non-Final finals).
- After: Final FINAL_DATE **21 / 1,659 (1.3%)**; Active/In Review/Inactive **0%**. Expiration copies remaining: **0**.
- Residual Final gaps: 1,638 Completed shells with blank/absent Completed Date and CO Date — not repairable from DATA.

## Repair script

- Script: `agent/scripts/fl/data_repair_fl_ocoee.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_ocoee_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 33 | 1 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 21 | 1,625 | 375 → 1,979 |
