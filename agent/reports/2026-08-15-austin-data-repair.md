# Austin (TX) data repair

**Summary:** First TX sample jurisdiction without an existing repair script (first-appearance order) was **Austin** (Houston already had `data_repair_tx_houston.py`). DATA is the City of Austin Issued Construction Permits open-data payload with Applied / Issued / Completed dates and `Status Current`. Two Active rows were mislabeled as Final with orphan FINAL_DATE values; 142 Inactive rows incorrectly carried Completed Date in FINAL_DATE. After repair: status aligns with `Status Current`; FILE_DATE and PERMIT_DATE remain 1988/1990 (2 blank-date stubs unrecoverable); Final FINAL_DATE is 1662/1663 (99.9%); Active/Inactive FINAL_DATE cleared to 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Austin was the first pair without `agent/scripts/tx/data_repair_tx_austin.py` (Houston already present).

## DATA shape

1,990 rows. Two near-identical key sets differing only by `Project ID`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| `issued_construction` | 1,001 |
| `issued_construction_project_id` | 989 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status Current` (`Final`→Final, `Active`→Active, `VOID`/`Expired`/`Withdrawn`→Inactive) |
| FILE_DATE | `Applied Date` |
| PERMIT_DATE | `Issued Date` |
| FINAL_DATE | `Completed Date` (Final rows only) |

## Field assessments

### STATUS_NORMALIZED

Before: fully populated (Final 1,665 / Inactive 281 / Active 44). Almost all rows already matched `Status Current`, except **2** rows with `Status Current == Active` but upstream `STATUS_ORIGINAL == final` / `STATUS_NORMALIZED == Final`. Those were FIXED to Active. After: Final 1,663 / Inactive 281 / Active 46; 0 null.

| Status Current | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Final | 1,663 | Final | Correct |
| VOID | 140 | Inactive | Correct |
| Expired | 130 | Inactive | Correct |
| Withdrawn | 11 | Inactive | Correct |
| Active | 46 | Active (44) / Final (2) | 2 FIXED → Active |

### FILE_DATE

Before/after: 1,988/1,990 populated. Every non-missing `FILE_DATE` already equals `Applied Date` (0 FILLED / FIXED). The 2 missing rows have blank `Applied Date` (and blank Issued/Completed) in DATA — not fillable.

### PERMIT_DATE

Before/after: 1,988/1,990 populated. Every non-missing `PERMIT_DATE` already equals `Issued Date` (0 FILLED / FIXED). Same 2 blank-date stubs lack `Issued Date`. Post-repair Active/Final coverage: 1,707/1,709 (99.9%).

### FINAL_DATE

Before: 1,806 present / 184 missing.

Issues:
- **2 Active-as-Final rows** had FINAL_DATE values that do not appear in DATA (`Completed Date` blank) → cleared when status FIXED to Active.
- **142 Inactive** rows had FINAL_DATE equal to `Completed Date` (void/expired/withdrawn close-out stamps). Under the normalized schema FINAL_DATE is for Final records only → cleared (FIXED).
- **1 Final** row has blank `Completed Date` (same all-blank stub as above) → cannot fill.
- Remaining Final rows already matched `Completed Date`.

After: Final FINAL_DATE 1,662/1,663 (99.9%); Active/Inactive 0.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_austin.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 2 | 0 → 0 |
| FILE_DATE | 0 | 0 | 2 → 2 |
| PERMIT_DATE | 0 | 0 | 2 → 2 |
| FINAL_DATE | 0 | 144 | 184 → 328 |

Post-repair coverage:

- STATUS_NORMALIZED null: 0
- FILE_DATE overall: 1,988/1,990 (99.9%)
- Active/Final PERMIT_DATE: 1,707/1,709 (99.9%)
- Final FINAL_DATE: 1,662/1,663 (99.9%)
- Active/Inactive FINAL_DATE: 0 (cleared)

Source chronology quirks preserved when they match DATA (e.g. one Applied-after-Issued row; one Completed Date of 1907).

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_austin.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_austin_repaired.parquet`
