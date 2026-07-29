# Los Altos Hills (CA) data repair

**Summary:** Assessed Los Altos Hills's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_los_altos_hills.py`. Civic portal `permit_info`/`search_data` is the canonical source. Filled 46 missing statuses (45 blank legacy stubs → In Review; 1 `APPROVED ON HOLD` → In Review) and fixed 13 mislabeled ones (FINALED left Active/Inactive → Final; ISSUED/APPROVED left In Review/Inactive → Active). FILE_DATE already correct where Applied exists (3 unfillable gaps). Filled 30 PERMIT_DATEs from Issued/Approved and 8 FINAL_DATEs (6 from PermitFinaledDate on status promotions, 2 from passed `**FINAL` inspections); cleared 10 junk Inactive FINAL_DATEs. After repair: status complete; Active PERMIT_DATE 99.3%; Final PERMIT_DATE 90.8% / FINAL_DATE 95.2%.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Los Altos Hills, CA**.

## DATA schema

All 2,000 rows have DATA. Single top-level key set:
`contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`.

Content variants (`INFERRED_SCHEMA`) by which `permit_info` dates are populated:

| Schema | N | Notes |
| --- | --- | --- |
| `permit_info_issued_finaled` | 1,324 | Issued + Finaled present |
| `permit_info_issued` | 400 | Issued present, Finaled blank |
| `permit_info_applied_only` | 128 | only Applied populated |
| `permit_info_finaled_only` | 85 | Finaled present, Issued blank |
| `legacy_no_status` | 45 | blank PermitStatus with Applied date |
| `permit_info_approved_only` | 18 | Approved present, Issued/Finaled blank |

Canonical mappings from DATA:

- `permit_info.PermitStatus` → `STATUS_NORMALIZED`
- `permit_info.PermitAppliedDate` (fallback `search_data.APPLIED`) → `FILE_DATE`
- `permit_info.PermitIssuedDate` (fallback `PermitApprovedDate` / `ISSUED` / `APPROVED`) → `PERMIT_DATE`
- `permit_info.PermitFinaledDate` (fallback `FINALED`, then passed `**FINAL` inspection) → `FINAL_DATE`

`search_data` date mirrors match `permit_info` when the full date block is present (1,890 rows). The other 110 rows are mostly legacy stubs with only identifiers. `PermitExpirationDate` is a validity window, not a completion date.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,466; Inactive 301; Active 146; missing 46; In Review 41.

Missing status causes:

1. **Blank PermitStatus legacy stubs** (45) — converted records with only `PermitAppliedDate`, empty status/inspections → FILLED as In Review.
2. **Unmapped label** (1) — `APPROVED ON HOLD` left null upstream → FILLED as In Review.

Incorrect status (stale `STATUS_ORIGINAL` lagging live `PermitStatus`):

1. **FINALED left Active** (5) → FIXED to Final.
2. **ISSUED left Inactive** (3; original=`expired`) → FIXED to Active.
3. **ISSUED left In Review** (3; original=`plan check` / `received`) → FIXED to Active.
4. **APPROVED left In Review** (1; original=`received`) → FIXED to Active.
5. **FINALED left Inactive** (1; original=`expired`) → FIXED to Final.

Inactive labels (Expired / Void / Cancelled / Withdrawn) are sticky even when `PermitFinaledDate` is present as a case-closure stamp. `LOW FUNDS` rows already carry FinaledDate and correctly stay Final via the canonical-Finaled override. Intermediate inspections are not used to override PermitStatus.

After: Final 1,472; Inactive 297; Active 148; In Review 83.

### FILE_DATE

Before: 3 missing. Where both present, every FILE_DATE matches `PermitAppliedDate` at calendar-day resolution (0 mismatches).

The 3 gaps (`16173`, `12055`, `9408`) have blank Applied / APPLIED in DATA — not fillable without inventing an application date from Issued. Left as-is.

Repair: **0 FILLED, 0 FIXED**. Coverage 1,997 / 2,000 (99.9%).

Source chronology quirks remain where Applied is after Issued (legacy converted shells); both dates match DATA, so left as-is (52 FILE > PERMIT inversions).

### PERMIT_DATE

Before: 280 missing. Existing PERMIT_DATE always matched Issued when both present.

Repair: **30 FILLED, 0 FIXED**:

- FINALED shells filled from Approved (13)
- APPROVED Active shells filled from Approved (9)
- ISSUED shells filled from Issued/Approved (6)
- CLOSED shells filled from Approved (2)

Remaining Active/Final gaps (136): CLOSED 105, FINALED 30, APPROVED 1 — no Issued or Approved date in DATA. Active coverage after repair: **147 / 148 (99.3%)**; Final: **1,337 / 1,472 (90.8%)**.

### FINAL_DATE

Before: 597 missing (73 on Final). Existing FINAL_DATE matched PermitFinaledDate when both present, but **10 Inactive** rows (Expired / Void) carried FINAL_DATE from closure stamps.

Repairs:

1. **FILLED** 6 from PermitFinaledDate on FINALED shells promoted from Active/Inactive (or previously missing).
2. **FILLED** 2 from passed `**FINAL` inspections on FINALED shells lacking PermitFinaledDate (`BLD23-0144` → 2023-11-28; `BLD22-0192` → 2022-05-20).
3. **FIXED** (cleared) 10 spurious Inactive closure stamps.

Remaining Final FINAL_DATE gaps (71): CLOSED 67, FINALED 4 — no PermitFinaledDate and no usable completed final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 46 | 13 | 46 → 0 |
| FILE_DATE | 0 | 0 | 3 → 3 |
| PERMIT_DATE | 30 | 0 | 280 → 250 |
| FINAL_DATE | 8 | 10 | 597 → 599 |

(Missing FINAL_DATE rises slightly because junk Inactive stamps were cleared.)

After repair coverage:

| Status | N | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- | --- |
| Active | 148 | 99.3% | 99.3% | 0% |
| Final | 1,472 | 99.9% | 90.8% | 95.2% |
| In Review | 83 | 100% | 0% | 0% |
| Inactive | 297 | 100% | 89.6% | 0% |

Ideal-rule summary:

| Rule | Coverage |
| --- | --- |
| FILE_DATE present (all) | 1,997 / 2,000 (99.9%) |
| PERMIT_DATE on Active | 147 / 148 (99.3%) |
| PERMIT_DATE on Final | 1,337 / 1,472 (90.8%) |
| FINAL_DATE on Final | 1,401 / 1,472 (95.2%) |
| FINAL_DATE absent on non-Final | 528 / 528 (100%) |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_los_altos_hills.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_los_altos_hills_repaired.parquet`
