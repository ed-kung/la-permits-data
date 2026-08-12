# Miami (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Miami was first. Its DATA is a City of Miami ArcGIS / open-data attribute payload (`BuildingPermitStatusDescription`, plan dates, `IssuedDate`, `Statusdate`). STATUS_NORMALIZED, PERMIT_DATE, and FINAL_DATE were already correct against DATA. The only substantive gap was FILE_DATE: 1,567 rows (78.4%) were missing because `FirstSubmissionDate` is blank on newer exports; all were filled from `PlanAcceptedDate`, bringing FILE_DATE to 100% coverage with 0 consistency violations.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Miami, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_miami.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/miami_repaired_sample.parquet`

## DATA schema

All records share the same Miami building-permit attribute fields. Key-set variants (INFERRED_SCHEMA prefixes):

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `miami_arcgis_bom_x` | 1,146 | BOM `X` / `ObjectId` / truncated `BuildingPermitStatusReasonDescr` |
| `miami_arcgis_appnum` | 817 | `ApplicationNumber`, `Location_1`, full reason field name |
| `miami_arcgis_xy` | 36 | plain `X`/`Y` + `ObjectId` |

Content suffixes (`_issued_finaled`, `_issued`) reflect whether Final/certificate signals are present alongside `IssuedDate` (always present in this sample).

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `BuildingPermitStatusDescription` |
| FILE_DATE | `FirstSubmissionDate`; else `PlanAcceptedDate`; else `PlanCreatedDate` |
| PERMIT_DATE | `IssuedDate` |
| FINAL_DATE | `Statusdate` (fallback `BuildingFinalLastInspDate`, then `Certificatedate`) when Final |

Status map: Active→Active, Final→Final, Hold→In Review, Expired/Revoked→Inactive.

## Field assessments

### STATUS_NORMALIZED

0 missing. Crosstab vs `BuildingPermitStatusDescription` is exact for all 1,999 rows (Active 361, Final 1,508, Hold→In Review 4, Expired 76 + Revoked 50 → Inactive 126). `IsPermitFinal` YES/true aligns only with Final. **0 FILLED / 0 FIXED.**

### FILE_DATE

Ideal: populated for all records.

- Before: **1,567 missing (78.4%)**. Every populated FILE_DATE equaled `FirstSubmissionDate` at day resolution (432/432).
- Root cause: `FirstSubmissionDate` is `""` on newer exports (mostly 2019+); upstream only copied that field into FILE_DATE.
- When both exist, `PlanAcceptedDate` equals `FirstSubmissionDate` on 396/432 rows (~92%); `PlanCreatedDate` is often one day earlier (record creation).
- **1,567 FILLED** from `PlanAcceptedDate` (0 from PlanCreatedDate after priority). **0 FIXED.**
- After: FILE_DATE present on **100%** of rows; never after `IssuedDate`.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Already **0 missing**; every PERMIT_DATE equals `IssuedDate`.
- Hold (In Review) rows also carry `IssuedDate` (issued then held) — left as-is.
- **0 FILLED / 0 FIXED.** Coverage after: Active/Final/In Review/Inactive all 100%.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before/after: Final 1,508/1,508 (100%) all equal `Statusdate`; non-Final 0/491.
- `Certificatedate` present on only 148 Final rows and often post-dates Statusdate (certificate after finalization) — Statusdate is the better “finaled” stamp.
- `BuildingFinalLastInspDate` matches Statusdate on 246/265 dual-populated Final rows; when they differ, Statusdate is later (status closed after last insp).
- One Hold row has an expired TCC/TCO certificate date; correctly kept non-Final with empty FINAL_DATE.
- **0 FILLED / 0 FIXED.** Remaining missing FINAL_DATE values are exclusively non-Final (by design).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 1,567 | 0 | 1,567 → 0 |
| PERMIT_DATE | 0 | 0 | 0 → 0 |
| FINAL_DATE | 0 | 0 | 491 → 491 (non-Final only) |

Consistency check against DATA extractors: **0 violations**.
