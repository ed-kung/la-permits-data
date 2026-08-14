# Pembroke Park (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Pembroke Park. Its DATA is a city-portal payload (same family as Hillsboro Beach / Deerfield Beach) with `Permit Information`, `Applications`, and `Inspections History`. Twelve `Archived` rows were incorrectly labeled In Review and were FIXED to Inactive. `FILE_DATE` already matched earliest `AppDate` on every row. `PERMIT_DATE` was a copy of `FILE_DATE` on all 2,000 rows; repair overwrote 288 rows from `ApprovedByDate`. `FINAL_DATE` was missing on all rows and was filled for 1,829 of 1,888 Final records from Passed/Complete FINAL inspections.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Pembroke Park was the first pair without `agent/scripts/fl/data_repair_fl_pembroke_park.py`.

## DATA shape

All 2,000 rows share the same top-level key set. `INFERRED_SCHEMA` content suffixes:

| Schema | n |
| --- | ---: |
| `city_portal_issued_finaled` | 1,807 |
| `city_portal_issued` | 137 |
| `city_portal_finaled` | 51 |
| `city_portal_applied` | 5 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Permit Information[0].StatusDesc` |
| FILE_DATE | earliest `Applications[].AppDate` |
| PERMIT_DATE | earliest `Applications[].ApprovedByDate` |
| FINAL_DATE | latest Passed/Complete inspection with `FINAL` in `inspectiondesc` (`scheduleddate`) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,888; Inactive 84; Active 16; In Review 12; **0 null**.

`StatusDesc` values and upstream mapping:

| StatusDesc | n | Upstream STATUS_NORMALIZED | Expected |
| --- | ---: | --- | --- |
| Permit Complete | 1,888 | Final | Final |
| Expired | 54 | Inactive | Inactive |
| Canceled Permit | 21 | Inactive | Inactive |
| Permit Issued | 16 | Active | Active |
| Archived | 12 | In Review | Inactive |
| Voided | 9 | Inactive | Inactive |

`Archived` was the only incorrect mapping: these are closed historical shells (often with canceled or empty inspection history), not permits under review. Repair FIXED all 12 to Inactive.

After: Final 1,888; Inactive 96; Active 16; In Review 0; **0 null**.

Flags: **0 FILLED, 12 FIXED**.

### FILE_DATE

Missing on 0/2,000. Every row’s `FILE_DATE` already equals earliest `Applications[].AppDate` (calendar day), including multi-application shells where a non-primary app is earlier than the primary.

Flags: **0 FILLED, 0 FIXED**. Ideal coverage: 2,000/2,000 (100%).

### PERMIT_DATE

Before: present on all 2,000 rows, but equal to `FILE_DATE` on every row (upstream copied application date into issuance).

`ApprovedByDate` is present on 1,944 shells. When it differs from the FILE_DATE copy (288 rows), it is the real issuance stamp (typically a few days later). Same-day ABD (1,656 rows) leaves `PERMIT_DATE` unchanged. Missing ABD (56 rows) keeps the upstream FILE_DATE copy — fee `DatePaid` is not a reliable issuance proxy here.

Repairs:

- **271** Active/Final rows → `PERMIT_DATE` FIXED from earliest `ApprovedByDate`
- **17** Inactive rows with differing `ApprovedByDate` → FIXED

After: Active 16/16; Final 1,888/1,888; Inactive 96/96; In Review n/a.

Residual: **1,633** Active/Final rows still have `PERMIT_DATE == FILE_DATE` because ABD is absent or same-day — left as-is. Eight Final rows have `PERMIT_DATE` after `FINAL_DATE`; these are ABD/earliest-app quirks vs. inspection history, not introduced by clearing dates.

Flags: **0 FILLED, 288 FIXED**.

### FINAL_DATE

Missing on all 2,000 rows before repair. Filled from latest inspection with `statusdesc` in `{Passed, Complete}` and `FINAL` in `inspectiondesc`. `Complete` is rare but meaningful here: two ENG finals note that the close-out inspection was performed under that status (one of those two lacked any Passed FINAL and was newly filled).

After: Final 1,829/1,888 (96.9%); non-Final 0 (correct — close-out dates not written onto Active/Inactive).

Remaining 59 Final gaps: empty inspection history (44), or history with only non-FINAL passed work (rough/service/backflow/etc.) and no Passed/Complete FINAL.

Flags: **1,829 FILLED, 0 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 12 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 288 | 0 → 0 |
| FINAL_DATE | 1,829 | 0 | 2,000 → 171 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_pembroke_park.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_pembroke_park_repaired.parquet`
