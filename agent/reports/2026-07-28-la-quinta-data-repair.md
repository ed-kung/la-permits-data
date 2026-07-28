# La Quinta (CA) data repair

**Summary:** La Quinta was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` / `search_data`). Status: **FILLED 175** blank `PermitStatus` CONV shells from dates, **FIXED 11** Active→Final where `PermitFinaledDate` was present. `FILE_DATE` already matched `PermitAppliedDate` (99.5% coverage; 10 legacy shells unrecoverable). `PERMIT_DATE`: **FILLED 141** Active/Final rows from `PermitIssuedDate` / `PermitApprovedDate`. `FINAL_DATE`: no new fills available (empty inspections); **FIXED 1** spurious final date on a DENIED row. Large residual gaps remain on CLOSED Final shells that lack Issued/Finaled stamps.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **La Quinta, CA** (n=2,001) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_la_quinta.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_la_quinta_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. `inspections` and `fees` are null/empty throughout the sample. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_applied_only` | 939 | Applied only (mostly OK TO ISSUE / CLOSED / early review) |
| `permit_info_issued` | 393 | Applied + Issued |
| `permit_info_full` | 368 | Applied + Issued + Finaled |
| `permit_info_approved` | 291 | Applied + Approved (no Issued) |
| `permit_info_partial` | 9 | Issued/Approved/Finaled without Applied |
| `permit_info_shell` | 1 | No usable date fields |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (date inference when blank; Finaled upgrades) |
| `FILE_DATE` | `permit_info.PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate` (fallback: `PermitApprovedDate`) |
| `FINAL_DATE` | `permit_info.PermitFinaledDate` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 763 · In Review 689 · Active 347 · missing 175 · Inactive 27

Upstream mapped `STATUS_ORIGINAL` from `PermitStatus` correctly for non-blank labels (e.g. FINALED/CLOSED→Final, ISSUED/APPROVED→Active, OK TO ISSUE/PLAN CHECK→In Review, VOIDED/EXPIRED/DENIED→Inactive). Two gaps:

1. **175 blank `PermitStatus`** (legacy `CONV:` RECORDID shells) had missing `STATUS_NORMALIZED` despite usable dates → FILLED: Final 73 · Active 59 · In Review 43.
2. **11 ISSUED/APPROVED rows** carried a true `PermitFinaledDate` but remained Active → FIXED to Final.

`OK TO ISSUE` stays In Review (aligned with READY TO ISSUE in peer CRW cities — approved/ready but not issued). Inactive labels are never upgraded by a finaled stamp (DENIED close dates are not sign-offs).

**After:** Final 847 · In Review 732 · Active 395 · Inactive 27 · missing 0  
Flags: **FILLED 175 · FIXED 11**

### FILE_DATE

**Before:** 10 missing (99.5%). Whenever `PermitAppliedDate` is present, `FILE_DATE` already matches (0 mismatches).

The 10 gaps are legacy shells (`Closed` / `Active` / `Permit Issued` / one `APPROVED`) with no Applied date in `permit_info` or `search_data` — only Issued. Issued is not used as an application-date proxy.

**After:** still 10 missing.  
Flags: **FILLED 0 · FIXED 0**

Coverage after: **99.5%**.

### PERMIT_DATE

**Before:** 1,231 missing. Populated values already matched `PermitIssuedDate` when both present.

Active/Final rows missing Issued but having Approved (plus blank-status shells remapped to Active/Final) → FILLED from Approved/Issued.

**After:** 1,090 missing.  
Flags: **FILLED 141 · FIXED 0**

Coverage after by status:

| Status | PERMIT_DATE present |
| --- | ---: |
| Active | 393 / 395 (99.5%) |
| Final | 515 / 847 (60.8%) |
| In Review | 2 / 732 (pre-existing SUBMITTED rows with Issued; left as-is) |
| Inactive | 1 / 27 (DENIED; left as-is) |

Residual Final gaps are almost all CLOSED (328) plus 4 FINALED without Issued/Approved.

### FINAL_DATE

**Before:** 1,599 missing. Populated values matched `PermitFinaledDate`. No inspection Completed dates exist as a proxy.

- No additional Final rows could be filled (FINALED without Finaled date: 38; CLOSED/Closed: 408 — none have Finaled).
- 1 DENIED row had a spurious `FINAL_DATE` → cleared (FIXED) after keeping status Inactive.

**After:** 1,600 missing (401 / 847 Final rows still have FINAL_DATE = 47.3%).  
Flags: **FILLED 0 · FIXED 1**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 175 | 11 | 175 → 0 |
| FILE_DATE | 0 | 0 | 10 → 10 |
| PERMIT_DATE | 141 | 0 | 1,231 → 1,090 |
| FINAL_DATE | 0 | 1 | 1,599 → 1,600 |

## Not repairable from DATA

- 10 FILE_DATE gaps with no Applied date.
- ~328 CLOSED Final rows without Issued/Approved → no PERMIT_DATE.
- ~446 Final rows (CLOSED + FINALED shells) without PermitFinaledDate and with empty inspections → no FINAL_DATE.
