# Broward County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Broward County was first. Its DATA is a POSSE/Accela-style master-permit payload. STATUS_NORMALIZED was missing on 8 rows and filled from `Permit.Status`. FILE_DATE already matched `ApplicationDate` wherever both existed (17 remaining gaps have no date in DATA). PERMIT_DATE is missing for all 2,000 rows because `Issue Date` is blank or the placeholder `mmm dd, yyyy`. FINAL_DATE was incorrectly populated from `ExpirationDate` on 617 rows and was cleared; DATA has no true completion/finaled stamp.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Broward County, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_broward_county.py` (`data_repair`)

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `posse_applied` | 1,358 | ApplicationDate present, no ExpirationDate |
| `posse_applied_expired` | 620 | ApplicationDate + ExpirationDate |
| `posse_status_only` | 16 | nested sections, no usable dates |
| `posse_fees_applied_expired` | 3 | + Fee Information |
| `posse_fees_applied` | 2 | + Fee Information |
| `posse_permit_status_only` | 1 | Permit key only |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Permit.Status` |
| FILE_DATE | `Permit Information.ApplicationDate` (fallback earliest `Plan Reviews[].Plans Submitted`) |
| PERMIT_DATE | `Permit.Issue Date` (never parseable in this sample) |
| FINAL_DATE | no true source; prior values equaled `ExpirationDate` and were cleared |

## Field assessments

### STATUS_NORMALIZED

8 missing; remaining rows already matched `Permit.Status`. **8 FILLED:**

| After | Permit.Status / STATUS_ORIGINAL | n |
| --- | --- | ---: |
| Active | All Permits Issued | 4 |
| Active | Primary Permit Issued | 1 |
| Final | All Permits Finaled | 1 |
| In Review | Plans Check | 1 |
| Inactive | All Permits Expired | 1 |

After repair: Final 1,848; Inactive 143; Active 5; In Review 4.

### FILE_DATE

Ideal: populated for all records. When present, every FILE_DATE matched ApplicationDate at day resolution (Plans Submitted always matched ApplicationDate too). **0 FILLED / 0 FIXED.** Remaining **17 missing** (mostly Cancelled, one New, one Permit-only) have empty ApplicationDate and no Plans Submitted.

Coverage after repair: Active 5/5; Final 1,847/1,848; In Review 3/4; Inactive 128/143.

### PERMIT_DATE

Ideal: populated for Active and Final. **All 2,000 missing before and after.** `Permit.Issue Date` is either blank (1,193) or the literal placeholder `mmm dd, yyyy` (807). Child `Permits[]` entries carry Status only (Finaled/Issued/Cancelled/…) with no issue dates. Not inventable from DATA.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 617 rows had FINAL_DATE; **every one equaled `ExpirationDate`** (565 Final, 51 Inactive, 1 then-unmapped All Permits Finaled). Expiration is a permit-expiry stamp, not completion/finaled/signoff.
- DATA contains no completion, CO, or final-inspection date.
- **617 FIXED** (cleared). After repair FINAL_DATE is missing for all statuses, including Final.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 8 | 0 | 8 → 0 |
| FILE_DATE | 0 | 0 | 17 → 17 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 617 | 1,383 → 2,000 |

Main corrective action is removing ExpirationDate misloads from FINAL_DATE. Status gaps are fully closed from `Permit.Status`. Issuance and true finalization dates are not present in the Broward County portal JSON sampled here.
