# San Antonio (TX) data repair

**Summary:** First TX sample jurisdiction without an existing repair script (first-appearance order after Austin, Fort Worth, and Houston) was **San Antonio**. DATA is an Accela Civic Access scrape (`status`, `date`, workflow `tasks`, optional `inspections`). Upstream `STATUS_NORMALIZED` often lagged live `DATA.status` (About to Expire labeled Inactive; Closed/LOC/COO still Active; several investigation/renewal statuses unmapped). After repair: status nulls fall 57→42 (empty-status stubs only); FILE_DATE reaches **100%**; Active PERMIT_DATE 50.5% and Final 54.6%; Final FINAL_DATE rises from ~0.4% to **90.9%**; spurious FINAL_DATE on non-Final rows cleared.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Austin, Fort Worth, and Houston already had repair scripts; **San Antonio** was the first missing (`agent/scripts/tx/data_repair_tx_san_antonio.py`).

## DATA shape

2,002 rows. Two Accela key-set variants:

| INFERRED_SCHEMA | n |
| --- | ---: |
| `accela_full` | 1,995 |
| `accela_lean` | 7 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` |
| FILE_DATE | `DATA.date` (fallback `search_data.Date`) |
| PERMIT_DATE | earliest `Permit Issued` Marked as Issued/Approved; else `Issuance` Marked as Active; else `Closure` Marked as Issued |
| FINAL_DATE | latest `Permit Closure` / `Closure` / LOC / `Case Inspection` Case Resolved|No Violation; else `Permit Issued`→Permit Closure; else Inspection Results / final-titled inspections |

## Field assessments

### STATUS_NORMALIZED

Before: Active 816 / Final 730 / Inactive 260 / In Review 139 / **null 57**.

Issues:
- **Lag vs live portal status** (STATUS_ORIGINAL snapshot): e.g. `DATA.status=Inactive` still Active (11); Closed/LOC/COO still Active (16); Issued/Expired/Withdrawn under wrong buckets.
- **About to Expire → Inactive (38)** — permit is still in force; mapped to Active.
- **Unmapped statuses left null (15 fillable)**: Awaiting Renewal, Pending Yellow/Red Investigation, Released, Renewal In Process, Pass No Red/Yellow Violation.
- **42 unfillable nulls**: empty `DATA.status` / `search_data.Status` on Contact Information and similar non-permit stubs.

After: Active 837 / Final 746 / Inactive 239 / In Review 138 / **null 42**. FILLED 15, FIXED 75.

### FILE_DATE

Before: **24 missing (1.2%)**. All 1,978 present values already equal `DATA.date` at day resolution (0 mismatches). The 24 missing rows still had `DATA.date` / `search_data.Date` → FILLED. After: **2,002/2,002 (100%)**.

### PERMIT_DATE

Before: **1,735 missing (86.7%)**. Only 267 rows had a date; among those with an Accela issuance event, 50 disagreed with the earliest Issued/Active marker (often COO/LOC records where upstream used a later non-issuance date).

Repair: fill/fix from `Permit Issued` Issued/Approved or `Issuance` Active. After: missing **988**. Coverage by repaired status: Active **50.5%**, Final **54.6%**, Inactive **72.4%**, In Review 8.0%.

Not recoverable in DATA:
- **Issued** stubs with only TBD / Pending Issuance / no Permit Issued task (264 Active).
- **Approved** pre-issuance (39).
- Many **Closed** / Completed / Case Resolved workflows with no Issued/Active event (339 Final).

### FINAL_DATE

Before: **1,978 missing (98.8%)**; only 24 present, of which **21 were on non-Final** (mostly still-Issued permits whose Inspection Results Completed was treated as final).

Issues repaired:
- **675 FILLED** on Final from Closure / Permit Closure / LOC / Case Resolved / Permit Closure-on-Issued markers.
- **21 FIXED** (clears): spurious FINAL_DATE on non-Final rows.

After: Final FINAL_DATE **678/746 (90.9%)**; Active/In Review/Inactive **0**. Remaining **68** Final gaps are mostly Closed MEP Trade / Tree permits with Issued events but no Closure/LOC task date (plus one LOC Issued electrical stub).

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_san_antonio.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 15 | 75 | 57 → 42 |
| FILE_DATE | 24 | 0 | 24 → 0 |
| PERMIT_DATE | 747 | 50 | 1,735 → 988 |
| FINAL_DATE | 675 | 21 | 1,978 → 1,324 |

Coverage after repair (by repaired status):

| Status | n | PERMIT_DATE | FINAL_DATE | FILE_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 837 | 50.5% | 0% | 100% |
| Final | 746 | 54.6% | 90.9% | 100% |
| In Review | 138 | 8.0% | 0% | 100% |
| Inactive | 239 | 72.4% | 0% | 100% |
| (null) | 42 | 0% | 0% | 100% |

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_san_antonio.py`
- Repaired parquet: `AGENT_DATA_PATH/repaired/permits_tx_san_antonio_repaired.parquet`
