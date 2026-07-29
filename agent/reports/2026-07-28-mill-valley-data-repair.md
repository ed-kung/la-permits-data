# Mill Valley (CA) data repair

**Summary:** Assessed Mill Valley's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_mill_valley.py`. Civic-portal `permit_info` is the canonical source (`search_data` has no workflow dates). Filled 253 missing statuses and fixed 14 mislabeled ones (ISSUED/PAID ONLINE with Finaled → Final; pre-issuance labels that already carry Issued → Active). Filled 119 missing PERMIT_DATEs (mostly FINALED FIRE shells with Approved only) and 1 FINAL_DATE from a final inspection. FILE_DATE already matched Applied whenever present; 252 gaps lack any application date and stay missing. After repair: status complete; Active PERMIT_DATE 99.7%; Final PERMIT_DATE 99.1% / FINAL_DATE 94.2%.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Mill Valley, CA**.

## DATA schema

All 2,000 rows have DATA. Top-level keys are always `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `permit_info_issued_finaled` | 1,023 | Issued + Finaled present |
| `permit_info_issued` | 471 | Issued present, Finaled blank |
| `legacy_no_status` | 212 | Blank PermitStatus with dates (almost all Issued-only legacy) |
| `permit_info_applied_only` | 128 | Only Applied |
| `permit_info_approved_only` | 87 | Approved, no Issued/Finaled |
| `permit_info_finaled_only` | 56 | Finaled, no Issued |
| `permit_info_empty_dates` | 23 | Status present, no usable dates |

Canonical mappings from DATA:

- `permit_info.PermitStatus` (+ Finaled / Issued overrides) → `STATUS_NORMALIZED`
- `permit_info.PermitAppliedDate` → `FILE_DATE`
- `permit_info.PermitIssuedDate` (fallback `PermitApprovedDate`) → `PERMIT_DATE`
- `permit_info.PermitFinaledDate` (fallback final inspection) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,141; Active 395; missing 253; Inactive 108; In Review 103.

Missing status causes:

1. **Blank PermitStatus** (212) — legacy shells with Issued (211) or Applied only (1); upstream left null because status string was empty.
2. **Unmapped labels** (41) — DPW FEES (23), APPLICANT * SUBMITTAL REQUIRED, APPROVED READY TO PAY, HARD COPIES REQUIRED, PREPARING FOR ISSUANCE, RESALE APPLIED ONLINE, REVISION UNDER REVIEW.

Incorrect status:

1. **ISSUED with PermitFinaledDate still Active** (5) → should be Final.
2. **In Review labels that already carry Issued** (READY TO PAY, PAID ONLINE, ON HOLD-PENDING ITEM, PENDING PLAN SUBMITL) (7) → should be Active.
3. **PAID ONLINE with Finaled** (1) → should be Final.
4. **APPROVED W/ COND left In Review** (1) → treated as Active (approval state).

APPROVED (5) already Active is correct (Approved used as issuance/approval evidence). EXPIRED / CANCELLED / STOP WORK ISSUED already Inactive — left as-is.

### FILE_DATE

Before: 252 missing. Whenever `PermitAppliedDate` is present, FILE_DATE already matches (1,748/1,748). The 252 gaps have blank Applied (legacy blank-status Issued shells, 18 ISSUED without Applied, 9 empty FIRE finals, In Review shells without Applied). No incorrect FILE_DATE values; nothing fillable from DATA.

### PERMIT_DATE

Before: 295 missing. Existing PERMIT_DATE always matched Issued when both present (0 mismatches). Gaps on Active/Final:

- Final missing PERMIT with Approved present (111) → FILLED from Approved.
- Active APPROVED missing Issued but with Approved (4) → FILLED.
- A few newly promoted Active rows already had PERMIT.

After repair: Active 615/617 (99.7%); Final 1,137/1,147 (99.1%). Remaining Final gaps are empty FIRE / finaled-only shells with neither Issued nor Approved.

### FINAL_DATE

Before: 921 missing (68 on Final). Existing FINAL_DATE always matched Finaled when both present. The 68 Final gaps have blank Finaled; 1 has a usable "Final Approval" inspection → FILLED. The 5 ISSUED→Final promotions already carried FINAL_DATE. Spurious FINAL on the PAID ONLINE row was absorbed by promoting that row to Final (no clear needed). Remaining Final FINAL_DATE gaps (67) have no Finaled and no usable final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 253 | 14 | 253 → 0 |
| FILE_DATE | 0 | 0 | 252 → 252 |
| PERMIT_DATE | 119 | 0 | 295 → 176 |
| FINAL_DATE | 1 | 0 | 921 → 920 |

After repair coverage:

| Status | N | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- | --- |
| Active | 617 | 399 / 617 (64.7%) | 615 / 617 (99.7%) | 0 / 617 |
| Final | 1,147 | 1,138 / 1,147 (99.2%) | 1,137 / 1,147 (99.1%) | 1,080 / 1,147 (94.2%) |
| In Review | 128 | 113 / 128 (88.3%) | 0 / 128 | 0 / 128 |
| Inactive | 108 | 108 / 108 (100%) | 72 / 108 (66.7%) | 0 / 108 |

Overall FILE_DATE: 1,748 / 2,000 (87.4%). Chronology: 8 PERMIT&lt;FILE and 8 FINAL&lt;PERMIT inversions present in source DATA and left as-is.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_mill_valley.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_mill_valley_repaired.parquet`
