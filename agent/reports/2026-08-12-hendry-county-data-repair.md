# Hendry County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Hendry County**. DATA is a uniform civic/eTRAKiT payload (`permit_info` + dict-format `inspections`). Upstream left 55 `STATUS_NORMALIZED` nulls (unmapped expiration/hold/awaiting labels and spaced `V O I D`), mislabeled `APPROVED`/`FINAL PROCESSING` as Active, and left a few issued `HOLD`/`REASSIGNED` rows as In Review. Present dates already matched `PermitAppliedDate` / `PermitIssuedDate` / `PermitFinaledDate` wherever set. The repair filled all 55 null statuses and fixed 42 more; filled 49 `PERMIT_DATE` values (mostly from `PermitApprovedDate`); filled 8 `FINAL_DATE` values from passed final inspections; and cleared 7 spurious non-Final finals. After repair: STATUS 100% populated; FILE_DATE unchanged at 99.8%; Active/Final PERMIT_DATE 86.3%/99.0%; Final FINAL_DATE 95.1%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Hendry County, FL** → `agent/scripts/fl/data_repair_fl_hendry_county.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. `search_data` is uniform (`Address`, `Permit Number`, `RECORDID`). Canonical lifecycle fields always live under `permit_info`. Content variants split by which `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `civic_issued_finaled` | 1,524 | Issued + finaled dates |
| `civic_issued` | 257 | Issued, no finaled |
| `civic_applied` | 115 | Applied only |
| `civic_approved` | 67 | Approved (no issued/finaled) |
| `civic_finaled` | 33 | Finaled without issued |
| `civic_status_only` | 4 | Empty date shells |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Final when `PermitFinaledDate` set, except Inactive terminals; In Review labels with issued → Active) |
| FILE_DATE | `PermitAppliedDate` else `PermitIssuedDate` |
| PERMIT_DATE | `PermitIssuedDate` else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` else latest passed FINAL / Cert of Compliance inspection |

## Field assessments

### STATUS_NORMALIZED

| PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| FINALED | 1,147 | Final | Correct |
| COMPLETE | 409 | Final | Correct |
| ACTIVE | 123 | Active (1 with `PermitFinaledDate`) | 1 should be Final |
| ADMIN CLOSURE | 80 | Final | Correct (admin-closed lifecycle) |
| UNDER REVIEW | 48 | In Review | Correct |
| APPROVED | 34 | **Active** | No issue date → In Review |
| CANCELLED | 32 | Inactive | Correct |
| EXPIRED | 22 | Inactive | Correct |
| EXP/CANC/MUSTREAPPLY | 21 | **null** | Fill → Inactive |
| INACTIVE | 19 | Inactive | Correct |
| AWAITING RESPONSE | 14 | **null** | Fill → In Review |
| DENIED | 12 | Inactive | Correct |
| VOID | 6 | Inactive | Correct |
| V O I D | 6 | **null** | Fill → Inactive |
| HOLD (+ multiline) | 9 | In Review (4) / **null** (4) | Issued rows → Active |
| EXP / 1ST NOTICE | 4 | **null** | Fill → Inactive |
| SUBMITTED | 4 | In Review | Correct |
| EXP/CODE CASE | 2 | **null** | Fill → Inactive |
| FINAL PROCESSING | 2 | **Active** | Approved only → In Review |
| REASSIGNED | 1 | In Review (has issued) | → Active |
| APPRVD AS NOTED | 1 | **null** (has issued) | → Active |
| FINALED/FAILED | 1 | **null** (has finaled) | → Final |
| EXPIRED/NO RENEWAL | 1 | **null** | Fill → Inactive |
| APPLIED | 1 | In Review | Correct |
| \<NONE\> | 1 | **null** (has finaled) | → Final |

**Root causes:**
1. Upstream mapper omitted expiration/cancel hybrids (`EXP/CANC/MUSTREAPPLY`, `EXP / 1ST NOTICE`, `EXP/CODE CASE`, `EXPIRED/NO RENEWAL`), `AWAITING RESPONSE`, spaced `V O I D`, multiline `HOLD`, `APPRVD AS NOTED`, `FINALED/FAILED`, and `<NONE>`.
2. `APPROVED` and `FINAL PROCESSING` were treated as Active even when `PermitIssuedDate` was blank (approved ≠ issued).
3. Issued `HOLD` / `REASSIGNED` rows kept an In Review label despite a real issue date.
4. One `ACTIVE` shell still carries `PermitFinaledDate` but kept an Active label.

**Repair performance:** FILLED 55, FIXED 42; missing 55 → 0.

### FILE_DATE

- Before: missing on **4 / 2,000** rows. Present values always matched `PermitAppliedDate` at calendar-day resolution (0 mismatches).
- All 4 gaps (UNDER REVIEW / VOID / COMPLETE×2) have blank applied, issued, and approved dates → not fillable from DATA.
- Ideal coverage already ~100% for every populated status class.

**Repair performance:** FILLED 0, FIXED 0; missing 4 → 4 (99.8% coverage).

### PERMIT_DATE

- Before: missing on **219 / 2,000**; present values always matched `PermitIssuedDate` (0 mismatches).
- Gaps concentrated in Active (57), Final (49), Inactive (29), In Review (54), and null-status (30).
- Filled 49 from `PermitApprovedDate` when issued was blank (Final COMPLETE/ADMIN CLOSURE/FINALED, Active ACTIVE, Inactive VOID|CANCELLED|EXPIRED hybrids).
- `APPROVED` / `FINAL PROCESSING` rows were demoted to In Review, so their approved dates were correctly *not* written into `PERMIT_DATE`.
- Issued `HOLD`/`REASSIGNED` rows were upgraded to Active, retaining existing `PERMIT_DATE` (no In Review clears for those).
- Remaining Active/Final gaps (35): `ACTIVE` (18), `FINALED` (9), `ADMIN CLOSURE` (5), `COMPLETE` (3) with neither issued nor approved in DATA.
- In Review rows correctly have no `PERMIT_DATE` after repair.

**Repair performance:** FILLED 49, FIXED 0; missing 219 → 170. Active coverage 86.3%; Final coverage 99.0%.

### FINAL_DATE

- Before: missing on **443 / 2,000**, including 89 Final rows; 1 Active and 7 Inactive rows incorrectly carried `PermitFinaledDate` (plus 2 null-status rows with finaled stamps that became Final).
- Filled 8 Final gaps from passed final-ish inspections (`FINAL`, `Final Electric`, `Final HVAC`, `RF- Final Roof`, `CC- Cert of Compl`, etc.) when `PermitFinaledDate` was blank.
- Cleared 7 spurious non-Final finals (FIXED). The Active+finaled row was upgraded to Final (status FIXED) so its date was retained; the two null-status finaled rows became Final.
- Remaining Final gaps (81): `ADMIN CLOSURE` (70), `FINALED` (6), `COMPLETE` (5) with no finaled stamp and no usable passed final inspection — mostly older admin-closed / legacy shells.

**Repair performance:** FILLED 8, FIXED 7; missing count 443 → 442 (fills offset by Inactive clears). Final coverage 95.1% (1,558 / 1,639) with 0% FINAL_DATE on Active / In Review / Inactive.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_hendry_county.py`
- Entry point: `data_repair(df)`
- Outputs: overwritten `STATUS_NORMALIZED` / `FILE_DATE` / `PERMIT_DATE` / `FINAL_DATE`; flags `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`}; `INFERRED_SCHEMA`
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and the civic pattern in `agent/scripts/fl/data_repair_fl_okeechobee_county.py`

## Artifacts

- Repaired sample parquet: `AGENT_DATA_PATH/hendry_county_repaired_sample.parquet`
