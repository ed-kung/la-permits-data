# Jacksonville Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Jacksonville Beach**. DATA is the city-portal family shared with Tarpon Springs / Lake Worth Beach (`detail` / `fees` / `permit_status_detail` / `insp_status_detail`). Upstream left **all 2,000** rows with null `STATUS_NORMALIZED`, `PERMIT_DATE`, and `FINAL_DATE` (`STATUS_ORIGINAL` also null); `FILE_DATE` already matched `Application Date` on every row. Repair filled all statuses from Application Status / Application/Permit Status, filled 1,901 `PERMIT_DATE` values from `Permit Issue Date`, and filled 1,062 `FINAL_DATE` values from successful inspections. After repair: STATUS 100%; FILE_DATE 100%; Active PERMIT_DATE 99.0%; Final PERMIT_DATE 99.9%; Final FINAL_DATE 91.5%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Jacksonville Beach, FL** → `agent/scripts/fl/data_repair_fl_jacksonville_beach.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_status` | 1,976 | `detail` / fees plus `permit_status_detail` + `insp_status_detail` |
| `fees_detail` | 24 | `detail` + fees only (Application Date / Application Status; no issue/inspections) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | Inactive / In-Review Application Status overrides; else `Application/Permit Status` (or `Status`) on `permit_status_detail`; else `Application Status` / `Status` on `detail` |
| FILE_DATE | `Application Date` |
| PERMIT_DATE | `Permit Issue Date` |
| FINAL_DATE | Latest successful non-NOC inspection (`APPROVED` / `WAIVED` / `PARTIALLY APPROVED` / `APPROVED WITH EXCEPTION`); Final rows only |

`Status Date` is **not** used for `FINAL_DATE`: it is dominated by administrative batch stamps (759× `01/02/14`, 195× `02/09/18`, 116× `12/14/99`).

## Field assessments

### STATUS_NORMALIZED

| Assessment | Detail |
| --- | --- |
| Before | **2,000 / 2,000 null** (`STATUS_ORIGINAL` also null) |
| Root cause | Upstream never mapped Jacksonville Beach portal statuses |
| Repair | FILLED 2,000 from portal status fields |

Resolution rules:

1. Terminal inactive Application Status (`INACTIVE - OVER 180 DAYS`, `REJECTED`, `REVOKED`, `WITHDRAWN APPLICATION`, …) → **Inactive**, even when `Application/Permit Status` is `CLOSED` (610+ such overrides).
2. Pre-issuance Application Status (`IN PLAN REVIEW`, `CORRECTIONS REQUIRED`, `APPROVED,PENDING ISSUANCE`, …) → **In Review**, overriding a stale `CLOSED` permit status.
3. Else prefer `Application/Permit Status` (`CLOSED` / `C.O. ISSUED` / `PERMIT PRINTED` / `PLAN CHECK` / `FINAL INSPECTION COMPLETE` / `PERMIT REVOKED` / …).
4. Else map Application Status (`PERMIT COMPLETE/CLOSED`, `CERTIFICATE ISSUED`, `APPROVED FOR PERMIT`, …).

After repair: Final 1,161; Inactive 701; Active 103; In Review 35; null 0.

### FILE_DATE

Ideal: populated for all records.

- Before: present on **2,000 / 2,000**; every value matches `Application Date` at day resolution.
- **0 FILLED, 0 FIXED.** Coverage remains 100% across all statuses.
- One residual `FILE_DATE > PERMIT_DATE` inversion: a `CLOSED-FS` row whose portal `Application Date` was overwritten to the `Reissue Date` (`11/08/19`) while `Permit Issue Date` stayed at the original issuance (`01/24/17`). Preserved as source DATA.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before: **0 / 2,000** present.
- **1,901 FILLED** from `Permit Issue Date` for Active / Final / Inactive.
- In Review kept at 0% (no spurious fills); blank Issue Date rows stay missing.
- Residual Active/Final gaps: **2** `fees_detail` rows (Active `ACTIVE/ON HOLD-REQURMNTS`; Final `PROCESS COMPLETED-PLANNIN`) with no `permit_status_detail` / Issue Date.

Coverage after repair: Active 102/103 (99.0%); Final 1,160/1,161 (99.9%); In Review 0/35; Inactive 639/701 (91.2%, retained when issued). `PERMIT_DATE` equals `Permit Issue Date` whenever both are present (0 mismatches / 1,904).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: **0 / 2,000** present.
- **1,062 FILLED** from latest successful non-NOC inspection on Final rows.
- Non-Final cleared / left null (Active / In Review / Inactive at 0%).
- Residual Final gaps: **99** without a usable success inspection — mainly statute batch closes and planning/public-works shells:

| Application Status | n missing FINAL_DATE |
| --- | ---: |
| CLOSED-FS 553.79(17)(C) | 73 |
| PROCESSED BY PUBLIC WORKS | 9 |
| PROCESS COMPLETED-PLANNIN | 8 |
| PERMIT COMPLETE/CLOSED | 3 |
| CONDITIONAL USE / VARIANCE APPROVED | 4 |
| CERTIFICATE ISSUED | 2 |

Final coverage after repair: **1,062 / 1,161 (91.5%)**. `PERMIT_DATE > FINAL_DATE` inversions: 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2,000 | 0 | 2,000 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1,901 | 0 | 2,000 → 99 |
| FINAL_DATE | 1,062 | 0 | 2,000 → 938 |

Remaining structural gaps: 2 Active/Final rows without `Permit Issue Date`; 99 Final rows without successful inspections (mostly `CLOSED-FS` / planning shells); 24 `fees_detail` rows have status + `FILE_DATE` only.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_jacksonville_beach.py`
- Repaired sample: `AGENT_DATA_PATH/jacksonville_beach_permits_repaired.parquet`
