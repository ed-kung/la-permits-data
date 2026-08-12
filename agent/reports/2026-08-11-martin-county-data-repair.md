# Martin County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Martin County was first. Its DATA is a uniform Accela Citizen Access payload. The dominant defect is Accela status `DONE` (966 rows) normalized as In Review despite a Certificate Issuance event; those rows also stored the certificate date in PERMIT_DATE and left FINAL_DATE empty. Repair remaps status from `DATA.status`, fills FINAL_DATE from Certificate Issuance (99.8% of Final rows), and replaces certificate-sourced PERMIT_DATE with Permit Issuance `Issued` when present (or clears it when not). FILE_DATE was already complete and correct.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Martin County, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_martin_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/martin_county_repaired_sample.parquet`

## DATA schema

All records are Accela-shaped (`status`, `date`, `tasks`, `search_data`, `more_details`). Most also include `inspections` and `fees_details`. Martin County has no `PERMIT DATES` block; issuance and finalization live in workflow tasks.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `accela_full_finaled` | 1,105 | inspections + final date; no Issued task |
| `accela_full_issued_finaled` | 655 | issued + final |
| `accela_full_applied` | 107 | no recoverable issue/final |
| `accela_full_issued` | 102 | issued only |
| `accela_basic_finaled` | 19 | final, no inspections list |
| `accela_basic_applied` | 10 | dated tasks only |
| `accela_shell_applied` | 1 | blank status |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` (fallback `search_data.Status`) |
| FILE_DATE | `DATA.date` / `search_data.Application Date` |
| PERMIT_DATE | Permit Issuance task `Issued` / `Issued - Revised` (earliest) |
| FINAL_DATE | Certificate Issuance `Certificate Issued` / `Closed Conditionally`; else Inspections `Completed`; else Passed final-ish inspections |

## Field assessments

### STATUS_NORMALIZED

37 missing; large systematic mislabel of `DONE` → In Review.

**36 FILLED** (unmapped originals): COND→Final (20), Closed Conditionally→Final (8), Awaiting Resubmittals→In Review (4), Closed-Certificate Issued→Final (2), Closed-Cancelled→Inactive (1), CLOS→Final (1).

**1,046 FIXED** (largest):

| Before → After | DATA.status | n |
| --- | --- | ---: |
| In Review → Final | DONE | 966 |
| Active → Final | Closed-Certificate Issued | 41 |
| In Review → Final | Closed-Certificate Issued | 20 |
| In Review → Active | Issued | 7 |
| Final → Active | Closed (plan-mod / Issued-Revised, no CO) | 4 |
| Active / In Review → Inactive | Expired / Closed-Cancelled / Application Expired | 6 |

Cause: upstream treated Accela `DONE` (legacy completed / certificate family) as a review state, lagged `DATA.status` on Closed-Certificate Issued and Issued rows, and left niche codes (COND, Closed Conditionally) unmapped. Bare `Closed` with Issued-Revised and no certificate is remapped to Active (revision records).

One shell row (`BLD2024110732`) has blank `status` / `search_data.Status` → STATUS_NORMALIZED stays null.

After repair: Final 1,716; Inactive 134; Active 86; In Review 62; null 1.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches `DATA.date` at day resolution. No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

Upstream often stored **Certificate Issued** as PERMIT_DATE (1,677 of 1,815 non-null values matched certificate and/or not Permit Issuance).

| Action | n |
| --- | ---: |
| FIXED → Permit Issuance Issued | 581 |
| FIXED cleared (cert-sourced, no Issued task) | 1,096 |
| FILLED from Issued task | 43 |

Remaining gap: **1,058 Final** still missing PERMIT_DATE — almost all `DONE` / `Closed-CH 2019-45` legacy rows with only a Certificate Issuance dated task (no Issued event). Not inventable from DATA. Active coverage after repair: **85/86 (98.8%)**; the one miss is `Permit Issued` with empty Permit Issuance history.

Coverage after repair: Active 85/86 (98.8%); Final 658/1,716 (38.3%); In Review 0/62; Inactive 19/134.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream: 607 present (nearly all Closed-Certificate Issued); **0** of 966 DONE had FINAL_DATE.
- **1,106 FILLED** from Certificate Issuance (and Closed Conditionally / Inspections Completed fallbacks).
- **2 FIXED** where existing FINAL_DATE disagreed with Certificate Issuance.
- Remaining: **3 Final** (COND legacy shells with no dated certificate/inspection events).
- Non-Final FINAL_DATE cleared; phantom Certificate Issued stamps on CNCL/VOID/Closed-Cancelled (often `02/17/2018`) are not used as FINAL_DATE. No PERMIT_DATE > FINAL_DATE inversions.

Coverage after repair: Final 1,713/1,716 (99.8%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 36 | 1,046 | 37 → 1 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 43 | 1,677 | 184 → 1,237 |
| FINAL_DATE | 1,106 | 2 | 1,392 → 286 |

PERMIT_DATE missing **increases** after repair because clearing certificate-sourced values is required for correctness; true issuance dates are unavailable on most DONE-era rows.
