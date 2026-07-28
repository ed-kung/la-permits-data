# Campbell (CA) data repair — 2026-07-28

Campbell was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Flat MyGovOnline (`PaymentProcessorModule=MGO`) JSON already has complete, correct `FILE_DATE` (from `DateCreated`) and nearly perfect `STATUS_NORMALIZED` from `ProjectStatus`, but two Expired rows still carry a stale prior status, and `DateIssued` is the .NET sentinel on every row so `PERMIT_DATE` / `FINAL_DATE` cannot be recovered from DATA. Repair fixes 2 statuses; date fields unchanged.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Campbell, CA** → `agent/scripts/ca/data_repair_ca_campbell.py` (n=2,000).

## DATA schema

All 2,000 rows share one flat MGO key set (`ProjectStatus`, `DateCreated`, `DateIssued`, `DateUpdated`, applicant/site fields, status boolean flags, etc.). No nested inspections/fees objects. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `mgo_imported` | 1,476 | `TypeList` contains `Imported Fee` (legacy fee shells) |
| `mgo_modern` | 524 | Modern portal fee schedules / applicants |

`ProjectStatus` values (after stripping a leading tab on all 59 Pending rows): Permit Finaled/Closed (1,407), Permit Expired (396), Permit Issued (84), Pending (Under Review) (59), Plan Check Expired (39), Approved (Ready for Issuance) (6), Withdrawn (5), Stop Work (2), Plan Check Wait (2).

## Field assessment

### STATUS_NORMALIZED

- Missing on 0 / 2,000.
- Canonical map from `ProjectStatus` matches the existing labels for 1,998 rows:
  - Finaled/Closed → Final; Issued → Active; Pending / Approved (Ready for Issuance) / Plan Check Wait / Stop Work → In Review; Permit Expired / Plan Check Expired / Withdrawn → Inactive.
- **Issues:** two modern rows where `ProjectStatus='Permit Expired'` (`ProjectStatusID=4041`, `ProjectStatusIsPermit=False`) but `STATUS_ORIGINAL` / `STATUS_NORMALIZED` still reflect a prior lifecycle step:
  - `BLD-2022-1135`: STATUS_ORIGINAL=`approved (ready for issuance)` → In Review (should be Inactive)
  - `BLD-2022-931`: STATUS_ORIGINAL=`permit issued` → Active (should be Inactive)
- Root cause: upstream normalization followed stale `STATUS_ORIGINAL` instead of current `ProjectStatus`.
- **Repair:** derive status from stripped `ProjectStatus` → **0 FILLED**, **2 FIXED**. Missing after: 0.

Status transitions: In Review→Inactive 1; Active→Inactive 1.

### FILE_DATE

- Missing on 0 / 2,000. Every value matches `DateCreated` at calendar-day resolution.
- No other application/submittal timestamp exists in DATA.
- **Repair:** none needed (**0 FILLED**, **0 FIXED**). Coverage remains 100%.

### PERMIT_DATE

- Missing on 2,000 / 2,000 (100%). Ideal: populated for Active and Final (and useful on Expired that were once issued).
- Sole candidate field `DateIssued` is `"0001-01-01T00:00:00"` on every row — treated as missing. `DateUpdated` is the same sentinel; scheduled/power request dates are null.
- **Repair:** script will fill from a real `DateIssued` if present in future extracts → **0 FILLED**, **0 FIXED** on this sample. Missing after: 2,000.
- Post-repair Active PERMIT coverage: 0/84; Final: 0/1,407.

### FINAL_DATE

- Missing on 2,000 / 2,000 (100%). Ideal: populated for Final.
- No finaled / completion / sign-off date field exists in the MGO payload (no inspections array, no `DateFinaled`, etc.).
- **Repair:** nothing recoverable → **0 FILLED**, **0 FIXED**. Missing after: 2,000.
- Post-repair Final FINAL coverage: 0/1,407.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 2 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Status distribution after repair: Final 1,407 · Inactive 440 · Active 84 · In Review 69.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 0% | 0% |
| Final | 100% | 0% | 0% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 0% | 0% |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_campbell.py`
- Function: `data_repair(df)` → adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` columns (`FILLED` / `FIXED`)
